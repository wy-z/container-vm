import functools
import ipaddress
import logging
import os
import pathlib
import time
import uuid

import click

from . import meta, utils

log = logging.getLogger(__name__)
sh = utils.sh


VM_ID_FILE = os.path.join(meta.STORAGE_DIR, "vm-id")


@functools.cache
def get_vm_id():
    pf = pathlib.Path(VM_ID_FILE)
    vm_id = None
    if not os.path.exists(VM_ID_FILE):
        os.makedirs(os.path.dirname(VM_ID_FILE), exist_ok=True)
        pf.touch()
    else:
        vm_id = pf.read_text().strip()
    if not vm_id:
        vm_id = uuid.uuid4().hex[:8]
        pf.write_text(vm_id)
    return vm_id


def get_qemu_archs():
    ret = sh("compgen -c | grep 'qemu-system-'")
    bins = ret.stdout.decode().split()
    return [x.split("-")[-1] for x in bins]


def gen_netdev_name(mode: meta.NetworkMode) -> tuple[str, str]:
    ifaces = utils.list_interfaces()
    while True:
        dev_id = str(uuid.uuid4().fields[-1])[:8]
        dev_name = mode + dev_id
        if dev_name not in ifaces:
            return dev_name, dev_id


def get_vm_interfaces():
    c = meta.config
    if not c.ifaces:
        return [utils.get_default_interface()]
    ifaces = utils.list_interfaces() - utils.list_bridges()
    for iface in c.ifaces:
        if iface not in ifaces:
            raise ValueError(f"iface '{iface}' not found in '{ifaces}'")
    return c.ifaces


def get_interface_ipnets(iface) -> list:
    c = meta.config
    ipnets, _ = utils.get_interface_info(iface)
    if not c.networks:
        if len(ipnets) > 1:
            raise EnvironmentError(
                f"multiple ipnets found in {iface}: {ipnets}, consider assign '--network' parameter"
            )
        return ipnets
    return list(
        filter(
            lambda x: any(
                ipaddress.ip_address(x.split("/")[0]) in n for n in c.networks
            ),
            ipnets,
        )
    )


def _setup_tap_bridge(iface, dev_name, dev_id, new_mac, ipnet: str | None = None):
    sh(f"ip link add dev {dev_name} type bridge")
    sh(f"ip link set {iface} master {dev_name}")
    # write bridge.conf
    conf_dir = "/etc/qemu"
    sh(f"mkdir -p {conf_dir}")
    sh(f"echo allow {dev_name} > {conf_dir}/bridge.conf")
    # mknod /dev/net/tun
    if not os.path.exists("/dev/net/tun"):
        sh("mkdir -m 755 /dev/net")
        sh("mknod -m 666 /dev/net/tun c 10 200")
    tap_name = "tap" + dev_id
    sh(f"ip tuntap add dev {tap_name} mode tap")
    sh(f"ip link set {tap_name} address {new_mac}")
    sh(f"ip link set {tap_name} up")
    sh(f"ip link set {tap_name} master {dev_name}")
    # up bridge
    sh(f"ip link set {dev_name} up")
    # reset ip for the bridge
    if ipnet:
        sh(f"ip address flush {iface}")
        sh(f"ip address add {ipnet} brd + dev {dev_name}")
    return tap_name


def _setup_macvlan_bridge(iface, dev_name, dev_id, new_mac, ipnet: str | None = None):
    # try create macvtap device
    vtapdev = f"macvtap{dev_id}"
    sh(
        f"ip link add link {iface} name {vtapdev} type macvtap mode bridge",
    )
    sh(f"ip link set {vtapdev} address {new_mac}")
    sh(f"ip link set {vtapdev} up")
    # create a macvlan device for the host
    sh(f"ip link add link {iface} name {dev_name} type macvlan mode bridge")
    # create dev file (there is no udev in container: need to be done manually)
    ret = sh(f"cat /sys/devices/virtual/net/{vtapdev}/tap*/dev")
    major, minor = ret.stdout.decode().split(":")
    sh(f"mknod '/dev/{vtapdev}' c {major} {minor}")
    sh(f"ip link set {dev_name} up")
    # set a non-conflicting ip for the macvlan device, for dhcp
    if ipnet:
        ip, cidr = ipnet.split("/")
        new_ip, new_cidr = utils.gen_non_conflicting_ip(ip, int(cidr))
        sh(f"ip address add {new_ip}/{new_cidr} dev {dev_name}")
    return vtapdev


