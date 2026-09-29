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


def test_ignores_when_contact_already_has_message():
    algo = ProphetRouting()
    assert algo.decide(_msg(), _FakeNode(1), _FakeNode(2, has_msg=True), now=0.0) is RoutingDecision.IGNORE


def test_cold_start_ignores_when_neither_node_has_met_destination():
    algo = ProphetRouting()
    assert algo.decide(_msg(dst_id=99), _FakeNode(1), _FakeNode(2), now=0.0) is RoutingDecision.IGNORE


def test_encounter_updates_predictability_symmetrically():
    algo = ProphetRouting(p_encounter_init=0.75)
    algo.decide(_msg(dst_id=5), _FakeNode(1), _FakeNode(2), now=0.0)
    assert algo._predictability[(1, 2)] == pytest.approx(0.75)
    assert algo._predictability[(2, 1)] == pytest.approx(0.75)


def test_predictability_decays_over_time():
    algo = ProphetRouting(gamma=0.9)
    algo.decide(_msg(dst_id=5), _FakeNode(1), _FakeNode(2), now=0.0)
    p_immediate = algo._decayed((1, 2), 0.0)
    p_later = algo._decayed((1, 2), 10.0)
    assert p_later < p_immediate


def test_repeated_calls_same_tick_do_not_double_update():
    algo = ProphetRouting()
    algo.decide(_msg(dst_id=5), _FakeNode(1), _FakeNode(2), now=0.0)
    p_after_first = algo._predictability[(1, 2)]
    algo.decide(_msg(dst_id=6), _FakeNode(1), _FakeNode(2), now=0.0)
    assert algo._predictability[(1, 2)] == pytest.approx(p_after_first)


def test_forwards_when_contact_previously_met_destination():
    algo = ProphetRouting()
    # Node 2 meets the destination (id 99) directly first, building up its
    # own predictability of reaching it.
    algo.decide(_msg(dst_id=99), _FakeNode(2), _FakeNode(99), now=0.0)
    # Node 1 (holder) has never met the destination; node 2 (contact) has.
    assert algo.decide(_msg(dst_id=99), _FakeNode(1), _FakeNode(2), now=1.0) is RoutingDecision.FORWARD


def test_ignores_when_holder_is_a_better_or_equal_carrier():
    algo = ProphetRouting()
    # Node 1 (holder) already met the destination; node 2 (contact) has not.
    algo.decide(_msg(dst_id=99), _FakeNode(1), _FakeNode(99), now=0.0)
    assert algo.decide(_msg(dst_id=99), _FakeNode(1), _FakeNode(2), now=1.0) is RoutingDecision.IGNORE
