import dataclasses
import math
import random
import pytest
import simpy
from festival_ble_sim.config import BleConfig, EnergyConfig
from festival_ble_sim.energy import EnergyModel
from festival_ble_sim.metrics import MetricsCollector
from festival_ble_sim.models import Message, Position
from festival_ble_sim.network import (
    _Fades, _link_failure_probability, _pair_fade_db, _update_crowd, network_engine,
)
from festival_ble_sim.nodes import BaseNode, BeaconNode
from festival_ble_sim.radio import crowd_range_m, max_range_m
from festival_ble_sim.routing.epidemic import EpidemicRouting
from festival_ble_sim.spatial import SpatialGrid


def _node(node_id, x, y, radio_range_m=1000.0):
    return BaseNode(node_id=node_id, position=Position(x, y), radio_range_m=radio_range_m, buffer_capacity=10, battery_mah=1e6)


def _crowd_ble(**kwargs):
    radio = dataclasses.replace(BleConfig().phone_radio, path_loss_exponent=1.8, tx_power_dbm=-19.4, shadowing_std_db=0.0)
    return BleConfig(phone_radio=radio, body_loss_db=0.8, **kwargs)


def _setup_energy():
    return EnergyModel(EnergyConfig(
        tx_cost_mah_per_event=0.0, tx_cost_mah_per_byte=0.0, rx_cost_mah_per_event=0.0, rx_cost_mah_per_byte=0.0,
        connection_setup_mah=1.0, extra_connection_current_ma=0.0,
    ))


def _engine(nodes, ble, until, energy=None, rng=None):
    grid = SpatialGrid(200.0, 200.0, cell_size_m=50.0)
    for node in nodes.values():
        grid.insert(node)
    env = simpy.Environment()
    env.process(network_engine(
        env, nodes, grid, EpidemicRouting(), energy or _setup_energy(), MetricsCollector(), 1.0, ble_config=ble, rng=rng,
    ))
    env.run(until=until)
    return env


def _pair_with_one_message():
    a, b = _node(1, 0.0, 0.0), _node(2, 5.0, 0.0)
    a.store_message(Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=1e6))
    return a, b


def test_an_idle_pair_is_not_redialed_until_the_backoff_ends():
    a, b = _pair_with_one_message()
    ble = BleConfig(connection_setup_s=0.0, connection_idle_timeout_s=10.0, reconnect_backoff_s=100.0)
    _engine({1: a, 2: b}, ble, until=100.5)
    assert b.has_message(1)
    # Opened once (1 mAh per end), closed idle around t=11, left alone since.
    assert a.energy_consumed_mah == pytest.approx(1.0)
    assert a.connection_energy_consumed_mah == pytest.approx(1.0)

    a, b = _pair_with_one_message()
    _engine({1: a, 2: b}, ble, until=130.5)
    assert a.energy_consumed_mah == pytest.approx(2.0)


def test_without_backoff_an_idle_pair_is_redialed_at_once():
    a, b = _pair_with_one_message()
    ble = BleConfig(connection_setup_s=0.0, connection_idle_timeout_s=10.0, reconnect_backoff_s=0.0)
    _engine({1: a, 2: b}, ble, until=100.5)
    assert a.energy_consumed_mah >= 8.0


def test_a_new_message_lifts_the_backoff():
    a, b = _pair_with_one_message()
    nodes = {1: a, 2: b}
    ble = BleConfig(connection_setup_s=0.0, connection_idle_timeout_s=10.0, reconnect_backoff_s=1000.0)
    grid = SpatialGrid(200.0, 200.0, cell_size_m=50.0)
    for node in nodes.values():
        grid.insert(node)
    env = simpy.Environment()
    env.process(network_engine(env, nodes, grid, EpidemicRouting(), _setup_energy(), MetricsCollector(), 1.0, ble_config=ble))
    env.run(until=40.5)
    assert a.energy_consumed_mah == pytest.approx(1.0)
    a.store_message(Message(msg_id=2, src_id=1, dst_id=99, size_bytes=10, creation_time=40.0, ttl_s=1e6))
    env.run(until=42.5)
    assert b.has_message(2)
    assert a.energy_consumed_mah == pytest.approx(2.0)


def test_crowd_range_matches_the_field_bench_anchors():
    ble = _crowd_ble()
    radio = ble.phone_radio
    assert max_range_m(radio) == pytest.approx(50.0, abs=0.5)
    assert crowd_range_m(radio, 0.0, 0.8, 0.5) == pytest.approx(50.0, abs=0.5)
    # 3 m2 per person: the 30 m measured with people in the way.
    assert crowd_range_m(radio, 1 / 3, 0.8, 0.5) == pytest.approx(30.0, abs=1.0)
    assert crowd_range_m(radio, 1.54, 0.8, 0.5) == pytest.approx(15.0, abs=1.0)
    assert crowd_range_m(radio, 1.54, 0.0, 0.5) == max_range_m(radio)