def get_unused_ip(network: ipaddress.IPv4Network) -> str | None:
    for ip in reversed(list(network.hosts())):
        if utils.is_host_avaliable(ip):
            continue
        return str(ip)
    return


def setup_bridge(
    iface: str, mode: meta.NetworkMode, ipnet: str, index: int = 0
) -> tuple[str, str | None]:
    dev_name, dev_id = gen_netdev_name(mode)
    fd = 10 + index * 10
    vhost_fd = fd + 1
    nic_id = "nic" + str(index)
    new_mac = utils.gen_random_mac()
    # mknod /dev/vhost-net
    if not os.path.exists("/dev/vhost-net"):
        sh("mknod -m 660 /dev/vhost-net c 10 238")
    if mode == meta.NetworkMode.TAP_BRIDGE:
        tap_name = _setup_tap_bridge(iface, dev_name, dev_id, new_mac, ipnet)
        meta.config.qemu.append(
            {
                "netdev": {
                    "tap": {
                        "id": nic_id,
                        "ifname": tap_name,
                        "script": "no",
                        "downscript": "no",
                    }
                }
            }
        )
    else:
        vtapdev = _setup_macvlan_bridge(iface, dev_name, dev_id, new_mac, ipnet)
        meta.config.qemu.append(
            {
                "netdev": {
                    "tap": {
                        "id": nic_id,
                        "fd": fd,
                        "vhost": "on",
                        "vhostfd": vhost_fd,
                    }
                }
            }
        )
        meta.config.qemu.ext_args.append(f"{fd}<>/dev/{vtapdev}")
        meta.config.qemu.ext_args.append(f"{vhost_fd}<>/dev/vhost-net")
    meta.config.qemu.append(
        {"device": {"virtio-net-pci": {"netdev": nic_id, "mac": new_mac}}}
    )
    # get new ip
    new_ip = None
    if ipnet:
        network = ipaddress.IPv4Network(ipnet, strict=False)
        log.info(f"finding available ip in '{network}' ...")
        new_ip = get_unused_ip(network)
        if not new_ip:
            raise EnvironmentError(f"no available ip in '{ipnet}'")
    return new_mac, (new_ip + "/" + ipnet.split("/")[1]) if new_ip else None


def configure_network() -> tuple[ipaddress.IPv4Address, dict[str, tuple[str, str]]]:
    c = meta.config
    iface_map = {}

    gw = ipaddress.IPv4Address(utils.get_default_route())
    mode = meta.NetworkMode.MACVLAN if c.enable_macvlan else meta.NetworkMode.TAP_BRIDGE
    ifaces = get_vm_interfaces()
    ipnets = {}
    for iface in ifaces:
        nets = get_interface_ipnets(iface)
        if not nets:
            log.info(f"no ip/net found in {iface}")
        ipnets[iface] = nets[0] if nets else None
    for index, iface in enumerate(ipnets.keys()):
        iface_map[iface] = setup_bridge(iface, mode, ipnets[iface], index)

    # reset default route
    sh(f"route add default gw {gw}", check=False)
    return gw, iface_map


def _select_default_network(
    gw: ipaddress.IPv4Address,
    ifaces: dict[str, tuple[str, str]],
):
    network, mac, ip = None, None, None
    for _mac, ipnet in ifaces.values():
        if not ipnet:  # skip no ip iface
            continue
        n = ipaddress.ip_network(ipnet, strict=False)
        if gw not in n:  # default network only
            continue
        network = n
        mac = _mac
        ip, _ = ipnet.split("/")
        ip = ipaddress.ip_address(ip)
    if not network:
        raise EnvironmentError(f"cannot find network for {gw}")
    return network, mac, ip


