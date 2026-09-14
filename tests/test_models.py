from festival_ble_sim.models import Position, Message


def test_position_distance_to():
    a = Position(0.0, 0.0)
    b = Position(3.0, 4.0)
    assert a.distance_to(b) == 5.0


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
