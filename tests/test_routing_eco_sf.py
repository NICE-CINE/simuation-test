from festival_ble_sim.models import Message
from festival_ble_sim.routing.base import RoutingDecision
from festival_ble_sim.routing.eco_sf import EcoSfRouting


class _Node:
    def __init__(self, node_id, battery=100.0):
        self.id = node_id
        self.is_beacon = False
        self.is_active = True
        self.initial_battery_mah = 100.0
        self.battery_mah = battery
        self.buffer = {}

    def has_message(self, msg_id):
        return msg_id in self.buffer


def _msg(msg_id=1, src=1, copies=None, created=0.0):
    m = Message(msg_id=msg_id, src_id=src, dst_id=9, size_bytes=100, creation_time=created, ttl_s=3600.0)
    if copies is not None:
        m.routing_state["copies"] = copies
    return m


def _forward(algo, msg, holder, contact):
    copy = Message(**{**msg.__dict__, "routing_state": dict(msg.routing_state)})
    contact.buffer[copy.msg_id] = copy
    algo.on_forward(msg, holder, contact, copy)
    return copy


def _setup(contact_battery=100.0):
    # holder 1 <-> contact 2 <-> destination 9: after the beacons, contact
    # has met 9 directly, holder only knows of 9 through contact.
    algo = EcoSfRouting(seed=1)
    holder, contact, dst = _Node(1), _Node(2, battery=contact_battery), _Node(9)
    nodes = {1: holder, 2: contact, 9: dst}
    algo.on_simulation_start(nodes)
    for t in range(4):
        algo.on_tick(float(t), {1: [contact], 2: [holder, dst], 9: [contact]})
    return algo, holder, contact


def test_no_connection_before_any_beacon_is_heard():
    algo = EcoSfRouting()
    holder, contact = _Node(1), _Node(2)
    msg = _msg(copies=8)
    holder.buffer[1] = msg
    algo.on_simulation_start({1: holder, 2: contact})
    assert algo.decide(msg, holder, contact, 0.0) is RoutingDecision.IGNORE


def test_spray_gives_the_better_carrier_the_larger_share():
    algo, holder, contact = _setup()
    msg = _msg(copies=8)
    holder.buffer[1] = msg
    assert algo.decide(msg, holder, contact, 4.0) is RoutingDecision.FORWARD
    copy = _forward(algo, msg, holder, contact)
    assert (msg.routing_state["copies"], copy.routing_state["copies"]) == (2, 6)


def test_focus_hands_over_the_last_copy():
    algo, holder, contact = _setup()
    msg = _msg(copies=1)
    holder.buffer[1] = msg
    assert algo.decide(msg, holder, contact, 4.0) is RoutingDecision.FORWARD
    _forward(algo, msg, holder, contact)
    assert 1 not in holder.buffer


def test_last_copy_stays_without_utility_gain():
    algo, holder, contact = _setup()
    msg = _msg(copies=1)
    contact.buffer[1] = msg
    assert algo.decide(msg, contact, holder, 4.0) is RoutingDecision.IGNORE


def test_connect_cooldown_between_the_same_pair():
    algo, holder, contact = _setup()
    first, second, third = _msg(1, copies=8), _msg(2, copies=8), _msg(3, copies=8)
    holder.buffer.update({1: first, 2: second, 3: third})
    assert algo.decide(first, holder, contact, 4.0) is RoutingDecision.FORWARD
    assert algo.decide(second, holder, contact, 4.0) is RoutingDecision.FORWARD
    assert algo.decide(third, holder, contact, 10.0) is RoutingDecision.IGNORE
    assert algo.decide(third, holder, contact, 24.0) is RoutingDecision.FORWARD
    assert algo.stats["connections"] == 2


def test_late_message_waits_for_its_destination():
    algo, holder, contact = _setup()
    msg = _msg(copies=8, created=-700.0)
    holder.buffer[1] = msg
    assert algo.decide(msg, holder, contact, 4.0) is RoutingDecision.IGNORE


def test_low_battery_contact_takes_no_relay():
    algo, holder, contact = _setup(contact_battery=15.0)
    msg = _msg(copies=8)
    holder.buffer[1] = msg
    assert algo.decide(msg, holder, contact, 4.0) is RoutingDecision.IGNORE


def test_copy_budget_shrinks_with_density():
    algo = EcoSfRouting()
    node = _Node(1)
    crowd = [_Node(i) for i in range(100, 140)]
    algo.on_simulation_start({1: node, **{n.id: n for n in crowd}})
    neighbors = {1: crowd, **{n.id: [node] for n in crowd}}
    for t in range(4):
        algo.on_tick(float(t), neighbors)
    node.buffer[1] = _msg()
    algo.on_tick(4.0, neighbors)
    assert node.buffer[1].routing_state["copies"] == 4

    lonely_algo, lonely = EcoSfRouting(), _Node(1)
    lonely_algo.on_simulation_start({1: lonely})
    lonely.buffer[1] = _msg()
    lonely_algo.on_tick(0.0, {1: []})
    assert lonely.buffer[1].routing_state["copies"] == 16


def test_trickle_backs_off_to_i_max_and_resets_on_new_message():
    algo = EcoSfRouting()
    node = _Node(1)
    algo.on_simulation_start({1: node})
    for t in range(200):
        algo.on_tick(float(t), {1: []})
    assert algo._states[1].interval == 30.0
    node.buffer[1] = _msg()
    algo.on_tick(200.0, {1: []})
    assert algo._states[1].interval == 2.0


def test_delivery_purges_every_copy():
    algo, holder, contact = _setup()
    msg = _msg(copies=8)
    holder.buffer[1] = msg
    algo.decide(msg, holder, contact, 4.0)
    _forward(algo, msg, holder, contact)
    algo.on_delivered(msg, contact)
    algo.on_tick(5.0, {1: [contact], 2: [holder]})
    assert not holder.buffer and not contact.buffer


def test_eviction_spares_own_messages():
    algo = EcoSfRouting()
    node = _Node(1)
    own, relayed = _msg(1, src=1), _msg(2, src=5)
    node.buffer.update({1: own, 2: relayed})
    assert algo.choose_eviction(node, 10.0) == 2
