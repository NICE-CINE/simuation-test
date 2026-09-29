from __future__ import annotations
import math
from dataclasses import dataclass
from typing import List, Set
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
    packet_loss_count: int = 0
    backhaul_transmissions: int = 0
    backoff_count: int = 0
    backhaul_loss_count: int = 0


@dataclass
class _DeliveryRecord:
    latency_s: float
    hops: int


class MetricsCollector:
    def __init__(self) -> None:
        self._messages_created = 0
        self._deliveries: List[_DeliveryRecord] = []
        self._delivered_msg_ids: Set[int] = set()
        self._total_transmissions = 0
        self._packet_loss_count = 0
        self._backhaul_transmissions = 0
        self._backoff_count = 0
        self._backhaul_loss_count = 0

    def record_creation(self, message: Message) -> None:
        self._messages_created += 1

    def record_transmission(self) -> None:
        self._total_transmissions += 1

    def record_packet_loss(self) -> None:
        self._packet_loss_count += 1

    def record_backhaul_transmission(self) -> None:
        self._backhaul_transmissions += 1

    def record_backoff(self) -> None:
        self._backoff_count += 1

    def record_backhaul_loss(self) -> None:
        self._backhaul_loss_count += 1

    def record_delivery(self, message: Message, delivered_at: float) -> None:
        if message.msg_id in self._delivered_msg_ids:
            return
        self._delivered_msg_ids.add(message.msg_id)
        self._deliveries.append(_DeliveryRecord(latency_s=delivered_at - message.creation_time, hops=message.hops))

    def build_report(
        self,
        node_energy_consumed_mah: List[float],
        dead_node_count: int,
        buffer_eviction_count: int = 0,
    ) -> SimulationReport:
        delivered = len(self._deliveries)
        delivery_ratio = delivered / self._messages_created if self._messages_created else 0.0
        latencies = sorted(d.latency_s for d in self._deliveries)
        avg_latency = sum(latencies) / delivered if delivered else 0.0
        p95_latency = latencies[math.ceil(0.95 * delivered) - 1] if delivered else 0.0
        avg_hops = sum(d.hops for d in self._deliveries) / delivered if delivered else 0.0
        overhead = self._total_transmissions / delivered if delivered else 0.0
        total_energy = sum(node_energy_consumed_mah)
        avg_energy = total_energy / len(node_energy_consumed_mah) if node_energy_consumed_mah else 0.0
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
            backoff_count=self._backoff_count,
            backhaul_loss_count=self._backhaul_loss_count,
        )


def format_report(report: SimulationReport) -> str:
    return (
        "===================================================================\n"
        "              RAPPORT DE SIMULATION RESEAU FESTIVAL\n"
        "===================================================================\n"
        f"Messages crees            : {report.messages_created}\n"
        f"Messages livres           : {report.messages_delivered}\n"
        f"Taux de livraison         : {report.delivery_ratio * 100:.2f} %\n"
        f"Latence moyenne           : {report.avg_latency_s:.1f} s\n"
        f"Latence p95               : {report.p95_latency_s:.1f} s\n"
        f"Nombre moyen de sauts     : {report.avg_hops:.2f}\n"
        f"Surcharge (overhead)      : {report.overhead:.2f}\n"
        f"Transmissions totales     : {report.total_transmissions}\n"
        f"Energie totale consommee  : {report.total_energy_consumed_mah:.2f} mAh\n"
        f"Energie moyenne / noeud   : {report.avg_energy_consumed_mah:.2f} mAh\n"
        f"Noeuds a plat (batterie)  : {report.dead_node_count}\n"
        f"Messages perdus (buffer)  : {report.buffer_eviction_count}\n"
        f"Paquets perdus (radio)    : {report.packet_loss_count}\n"
        f"Transmissions backhaul    : {report.backhaul_transmissions}\n"
        f"Backoffs (contention)     : {report.backoff_count}\n"
        f"Paquets perdus (backhaul) : {report.backhaul_loss_count}\n"
        "===================================================================\n"
    )
