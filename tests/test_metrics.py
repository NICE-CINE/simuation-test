import pytest
from festival_ble_sim.metrics import MetricsCollector, format_report
from festival_ble_sim.models import Message


def _msg(msg_id, creation_time, hops):
    m = Message(msg_id=msg_id, src_id=1, dst_id=2, size_bytes=10, creation_time=creation_time, ttl_s=1000.0)
    m.hops = hops
    return m


def test_build_report_computes_delivery_ratio_and_latency():
    collector = MetricsCollector()
    m1 = _msg(1, creation_time=0.0, hops=1)
    m2 = _msg(2, creation_time=0.0, hops=2)
    m3 = _msg(3, creation_time=0.0, hops=0)
    for m in (m1, m2, m3):
        collector.record_creation(m)
    collector.record_transmission()
    collector.record_transmission()
    collector.record_transmission()
    collector.record_delivery(m1, delivered_at=10.0)
    collector.record_delivery(m2, delivered_at=20.0)

    report = collector.build_report(node_energy_consumed_mah=[1.0, 3.0], dead_node_count=1)

    assert report.messages_created == 3
    assert report.messages_delivered == 2
    assert report.delivery_ratio == pytest.approx(2 / 3)
    assert report.avg_latency_s == pytest.approx((10.0 + 20.0) / 2)
    assert report.p95_latency_s == pytest.approx(20.0)
    assert report.avg_hops == pytest.approx((1 + 2) / 2)
    assert report.overhead == pytest.approx((3 - 2) / 2)
    assert report.total_transmissions == 3
    assert report.total_energy_consumed_mah == pytest.approx(4.0)
    assert report.avg_energy_consumed_mah == pytest.approx(2.0)
    assert report.dead_node_count == 1


def test_duplicate_delivery_is_recorded_once():
    collector = MetricsCollector()
    m1 = _msg(1, creation_time=0.0, hops=1)
    collector.record_creation(m1)
    collector.record_delivery(m1, delivered_at=5.0)
    collector.record_delivery(m1, delivered_at=6.0)
    report = collector.build_report([], 0)
    assert report.messages_delivered == 1


def test_empty_collector_reports_zero_without_division_errors():
    collector = MetricsCollector()
    report = collector.build_report([], 0)
    assert report.messages_created == 0
    assert report.delivery_ratio == 0.0
    assert report.avg_latency_s == 0.0


def test_format_report_includes_key_numbers():
    collector = MetricsCollector()
    m1 = _msg(1, creation_time=0.0, hops=1)
    collector.record_creation(m1)
    collector.record_delivery(m1, delivered_at=5.0)
    report = collector.build_report([2.0], 0)
    text = format_report(report)
    assert "100.00" in text
    assert "5.0" in text


def test_messages_created_after_the_measured_window_are_ignored():
    collector = MetricsCollector(measure_until=100.0)
    early = Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=99.0, ttl_s=500.0)
    late = Message(msg_id=2, src_id=1, dst_id=2, size_bytes=10, creation_time=100.0, ttl_s=500.0)
    for message in (early, late):
        collector.record_creation(message)
        collector.record_transmission(message)
        collector.record_packet_loss(message)
        collector.record_delivery(message, 150.0)
    report = collector.build_report([], 0)
    assert (report.messages_created, report.messages_delivered) == (1, 1)
    assert (report.total_transmissions, report.packet_loss_count) == (1, 1)


def test_replies_are_reported_apart_from_spontaneous_messages():
    collector = MetricsCollector()
    spontaneous = Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=500.0)
    reply = Message(msg_id=2, src_id=2, dst_id=1, size_bytes=10, creation_time=50.0, ttl_s=500.0, is_reply=True)
    unanswered = Message(msg_id=3, src_id=2, dst_id=1, size_bytes=10, creation_time=60.0, ttl_s=500.0, is_reply=True)
    for message in (spontaneous, reply, unanswered):
        collector.record_creation(message)
    collector.record_delivery(spontaneous, 10.0)
    collector.record_delivery(reply, 150.0)
    for _ in range(4):
        collector.record_transmission(spontaneous)
    report = collector.build_report([], 0)
    assert (report.messages_created, report.messages_delivered, report.delivery_ratio) == (1, 1, 1.0)
    assert report.avg_latency_s == pytest.approx(10.0)
    assert (report.replies_created, report.replies_delivered) == (2, 1)
    assert report.reply_delivery_ratio == pytest.approx(0.5)
    assert report.overhead == pytest.approx((4 - 2) / 2)
    assert "Reponses creees / livrees : 2 / 1" in format_report(report)


def test_overhead_counts_resends_and_overhead_bytes_counts_every_byte():
    collector = MetricsCollector(measure_until=100.0)
    m = _msg(1, creation_time=0.0, hops=1)
    collector.record_creation(m)
    collector.record_transmission(m, airtime=20.0)
    collector.record_delivery(m, 5.0)
    collector.record_overhead_bytes("summary", 8.0, now=10.0)
    collector.record_overhead_bytes("control", 50.0, now=10.0)
    collector.record_overhead_bytes("control", 999.0, now=150.0)
    report = collector.build_report([], 0)
    assert report.overhead == pytest.approx(1.0)
    assert report.retransmitted_bytes == pytest.approx(10.0)
    assert (report.data_bytes, report.summary_bytes, report.control_bytes) == (20.0, 8.0, 50.0)
    assert report.overhead_bytes == pytest.approx(78.0)
