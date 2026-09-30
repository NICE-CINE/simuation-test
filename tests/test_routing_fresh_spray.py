from festival_ble_sim.models import Message
from festival_ble_sim.routing.base import RoutingDecision
from festival_ble_sim.routing.fresh_spray import FreshSprayRouting


class _Node:
    def __init__(self, node_id, is_beacon=False, battery=100.0):
        self.id = node_id
        self.is_beacon = is_beacon
        self.initial_battery_mah = 100.0
        self.battery_mah = battery
        self.buffer = {}

    def has_message(self, msg_id):
        return msg_id in self.buffer


def _msg(tokens=None):
    m = Message(msg_id=1, src_id=1, dst_id=9, size_bytes=100, creation_time=0.0, ttl_s=1800.0)
    if tokens is not None:
        m.routing_state["tokens"] = tokens
    return m


def _setup(tokens=None):
    algo = FreshSprayRouting(initial_tokens=4, met_dst_window_s=60.0)
    holder, contact = _Node(1), _Node(2)
    msg = _msg(tokens)
    holder.buffer[msg.msg_id] = msg
    algo.on_simulation_start({1: holder, 2: contact})
    return algo, holder, contact, msg


def _forward(algo, msg, holder, contact):
    copy = Message(**{**msg.__dict__, "routing_state": dict(msg.routing_state)})
    contact.buffer[copy.msg_id] = copy
    algo.on_forward(msg, holder, contact, copy)
    return copy


def test_spray_splits_tokens():
    algo, holder, contact, msg = _setup()
    assert algo.decide(msg, holder, contact, 0.0) is RoutingDecision.FORWARD
    copy = _forward(algo, msg, holder, contact)
    assert (msg.routing_state["tokens"], copy.routing_state["tokens"]) == (2, 2)


def test_last_copy_waits_without_fresher_contact():
    algo, holder, contact, msg = _setup(tokens=1)
    assert algo.decide(msg, holder, contact, 0.0) is RoutingDecision.IGNORE


def test_last_copy_handed_to_fresher_contact():
    algo, holder, contact, msg = _setup(tokens=1)
    algo.on_tick(10.0, {2: [_Node(9)]})
    assert algo.decide(msg, holder, contact, 100.0) is RoutingDecision.FORWARD
    _forward(algo, msg, holder, contact)
    assert 1 not in holder.buffer


def test_contact_that_met_dst_gets_replica_holder_keeps_copy():
    algo, holder, contact, msg = _setup(tokens=1)
    algo.on_tick(50.0, {2: [_Node(9)]})
    assert algo.decide(msg, holder, contact, 60.0) is RoutingDecision.FORWARD
    copy = _forward(algo, msg, holder, contact)
    assert 1 in holder.buffer and copy.routing_state["tokens"] == 1


def test_one_replica_to_beacon_only():
    algo, holder, _, msg = _setup(tokens=1)
    beacon, beacon2 = _Node(5, is_beacon=True), _Node(6, is_beacon=True)
    assert algo.decide(msg, holder, beacon, 0.0) is RoutingDecision.FORWARD
    _forward(algo, msg, holder, beacon)
    assert 1 in holder.buffer
    assert algo.decide(msg, holder, beacon2, 0.0) is RoutingDecision.IGNORE


def test_delivery_purges_every_buffer():
    algo, holder, contact, msg = _setup()
    _forward(algo, msg, holder, contact)
    algo.on_delivered(msg, holder)
    algo.on_tick(1.0, {2: []})
    assert not holder.buffer and not contact.buffer


def test_low_battery_contact_skipped():
    algo, holder, _, msg = _setup()
    assert algo.decide(msg, holder, _Node(3, battery=5.0), 0.0) is RoutingDecision.IGNORE
