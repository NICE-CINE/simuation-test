from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Set
from .models import Message


@dataclass
class SimulationReport:
    messages_created: int
    messages_delivered: int
    delivery_ratio: float
    avg_latency_s: float
    p95_latency_s: float
    avg_hops: float
    overhead: float
    total_transmissions: int
    total_energy_consumed_mah: float
    avg_energy_consumed_mah: float
    dead_node_count: int
    buffer_eviction_count: int = 0
    # Connectionless control broadcast receptions lost (data on a
    # connection is resent instead, see retransmitted_bytes).
    packet_loss_count: int = 0
    backhaul_transmissions: int = 0
    retransmitted_bytes: float = 0.0
    backhaul_loss_count: int = 0
    replies_created: int = 0
    replies_delivered: int = 0
    reply_delivery_ratio: float = 0.0
    # Mesh share of the energy above: being reachable + tx/rx + algorithm
    # extras, without EnergyConfig.phone_current_ma (identical for every algorithm).
    total_mesh_energy_consumed_mah: float = 0.0
    avg_mesh_energy_consumed_mah: float = 0.0
    # Mesh energy without background_current_ma either: what the algorithm
    # itself spends (tx/rx, connections, GPS, beacons), which the baseline
    # otherwise drowns (it is identical for every algorithm while phones live).
    total_algo_energy_consumed_mah: float = 0.0
    avg_algo_energy_consumed_mah: float = 0.0
    # Bytes put on the air: data (resends included) of measured messages;
    # summaries, acks, algorithm tables and control broadcasts sent before
    # the end of the measured window. overhead_bytes = all of it per
    # delivered message, the airtime cost to compare algorithms on.
    data_bytes: float = 0.0
    summary_bytes: float = 0.0
    ack_bytes: float = 0.0
    table_bytes: float = 0.0
    control_bytes: float = 0.0
    overhead_bytes: float = 0.0


@dataclass
class _DeliveryRecord:
    latency_s: float
    hops: int
    is_reply: bool = False


class MetricsCollector:
    # measure_until: only messages created before it count (creations,
    # deliveries, transmissions, losses). The run continues past it for the
    # cooldown so late messages get their chance instead of counting as lost.
    def __init__(self, measure_until: Optional[float] = None) -> None:
        self._measure_until = measure_until
        self._messages_created = 0
        self._replies_created = 0
        self._deliveries: List[_DeliveryRecord] = []
        self._delivered_msg_ids: Set[int] = set()
        self._total_transmissions = 0
        self._packet_loss_count = 0
        self._backhaul_transmissions = 0
        self._retransmitted_bytes = 0.0
        self._attempts = 0.0
        self._data_bytes = 0.0
        self._overhead_bytes: Dict[str, float] = {"summary": 0.0, "ack": 0.0, "table": 0.0, "control": 0.0}
        self._backhaul_loss_count = 0

    def _measured(self, message: Optional[Message]) -> bool:
        return self._measure_until is None or message is None or message.creation_time < self._measure_until

    def record_creation(self, message: Message) -> None:
        if not self._measured(message):
            return
        if message.is_reply:
            self._replies_created += 1
        else:
            self._messages_created += 1

    def record_transmission(self, message: Optional[Message] = None, airtime: Optional[float] = None) -> None:
        # airtime: bytes on the air for this copy, resends included.
        if not self._measured(message):
            return
        self._total_transmissions += 1
        if message is None or airtime is None:
            self._attempts += 1.0
            return
        self._attempts += airtime / message.size_bytes
        self._data_bytes += airtime
        self._retransmitted_bytes += airtime - message.size_bytes

    def record_overhead_bytes(self, kind: str, nbytes: float, now: float) -> None:
        if self._measure_until is None or now < self._measure_until:
            self._overhead_bytes[kind] += nbytes

    def record_packet_loss(self, message: Optional[Message] = None) -> None:
        if self._measured(message):
            self._packet_loss_count += 1

    def record_backhaul_transmission(self, message: Optional[Message] = None) -> None:
        if self._measured(message):
            self._backhaul_transmissions += 1

    def record_backhaul_loss(self, message: Optional[Message] = None) -> None:
        if self._measured(message):
            self._backhaul_loss_count += 1

    def record_delivery(self, message: Message, delivered_at: float) -> None:
        if not self._measured(message) or message.msg_id in self._delivered_msg_ids:
            return
        self._delivered_msg_ids.add(message.msg_id)
        self._deliveries.append(
            _DeliveryRecord(latency_s=delivered_at - message.creation_time, hops=message.hops, is_reply=message.is_reply)
        )

    def build_report(
        self,
        node_energy_consumed_mah: List[float],
        dead_node_count: int,
        buffer_eviction_count: int = 0,
        node_mesh_energy_consumed_mah: Optional[List[float]] = None,
        node_algo_energy_consumed_mah: Optional[List[float]] = None,
    ) -> SimulationReport:
        # Delivery, latency and hops: spontaneous messages only, the same set
        # for every algorithm at a given seed. Overhead covers all traffic.
        spontaneous = [d for d in self._deliveries if not d.is_reply]
        delivered = len(spontaneous)
        replies_delivered = len(self._deliveries) - delivered
        delivery_ratio = delivered / self._messages_created if self._messages_created else 0.0
        latencies = sorted(d.latency_s for d in spontaneous)
        avg_latency = sum(latencies) / delivered if delivered else 0.0
        p95_latency = latencies[math.ceil(0.95 * delivered) - 1] if delivered else 0.0
        avg_hops = sum(d.hops for d in spontaneous) / delivered if delivered else 0.0
        # Extra transmissions per delivered message, as in The ONE: a
        # single-hop delivery with no other copy scores 0. Counted in
        # attempts, so resends on a lossy link count too.
        all_delivered = len(self._deliveries)
        overhead = (self._attempts - all_delivered) / all_delivered if all_delivered else 0.0
        all_bytes = self._data_bytes + sum(self._overhead_bytes.values())
        total_energy = sum(node_energy_consumed_mah)
        avg_energy = total_energy / len(node_energy_consumed_mah) if node_energy_consumed_mah else 0.0
        mesh = node_mesh_energy_consumed_mah or []
        total_mesh = sum(mesh)
        algo = node_algo_energy_consumed_mah or []
        total_algo = sum(algo)
        return SimulationReport(
            messages_created=self._messages_created,
            messages_delivered=delivered,
            delivery_ratio=delivery_ratio,
            avg_latency_s=avg_latency,
            p95_latency_s=p95_latency,
            avg_hops=avg_hops,
            overhead=overhead,
            total_transmissions=self._total_transmissions,
            total_energy_consumed_mah=total_energy,
            avg_energy_consumed_mah=avg_energy,
            dead_node_count=dead_node_count,
            buffer_eviction_count=buffer_eviction_count,
            packet_loss_count=self._packet_loss_count,
            backhaul_transmissions=self._backhaul_transmissions,
            retransmitted_bytes=self._retransmitted_bytes,
            backhaul_loss_count=self._backhaul_loss_count,
            replies_created=self._replies_created,
            replies_delivered=replies_delivered,
            reply_delivery_ratio=replies_delivered / self._replies_created if self._replies_created else 0.0,
            total_mesh_energy_consumed_mah=total_mesh,
            avg_mesh_energy_consumed_mah=total_mesh / len(mesh) if mesh else 0.0,
            total_algo_energy_consumed_mah=total_algo,
            avg_algo_energy_consumed_mah=total_algo / len(algo) if algo else 0.0,
            data_bytes=self._data_bytes,
            summary_bytes=self._overhead_bytes["summary"],
            ack_bytes=self._overhead_bytes["ack"],
            table_bytes=self._overhead_bytes["table"],
            control_bytes=self._overhead_bytes["control"],
            overhead_bytes=all_bytes / all_delivered if all_delivered else 0.0,
        )


