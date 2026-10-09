import pytest
from festival_ble_sim.config import BleConfig, EnergyConfig
from festival_ble_sim.energy import EnergyModel
from festival_ble_sim.metrics import MetricsCollector
from festival_ble_sim.models import Message, Position
from festival_ble_sim.network import process_node_contacts
from festival_ble_sim.nodes import BaseNode
from festival_ble_sim.routing.band_fanout import BandFanoutRouting
from festival_ble_sim.routing.base import RoutingDecision
from festival_ble_sim.spatial import SpatialGrid

RANGE_M = 30.0
ORIGIN_X = 50.0


def _node(node_id, distance_m=0.0):
    return BaseNode(
        node_id=node_id,
        position=Position(ORIGIN_X + distance_m, 50.0),
        radio_range_m=RANGE_M,
        buffer_capacity=10,
        battery_mah=100.0,
    )


def _msg(dst_id=99, fanout_left=None, hops=0):
    message = Message(msg_id=1, src_id=1, dst_id=dst_id, size_bytes=10, creation_time=0.0, ttl_s=1000.0, hops=hops)
    if fanout_left is not None:
        message.routing_state["fanout_left"] = fanout_left
    return message


def _world(algo, distances):
    holder = _node(1)
    contacts = [_node(10 + i, d) for i, d in enumerate(distances)]
    nodes = {n.id: n for n in [holder] + contacts}
    algo.on_simulation_start(nodes)
    return holder, contacts


def _tick(algo, holder, contacts):
    if not holder.buffer:
        holder.store_message(_msg())
    algo.on_tick(0.0, {holder.id: list(contacts)})


def _selected(algo, holder, contacts, message=None):
    message = message or _msg()
    return {c.id for c in contacts if algo.decide(message, holder, c, now=0.0) is RoutingDecision.FORWARD}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fanout": 0},
        {"max_hops": 0},
        {"band": (0.6, 0.4)},
        {"band": (-0.1, 0.5)},
        {"band": (0.4, 0.4)},
    ],
)
def test_invalid_parameters_are_rejected(kwargs):
    with pytest.raises(ValueError):
        BandFanoutRouting(**kwargs)


def test_prefers_contact_inside_the_band():
    algo = BandFanoutRouting(fanout=1)
    holder, contacts = _world(algo, [3.0, 15.0, 28.0])
    _tick(algo, holder, contacts)
    assert _selected(algo, holder, contacts) == {contacts[1].id}


def test_fills_with_contacts_closest_to_the_band_when_band_is_short():
    algo = BandFanoutRouting(fanout=2)
    holder, contacts = _world(algo, [3.0, 15.0, 28.0])
    _tick(algo, holder, contacts)
    assert _selected(algo, holder, contacts) == {contacts[0].id, contacts[1].id}


def test_picks_exactly_fanout_contacts_among_those_in_band():
    algo = BandFanoutRouting(fanout=2)
    holder, contacts = _world(algo, [13.0, 14.0, 15.0, 16.0, 17.0, 3.0])
    _tick(algo, holder, contacts)
    chosen = _selected(algo, holder, contacts)
    assert len(chosen) == 2
    assert chosen <= {c.id for c in contacts[:5]}


def test_choice_among_band_contacts_is_random_but_seeded():
    def run(seed):
        algo = BandFanoutRouting(fanout=2, seed=seed)
        holder, contacts = _world(algo, [13.0, 14.0, 15.0, 16.0, 17.0])
        _tick(algo, holder, contacts)
        return _selected(algo, holder, contacts)

    assert run(7) == run(7)
    assert len({frozenset(run(seed)) for seed in range(20)}) > 1


def test_selection_ranks_every_neighbor_not_only_the_nearest():
    algo = BandFanoutRouting(fanout=1)
    holder, contacts = _world(algo, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 15.0])
    _tick(algo, holder, contacts)
    assert _selected(algo, holder, contacts) == {contacts[6].id}


