from festival_ble_sim.models import Message, Position
from festival_ble_sim.routing.base import RoutingDecision
from festival_ble_sim.routing.horizon import HorizonRouting


class _Node:
    def __init__(self, node_id, x=0.0, is_beacon=False):
        self.id = node_id
        self.is_beacon = is_beacon
        self.position = Position(x, 0.0)
        self.battery_capacity_mah = 100.0
        self.battery_mah = 100.0
        self.buffer = {}

    @property
    def battery_fraction(self):
        return self.battery_mah / self.battery_capacity_mah

    def has_message(self, msg_id):
        return msg_id in self.buffer


def _line(algo, n=5):
    # 1 - 2 - 3 - 4 - 5 on a line, 10 m apart, plus 6 hanging off 1.
    nodes = {i: _Node(i, x=10.0 * i) for i in range(1, n + 1)}
    nodes[6] = _Node(6, x=5.0)
    links = {i: [nodes[j] for j in (i - 1, i + 1) if j in nodes and j <= n] for i in range(1, n + 1)}
    links[1].append(nodes[6])
    links[6] = [nodes[1]]
    algo.on_simulation_start(nodes)
    return nodes, links


def _tick(algo, now, links, lost=()):
    # What network_engine does: on_tick, then deliver the tick's broadcasts
    # to the sender's neighbors unless the (sender, receiver) pair is lost.
    algo.on_tick(now, links)
    sizes = algo.control_broadcasts(now)
    received = {}
    for sender_id in sizes:
        for n in links.get(sender_id, ()):
            if (sender_id, n.id) not in lost:
                received.setdefault(n.id, []).append(sender_id)
    algo.on_control_received(now, received)
    return sizes


def _settle(algo, links, until=40, start=0, lost=()):
    for t in range(start, until):
        _tick(algo, float(t), links, lost)


def _msg(hops=0, ttl_hops=8, tokens=None):
    m = Message(msg_id=1, src_id=1, dst_id=5, size_bytes=100, creation_time=0.0, ttl_s=1800.0,
                hops=hops, ttl_hops=ttl_hops)
    if tokens is not None:
        m.routing_state["tokens"] = tokens
    return m


def _forward(algo, msg, holder, contact):
    copy = Message(**{**msg.__dict__, "routing_state": dict(msg.routing_state)})
    contact.buffer[copy.msg_id] = copy
    algo.on_forward(msg, holder, contact, copy)
    return copy


def test_distance_field_converges_over_jittered_rounds():
    algo = HorizonRouting(horizon_hops=5)
    nodes, links = _line(algo)
    _settle(algo, links)
    assert algo._dist[1][5] == 4 and algo._dist[6][5] == 5


def test_each_node_announces_once_per_period_at_its_own_phase():
    algo = HorizonRouting(announce_period_s=5.0, announce_entry_bytes=5)
    nodes, links = _line(algo)
    _settle(algo, links, until=20)
    seen = {}
    for t in range(20, 25):
        sizes = _tick(algo, float(t), links)
        assert len(sizes) < len(links)
        for node_id, size in sizes.items():
            seen[node_id] = seen.get(node_id, 0) + 1
            assert size == 5 * len(algo._vectors[node_id])
    assert seen == {node_id: 1 for node_id in links}


def test_copy_moves_down_the_gradient_only():
    algo = HorizonRouting()
    nodes, links = _line(algo)
    _settle(algo, links)
    msg = _msg(tokens=4)
    nodes[1].buffer[1] = msg
    assert algo.decide(msg, nodes[1], nodes[6], 30.0) is RoutingDecision.IGNORE
    assert algo.decide(msg, nodes[1], nodes[2], 30.0) is RoutingDecision.FORWARD
    copy = _forward(algo, msg, nodes[1], nodes[2])
    assert 1 not in nodes[1].buffer and copy.routing_state["tokens"] == 4
    assert algo.stats["pull"] == 1


