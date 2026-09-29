import pytest
from festival_ble_sim.config import EnergyConfig
from festival_ble_sim.energy import EnergyModel
from festival_ble_sim.metrics import MetricsCollector
from festival_ble_sim.models import Message, Position
from festival_ble_sim.network import process_node_contacts
from festival_ble_sim.nodes import BaseNode
from festival_ble_sim.routing.base import RoutingDecision
from festival_ble_sim.routing.spray_and_wait import SprayAndWaitRouting
from festival_ble_sim.spatial import SpatialGrid


class _FakeNode:
    def __init__(self, has_msg=False):
        self._has_msg = has_msg

    def has_message(self, msg_id):
        return self._has_msg


def _msg(copies_left=None):
    message = Message(msg_id=1, src_id=1, dst_id=2, size_bytes=100, creation_time=0.0, ttl_s=60.0)
    if copies_left is not None:
        message.routing_state["copies_left"] = copies_left
    return message


def test_initial_copies_must_be_at_least_two():
    with pytest.raises(ValueError):
        SprayAndWaitRouting(initial_copies=1)


def test_forwards_when_copies_left_above_one():
    algo = SprayAndWaitRouting(initial_copies=8)
    assert algo.decide(_msg(), _FakeNode(), _FakeNode(), now=0.0) is RoutingDecision.FORWARD


def test_ignores_in_wait_phase():
    algo = SprayAndWaitRouting(initial_copies=8)
    msg = _msg(copies_left=1)
    assert algo.decide(msg, _FakeNode(), _FakeNode(), now=0.0) is RoutingDecision.IGNORE


def test_ignores_when_contact_already_has_message():
    algo = SprayAndWaitRouting()
    assert algo.decide(_msg(), _FakeNode(), _FakeNode(has_msg=True), now=0.0) is RoutingDecision.IGNORE


def test_on_forward_splits_copies_asymmetrically_for_odd_count():
    algo = SprayAndWaitRouting()
    holder_msg = _msg(copies_left=7)
    forwarded_copy = _msg(copies_left=7)
    algo.on_forward(holder_msg, _FakeNode(), _FakeNode(), forwarded_copy)
    assert holder_msg.routing_state["copies_left"] == 3
    assert forwarded_copy.routing_state["copies_left"] == 4
    assert holder_msg.routing_state["copies_left"] + forwarded_copy.routing_state["copies_left"] == 7


def test_engine_integration_splits_copies_between_holder_and_contact():
    sender = BaseNode(node_id=1, position=Position(0.0, 0.0), radio_range_m=20.0, buffer_capacity=10, battery_mah=100.0)
    contact = BaseNode(node_id=2, position=Position(5.0, 0.0), radio_range_m=20.0, buffer_capacity=10, battery_mah=100.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(contact)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    msg.routing_state["copies_left"] = 8
    sender.store_message(msg)
    metrics = MetricsCollector()
    energy_model = EnergyModel(EnergyConfig())
    algo = SprayAndWaitRouting(initial_copies=8)
    process_node_contacts(now=1.0, sender=sender, grid=grid, routing_algorithm=algo, energy_model=energy_model, metrics=metrics)
    assert sender.buffer[1].routing_state["copies_left"] == 4
    assert contact.buffer[1].routing_state["copies_left"] == 4


def test_engine_integration_wait_phase_stops_flooding():
    sender = BaseNode(node_id=1, position=Position(0.0, 0.0), radio_range_m=20.0, buffer_capacity=10, battery_mah=100.0)
    contact = BaseNode(node_id=2, position=Position(5.0, 0.0), radio_range_m=20.0, buffer_capacity=10, battery_mah=100.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(contact)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    msg.routing_state["copies_left"] = 1
    sender.store_message(msg)
    metrics = MetricsCollector()
    energy_model = EnergyModel(EnergyConfig())
    algo = SprayAndWaitRouting(initial_copies=8)
    process_node_contacts(now=1.0, sender=sender, grid=grid, routing_algorithm=algo, energy_model=energy_model, metrics=metrics)
    assert contact.has_message(1) is False
