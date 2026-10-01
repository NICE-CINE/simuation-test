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
from .traffic import traffic_process
from .viz.history import SimulationHistory


def _mobile_process(env, node: MobileNode, config: SimulationConfig, grid: SpatialGrid):
    while True:
        yield env.timeout(config.mobility.tick_interval_s)
        if not node.is_active:
            # Not yet arrived / already departed (see _churn_process) or
            # battery-dead: frozen in place rather than wandering while it
            # can't participate in BLE anyway.
            continue
        node.consume_energy(config.energy.background_current_ma * config.mobility.tick_interval_s / 3600.0)
        old_x, old_y = node.position.x, node.position.y
        node.move(config.mobility.tick_interval_s, config.area)
        grid.update(node, old_x, old_y)


def _churn_process(env, node: MobileNode, arrival_time_s: float, departure_time_s: float):
    if arrival_time_s > 0:
        node.is_active = False
        yield env.timeout(arrival_time_s)
        node.is_active = True
    remaining_s = departure_time_s - max(arrival_time_s, 0.0)
    if remaining_s > 0:
        yield env.timeout(remaining_s)
        node.is_active = False


def _history_recorder(env, history: SimulationHistory, mobile_nodes: Dict[int, MobileNode], tick_interval_s: float):
    # A dedicated process rather than hooking _mobile_process, so one
    # snapshot captures every node's post-move position for a given tick
    # instead of N per-node partial writes. Registered after every
    # _mobile_process below so SimPy's same-time event ordering guarantees
    # this fires after that tick's moves, not before.
    while True:
        yield env.timeout(tick_interval_s)
        snapshot = {node_id: (node.position.x, node.position.y) for node_id, node in mobile_nodes.items() if node.is_active}
        history.position_snapshots.append((env.now, snapshot))


def _progress_reporter(env, callback: Callable[[float], None], interval_s: float):
    while True:
        yield env.timeout(interval_s)
        callback(env.now)


def run_simulation(
    config: SimulationConfig,
    routing_algorithm: Optional[RoutingAlgorithm] = None,
    mobility_factory: Optional[Callable[[random.Random], MobilityModel]] = None,
    history: Optional[SimulationHistory] = None,
    progress_callback: Optional[Callable[[float], None]] = None,
    progress_interval_s: float = 10.0,
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
    # Sized to the phone range, not max(phone, beacon): phones vastly
    # outnumber beacons in any realistic scenario, and SpatialGrid.get_nearby's
    # cost is driven by (candidates per cell) x (cells swept). Sizing cells to
    # the rarer, usually-larger beacon range would inflate candidates-per-cell
    # for every phone-originated query (the vast majority) just so beacon
    # queries (few, and cheaply covered by a larger cell_radius instead) stay
    # single-cell-radius too.
    grid = SpatialGrid(config.area.width_m, config.area.height_m, cell_size_m=phone_range_m)

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
        if history is not None:
            history.beacon_positions[node_id] = (position.x, position.y)

    mobile_nodes: Dict[int, MobileNode] = {}
    msg_id_counter = itertools.count(1)
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

        if config.churn.enabled:
            arrival_time_s = rng.uniform(*config.churn.arrival_window_s)
            departure_time_s = arrival_time_s + rng.uniform(*config.churn.session_duration_range_s)
            if arrival_time_s > 0 or departure_time_s < config.duration_s:
                env.process(_churn_process(env, mobile, arrival_time_s, departure_time_s))

        traffic_rng = random.Random(rng.randrange(1 << 30))
        env.process(traffic_process(env, mobile, mobile_nodes, config.traffic, metrics, msg_id_counter, traffic_rng))

    if history is not None:
        env.process(_history_recorder(env, history, mobile_nodes, config.mobility.tick_interval_s))

    routing_algorithm.on_simulation_start(nodes)
    network_rng = random.Random(rng.randrange(1 << 30))
    env.process(
        network_engine(
            env, nodes, grid, routing_algorithm, energy_model, metrics,
            config.ble.contact_check_interval_s,
            ble_config=config.ble,
            beacon_config=config.beacons,
            rng=network_rng,
            event_log=history.events if history is not None else None,
        )
    )

    if progress_callback is not None:
        env.process(_progress_reporter(env, progress_callback, progress_interval_s))

    env.run(until=config.duration_s)
    if progress_callback is not None:
        progress_callback(config.duration_s)

    energy_samples = [n.energy_consumed_mah for n in nodes.values() if n.initial_battery_mah != math.inf]
    dead_count = sum(1 for n in nodes.values() if n.battery_depleted)
    buffer_evictions = sum(n.buffer_evictions for n in nodes.values())
    return metrics.build_report(energy_samples, dead_count, buffer_evictions)