def test_no_pull_when_hop_ttl_cannot_reach_destination():
    algo = HorizonRouting()
    nodes, links = _line(algo)
    _settle(algo, links)
    msg = _msg(hops=6, tokens=4)  # 1 -> 5 needs 3 relays then a direct delivery: 6 + 3 > 8
    nodes[1].buffer[1] = msg
    assert algo.decide(msg, nodes[1], nodes[2], 30.0) is RoutingDecision.IGNORE


def test_hop_reserve_stops_spray_outside_horizon():
    algo = HorizonRouting(horizon_hops=5)
    nodes, links = _line(algo)
    msg = _msg(hops=3, tokens=4)
    nodes[1].buffer[1] = msg
    assert algo.decide(msg, nodes[1], nodes[6], 0.0) is RoutingDecision.IGNORE
    assert algo.decide(_msg(hops=2, tokens=4), nodes[1], nodes[6], 0.0) is RoutingDecision.FORWARD


def test_select_links_puts_next_hop_first():
    algo = HorizonRouting()
    nodes, links = _line(algo)
    _settle(algo, links)
    nodes[1].buffer[1] = _msg(tokens=4)
    assert [n.id for n in algo.select_links(nodes[1], [nodes[6], nodes[2]], 1)] == [2]


def test_route_survives_a_lost_announce_but_expires_after_entry_ttl():
    algo = HorizonRouting(entry_ttl_s=15.0)
    nodes, links = _line(algo)
    _settle(algo, links)
    _settle(algo, links, start=40, until=46, lost={(2, 1)})
    assert algo._dist[1].get(5) == 4
    _settle(algo, links, start=46, until=70, lost={(2, 1)})
    assert 5 not in algo._dist[1]


def test_pull_uses_the_vector_heard_not_the_neighbors_live_table():
    algo = HorizonRouting()
    nodes, links = _line(algo)
    _settle(algo, links, lost={(2, 1)})
    msg = _msg(tokens=4)
    nodes[1].buffer[1] = msg
    assert algo._dist[2][5] == 3
    assert algo._next_hop(nodes[1], 5) is None


def test_announce_is_capped_to_the_nearest_destinations():
    algo = HorizonRouting(announce_entry_bytes=5, max_announce_bytes=10)
    nodes, links = _line(algo)
    _settle(algo, links)
    assert len(algo._dist[1]) > 2
    assert algo._vectors[1] == {1: (0, 1), 2: (1, 2)}
    assert algo._heard[2][1][0] == algo._vectors[1]


def test_vector_heard_over_a_one_way_link_is_ignored():
    algo = HorizonRouting()
    nodes, links = _line(algo)
    nodes[7] = _Node(7, x=30.0, is_beacon=True)
    links[7] = [nodes[1], nodes[5]]
    links[5].append(nodes[7])
    algo.on_simulation_start(nodes)
    _settle(algo, links)
    assert algo._dist[1][5] == 4 and 7 not in algo._heard[1]


def test_pull_from_a_beacon_hands_out_a_single_token():
    algo = HorizonRouting()
    nodes, links = _line(algo)
    nodes[1].is_beacon = True
    _settle(algo, links)
    msg = _msg(tokens=16)
    nodes[1].buffer[1] = msg
    assert algo.decide(msg, nodes[1], nodes[2], 30.0) is RoutingDecision.FORWARD
    copy = _forward(algo, msg, nodes[1], nodes[2])
    assert 1 in nodes[1].buffer and copy.routing_state["tokens"] == 1


def test_route_to_a_departed_node_does_not_count_up():
    algo = HorizonRouting(entry_ttl_s=15.0)
    nodes, links = _line(algo)
    _settle(algo, links)
    links[4] = [nodes[3]]
    del links[5]
    for t in range(40, 80):
        _tick(algo, float(t), links)
        assert all(algo._dist[i].get(5, 0) <= {1: 4, 2: 3, 3: 2, 4: 1, 6: 5}[i] for i in algo._dist if i != 5)
    assert not any(5 in algo._dist[i] for i in algo._dist if i != 5)