def test_select_links_keeps_chosen_relays_beyond_the_nearest_links():
    algo = BandFanoutRouting(fanout=1)
    holder, contacts = _world(algo, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 15.0])
    _tick(algo, holder, contacts)
    kept = algo.select_links(holder, contacts, 6)
    assert len(kept) == 6
    assert contacts[6] in kept
    assert [c.id for c in kept if c is not contacts[6]] == [c.id for c in contacts[:5]]


def test_select_links_never_exceeds_max_links():
    algo = BandFanoutRouting(fanout=3)
    holder, contacts = _world(algo, [13.0, 14.0, 15.0, 16.0, 17.0])
    _tick(algo, holder, contacts)
    assert len(algo.select_links(holder, contacts, 2)) == 2


def test_select_links_falls_back_to_nearest_without_a_selection():
    algo = BandFanoutRouting(fanout=1)
    holder, contacts = _world(algo, [9.0, 1.0, 5.0, 15.0])
    kept = algo.select_links(holder, contacts, 2)
    assert [c.id for c in kept] == [contacts[1].id, contacts[2].id]


def test_selection_is_rebuilt_every_tick():
    algo = BandFanoutRouting(fanout=1)
    holder, contacts = _world(algo, [15.0])
    _tick(algo, holder, contacts)
    assert _selected(algo, holder, contacts) == {contacts[0].id}
    algo.on_tick(1.0, {holder.id: []})
    assert _selected(algo, holder, contacts) == set()


def test_holder_with_empty_buffer_gets_no_selection():
    algo = BandFanoutRouting(fanout=1)
    holder, contacts = _world(algo, [15.0])
    algo.on_tick(0.0, {holder.id: list(contacts)})
    assert _selected(algo, holder, contacts) == set()


def test_ignores_before_any_tick_selection():
    algo = BandFanoutRouting()
    holder, contacts = _world(algo, [15.0])
    assert _selected(algo, holder, contacts) == set()


def test_ignores_contact_that_already_has_the_message():
    algo = BandFanoutRouting(fanout=1)
    holder, contacts = _world(algo, [15.0])
    contacts[0].store_message(_msg())
    _tick(algo, holder, contacts)
    assert _selected(algo, holder, contacts) == set()


def test_ignores_when_algorithm_hop_limit_reached():
    algo = BandFanoutRouting(fanout=1, max_hops=2)
    holder, contacts = _world(algo, [15.0])
    _tick(algo, holder, contacts)
    assert _selected(algo, holder, contacts, _msg(hops=1)) == {contacts[0].id}
    assert _selected(algo, holder, contacts, _msg(hops=2)) == set()


def test_ignores_when_fanout_budget_is_spent():
    algo = BandFanoutRouting(fanout=3)
    holder, contacts = _world(algo, [15.0])
    _tick(algo, holder, contacts)
    assert _selected(algo, holder, contacts, _msg(fanout_left=0)) == set()


def test_on_forward_spends_one_relay_and_gives_the_copy_a_fresh_budget():
    algo = BandFanoutRouting(fanout=3)
    holder, contacts = _world(algo, [15.0])
    original = _msg(fanout_left=2)
    forwarded = _msg(fanout_left=2)
    algo.on_forward(original, holder, contacts[0], forwarded)
    assert original.routing_state["fanout_left"] == 1
    assert forwarded.routing_state["fanout_left"] == 3


def test_fresh_message_uses_the_configured_fanout_as_budget():
    algo = BandFanoutRouting(fanout=4)
    holder, contacts = _world(algo, [15.0])
    original = _msg()
    forwarded = _msg()
    algo.on_forward(original, holder, contacts[0], forwarded)
    assert original.routing_state["fanout_left"] == 3
    assert forwarded.routing_state["fanout_left"] == 4


def _engine_world(algo, distances):
    holder, contacts = _world(algo, distances)
    grid = SpatialGrid(200.0, 200.0, cell_size_m=RANGE_M)
    grid.insert(holder)
    for c in contacts:
        grid.insert(c)
    return holder, contacts, grid


