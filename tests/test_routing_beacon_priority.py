from festival_ble_sim.models import Message
from festival_ble_sim.routing.base import RoutingDecision
from festival_ble_sim.routing.beacon_priority import BeaconPriorityRouting
from festival_ble_sim.routing.epidemic import EpidemicRouting


class _FakeNode:
    def __init__(self, has_msg=False, is_beacon=False):
        self._has_msg = has_msg
        self.is_beacon = is_beacon

    def has_message(self, msg_id):
        return self._has_msg


def _msg():
    return Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=100.0)


def test_ignores_when_contact_already_has_message():
    algo = BeaconPriorityRouting()
    assert algo.decide(_msg(), _FakeNode(), _FakeNode(has_msg=True), now=0.0) is RoutingDecision.IGNORE


def test_forwards_to_beacon_and_sets_flag():
    algo = BeaconPriorityRouting()
    msg = _msg()
    assert algo.decide(msg, _FakeNode(), _FakeNode(is_beacon=True), now=0.0) is RoutingDecision.FORWARD
    assert msg.routing_state["reached_beacon"] is True


def test_floods_other_phones_before_reaching_any_beacon():
    algo = BeaconPriorityRouting()
    assert algo.decide(_msg(), _FakeNode(), _FakeNode(), now=0.0) is RoutingDecision.FORWARD


def test_stops_flooding_phones_once_reached_beacon():
    algo = BeaconPriorityRouting()
    msg = _msg()
    msg.routing_state["reached_beacon"] = True
    assert algo.decide(msg, _FakeNode(), _FakeNode(), now=0.0) is RoutingDecision.IGNORE


def test_keeps_forwarding_to_further_beacons_even_after_flag_set():
    algo = BeaconPriorityRouting()
    msg = _msg()
    msg.routing_state["reached_beacon"] = True
    assert algo.decide(msg, _FakeNode(), _FakeNode(is_beacon=True), now=0.0) is RoutingDecision.FORWARD


def test_degenerates_to_epidemic_without_any_beacon_in_the_run():
    beacon_priority = BeaconPriorityRouting()
    epidemic = EpidemicRouting()
    holder, phone = _FakeNode(), _FakeNode()
    assert beacon_priority.decide(_msg(), holder, phone, now=0.0) == epidemic.decide(_msg(), holder, phone, now=0.0)
