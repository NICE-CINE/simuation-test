import math
import pytest
from dataclasses import replace
from festival_ble_sim.config import BleConfig, EnergyConfig
from festival_ble_sim.energy import EnergyModel
from festival_ble_sim.metrics import MetricsCollector
from festival_ble_sim.models import Message, Position
from festival_ble_sim.network import ChannelState, process_node_contacts
from festival_ble_sim.nodes import BaseNode
from festival_ble_sim.routing.epidemic import EpidemicRouting
from festival_ble_sim.spatial import SpatialGrid


def _node(node_id, x, y, buffer_capacity=10, battery=100.0):
    return BaseNode(node_id=node_id, position=Position(x, y), radio_range_m=20.0, buffer_capacity=buffer_capacity, battery_mah=battery)


def _energy_model():
    return EnergyModel(
        EnergyConfig(tx_cost_mah_per_event=1.0, tx_cost_mah_per_byte=0.0, rx_cost_mah_per_event=0.5, rx_cost_mah_per_byte=0.0)
    )


def _ble(**kw):
    ble = BleConfig(packet_loss_base_probability=0.0, weak_signal_max_probability=0.0)
    radio = replace(ble.phone_radio, shadowing_std_db=0.0)
    return replace(ble, phone_radio=radio, beacon_radio=radio, **kw)


def _send(channel=None, ble=None, size=10):
    sender, contact = _node(1, 0.0, 0.0), _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(contact)
    sender.store_message(Message(msg_id=1, src_id=1, dst_id=99, size_bytes=size, creation_time=0.0, ttl_s=100.0))
    metrics = MetricsCollector()
    process_node_contacts(
        now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
        energy_model=_energy_model(), metrics=metrics, ble_config=ble or _ble(), channel=channel,
    )
    return sender, contact, metrics.build_report([], 0)


def test_lossy_link_resends_instead_of_dropping():
    sender, contact, report = _send(ble=_ble(packet_loss_base_probability=0.5))
    assert contact.has_message(1)
    assert sender.battery_mah == pytest.approx(98.0)
    assert contact.battery_mah == pytest.approx(99.0)
    assert report.retransmitted_bytes == pytest.approx(10.0)


def test_outage_carries_nothing_and_costs_nothing():
    sender, contact, report = _send(ble=_ble(packet_loss_base_probability=1.0))
    assert not contact.has_message(1)
    assert sender.battery_mah == 100.0
    assert report.total_transmissions == 0


def test_load_heard_by_the_receiver_costs_retransmissions():
    half = ChannelState(heard_data={2: 79 * math.log(2)})
    sender, contact, report = _send(channel=half)
    assert contact.has_message(1)
    assert sender.battery_mah == pytest.approx(98.0)


def test_the_senders_own_duty_is_not_counted_against_it():
    own = ChannelState(heard_data={2: 1.0}, duty_data={1: 1.0})
    sender, _, report = _send(channel=own)
    assert sender.battery_mah == pytest.approx(99.0)
    assert report.retransmitted_bytes == 0.0


def test_resends_that_dont_fit_the_airtime_keep_the_message_queued():
    half = ChannelState(heard_data={2: 79 * math.log(2)})
    sender, contact, _ = _send(channel=half, ble=_ble(transfer_rate_bytes_per_s=100.0), size=60)
    assert not contact.has_message(1) and 1 in sender.buffer


def test_no_collision_cap_a_saturated_receiver_is_unreachable():
    packed = ChannelState(heard_data={2: 79 * 50.0})
    _, contact, _ = _send(channel=packed)
    assert not contact.has_message(1)


def test_load_is_last_ticks_actual_sends_seen_by_neighbors_only():
    a, b = _node(1, 0.0, 0.0), _node(2, 5.0, 0.0)
    state = ChannelState(sent_data={1: 50.0}, sent_control={2: 10.0})
    nxt = state.next_tick({1: [b], 2: [a], 3: []}, budget=100.0)
    assert nxt.duty_data == {1: 0.5} and nxt.heard_data == {2: 0.5}
    assert nxt.heard_control == {1: 0.1}
    assert nxt.sent_data == {} and 3 not in nxt.heard_data
