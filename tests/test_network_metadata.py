from dataclasses import replace
import pytest
from festival_ble_sim.config import BleConfig, EnergyConfig
from festival_ble_sim.energy import EnergyModel
from festival_ble_sim.metrics import MetricsCollector
from festival_ble_sim.models import Message, Position
from festival_ble_sim.network import _Connection, _exchange_metadata, process_node_contacts
from festival_ble_sim.nodes import BaseNode
from festival_ble_sim.routing.epidemic import EpidemicRouting
from festival_ble_sim.spatial import SpatialGrid


def _node(node_id, x=0.0):
    return BaseNode(node_id=node_id, position=Position(x, 0.0), radio_range_m=20.0, buffer_capacity=10, battery_mah=1000.0)


def _msg(msg_id, dst_id=99):
    return Message(msg_id=msg_id, src_id=1, dst_id=dst_id, size_bytes=10, creation_time=0.0, ttl_s=100.0)


def _per_byte():
    return EnergyModel(EnergyConfig(tx_cost_mah_per_event=0.0, tx_cost_mah_per_byte=1.0,
                                    rx_cost_mah_per_event=0.0, rx_cost_mah_per_byte=1.0))


def _ble():
    ble = BleConfig(packet_loss_base_probability=0.0, weak_signal_max_probability=0.0)
    radio = replace(ble.phone_radio, shadowing_std_db=0.0)
    return replace(ble, phone_radio=radio, beacon_radio=radio)


class _Acking(EpidemicRouting):
    uses_delivery_acks = True

    def __init__(self, table_bytes=0):
        self.table_bytes = table_bytes

    def connection_table_bytes(self, node, peer):
        return self.table_bytes


def _exchange(a, b, conn, algo):
    _exchange_metadata(a, b, conn, algo, _per_byte(), _ble(), None, None, {})


def test_summary_vector_bills_only_ids_not_yet_listed_on_the_connection():
    a, b = _node(1), _node(2, 5.0)
    for i in (1, 2, 3):
        a.store_message(_msg(i))
    conn = _Connection(0.0)
    _exchange(a, b, conn, EpidemicRouting())
    assert a.energy_consumed_mah == pytest.approx(12.0) and b.energy_consumed_mah == pytest.approx(12.0)
    _exchange(a, b, conn, EpidemicRouting())
    assert a.energy_consumed_mah == pytest.approx(12.0)
    a.store_message(_msg(4))
    _exchange(a, b, conn, EpidemicRouting())
    assert a.energy_consumed_mah == pytest.approx(16.0)


def test_ack_reaches_only_a_node_listing_the_message_and_purges_its_copy():
    a, b, c = _node(1), _node(2, 5.0), _node(3, 10.0)
    a.acked[5] = 100.0
    b.store_message(_msg(5))
    _exchange(a, b, _Connection(0.0), _Acking())
    _exchange(a, c, _Connection(0.0), _Acking())
    assert 5 not in b.buffer and 5 in b.acked
    assert 5 not in c.acked


def test_acks_stay_put_for_an_algorithm_that_does_not_use_them():
    a, b = _node(1), _node(2, 5.0)
    a.acked[5] = 100.0
    b.store_message(_msg(5))
    _exchange(a, b, _Connection(0.0), EpidemicRouting())
    assert 5 in b.buffer


def test_algorithm_tables_are_billed_once_per_connection():
    a, b = _node(1), _node(2, 5.0)
    conn = _Connection(0.0)
    _exchange(a, b, conn, _Acking(table_bytes=50))
    _exchange(a, b, conn, _Acking(table_bytes=50))
    assert a.energy_consumed_mah == pytest.approx(100.0)


def test_destination_acks_the_delivering_holder_which_drops_its_copy():
    holder, dst = _node(1), _node(2, 5.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(holder)
    grid.insert(dst)
    holder.store_message(_msg(7, dst_id=2))
    process_node_contacts(
        now=1.0, sender=holder, grid=grid, routing_algorithm=_Acking(),
        energy_model=_per_byte(), metrics=MetricsCollector(), ble_config=_ble(),
    )
    assert 7 in dst.delivered_ids and 7 in dst.acked
    assert 7 not in holder.buffer and 7 in holder.acked


def _delivery(ble, **kwargs):
    holder, dst = _node(1), _node(2, 5.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(holder)
    grid.insert(dst)
    holder.store_message(_msg(7, dst_id=2))
    metrics = MetricsCollector()
    process_node_contacts(
        now=1.0, sender=holder, grid=grid, routing_algorithm=_Acking(),
        energy_model=_per_byte(), metrics=metrics, ble_config=ble, **kwargs,
    )
    return holder, dst, metrics


def test_delivery_ack_takes_airtime_and_channel_load_like_data():
    from festival_ble_sim.network import ChannelState
    airtime_left, channel = {}, ChannelState()
    _delivery(_ble(), airtime_left=airtime_left, channel=channel)
    budget = 31_000.0
    assert airtime_left[1] == pytest.approx(budget - 10 - 210)
    assert airtime_left[2] == pytest.approx(budget - 10 - 210)
    assert channel.sent_data == {1: pytest.approx(10.0), 2: pytest.approx(210.0)}


def test_delivery_ack_is_resent_on_a_lossy_link_like_data():
    holder, dst, metrics = _delivery(replace(_ble(), packet_loss_base_probability=0.5))
    assert metrics.build_report([], 0).ack_bytes == pytest.approx(420.0)
    # The 10-byte message and the 210-byte ack, each sent twice on average, both ways round.
    assert dst.energy_consumed_mah == pytest.approx(2 * 10 + 2 * 210)
    assert holder.energy_consumed_mah == pytest.approx(2 * 10 + 2 * 210)


def test_delivery_record_is_dropped_once_the_message_expires():
    holder, dst = _node(1), _node(2, 5.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(holder)
    grid.insert(dst)
    holder.store_message(_msg(7, dst_id=2))

    def tick(now, sender):
        process_node_contacts(
            now=now, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
            energy_model=_per_byte(), metrics=MetricsCollector(), ble_config=_ble(),
        )

    tick(1.0, holder)
    assert 7 in dst.delivered_ids
    tick(50.0, dst)
    assert 7 in dst.delivered_ids
    tick(101.0, dst)
    assert 7 not in dst.delivered_ids and not dst.has_message(7)
