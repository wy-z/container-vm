import ipaddress
import logging
import os
import pathlib
import typing

import click
import typer

from . import meta, vm

log = logging.getLogger(__name__)


def run_qemu(*args, **kwargs):
    vm.run_qemu()


app = typer.Typer(
    chain=True,
    invoke_without_command=True,
    result_callback=run_qemu,
)


QEMU_ARCHS = vm.get_qemu_archs()


def str_or_none(value: str):
    if value.lower() in ["no", "false", "none", "nil", "null"]:
        return None
    return value


@app.callback()
def main(
    cpu_num: int = typer.Option(None, "-c", "--cpu", help="CPU cores"),
    mem_size: int = typer.Option(None, "-m", "--mem", min=1, help="Memory size in MB"),
    arch: str = typer.Option(
        default="x86_64", help="VM arch", click_type=click.Choice(QEMU_ARCHS)
    ),
    iso: pathlib.Path = typer.Option(default=None, help="ISO file path", exists=True),
    accel: bool = typer.Option(default=True, help="Enable acceleration"),
    macvlan: bool = typer.Option(
        default=True, help="Enable macvlan network, otherwise use bridge network"
    ),
    dhcp: bool = typer.Option(default=True, help="Enable DHCP"),
    vnc_web: bool = typer.Option(default=True, help="Enable VNC web client (noVNC)"),
    console: bool = typer.Option(
        default=True, help="Enable Qemu monitor (mon+telnet+qmp)"
    ),
    machine: str = typer.Option(None, help="Machine type"),
    boot: typing.Optional[str] = typer.Option(
        "once=dc", help="Boot options", parser=str_or_none
    ),
    boot_mode: meta.BootMode = typer.Option(meta.BootMode.LEGACY, help="Boot mode"),
    ifaces: list[str] = typer.Option(
        [],
        "--iface",
        help="(multiple) Special VM network interface (e.g. eth1)",
    ),
    networks: list[str] = typer.Option(
        [],
        "--network",
        help="(multiple) Special VM network CIDR (IPv4) (e.g. 192.168.1.0/24)",
    ),
):
    meta.config.update(
        arch=arch,
        mem_size=mem_size,
        cpu_num=cpu_num,
        iso=iso,
        enable_accel=accel,
        enable_macvlan=macvlan,
        enable_dhcp=dhcp,
        enable_vnc_web=vnc_web,
        enable_console=console,
        machine=machine,
        boot_mode=boot_mode,
        boot=boot,
        ifaces=ifaces,
        networks=[ipaddress.IPv4Network(n) for n in networks],
    )


@app.command()
def windows(
    virtio_iso: pathlib.Path = typer.Option(
        None,
        help="Window virtio driver iso, "
        "download from https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio",
        exists=True,
    ),
    tpm: bool = typer.Option(True, help="Enable TPM"),
):
    """Windows specific options"""
    if not virtio_iso:
        log.info(
            "For better Windows VM performance, consider download VirtIO driver "
            "(https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio)"
        )
    c = meta.config
    c.win_opts = meta.WinOpts(virtio_iso=virtio_iso, enable_tmp=tpm)
    if virtio_iso:
        c.qemu.append({"drive": f"file={virtio_iso},if=ide,media=cdrom,readonly=on"})
    if tpm:
        vm.setup_swtpm()
    if c.boot_mode == meta.BootMode.LEGACY:
        c.boot_mode = meta.BootMode.WINDOWS


def gen_disk_name(sn: str, type="qcow2"):
    vm_id = vm.get_vm_id()
    return f"{vm_id}@{sn}.{type}"


@app.command()
def apply_disk(
    name: str = typer.Argument(..., help="Disk name (e.g. disk1)"),
    size: str = typer.Option("16G", "-s", "--size", help="Disk size (e.g. 32G)"),
    file_type: str = typer.Option("qcow2", help="Drive file type (e.g. qcow2,raw)"),
    if_type: str = typer.Option(None, help="Drive interface type (e.g. virtio,ide)"),
    opts: str = typer.Option(
        None, help="External drive options (e.g. index=i,format=f)"
    ),
):
    """Apply VM disk"""
    c = meta.config
    name = gen_disk_name(name, file_type)
    drive_file = os.path.join(meta.STORAGE_DIR, name)
    if_type = "virtio"
    if c.is_win and not c.win_opts.virtio_iso:
        if_type = "ide"
    if not os.path.exists(drive_file):
        vm.create_drive(drive_file, size, file_type)
    else:
        log.info(f"{drive_file} already exists, skip creating")
    v = f"file={drive_file},if={if_type}"
    if opts:
        v += "," + opts
    c.qemu.append({"drive": v})
    return


@app.command()
def ext_args(args: list[str] = typer.Argument(..., help="External Qemu args")):
    """External Qemu args"""
    meta.config.extra_args += " ".join(args)


@app.command()
def port_forward(
    ports: list[str] = typer.Option(
        None, "-p", "--port", help="(multiple) Port forward spec (e.g. 80:8088)"
    ),
):
    """Forward VM ports"""
    meta.config.port_forwards = ports
