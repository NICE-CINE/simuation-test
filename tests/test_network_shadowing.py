import random
import pytest
from festival_ble_sim.config import BleConfig, EnergyConfig, RadioParams
from festival_ble_sim.energy import EnergyModel
from festival_ble_sim.metrics import MetricsCollector
from festival_ble_sim.models import Message, Position
from festival_ble_sim.network import process_node_contacts
from festival_ble_sim.nodes import BaseNode
from festival_ble_sim.radio import max_range_m
from festival_ble_sim.routing.epidemic import EpidemicRouting
from festival_ble_sim.spatial import SpatialGrid


def _node(node_id, x, y, buffer_capacity=10, battery=100.0):
    return BaseNode(node_id=node_id, position=Position(x, y), radio_range_m=1000.0, buffer_capacity=buffer_capacity, battery_mah=battery)


def _energy_model():
    return EnergyModel(
        EnergyConfig(tx_cost_mah_per_event=1.0, tx_cost_mah_per_byte=0.0, rx_cost_mah_per_event=0.5, rx_cost_mah_per_byte=0.0)
    )


def _shadowed_radio(std_db: float) -> RadioParams:
    return RadioParams(
        tx_power_dbm=0.0, path_loss_exponent=2.0, reference_distance_m=1.0,
        reference_loss_db=40.0, receiver_sensitivity_dbm=-90.0, shadowing_std_db=std_db,
    )


def test_zero_shadowing_never_causes_outage_within_deterministic_range():
    radio = _shadowed_radio(0.0)
    ble_config = BleConfig(
        phone_radio=radio, beacon_radio=radio,
        packet_loss_base_probability=0.0, packet_loss_congestion_coefficient=0.0,
        weak_signal_max_probability=0.0, packet_loss_max_probability=1.0,
        relay_backoff_coefficient=0.0, collision_loss_coefficient=0.0,
    )
    range_m = max_range_m(radio)
    for seed in range(50):
        sender = _node(1, 0.0, 0.0)
        contact = _node(2, range_m * 0.5, 0.0)
        grid = SpatialGrid(2000.0, 2000.0, cell_size_m=1000.0)
        grid.insert(sender)
        grid.insert(contact)
        msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
        sender.store_message(msg)
        process_node_contacts(
            now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
            energy_model=_energy_model(), metrics=MetricsCollector(), ble_config=ble_config,
            rng=random.Random(seed),
        )
        assert contact.has_message(1) is True


def test_shadowing_causes_intermittent_outage_near_deterministic_edge_of_range():
    radio = _shadowed_radio(8.0)
    ble_config = BleConfig(
        phone_radio=radio, beacon_radio=radio,
        packet_loss_base_probability=0.0, packet_loss_congestion_coefficient=0.0,
        weak_signal_max_probability=0.0, packet_loss_max_probability=1.0,
        relay_backoff_coefficient=0.0, collision_loss_coefficient=0.0,
    )
    range_m = max_range_m(radio)
    losses = 0
    trials = 300
    for seed in range(trials):
        sender = _node(1, 0.0, 0.0)
        contact = _node(2, range_m * 0.95, 0.0)
        grid = SpatialGrid(2000.0, 2000.0, cell_size_m=1000.0)
        grid.insert(sender)
        grid.insert(contact)
        msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
        sender.store_message(msg)
        process_node_contacts(
            now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
            energy_model=_energy_model(), metrics=MetricsCollector(), ble_config=ble_config,
            rng=random.Random(seed),
        )
        if not contact.has_message(1):
            losses += 1
    loss_rate = losses / trials
    assert 0.1 < loss_rate < 0.9


def test_outage_bypasses_packet_loss_max_probability_cap():
    radio = _shadowed_radio(20.0)
    ble_config = BleConfig(
        phone_radio=radio, beacon_radio=radio,
        packet_loss_base_probability=0.0, packet_loss_congestion_coefficient=0.0,
        weak_signal_max_probability=0.0, packet_loss_max_probability=0.05,
        relay_backoff_coefficient=0.0, collision_loss_coefficient=0.0,
    )
    range_m = max_range_m(radio)
    losses = 0
    trials = 200
    for seed in range(trials):
        sender = _node(1, 0.0, 0.0)
        contact = _node(2, range_m * 1.5, 0.0)
        grid = SpatialGrid(3000.0, 3000.0, cell_size_m=1500.0)
        sender.radio_range_m = range_m * 2.0
        grid.insert(sender)
        grid.insert(contact)
        msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
        sender.store_message(msg)
        process_node_contacts(
            now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
            energy_model=_energy_model(), metrics=MetricsCollector(), ble_config=ble_config,
            rng=random.Random(seed),
        )
        if not contact.has_message(1):
            losses += 1
    # Deterministic margin here is already well negative; even a tiny
    # packet_loss_max_probability cap must not water this down.
    assert losses / trials > 0.5
