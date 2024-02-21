import ipaddress
import logging
import pathlib

import click
import typer

import meta
import vm

logging.basicConfig(format="%(asctime)s %(levelname)s:%(message)s", level=logging.INFO)


app = typer.Typer(chain=True, invoke_without_command=True)


QEMU_ARCHS = vm.get_qemu_archs()


@app.callback()
def main(
    cpu_num: int = typer.Option(None, "--cpu", help="CPU cores"),
    mem_size: int = typer.Option(None, "--mem", min=1, help="Memory size in MB"),
    arch: str = typer.Option(
        default="x86_64", help="VM arch", click_type=click.Choice(QEMU_ARCHS)
    ),
    iso: pathlib.Path = typer.Option(default=None, help="ISO file path"),
    kvm: bool = typer.Option(default=True, help="Enable KVM"),
    macvlan: bool = typer.Option(
        default=True, help="Enable macvlan network, otherwise use bridge network"
    ),
    dhcp: bool = typer.Option(default=True, help="Enable DHCP"),
    vnc_web: bool = typer.Option(default=True, help="Enable VNC web client (noVNC)"),
    console: bool = typer.Option(
        default=True, help="Enable Qemu monitor (mon+telnet+qmp)"
    ),
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
        enable_kvm=kvm,
        enable_macvlan=macvlan,
        enable_dhcp=dhcp,
        enable_vnc_web=vnc_web,
        enable_console=console,
        ifaces=ifaces,
        networks=[ipaddress.IPv4Network(n) for n in networks],
    )
    # start kvm
    vm.run_qemu()


if __name__ == "__main__":
    app()
