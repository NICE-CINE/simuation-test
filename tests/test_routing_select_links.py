from festival_ble_sim.models import Position
from festival_ble_sim.nodes import BaseNode
from festival_ble_sim.routing.epidemic import EpidemicRouting


def _node(node_id, x):
    return BaseNode(node_id=node_id, position=Position(x, 0.0), radio_range_m=30.0, buffer_capacity=10, battery_mah=100.0)


def test_default_select_links_keeps_the_nearest_contacts_first():
    sender = _node(1, 0.0)
    contacts = [_node(2, 9.0), _node(3, 1.0), _node(4, 5.0), _node(5, 20.0)]
    kept = EpidemicRouting().select_links(sender, contacts, 3)
    assert [c.id for c in kept] == [3, 4, 2]


def test_default_select_links_returns_everyone_when_under_the_cap():
    sender = _node(1, 0.0)
    contacts = [_node(2, 9.0), _node(3, 1.0)]
    assert len(EpidemicRouting().select_links(sender, contacts, 6)) == 2
