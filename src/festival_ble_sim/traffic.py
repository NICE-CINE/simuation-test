from __future__ import annotations
import random
from typing import Dict, Iterator, Optional, Tuple
from .config import TrafficConfig
from .metrics import MetricsCollector
from .models import Message, Position
from .nodes import MobileNode


def sample_message_rate_per_hour(config: TrafficConfig, rng: random.Random) -> float:
    return rng.uniform(*config.messages_per_hour_range)


def sample_interval_s(rate_per_hour: float, rng: random.Random) -> float:
    return rng.expovariate(rate_per_hour / 3600.0)


def generate_message(
    msg_id: int,
    now: float,
    src_id: int,
    dst_id: int,
    config: TrafficConfig,
    rng: random.Random,
    src_position: Optional[Position] = None,
    dst_known: Optional[Tuple[Position, float]] = None,
) -> Message:
    lo, hi = config.payload_size_range_bytes
    size_bytes = rng.randint(lo, hi)
    return Message(
        msg_id=msg_id,
        src_id=src_id,
        dst_id=dst_id,
        size_bytes=size_bytes,
        creation_time=now,
        ttl_s=config.message_ttl_s,
        ttl_hops=config.message_ttl_hops,
        src_position=src_position,
        dst_position=dst_known[0] if dst_known is not None else None,
        dst_position_time=dst_known[1] if dst_known is not None else None,
    )


def traffic_process(
    env,
    node: MobileNode,
    nodes: Dict[int, MobileNode],
    config: TrafficConfig,
    metrics: MetricsCollector,
    id_generator: Iterator[int],
    rng: random.Random,
):
    rate_per_hour = sample_message_rate_per_hour(config, rng)
    if rate_per_hour <= 0:
        return
    while True:
        yield env.timeout(sample_interval_s(rate_per_hour, rng))
        if not node.is_active:
            continue
        if config.friends_only:
            if not node.friends:
                return
            candidate_ids = sorted(f for f in node.friends if f in nodes and nodes[f].is_active)
        else:
            candidate_ids = [dst_id for dst_id, other in nodes.items() if dst_id != node.id and other.is_active]
        if not candidate_ids:
            continue
        dst_id = rng.choice(candidate_ids)
        message = generate_message(
            next(id_generator), env.now, node.id, dst_id, config, rng,
            src_position=node.gps_position(),
            dst_known=node.known_positions.get(dst_id),
        )
        node.store_message(message)
        metrics.record_creation(message)


def reply_process(
    env,
    node: MobileNode,
    dst_id: int,
    delay_s: float,
    nodes: Dict[int, MobileNode],
    config: TrafficConfig,
    metrics: MetricsCollector,
    id_generator: Iterator[int],
    rng: random.Random,
):
    yield env.timeout(delay_s)
    target = nodes.get(dst_id)
    if not node.is_active or target is None or not target.is_active:
        return
    message = generate_message(
        next(id_generator), env.now, node.id, dst_id, config, rng,
        src_position=node.gps_position(),
        dst_known=node.known_positions.get(dst_id),
    )
    node.store_message(message)
    metrics.record_creation(message)
