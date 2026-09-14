from __future__ import annotations
import random
from typing import Dict, Iterator
from .config import TrafficConfig
from .metrics import MetricsCollector
from .models import Message
from .nodes import MobileNode


def sample_interval_s(config: TrafficConfig, rng: random.Random) -> float:
    return rng.expovariate(1.0 / config.mean_interval_s)


def generate_message(
    msg_id: int,
    now: float,
    src_id: int,
    dst_id: int,
    config: TrafficConfig,
    rng: random.Random,
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
    )


def traffic_generator(
    env,
    nodes: Dict[int, MobileNode],
    config: TrafficConfig,
    metrics: MetricsCollector,
    id_generator: Iterator[int],
    rng: random.Random,
):
    while True:
        yield env.timeout(sample_interval_s(config, rng))
        active_ids = [node_id for node_id, node in nodes.items() if node.is_active]
        if len(active_ids) < 2:
            continue
        src_id, dst_id = rng.sample(active_ids, 2)
        message = generate_message(next(id_generator), env.now, src_id, dst_id, config, rng)
        nodes[src_id].store_message(message)
        metrics.record_creation(message)
