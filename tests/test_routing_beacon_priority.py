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


def test_forwards_to_beacon_and_sets_flag_once_the_copy_is_sent():
    from dataclasses import replace
    algo = BeaconPriorityRouting()
    msg = _msg()
    beacon = _FakeNode(is_beacon=True)
    assert algo.decide(msg, _FakeNode(), beacon, now=0.0) is RoutingDecision.FORWARD
    assert "reached_beacon" not in msg.routing_state
    copy = replace(msg, routing_state=dict(msg.routing_state))
    algo.on_forward(msg, _FakeNode(), beacon, copy)
    assert msg.routing_state["reached_beacon"] is True
    assert copy.routing_state["reached_beacon"] is True


def test_lost_transfer_to_a_beacon_does_not_set_the_flag():
    import random
    from festival_ble_sim.config import BleConfig, EnergyConfig
    from festival_ble_sim.energy import EnergyModel
    from festival_ble_sim.metrics import MetricsCollector
    from festival_ble_sim.models import Position
    from festival_ble_sim.network import process_node_contacts
    from festival_ble_sim.nodes import BaseNode, BeaconNode
    from festival_ble_sim.spatial import SpatialGrid

    class AlwaysLose(random.Random):
        def random(self):
            return 0.0

    phone = BaseNode(1, Position(0.0, 0.0), 30.0, 10, 3000.0)
    beacon = BeaconNode(2, Position(5.0, 0.0), 60.0, 10)
    grid = SpatialGrid(100.0, 100.0, 30.0)
    grid.insert(phone)
    grid.insert(beacon)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=100, creation_time=0.0, ttl_s=1800.0)
    phone.store_message(msg)
    process_node_contacts(
        1.0, phone, grid, BeaconPriorityRouting(), EnergyModel(EnergyConfig()), MetricsCollector(),
        ble_config=BleConfig(packet_loss_base_probability=1.0), rng=AlwaysLose(),
    )
    assert not beacon.has_message(1)
    assert "reached_beacon" not in msg.routing_state


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
