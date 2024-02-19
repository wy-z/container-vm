import ipaddress
import logging
import os
import random
import re
import subprocess
import typing
import uuid

import meta

log = logging.getLogger(__name__)

#
# Utils
#


def sh(*args, **kwargs):
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.PIPE)
    kwargs.setdefault("check", True)
    if len(args) == 1 and isinstance(args[0], str):
        args = [["bash", "-c", args[0]]]
    return subprocess.run(*args, **kwargs)


def get_qemu_archs():
    ret = sh("compgen -c | grep 'qemu-system-'")
    bins = ret.stdout.decode().split()
    return [x.split("-")[-1] for x in bins]


def is_kvm_avaliable():
    return sh("grep -E 'svm|vmx' /proc/cpuinfo", check=False).returncode == 0


def gen_random_mac():
    return "02:" + ":".join(
        [("0" + hex(random.randint(0, 256))[2:])[-2:].upper() for _ in range(5)]
    )


def gen_netdev_name(
    mode: meta.NetworkMode, ifaces: typing.Iterable[str] = []
) -> tuple[str, str]:
    while True:
        dev_id = str(uuid.uuid4().fields[-1])[:8]
        dev_name = mode + dev_id
        if dev_name not in ifaces:
            return dev_name, dev_id


def gen_non_conflicting_ip(ip: str, cidr: int):
    new_cidr = cidr - 1
    ip_int = int(ipaddress.ip_address(ip))
    j = ip_int ^ (1 << (32 - cidr))
    new_ip = ipaddress.ip_address(j)
    return new_ip, new_cidr


def list_interfaces(exclude_bridge: bool = True):
    # get all interfaces
    ret = sh(
        "ip link show | grep -v noop | grep state "
        "| grep -v LOOPBACK | awk '{print $2}' | tr -d : | sed 's/@.*$//'"
    )
    all_ifaces = set(ret.stdout.decode().split())
    if not exclude_bridge:
        return all_ifaces
    # bridges
    ret = sh("brctl show | tail -n +2 | awk '{print $1}'")
    bridges = set(ret.stdout.decode().split())
    return all_ifaces - bridges


def list_nameservers():
    ret = sh("grep nameserver /etc/resolv.conf | sed 's/nameserver //'")
    return [i.strip() for i in ret.stdout.decode().splitlines()]


def get_default_route():
    ret = sh("ip route | grep default | awk '{print $3}'")
    return ret.stdout.decode().strip()


def get_hostname():
    return sh("hostname -s").stdout.decode().strip()


#
# VM Setup
#


def _setup_tap_bridge(iface, dev_name):
    sh(f"brctl addbr {dev_name}")
    sh(f"brctl addif {dev_name} {iface}")
    # reset mtu (mtu will be 65535 in macos docker desktop?)
    sh(f"ip link set dev {dev_name} mtu 1500")
    # write bridge.conf
    conf_dir = "/etc/qemu"
    sh(f"mkdir {conf_dir}")
    sh(f"echo allow {dev_name} >> {conf_dir}/bridge.conf")
    # mknod /dev/net/tun
    if not os.path.exists("/dev/net/tun"):
        sh("mkdir -m 755 /dev/net")
        sh("mknod -m 666 /dev/net/tun c 10 200")


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
    sh(f"ip link set {dev_name} up")
    # create dev file (there is no udev in container: need to be done manually)
    ret = sh(f"cat /sys/devices/virtual/net/{vtapdev}/tap*/dev")
    major, minor = ret.stdout.decode().split(":")
    sh(f"mknod '/dev/{vtapdev}' c {major} {minor}")
    return vtapdev


def setup_bridge(
    iface: str, mode: meta.NetworkMode, mac: str, ip_cidr: str | None, index: int
):
    dev_name, dev_id = gen_netdev_name(mode, list_interfaces(False))
    fd = 10 + index * 10
    vhost_fd = fd + 1
    nic_id = "nic" + str(index)
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
        # mknod /dev/vhost-net
        if not os.path.exists("/dev/vhost-net"):
            sh("mknod -m 660 /dev/vhost-net c 10 238")
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

    # get a new IP for the guest machine in a broader network broadcast domain
    if ip_cidr:
        ip, cidr = ip_cidr.split("/")
        new_ip, new_cidr = gen_non_conflicting_ip(ip, int(cidr))
        sh(f"ip address del {ip}/{cidr} dev {iface}")
        sh(f"ip address add {new_ip}/{new_cidr} dev {dev_name}")
    sh(f"ip link set dev '{dev_name}' up")
    return dev_name, dev_id


ip_addr_iface_ip = re.compile(r"inet\s+(.+)\s+brd")
ip_addr_iface_mac = re.compile(r"link/ether\s+(.+)\s+brd")


def configure_network() -> dict[str, tuple[str, str]]:
    c = meta.config
    nics = {}

    ifaces = list_interfaces()
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
        sh(f"ip link set {iface} address {gen_random_mac()}")
        sh(f"ip link set {iface} up")

        dev_name, dev_id = setup_bridge(iface, mode, mac, ip_cidr, i)
        # add device
        c.qemu.append(
            {"device": {"virtio-net-pci": {"netdev": "nic" + str(i), "mac": mac}}}
        )
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
        f"--dhcp-option=option:dns-server,{','.join(list_nameservers())}",
        f"--dhcp-option=option:router,{gw}",
    ]
    log.info(dnsmasq_opts)
    sh(["dnsmasq", *dnsmasq_opts])


def configure_monitor():
    c = meta.config
    if not c.enable_monitor:
        return
    c.qemu.append({"monitor": "tcp:127.0.0.1:10000,server,nowait"})
    c.qemu.append({"qmp": "tcp:127.0.0.1:10001,server,nowait"})


def configure_vnc():
    c = meta.config
    pass


def run_qemu():
    c = meta.config
    # cpu
    if c.cpu_num:
        c.qemu.append({"smp": c.cpu_num})
    # memory
    if c.mem_size:
        c.qemu.append({"m": c.mem_size})
    # kvm
    if c.enable_kvm and is_kvm_avaliable():
        c.qemu.append({"enable-kvm": True})

    # cdrom
    if c.iso:
        c.qemu.append({"cdrom": str(c.iso)})
    # network
    gw = ipaddress.ip_address(get_default_route())
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
