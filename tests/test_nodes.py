import math
from festival_ble_sim.config import AreaConfig
from festival_ble_sim.models import Message, Position
from festival_ble_sim.nodes import BaseNode, MobileNode, BeaconNode


def _make_message(msg_id=1):
    return Message(msg_id=msg_id, src_id=1, dst_id=2, size_bytes=50, creation_time=0.0, ttl_s=100.0)


def test_store_message_evicts_oldest_when_full():
    node = BaseNode(node_id=1, position=Position(0, 0), radio_range_m=10.0, buffer_capacity=2, battery_mah=100.0)
    node.store_message(_make_message(1))
    node.store_message(_make_message(2))
    node.store_message(_make_message(3))
    assert set(node.buffer.keys()) == {2, 3}


def test_store_message_evicts_the_victim_chosen_by_the_caller():
    node = BaseNode(node_id=1, position=Position(0, 0), radio_range_m=10.0, buffer_capacity=2, battery_mah=100.0)
    node.store_message(_make_message(1))
    node.store_message(_make_message(2))
    node.store_message(_make_message(3), choose_victim=lambda n: 2)
    assert set(node.buffer.keys()) == {1, 3}
    assert node.buffer_evictions == 1


def test_store_message_falls_back_to_fifo_when_victim_is_unknown():
    node = BaseNode(node_id=1, position=Position(0, 0), radio_range_m=10.0, buffer_capacity=2, battery_mah=100.0)
    node.store_message(_make_message(1))
    node.store_message(_make_message(2))
    node.store_message(_make_message(3), choose_victim=lambda n: None)
    assert set(node.buffer.keys()) == {2, 3}


def test_has_message_true_after_store_and_after_delivery():
    node = BaseNode(node_id=1, position=Position(0, 0), radio_range_m=10.0, buffer_capacity=5, battery_mah=100.0)
    node.store_message(_make_message(1))
    assert node.has_message(1) is True
    node.mark_delivered(1)
    assert node.has_message(1) is True
    assert 1 not in node.buffer


def test_consume_energy_deactivates_node_at_zero_battery():
    node = BaseNode(node_id=1, position=Position(0, 0), radio_range_m=10.0, buffer_capacity=5, battery_mah=1.0)
    node.consume_energy(0.5)
    assert node.is_active is True
    node.consume_energy(0.6)
    assert node.battery_mah == 0.0
    assert node.is_active is False


def test_consume_energy_never_goes_negative():
    node = BaseNode(node_id=1, position=Position(0, 0), radio_range_m=10.0, buffer_capacity=5, battery_mah=1.0)
    node.consume_energy(10.0)
    assert node.battery_mah == 0.0


def test_unlimited_power_node_never_deactivates():
    node = BaseNode(node_id=1, position=Position(0, 0), radio_range_m=10.0, buffer_capacity=5, battery_mah=math.inf)
    node.consume_energy(1_000_000.0)
    assert node.is_active is True
    assert node.energy_consumed_mah == 0.0


def test_mobile_node_uses_injected_mobility_for_initial_position_and_move():
    class _StubMobility:
        def initial_position(self, area):
            return Position(1.0, 2.0)

        def step(self, current, dt, area):
            return Position(current.x + 1.0, current.y)

    area = AreaConfig(width_m=100.0, height_m=100.0)
    node = MobileNode(node_id=1, mobility=_StubMobility(), radio_range_m=10.0, buffer_capacity=5, battery_mah=100.0, area=area)
    assert node.position.x == 1.0
    node.move(dt=1.0, area=area)
    assert node.position.x == 2.0


def test_beacon_node_has_unlimited_power_by_default():
    beacon = BeaconNode(node_id=1, position=Position(0, 0), radio_range_m=60.0, buffer_capacity=100)
    assert beacon.battery_mah == math.inf
    assert beacon.is_active is True


def test_beacon_node_can_have_limited_power():
    beacon = BeaconNode(node_id=1, position=Position(0, 0), radio_range_m=60.0, buffer_capacity=100, unlimited_power=False, battery_mah=5.0)
    beacon.consume_energy(10.0)
    assert beacon.is_active is False


def test_gps_position_is_exact_without_noise_and_seeded_noisy_otherwise():
    import random
    node = BaseNode(node_id=1, position=Position(10.0, 20.0), radio_range_m=10.0, buffer_capacity=5, battery_mah=100.0)
    assert node.gps_position() == Position(10.0, 20.0)
    node.gps_noise_std_m = 5.0
    node.gps_rng = random.Random(3)
    first = node.gps_position()
    assert first != Position(10.0, 20.0)
    assert first.distance_to(node.position) < 50.0
    node.gps_rng = random.Random(3)
    assert node.gps_position() == first


def test_record_known_position_keeps_the_most_recent():
    node = BaseNode(node_id=1, position=Position(0, 0), radio_range_m=10.0, buffer_capacity=5, battery_mah=100.0)
    node.record_known_position(2, Position(1, 1), 10.0)
    node.record_known_position(2, Position(9, 9), 5.0)
    assert node.known_positions[2] == (Position(1, 1), 10.0)
