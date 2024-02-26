from src import meta, utils


def test_help(cli):
    ret = cli(["run", "--help"])
    assert ret.exit_code == 0


def test_opts(cli, c):
    iface = utils.get_default_interface()
    ipnets, _ = utils.get_interface_info(iface)
    ipnet = ipnets[0]
    ret = cli(
        [
            "run",
            "--dry",
            "--cpu=2",
            "--mem=1024",
            "--arch=aarch64",
            "--no-accel",
            "--no-macvlan",
            "--no-netdev",
            "--no-dhcp",
            "--no-vnc-web",
            "--no-console",
            "--machine=virt",
            "--boot=order=dc",
            f"--boot-mode={meta.BootMode.SECURE}",
            f"--network={ipnet}",
            f"--network={ipnet}",
            f"--iface={iface}",
            f"--iface={iface}",
        ]
    )
    assert ret.exit_code == 0
    assert c.cpu_num == 2
    assert c.mem_size == 1024
    assert c.arch == "aarch64"
    assert c.enable_accel == False
    assert c.enable_macvlan == False
    assert c.setup_netdev == False
    assert c.enable_dhcp == False
    assert c.enable_vnc_web == False
    assert c.enable_console == False
    assert c.machine == "virt"
    assert c.boot == "order=dc"
    assert c.boot_mode == meta.BootMode.SECURE
    assert len(c.networks) == 2
    assert len(c.ifaces) == 2