def _run_tick(algo, holder, contacts, grid, now):
    algo.on_tick(now, {holder.id: grid.get_nearby(holder, holder.radio_range_m)})
    process_node_contacts(
        now=now,
        sender=holder,
        grid=grid,
        routing_algorithm=algo,
        energy_model=EnergyModel(EnergyConfig()),
        metrics=MetricsCollector(),
    )


def test_engine_integration_relays_to_fanout_contacts_then_waits():
    algo = BandFanoutRouting(fanout=2, seed=3)
    holder, contacts, grid = _engine_world(algo, [13.0, 14.0, 15.0, 16.0, 17.0])
    holder.store_message(_msg())

    _run_tick(algo, holder, contacts, grid, now=1.0)
    holders = [c for c in contacts if c.has_message(1)]
    assert len(holders) == 2
    assert holder.buffer[1].routing_state["fanout_left"] == 0
    assert all(c.buffer[1].routing_state["fanout_left"] == 2 for c in holders)
    assert all(c.buffer[1].hops == 1 for c in holders)

    _run_tick(algo, holder, contacts, grid, now=2.0)
    assert len([c for c in contacts if c.has_message(1)]) == 2


def test_engine_integration_still_delivers_to_destination_after_budget_is_spent():
    algo = BandFanoutRouting(fanout=1)
    holder, contacts, grid = _engine_world(algo, [3.0])
    destination = contacts[0]
    holder.store_message(_msg(dst_id=destination.id, fanout_left=0))
    _run_tick(algo, holder, contacts, grid, now=1.0)
    assert destination.has_message(1)


def test_delivery_removes_the_holders_copy():
    algo = BandFanoutRouting()
    holder, _ = _world(algo, [15.0])
    holder.store_message(_msg())
    algo.on_delivered(_msg(), holder)
    assert not holder.has_message(1)


def test_next_tick_purges_delivered_message_from_every_buffer():
    algo = BandFanoutRouting()
    holder, contacts = _world(algo, [15.0, 16.0])
    for node in [holder] + contacts:
        node.store_message(_msg())
    algo.on_delivered(_msg(), contacts[1])
    assert holder.has_message(1) and contacts[0].has_message(1)
    algo.on_tick(1.0, {node.id: [] for node in [holder] + contacts})
    assert not any(node.has_message(1) for node in [holder] + contacts)


def test_purge_leaves_other_messages_alone():
    algo = BandFanoutRouting()
    holder, _ = _world(algo, [15.0])
    other = Message(msg_id=2, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=1000.0)
    holder.store_message(_msg())
    holder.store_message(other)
    algo.on_delivered(_msg(), holder)
    algo.on_tick(1.0, {holder.id: []})
    assert holder.has_message(2)


def test_delivered_message_is_never_forwarded_again():
    algo = BandFanoutRouting(fanout=1)
    holder, contacts = _world(algo, [15.0])
    _tick(algo, holder, contacts)
    algo.on_delivered(_msg(), contacts[0])
    assert _selected(algo, holder, contacts) == set()


def test_purge_can_be_disabled():
    algo = BandFanoutRouting(fanout=1, purge_delivered=False)
    holder, contacts = _world(algo, [15.0])
    holder.store_message(_msg())
    algo.on_delivered(_msg(), contacts[0])
    algo.on_tick(1.0, {holder.id: list(contacts)})
    assert holder.has_message(1)
    assert _selected(algo, holder, contacts) == {contacts[0].id}


def test_engine_integration_relay_beyond_the_link_cap_receives_the_copy():
    algo = BandFanoutRouting(fanout=1)
    holder, contacts, grid = _engine_world(algo, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 15.0])
    holder.store_message(_msg())
    algo.on_tick(1.0, {holder.id: grid.get_nearby(holder, holder.radio_range_m)})
    process_node_contacts(
        now=1.0,
        sender=holder,
        grid=grid,
        routing_algorithm=algo,
        energy_model=EnergyModel(EnergyConfig()),
        metrics=MetricsCollector(),
        ble_config=BleConfig(max_concurrent_links=6),
    )
    assert [c.id for c in contacts if c.has_message(1)] == [contacts[6].id]