def format_report(report: SimulationReport) -> str:
    return (
        "===================================================================\n"
        "              RAPPORT DE SIMULATION RESEAU FESTIVAL\n"
        "===================================================================\n"
        f"Messages crees (spontanes): {report.messages_created}\n"
        f"Messages livres           : {report.messages_delivered}\n"
        f"Taux de livraison         : {report.delivery_ratio * 100:.2f} %\n"
        f"Latence moyenne           : {report.avg_latency_s:.1f} s\n"
        f"Latence p95               : {report.p95_latency_s:.1f} s\n"
        f"Nombre moyen de sauts     : {report.avg_hops:.2f}\n"
        f"Reponses creees / livrees : {report.replies_created} / {report.replies_delivered}"
        f" ({report.reply_delivery_ratio * 100:.2f} %)\n"
        f"Surcharge (overhead)      : {report.overhead:.2f}\n"
        f"Transmissions totales     : {report.total_transmissions}\n"
        f"Octets emis / livre       : {report.overhead_bytes:.0f}\n"
        f"  donnees / resumes / ACK : {report.data_bytes:.0f} / {report.summary_bytes:.0f} / {report.ack_bytes:.0f}\n"
        f"  tables / controle       : {report.table_bytes:.0f} / {report.control_bytes:.0f}\n"
        f"Energie totale consommee  : {report.total_energy_consumed_mah:.2f} mAh\n"
        f"Energie moyenne / noeud   : {report.avg_energy_consumed_mah:.2f} mAh\n"
        f"  dont mesh (totale / moy): {report.total_mesh_energy_consumed_mah:.2f} / {report.avg_mesh_energy_consumed_mah:.2f} mAh\n"
        f"  dont algo, hors base    : {report.total_algo_energy_consumed_mah:.2f} / {report.avg_algo_energy_consumed_mah:.2f} mAh\n"
        f"Noeuds a plat (batterie)  : {report.dead_node_count}\n"
        f"Copies evincees (buffer)  : {report.buffer_eviction_count}\n"
        f"Annonces perdues (radio)  : {report.packet_loss_count}\n"
        f"Transmissions backhaul    : {report.backhaul_transmissions}\n"
        f"Octets retransmis (radio) : {report.retransmitted_bytes:.0f}\n"
        f"Paquets perdus (backhaul) : {report.backhaul_loss_count}\n"
        "===================================================================\n"
    )