def configure_dhcp(
    gw: ipaddress.IPv4Address,
    ifaces: dict[str, tuple[str, str]],
):
    network, mac, ip = _select_default_network(gw, ifaces)
    log_file = "/var/log/dnsmasq.log"
    dnsmasq_opts = [
        "--log-queries",
        f"--log-facility={log_file}",
        f"--dhcp-range={ip},{ip}",
        f"--dhcp-host={mac},{ip},infinite",
        f"--dhcp-option=option:netmask,{network.netmask}",
        f"--dhcp-option=option:dns-server,{','.join(utils.list_nameservers())}",
        f"--dhcp-option=option:router,{gw}",
    ]
    log.info(f"Running dnsmasq {' '.join(dnsmasq_opts)} ...")
    sh(["dnsmasq", *dnsmasq_opts], stdout=None, stderr=None)


DEFAULT_PORT_FORWARDS = ["22:22", "3389:3389"]


def configure_port_forward(
    gw: ipaddress.IPv4Address, ifaces: dict[str, tuple[str, str]]
):
    _, _, ip = _select_default_network(gw, ifaces)
    c = meta.config
    if c.port_forwards is None:
        c.port_forwards = DEFAULT_PORT_FORWARDS
    for spec in c.port_forwards:
        if ":" not in spec:
            raise ValueError(f"invalid port forward spec: {spec}")
        int_port, pub_port = spec.split(":")
        sh(
            f"iptables -t nat -A PREROUTING -p tcp --dport {pub_port} -j DNAT --to-destination {ip}:{int_port}"
        )
        sh(
            f"iptables -t nat -A POSTROUTING -p tcp -d {ip} --dport {int_port} -j MASQUERADE"
        )


def configure_console():
    c = meta.config
    if not c.enable_console:
        return
    c.qemu.append(
        {"serial": f"mon:telnet:127.0.0.1:{meta.VmPort.TELNET},server,nowait"}
    )
    c.qemu.append({"qmp": f"tcp:127.0.0.1:{meta.VmPort.QMP},server,nowait"})


def configure_vnc():
    c = meta.config
    if not c.enable_vnc_web:
        return
    c.qemu.append({"vnc": f":0,websocket={meta.VmPort.VNC_WS}", "vga": "virtio"})
    # run caddy
    log.info("Running caddy ...")
    sh("caddy start --config /etc/caddy/Caddyfile", stdout=None, stderr=None)


def check_capabilities():
    # NET_ADMIN
    if not utils.check_linux_capability("NET_ADMIN"):
        raise click.UsageError(
            "'CAP_NET_ADMIN' is required, please run container with '--cap-add=NET_ADMIN' or '--privileged'"
        )
    # vhost dev
    vhost_dev = "/dev/tmp-vhost-net"
    try:
        if meta.config.enable_macvlan:
            sh(f"mknod -m 660 {vhost_dev} c 10 238")
            if (
                b"Operation not permitted"
                in sh(f"echo 1 >{vhost_dev}", check=False).stderr
            ):
                raise click.UsageError(
                    "device permissions are required for macvlan network, "
                    'consider run container with "--device-cgroup-rule=\'c *:* rwm\'" or "--privileged"'
                )
    finally:
        sh(f"rm -f {vhost_dev}")


OVMF_DIR = "/usr/share/OVMF"
PREFER_MACHINES = ["q35", "virt"]


def _get_prefer_machine():
    c = meta.config
    machs = utils.get_qemu_machines(c.arch)
    for i in PREFER_MACHINES:
        if i in machs:
            return i
    active_machs = utils.get_qemu_machines(c.arch, active_only=True)
    if active_machs:
        return active_machs[0]
    log.warn("cannot find available machine type, consider assign '--machine'")
    return


