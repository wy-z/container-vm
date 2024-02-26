import ipaddress

from src import meta, utils, vm


def test_get_vm_interfaces():
    ifaces = vm.get_vm_interfaces()
    assert "eth0" in ifaces


def test_get_interface_ipnets():
    ifaces = vm.get_vm_interfaces()
    for iface in ifaces:
        ipnets = vm.get_interface_ipnets(iface)
        assert len(ipnets) > 0
        for ipnet in ipnets:
            assert ipaddress.IPv4Network(ipnet, False)


def test_setup_tap_bridge():
    iface = utils.get_default_interface()
    ipnets, _ = utils.get_interface_info(iface)
    assert ipnets
    ipnet = ipnets[0]
    mode = meta.NetworkMode.TAP_BRIDGE
    dev_name, dev_id = vm._gen_netdev_name(mode)

    tap_name = vm._setup_tap_bridge(iface, dev_name, dev_id, ipnet)
    ifaces = utils.list_interfaces()
    assert tap_name in ifaces
    assert dev_name in ifaces


def test_setup_macvlan_bridge():
    iface = utils.get_default_interface()
    ipnets, _ = utils.get_interface_info(iface)
    assert ipnets
    ipnet = ipnets[0]
    mode = meta.NetworkMode.TAP_BRIDGE
    dev_name, dev_id = vm._gen_netdev_name(mode)
    new_mac = utils.gen_random_mac()

    vtapdev = vm._setup_macvlan_bridge(iface, dev_name, dev_id, new_mac, ipnet)
    ifaces = utils.list_interfaces()
    assert vtapdev in ifaces
    assert dev_name in ifaces


def test_configure_network():
    vm.configure_network()


def test_configure_network_with_tap_mode(c):
    c.enable_macvlan = False
    vm.configure_network()
