import ipaddress
import logging
import os
import random
import re
import subprocess

log = logging.getLogger(__name__)


def sh(*args, **kwargs):
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.PIPE)
    kwargs.setdefault("check", True)
    if len(args) == 1 and isinstance(args[0], str):
        args = [["bash", "-c", args[0]]]
    return subprocess.run(*args, **kwargs)


def is_kvm_avaliable():
    return sh("grep -E 'svm|vmx' /proc/cpuinfo", check=False).returncode == 0


def check_linux_capability(cap: str):
    cap = cap.lower()
    if not cap.startswith("cap_"):
        cap = "cap_" + cap
    return sh(f"capsh --print | grep '!{cap}'", check=False).returncode != 0


def gen_random_mac():
    return "02:" + ":".join(
        [("0" + hex(random.randint(0, 256))[2:])[-2:].upper() for _ in range(5)]
    )


def gen_non_conflicting_ip(ip: str, cidr: int):
    new_cidr = cidr - 1
    ip_int = int(ipaddress.ip_address(ip))
    j = ip_int ^ (1 << (32 - cidr))
    new_ip = ipaddress.ip_address(j)
    return new_ip, new_cidr


def list_interfaces():
    ret = sh(
        "ip link show | grep -v noop | grep state "
        "| grep -v LOOPBACK | awk '{print $2}' | tr -d : | sed 's/@.*$//'"
    )
    return set(x.strip() for x in ret.stdout.decode().split())


def list_nameservers():
    ret = sh("grep nameserver /etc/resolv.conf | sed 's/nameserver //'")
    return [i.strip() for i in ret.stdout.decode().splitlines()]


def get_default_route():
    ret = sh("ip route | grep default | awk '{print $3}'")
    return ret.stdout.decode().strip()


def get_default_interface():
    ret = sh("ip route | grep default | awk '{print $5}'")
    return ret.stdout.decode().strip()


def get_hostname():
    return sh("hostname -s").stdout.decode().strip()


ip_addr_iface_ip_cidr = re.compile(r"inet\s+(.+)\s+brd")
ip_addr_iface_mac = re.compile(r"link/ether\s+(.+)\s+brd")


def get_interface_info(iface):
    ret = sh(f"ip address show dev {iface}")
    info = ret.stdout.decode()
    ip_cidr_list = ip_addr_iface_ip_cidr.findall(info)  # ip/cidr
    macs = ip_addr_iface_mac.findall(info)
    if not macs:
        raise ValueError(f"cannot find mac for {iface}, output: {info}")
    mac = macs[0]
    return ip_cidr_list, mac


def is_host_avaliable(ip, times: int = 1, timeout: float = 1):
    return os.system(f"ping -c {times} -W {timeout} {ip} >/dev/null") == 0


def get_qemu_accels(arch: str):
    ret = sh(f"qemu-system-{arch} -accel help | tail -n +2")
    return [i.strip() for i in ret.stdout.decode().splitlines()]


def get_qemu_machines(arch: str, active_only=False):
    if active_only:
        ret = sh(
            f"qemu-system-{arch} -machine help | tail -n +2 | grep alias | awk '{{print $1}}'"
        )
    else:
        ret = sh(f"qemu-system-{arch} -machine help | tail -n +2 | awk '{{print $1}}'")
    return [i.strip() for i in ret.stdout.decode().splitlines()]
