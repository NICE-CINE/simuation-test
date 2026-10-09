import pytest
from festival_ble_sim.models import Message
from festival_ble_sim.routing.base import RoutingDecision
from festival_ble_sim.routing.prophet import ProphetRouting


class _FakeNode:
    def __init__(self, node_id, has_msg=False):
        self.id = node_id
        self._has_msg = has_msg

    def has_message(self, msg_id):
        return self._has_msg


def _msg(dst_id=99):
    return Message(msg_id=1, src_id=1, dst_id=dst_id, size_bytes=10, creation_time=0.0, ttl_s=100.0)


def _meet(algo, a, b, now):
    algo.on_tick(now, {a: [_FakeNode(b)], b: [_FakeNode(a)]})


def test_ignores_when_contact_already_has_message():
    algo = ProphetRouting()
    assert algo.decide(_msg(), _FakeNode(1), _FakeNode(2, has_msg=True), now=0.0) is RoutingDecision.IGNORE


def test_cold_start_ignores_when_neither_node_has_met_destination():
    algo = ProphetRouting()
    assert algo.decide(_msg(dst_id=99), _FakeNode(1), _FakeNode(2), now=0.0) is RoutingDecision.IGNORE


def test_encounter_is_recorded_without_any_message_to_exchange():
    algo = ProphetRouting(p_encounter_init=0.75)
    _meet(algo, 1, 2, now=0.0)
    assert algo._predictability[(1, 2)] == pytest.approx(0.75)
    assert algo._predictability[(2, 1)] == pytest.approx(0.75)


def test_decide_does_not_record_encounters():
    algo = ProphetRouting()
    algo.decide(_msg(dst_id=5), _FakeNode(1), _FakeNode(2), now=0.0)
    assert algo._predictability == {}


def test_predictability_decays_over_time():
    algo = ProphetRouting(gamma=0.9)
    _meet(algo, 1, 2, now=0.0)
    assert algo._decayed((1, 2), 10.0) < algo._decayed((1, 2), 0.0)


def test_contact_spanning_several_ticks_is_one_encounter():
    algo = ProphetRouting(p_encounter_init=0.75, gamma=1.0)
    for t in (0.0, 1.0, 2.0):
        _meet(algo, 1, 2, now=t)
    assert algo._predictability[(1, 2)] == pytest.approx(0.75)


def test_contact_resumed_after_a_gap_is_a_new_encounter():
    algo = ProphetRouting(p_encounter_init=0.75, gamma=1.0)
    _meet(algo, 1, 2, now=0.0)
    algo.on_tick(1.0, {1: [], 2: []})
    _meet(algo, 1, 2, now=2.0)
    assert algo._predictability[(1, 2)] == pytest.approx(0.75 + 0.25 * 0.75)


def test_forwards_when_contact_previously_met_destination():
    algo = ProphetRouting()
    _meet(algo, 2, 99, now=0.0)
    assert algo.decide(_msg(dst_id=99), _FakeNode(1), _FakeNode(2), now=1.0) is RoutingDecision.FORWARD


def test_ignores_when_holder_is_a_better_or_equal_carrier():
    algo = ProphetRouting()
    _meet(algo, 1, 99, now=0.0)
    assert algo.decide(_msg(dst_id=99), _FakeNode(1), _FakeNode(2), now=1.0) is RoutingDecision.IGNORE


def test_transitivity_lets_a_node_learn_from_its_contact_table():
    algo = ProphetRouting(p_encounter_init=0.75, beta=0.25, gamma=1.0, enable_transitivity=True)
    _meet(algo, 2, 99, now=0.0)
    algo.on_tick(1.0, {1: [], 2: [], 99: []})
    _meet(algo, 1, 2, now=2.0)
    assert algo._predictability[(1, 99)] == pytest.approx(0.75 * 0.75 * 0.25)
