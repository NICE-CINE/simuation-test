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
    assert report.p95_latency_s == pytest.approx(10.0)
    assert report.avg_hops == pytest.approx((1 + 2) / 2)
    assert report.overhead == pytest.approx(3 / 2)
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
