import ipaddress
import logging
import random
import re
import subprocess
import typing
import uuid

import meta

log = logging.getLogger(__name__)


def sh(*args, **kwargs):
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.PIPE)
    kwargs.setdefault("check", True)
    if len(args) == 1 and isinstance(args[0], str):
        args = ["bash", "-c", args[0]]
    return subprocess.run(args, **kwargs)


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


ip_addr_iface_ip = re.compile(r"inet\s+(.+)\s+brd")
ip_addr_iface_mac = re.compile(r"link/ether\s+(.+)\s+brd")


def _setup_tap_bridge(iface, dev_name, mac):
    sh(f"brctl addbr {dev_name}")
    sh(f"brctl addif {dev_name} {iface}")
    sh(f"ip link set {dev_name} address {mac}")
    # reset mtu (mtu will be 65535 in macos docker desktop?)
    sh(f"ip link set dev {dev_name} mtu 1500")
    # write bridge.conf
    conf_dir = "/etc/qemu"
    sh(f"mkdir {conf_dir}")
    sh(f"echo allow {dev_name} >> {conf_dir}/bridge.conf")
    # mknod /dev/net/tun
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
    iface: str, mode: meta.NetworkMode, mac: str, ip: str, cidr: str, index: int
):
    dev_name, dev_id = gen_netdev_name(mode, list_interfaces(False))
    # mknod /dev/vhost-net
    sh("mknod -m 660 /dev/vhost-net c 10 238")
    fd = 10 + index * 10
    vhost_fd = fd + 1
    nic_id = "nic" + str(index)
    if mode == meta.NetworkMode.TAP_BRIDGE:
        _setup_tap_bridge(iface, dev_name, mac)
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

    # get a new IP for the guest machine in a broader network broadcast domain
    new_ip, new_cidr = gen_non_conflicting_ip(ip, int(cidr))
    sh(f"ip address del {ip}/{cidr} dev {iface}")
    sh(f"ip address add {new_ip}/{new_cidr} dev {dev_name}")
    sh(f"ip link set dev '{dev_name}' up")
    return dev_name, dev_id


def configure_network():
    c = meta.config
    ifaces = list_interfaces()

    mode = meta.NetworkMode.MACVLAN if c.enable_macvlan else meta.NetworkMode.TAP_BRIDGE
    for i, iface in enumerate(ifaces):
        # get iface info
        ret = sh(f"ip address show dev {iface}")
        info = ret.stdout.decode()
        ips = ip_addr_iface_ip.findall(info)
        if not ips:
            return
        if c.networks:
            ips = list(
                filter(
                    lambda x: any(
                        ipaddress.ip_address(x.split("/")[0]) in n for n in c.networks
                    ),
                    ips,
                )
            )
            if not ips:
                log.info(f"cannot find ip in {c.networks} for {iface}, ignored")
                return
        ip, cidr = ips[0].split("/")
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

        dev_name, dev_id = setup_bridge(iface, mode, mac, ip, cidr, i)
        # add device
        c.qemu.append(
            {"device": {"virtio-net-pci": {"netdev": "nic" + str(i), "mac": mac}}}
        )


# def configure_storage():
#     c = meta.config
#     pass


def configure_vnc():
    c = meta.config
    pass


def configure_monitor():
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
    log.info("Configuring network ...")
    configure_network()
    # storage
    # configure_storage()
    # vnc
    configure_vnc()
    # monitor
    configure_monitor()

    # run qemu
    cmd = f"qemu-system-{c.arch} {c.qemu.to_args()}"
    log.info(f"Running {cmd} ...")
    sh(cmd, stdout=None, stderr=None)
