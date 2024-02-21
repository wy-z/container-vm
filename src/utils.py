import ipaddress
import logging
import random
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
