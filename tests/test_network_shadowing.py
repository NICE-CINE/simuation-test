import random
from festival_ble_sim.config import BleConfig, EnergyConfig, RadioParams
from festival_ble_sim.energy import EnergyModel
from festival_ble_sim.metrics import MetricsCollector
from festival_ble_sim.models import Message, Position
from festival_ble_sim.network import _link_failure_probability, process_node_contacts
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
        packet_loss_base_probability=0.0, weak_signal_max_probability=0.0,
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
        packet_loss_base_probability=0.0, weak_signal_max_probability=0.0,
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


def test_outage_carries_nothing_beyond_the_deterministic_range():
    radio = _shadowed_radio(20.0)
    ble_config = BleConfig(
        phone_radio=radio, beacon_radio=radio,
        packet_loss_base_probability=0.0, weak_signal_max_probability=0.0,
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
    assert losses / trials > 0.5


def _shadowed_ble(std_db=8.0):
    radio = _shadowed_radio(std_db)
    return BleConfig(
        phone_radio=radio, beacon_radio=radio, connection_setup_s=0.0,
        packet_loss_base_probability=0.0, weak_signal_max_probability=0.0,
    )


def test_both_directions_of_a_pair_share_one_fade_per_tick():
    ble_config = _shadowed_ble()
    a, b = _node(1, 0.0, 0.0), _node(2, 100.0, 0.0)
    rng = random.Random(3)
    fades = {}
    forward = _link_failure_probability(a, b, ble_config, rng, None, None, 79, fades=fades)
    backward = _link_failure_probability(b, a, ble_config, rng, None, None, 79, fades=fades)
    assert forward == backward
    assert list(fades) == [(1, 2)]


def test_a_cached_fade_decides_the_link_in_process_node_contacts():
    ble_config = _shadowed_ble()
    range_m = max_range_m(ble_config.phone_radio)

    def delivered(distance_m, fade_db):
        sender, contact = _node(1, 0.0, 0.0), _node(2, distance_m, 0.0)
        grid = SpatialGrid(2000.0, 2000.0, cell_size_m=1000.0)
        grid.insert(sender)
        grid.insert(contact)
        sender.store_message(Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0))
        process_node_contacts(
            now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
            energy_model=_energy_model(), metrics=MetricsCollector(), ble_config=ble_config,
            rng=random.Random(0), neighbors=[contact], fades={(1, 2): fade_db},
        )
        return contact.has_message(1)

    assert delivered(range_m * 0.5, -200.0) is False
    assert delivered(range_m * 1.5, 200.0) is True


class _GaussCounter(random.Random):
    gauss_calls = 0

    def gauss(self, mu=0.0, sigma=1.0):
        self.gauss_calls += 1
        return super().gauss(mu, sigma)


def test_engine_draws_one_fade_per_pair_per_tick():
    import simpy
    from festival_ble_sim.network import network_engine
    a, b = _node(1, 0.0, 0.0), _node(2, 5.0, 0.0)
    grid = SpatialGrid(2000.0, 2000.0, cell_size_m=1000.0)
    grid.insert(a)
    grid.insert(b)
    a.store_message(Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0))
    rng = _GaussCounter(0)
    env = simpy.Environment()
    env.process(network_engine(
        env, {1: a, 2: b}, grid, EpidemicRouting(), _energy_model(), MetricsCollector(), 1.0,
        ble_config=_shadowed_ble(), rng=rng,
    ))
    env.run(until=2.5)
    assert rng.gauss_calls == 2
