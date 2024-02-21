import ipaddress
import logging
import os
import uuid

import click

import meta
import utils

log = logging.getLogger(__name__)

sh = utils.sh


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


def configure_dhcp(
    gw: ipaddress.IPv4Address,
    ifaces: dict[str, tuple[str, str]],
):
    network, mac, ip = None, None, None
    for v in ifaces.values():
        if not v[1]:  # skip no ip iface
            continue
        n = ipaddress.ip_network(v[1], strict=False)
        if gw not in n:  # default network only
            continue
        network = n
        mac = v[0]
        ip, _ = v[1].split("/")
        ip = ipaddress.ip_address(ip)
    if not network:
        raise EnvironmentError(f"cannot find network for {gw}")

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
    sh(["dnsmasq", *dnsmasq_opts])


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
    sh("caddy start", stdout=None, stderr=None)


def config_port_forwarding():
    pass


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


def run_qemu():
    check_capabilities()

    c = meta.config
    # cpu
    if c.cpu_num:
        c.qemu.append({"smp": c.cpu_num})
    # memory
    if c.mem_size:
        c.qemu.append({"m": c.mem_size})
    # kvm
    if c.enable_kvm and utils.is_kvm_avaliable():
        c.qemu.append({"enable-kvm": True})
    # cdrom
    if c.iso:
        c.qemu.append({"cdrom": str(c.iso)})

    # network
    gw, iface_map = configure_network()
    # dhcp
    configure_dhcp(gw, iface_map)
    # console
    configure_console()
    # vnc
    configure_vnc()

    # run qemu
    cmd = f"qemu-system-{c.arch} {c.qemu.to_args()}"
    log.info(f"Running {cmd} ...")
    sh(cmd, stdout=None, stderr=None)
