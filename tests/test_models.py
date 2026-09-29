import pytest
from festival_ble_sim.models import Position, Message


def test_position_distance_to():
    a = Position(0.0, 0.0)
    b = Position(3.0, 4.0)
    assert a.distance_to(b) == 5.0


def test_position_distance_squared_to():
    a = Position(0.0, 0.0)
    b = Position(3.0, 4.0)
    assert a.distance_squared_to(b) == 25.0


def test_position_distance_squared_to_matches_distance_to_squared():
    a = Position(1.5, -2.0)
    b = Position(-7.25, 10.0)
    assert a.distance_squared_to(b) == pytest.approx(a.distance_to(b) ** 2)


def test_message_is_expired_true_after_ttl():
    msg = Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    assert msg.is_expired(now=150.0) is True


def test_message_is_expired_false_within_ttl():
    msg = Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    assert msg.is_expired(now=50.0) is False


def test_message_defaults():
    msg = Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    assert msg.hops == 0
    assert msg.routing_state == {}
    assert msg.ttl_hops is None


def test_hop_limit_reached_false_when_ttl_hops_is_none():
    msg = Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=100.0, hops=1000)
    assert msg.hop_limit_reached() is False


def test_hop_limit_reached_false_below_limit():
    msg = Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=100.0, hops=2, ttl_hops=4)
    assert msg.hop_limit_reached() is False


def test_hop_limit_reached_true_at_limit():
    msg = Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=100.0, hops=4, ttl_hops=4)
    assert msg.hop_limit_reached() is True


def test_hop_limit_reached_true_beyond_limit():
    msg = Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=100.0, hops=5, ttl_hops=4)
    assert msg.hop_limit_reached() is True