def test_update_crowd_shrinks_the_range_of_phones_in_a_packed_cell():
    ble = _crowd_ble()
    nodes = {i: _node(i, 0.5 + (i % 10) * 0.9, 0.5 + (i // 10) * 0.9) for i in range(100)}
    alone = nodes[200] = _node(200, 150.0, 150.0)
    away = nodes[201] = _node(201, 5.0, 5.0)
    away.on_site = False
    beacon = nodes[300] = BeaconNode(300, Position(5.0, 5.0), radio_range_m=60.0, buffer_capacity=10)
    grid = SpatialGrid(200.0, 200.0, cell_size_m=50.0)
    _update_crowd(nodes, grid, ble, {})
    # 100 people on a 10 m cell: 1 per m2. The absent one doesn't count.
    assert nodes[1].crowd_density == pytest.approx(1.0)
    assert nodes[1].radio_range_m == pytest.approx(crowd_range_m(ble.phone_radio, 1.0, 0.8, 0.5))
    assert alone.crowd_density <= 0.02
    assert alone.radio_range_m > 45.0 > 25.0 > nodes[1].radio_range_m
    assert away.crowd_density == 0.0 and away.radio_range_m == 1000.0
    assert beacon.crowd_density == 0.0 and beacon.radio_range_m == 60.0


def test_bodies_put_a_link_in_outage_that_open_air_carries():
    ble = _crowd_ble(packet_loss_base_probability=0.0)
    a, b = _node(1, 0.0, 0.0), _node(2, 25.0, 0.0)
    assert _link_failure_probability(a, b, ble, None, None, None, ble.data_channels) < 1.0
    a.crowd_density = 1.5
    assert _link_failure_probability(a, b, ble, None, None, None, ble.data_channels) == 1.0
    # The denser end decides, whichever side sends.
    assert _link_failure_probability(b, a, ble, None, None, None, ble.data_channels) == 1.0


def test_fades_without_memory_are_the_same_draws_as_a_plain_dict():
    radio = BleConfig().phone_radio
    a, b = _node(1, 0.0, 0.0), _node(2, 5.0, 0.0)
    plain_rng, fades_rng = random.Random(3), random.Random(3)
    for tick in range(20):
        assert _pair_fade_db(a, b, radio, plain_rng, {}) == _pair_fade_db(a, b, radio, fades_rng, _Fades(float(tick)))


def test_fades_with_memory_keep_their_variance_and_last():
    radio = BleConfig().phone_radio
    a, b = _node(1, 0.0, 0.0), _node(2, 5.0, 0.0)
    rng = random.Random(5)
    memory = {}
    series = []
    for tick in range(20000):
        fades = _Fades(float(tick), 20.0, memory)
        series.append(_pair_fade_db(a, b, radio, rng, fades))
        # Within a tick the pair still sees one fade.
        assert _pair_fade_db(b, a, radio, rng, fades) == series[-1]
    mean = sum(series) / len(series)
    variance = sum((x - mean) ** 2 for x in series) / len(series)
    lag1 = sum((x - mean) * (y - mean) for x, y in zip(series, series[1:])) / (len(series) - 1) / variance
    assert math.sqrt(variance) == pytest.approx(radio.shadowing_std_db, rel=0.15)
    assert lag1 == pytest.approx(math.exp(-1 / 20.0), abs=0.02)


def test_engine_with_fade_memory_and_body_loss_still_delivers():
    a, b = _node(1, 0.0, 0.0, radio_range_m=50.0), _node(2, 5.0, 0.0, radio_range_m=50.0)
    a.store_message(Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=1e6))
    radio = dataclasses.replace(BleConfig().phone_radio, path_loss_exponent=1.8, tx_power_dbm=-19.4)
    ble = BleConfig(phone_radio=radio, body_loss_db=0.8, shadowing_coherence_s=20.0, connection_setup_s=0.0)
    _engine({1: a, 2: b}, ble, until=5.5, rng=random.Random(1))
    assert 1 in b.delivered_ids
    # Two people on a 10 m cell.
    assert a.radio_range_m == pytest.approx(crowd_range_m(radio, 0.02, 0.8, 0.5))


def test_report_separates_the_energy_of_connections():
    from festival_ble_sim.config import AreaConfig, SimulationConfig, TrafficConfig
    from festival_ble_sim.simulation import run_simulation
    report = run_simulation(SimulationConfig(
        duration_s=120.0, num_festivaliers=12, random_seed=2, area=AreaConfig(width_m=40.0, height_m=40.0),
        traffic=TrafficConfig(messages_per_hour_range=(60.0, 120.0), payload_size_range_bytes=(20, 100)),
    ))
    assert 0.0 < report.total_connection_energy_consumed_mah < report.total_algo_energy_consumed_mah
    assert report.avg_connection_energy_consumed_mah == pytest.approx(report.total_connection_energy_consumed_mah / 12)
