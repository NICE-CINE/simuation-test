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


def test_default_select_links_puts_destinations_of_carried_messages_first():
    from festival_ble_sim.models import Message
    sender = _node(1, 0.0)
    sender.store_message(Message(msg_id=1, src_id=1, dst_id=5, size_bytes=10, creation_time=0.0, ttl_s=100.0))
    contacts = [_node(2, 9.0), _node(3, 1.0), _node(4, 5.0), _node(5, 20.0)]
    kept = EpidemicRouting().select_links(sender, contacts, 2)
    assert [c.id for c in kept] == [5, 3]
