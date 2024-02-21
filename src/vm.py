import ipaddress
import logging
import os
import re

import click

import meta
import utils

log = logging.getLogger(__name__)

sh = utils.sh


def get_qemu_archs():
    ret = sh("compgen -c | grep 'qemu-system-'")
    bins = ret.stdout.decode().split()
    return [x.split("-")[-1] for x in bins]


def _setup_tap_bridge(iface, dev_name):
    sh(f"ip link add dev {dev_name} type bridge")
    sh(f"ip link set {iface} master {dev_name}")
    # reset mtu (mtu will be 65535 in macos docker desktop?)
    sh(f"ip link set {dev_name} mtu 1500")
    # write bridge.conf
    conf_dir = "/etc/qemu"
    sh(f"mkdir {conf_dir}")
    sh(f"echo allow {dev_name} >> {conf_dir}/bridge.conf")
    # mknod /dev/net/tun
    if not os.path.exists("/dev/net/tun"):
        sh("mkdir -m 755 /dev/net")
        sh("mknod -m 666 /dev/net/tun c 10 200")
    sh(f"ip link set {dev_name} up")


def _setup_macvlan_bridge(iface, dev_name, dev_id, mac):
    # try create macvtap device
    vtapdev = f"macvtap{dev_id}"
    sh(
        f"ip link add link {iface} name {vtapdev} type macvtap mode bridge",
    )
    sh(f"ip link set {vtapdev} address {mac}")
    sh(f"ip link set {vtapdev} up")
    # create a macvlan device for the host
    sh(f"ip link add link {iface} name {dev_name} type macvlan mode bridge")
    # create dev file (there is no udev in container: need to be done manually)
    ret = sh(f"cat /sys/devices/virtual/net/{vtapdev}/tap*/dev")
    major, minor = ret.stdout.decode().split(":")
    sh(f"mknod '/dev/{vtapdev}' c {major} {minor}")
    sh(f"ip link set {dev_name} up")
    return vtapdev


def setup_bridge(
    iface: str, mode: meta.NetworkMode, mac: str, ip_cidr: str | None, index: int
):
    dev_name, dev_id = utils.gen_netdev_name(mode, utils.list_interfaces(False))
    fd = 10 + index * 10
    vhost_fd = fd + 1
    nic_id = "nic" + str(index)
    # mknod /dev/vhost-net
    if not os.path.exists("/dev/vhost-net"):
        sh("mknod -m 660 /dev/vhost-net c 10 238")
    if mode == meta.NetworkMode.TAP_BRIDGE:
        _setup_tap_bridge(iface, dev_name)
        meta.config.qemu.append(
            {
                "netdev": {
                    "bridge": {
                        "id": nic_id,
                        "br": dev_name,
                    }
                }
            }
        )
    else:
        vtapdev = _setup_macvlan_bridge(iface, dev_name, dev_id, mac)
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
        {"device": {"virtio-net-pci": {"netdev": nic_id, "mac": mac}}}
    )
    # get a new IP for the guest machine in a broader network broadcast domain
    if ip_cidr:
        ip, cidr = ip_cidr.split("/")
        new_ip, new_cidr = utils.gen_non_conflicting_ip(ip, int(cidr))
        sh(f"ip address del {ip}/{cidr} dev {iface}")
        sh(f"ip address add {new_ip}/{new_cidr} dev {dev_name}")


ip_addr_iface_ip = re.compile(r"inet\s+(.+)\s+brd")
ip_addr_iface_mac = re.compile(r"link/ether\s+(.+)\s+brd")


def configure_network() -> dict[str, tuple[str, str]]:
    c = meta.config
    nics = {}

    ifaces = utils.list_interfaces()
    mode = meta.NetworkMode.MACVLAN if c.enable_macvlan else meta.NetworkMode.TAP_BRIDGE
    for i, iface in enumerate(ifaces):
        # get iface info
        ret = sh(f"ip address show dev {iface}")
        info = ret.stdout.decode()
        ip_cidr_list = ip_addr_iface_ip.findall(info)  # ip/cidr
        if c.networks:
            ip_cidr_list = list(
                filter(
                    lambda x: any(
                        ipaddress.ip_address(x.split("/")[0]) in n for n in c.networks
                    ),
                    ip_cidr_list,
                )
            )
        ip_cidr = ip_cidr_list[0] if ip_cidr_list else None
        # get mac
        macs = ip_addr_iface_mac.findall(info)
        if not macs:
            raise ValueError(f"cannot find mac for {iface}, output: {info}")
        mac = macs[0]

        # use container MAC address ($MAC) for tap device
        # and generate a new one for the local interface
        sh(f"ip link set {iface} down")
        sh(f"ip link set {iface} address {utils.gen_random_mac()}")
        sh(f"ip link set {iface} up")

        setup_bridge(iface, mode, mac, ip_cidr, i)
        nics[iface] = (ip_cidr, mac)
    return nics


def configure_dhcp(
    gw: ipaddress.IPv4Address | ipaddress.IPv6Address,
    nics: dict[str, tuple[str, str]],
):
    network = None
    for v in nics.values():
        n = ipaddress.ip_network(v[0], strict=False)
        if gw not in n:
            continue
        network = n
        mac = v[1]
        ip, _ = v[0].split("/")
        ip = ipaddress.ip_address(ip)
    if not network:
        raise EnvironmentError(f"cannot find network for {gw}")

    # ipv4 only
    if (
        isinstance(gw, ipaddress.IPv6Address)
        or isinstance(network, ipaddress.IPv6Network)
        or isinstance(ip, ipaddress.IPv6Address)
    ):
        raise NotImplementedError(
            "ipv6 is not supported yet, consider run with '--no-dhcp'"
        )
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
    log.info(dnsmasq_opts)
    sh(["dnsmasq", *dnsmasq_opts])


def configure_monitor():
    c = meta.config
    if not c.enable_monitor:
        return
    c.qemu.append({"monitor": f"tcp:127.0.0.1:{meta.VmPort.MON},server,nowait"})
    c.qemu.append({"qmp": f"tcp:127.0.0.1:{meta.VmPort.QMP},server,nowait"})


def configure_vnc():
    c = meta.config
    if not c.enable_vnc_web:
        return
    c.qemu.append({"vnc": f":0,websocket={meta.VmPort.VNC_WS}"})


def config_port_forwarding():
    pass


def check_capabilities():
    # NET_ADMIN
    if not utils.check_linux_capability("NET_ADMIN"):
        raise click.UsageError(
            "'CAP_NET_ADMIN' is required, please run container with '--cap-add=NET_ADMIN' or '--privileged'"
        )
    # macvtap dev
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
    gw = ipaddress.ip_address(utils.get_default_route())
    nics = configure_network()
    # dhcp
    configure_dhcp(gw, nics)
    # monitor
    configure_monitor()
    # vnc
    configure_vnc()

    # run qemu
    cmd = f"qemu-system-{c.arch} {c.qemu.to_args()}"
    log.info(f"Running {cmd} ...")
    sh(cmd, stdout=None, stderr=None)
