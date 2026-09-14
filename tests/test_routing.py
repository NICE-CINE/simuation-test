from festival_ble_sim.models import Message
from festival_ble_sim.routing.base import RoutingDecision
from festival_ble_sim.routing.epidemic import EpidemicRouting


class _FakeNode:
    def __init__(self, has_msg: bool):
        self._has_msg = has_msg

    def has_message(self, msg_id: int) -> bool:
        return self._has_msg


def _msg():
    return Message(msg_id=1, src_id=1, dst_id=2, size_bytes=100, creation_time=0.0, ttl_s=60.0)


def test_epidemic_forwards_when_contact_missing_message():
    algo = EpidemicRouting()
    holder = _FakeNode(has_msg=False)
    contact = _FakeNode(has_msg=False)
    assert algo.decide(_msg(), holder, contact) is RoutingDecision.FORWARD


def test_epidemic_ignores_when_contact_already_has_message():
    algo = EpidemicRouting()
    holder = _FakeNode(has_msg=False)
    contact = _FakeNode(has_msg=True)
    assert algo.decide(_msg(), holder, contact) is RoutingDecision.IGNORE


def test_on_delivered_default_hook_is_noop():
    algo = EpidemicRouting()
    holder = _FakeNode(has_msg=True)
    algo.on_delivered(_msg(), holder)