def configure_boot():
    c = meta.config
    # machine
    mach = c.machine or _get_prefer_machine()
    if mach:
        log.info(f"Using machine type: {mach}")
        c.qemu.append({"machine": mach})
    # boot options
    if c.boot is not None:
        c.qemu.append({"boot": c.boot})
    # boot mode
    if c.boot_mode == meta.BootMode.LEGACY:
        return

    rom, vars = None, None
    match c.boot_mode:
        case meta.BootMode.UEFI:
            rom = "OVMF_CODE_4M.fd"
            vars = "OVMF_VARS_4M.fd"
        case meta.BootMode.SECURE:
            rom = "OVMF_CODE_4M.secboot.fd"
            vars = "OVMF_VARS_4M.secboot.fd"
        case meta.BootMode.WINDOWS:
            rom = "OVMF_CODE_4M.ms.fd"
            vars = "OVMF_VARS_4M.ms.fd"
        case _:
            raise click.UsageError(f"invalid boot mode '{c.boot_mode}'")
    boot_dir = os.path.join(meta.STORAGE_DIR, "boot")
    os.makedirs(boot_dir, exist_ok=True)
    rom_file = os.path.join(boot_dir, c.boot_mode + ".rom")
    vars_file = os.path.join(boot_dir, c.boot_mode + ".vars")
    if not os.path.exists(rom_file):
        sh(f"cp {os.path.join(OVMF_DIR, rom)} {rom_file}")
    if not os.path.exists(vars_file):
        sh(f"cp {os.path.join(OVMF_DIR, vars)} {vars_file}")
    c.qemu.append({"drive": f"file={rom_file},if=pflash,format=raw,readonly=on"})
    c.qemu.append({"drive": f"file={vars_file},if=pflash,format=raw"})


def configure_opts():
    c = meta.config
    # cpu
    if c.cpu_num:
        c.qemu.append({"smp": c.cpu_num})
    # memory
    if c.mem_size:
        c.qemu.append({"m": c.mem_size})
    # kvm
    if c.enable_accel:
        if utils.is_kvm_avaliable():
            c.qemu.append({"enable-kvm": True})
        elif accels := utils.get_qemu_accels(c.arch):
            c.qemu.append({"accel": accels[0]})
    # cdrom
    if c.iso:
        c.qemu.append({"cdrom": str(c.iso)})


def run_qemu():
    check_capabilities()
    configure_opts()
    # boot
    configure_boot()
    # network
    gw, iface_map = configure_network()
    # port forward
    configure_port_forward(gw, iface_map)
    # dhcp
    configure_dhcp(gw, iface_map)
    # console
    configure_console()
    # vnc
    configure_vnc()

    # run qemu
    c = meta.config
    cmd = f"qemu-system-{c.arch} {c.qemu.to_args()} {c.extra_args}"
    log.info(f"Running {cmd} ...")
    sh(cmd, stdout=None, stderr=None)


def create_drive(file, size, file_type="qcow2"):
    os.makedirs(os.path.dirname(file), exist_ok=True)
    log.info(f"Createing {file} ...")
    sh(f"qemu-img create -f {file_type} {file} {size}")


def setup_swtpm():
    tpm_dir = "/run/shm/tpm"
    pid_file = "/var/run/tpm.pid"
    sock_file = "/run/swtpm-sock"
    sh(f"rm -rf {tpm_dir}")
    sh(f"rm -f {pid_file}")
    sh(f"mkdir -m 755 -p {tpm_dir}")
    sh(
        f"swtpm socket -t -d --tpmstate dir={tpm_dir} --ctrl type=unixio,path={sock_file} --pid file={pid_file} --tpm2"
    )
    for i in reversed(range(6)):
        if os.path.exists(sock_file):
            break
        if i == 0:
            raise EnvironmentError("failed to start swtpm")
        time.sleep(1)
    meta.config.qemu.append({"chardev": f"socket,id=chrtpm,path={sock_file}"})
    meta.config.qemu.append(
        {"tpmdev": "emulator,id=tpm0,chardev=chrtpm -device tpm-tis,tpmdev=tpm0"}
    )
