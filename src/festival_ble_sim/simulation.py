from __future__ import annotations
import itertools
import math
import random
from typing import Callable, Dict, Optional
import simpy
from .beacons import place_beacons
from .config import SimulationConfig
from .energy import EnergyModel
from .metrics import MetricsCollector, SimulationReport
from .mobility.base import MobilityModel
from .mobility.random_waypoint import RandomWaypointMobility
from .network import network_engine
from .nodes import BaseNode, BeaconNode, MobileNode
from .radio import max_range_m
from .routing.base import RoutingAlgorithm
from .routing.epidemic import EpidemicRouting
from .spatial import SpatialGrid
from .traffic import traffic_generator


def _mobile_process(env, node: MobileNode, config: SimulationConfig, grid: SpatialGrid):
    while True:
        yield env.timeout(config.mobility.tick_interval_s)
        old_x, old_y = node.position.x, node.position.y
        node.move(config.mobility.tick_interval_s, config.area)
        grid.update(node, old_x, old_y)


def run_simulation(
    config: SimulationConfig,
    routing_algorithm: Optional[RoutingAlgorithm] = None,
    mobility_factory: Optional[Callable[[random.Random], MobilityModel]] = None,
) -> SimulationReport:
    rng = random.Random(config.random_seed)
    routing_algorithm = routing_algorithm if routing_algorithm is not None else EpidemicRouting()
    if mobility_factory is None:
        mobility_factory = lambda node_rng: RandomWaypointMobility(config.mobility, rng=node_rng)
    energy_model = EnergyModel(config.energy)
    metrics = MetricsCollector()
    env = simpy.Environment()

    phone_range_m = max_range_m(config.ble.phone_radio)
    beacon_range_m = max_range_m(config.ble.beacon_radio)
    grid = SpatialGrid(config.area.width_m, config.area.height_m, cell_size_m=max(phone_range_m, beacon_range_m))

    nodes: Dict[int, BaseNode] = {}
    id_counter = itertools.count(1)

    for position in place_beacons(config.area, config.beacons):
        node_id = next(id_counter)
        beacon = BeaconNode(
            node_id=node_id,
            position=position,
            radio_range_m=beacon_range_m,
            buffer_capacity=config.node_buffer_capacity,
            unlimited_power=config.beacons.unlimited_power,
            battery_mah=config.energy.initial_battery_mah,
        )
        nodes[node_id] = beacon
        grid.insert(beacon)

    mobile_nodes: Dict[int, MobileNode] = {}
    for _ in range(config.num_festivaliers):
        node_id = next(id_counter)
        node_rng = random.Random(rng.randrange(1 << 30))
        mobility = mobility_factory(node_rng)
        mobile = MobileNode(
            node_id=node_id,
            mobility=mobility,
            radio_range_m=phone_range_m,
            buffer_capacity=config.node_buffer_capacity,
            battery_mah=config.energy.initial_battery_mah,
            area=config.area,
        )
        nodes[node_id] = mobile
        mobile_nodes[node_id] = mobile
        grid.insert(mobile)
        env.process(_mobile_process(env, mobile, config, grid))

    msg_id_counter = itertools.count(1)
    network_rng = random.Random(rng.randrange(1 << 30))
    env.process(traffic_generator(env, mobile_nodes, config.traffic, metrics, msg_id_counter, rng))
    env.process(
        network_engine(
            env, nodes, grid, routing_algorithm, energy_model, metrics,
            config.ble.contact_check_interval_s,
            ble_config=config.ble,
            rng=network_rng,
        )
    )

    env.run(until=config.duration_s)

    energy_samples = [n.energy_consumed_mah for n in nodes.values() if n.initial_battery_mah != math.inf]
    dead_count = sum(1 for n in nodes.values() if not n.is_active)
    buffer_evictions = sum(n.buffer_evictions for n in nodes.values())
    return metrics.build_report(energy_samples, dead_count, buffer_evictions)
