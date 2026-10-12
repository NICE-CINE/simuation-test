from festival_ble_sim.config import AreaConfig, BeaconConfig, SimulationConfig, TrafficConfig
from festival_ble_sim.simulation import run_simulation
from festival_ble_sim.viz.history import CompactEventLog, SimulationHistory


def _dense_config(**overrides):
    defaults = dict(
        duration_s=300.0,
        num_festivaliers=15,
        random_seed=7,
        area=AreaConfig(width_m=60.0, height_m=60.0),
        traffic=TrafficConfig(
            messages_per_hour_range=(1800.0, 3600.0), payload_size_range_bytes=(20, 100), message_ttl_s=600.0
        ),
    )
    defaults.update(overrides)
    return SimulationConfig(**defaults)


def test_run_simulation_without_history_is_unaffected():
    config = _dense_config()
    report = run_simulation(config)
    assert report.messages_delivered > 0


def test_history_records_one_position_snapshot_per_mobility_tick():
    config = _dense_config()
    history = SimulationHistory(
        area_width_m=config.area.width_m, area_height_m=config.area.height_m,
        tick_interval_s=config.mobility.tick_interval_s,
    )
    run_simulation(config, history=history)
    # env.run(until=duration_s) excludes an event scheduled at exactly
    # duration_s, so an evenly-divisible duration yields one fewer tick
    # than the naive duration/tick_interval count.
    expected_ticks = int(config.duration_s / config.mobility.tick_interval_s) - 1
    assert len(history.position_snapshots) == expected_ticks
    first_time, first_positions = history.position_snapshots[0]
    assert first_time == config.mobility.tick_interval_s
    assert len(first_positions) == config.num_festivaliers
    for x, y in first_positions.values():
        assert 0.0 <= x <= config.area.width_m
        assert 0.0 <= y <= config.area.height_m


def test_history_records_beacon_positions():
    config = _dense_config(beacons=BeaconConfig(count=3))
    history = SimulationHistory(
        area_width_m=config.area.width_m, area_height_m=config.area.height_m,
        tick_interval_s=config.mobility.tick_interval_s,
    )
    run_simulation(config, history=history)
    assert len(history.beacon_positions) == 3


def test_history_records_forward_and_delivery_events():
    config = _dense_config()
    history = SimulationHistory(
        area_width_m=config.area.width_m, area_height_m=config.area.height_m,
        tick_interval_s=config.mobility.tick_interval_s,
    )
    report = run_simulation(config, history=history)
    assert len(history.events) > 0
    assert any(e["delivered"] for e in history.events)
    assert sum(1 for e in history.events if e["delivered"]) == report.messages_delivered
    for e in history.events:
        assert {"time", "from", "to", "delivered"} <= e.keys()


def test_history_produces_same_report_as_without_history():
    config = _dense_config()
    report_without = run_simulation(config)
    history = SimulationHistory(
        area_width_m=config.area.width_m, area_height_m=config.area.height_m,
        tick_interval_s=config.mobility.tick_interval_s,
    )
    report_with = run_simulation(config, history=history)
    assert report_without == report_with


def test_history_events_carry_message_identity_and_hop_count():
    config = _dense_config()
    history = SimulationHistory(
        area_width_m=config.area.width_m, area_height_m=config.area.height_m,
        tick_interval_s=config.mobility.tick_interval_s,
    )
    run_simulation(config, history=history)
    for event in history.events:
        assert {"msg", "hops", "src", "dst", "created"} <= set(event)
    deliveries = [e for e in history.events if e["delivered"]]
    assert all(e["to"] == e["dst"] for e in deliveries)
    assert all(e["hops"] >= 1 for e in deliveries)


def test_history_records_beacon_backhaul_relays():
    config = _dense_config(beacons=BeaconConfig(count=4, placement="grid"))
    history = SimulationHistory(
        area_width_m=config.area.width_m, area_height_m=config.area.height_m,
        tick_interval_s=config.mobility.tick_interval_s,
    )
    run_simulation(config, history=history)
    backhaul = [e for e in history.events if e.get("backhaul")]
    assert backhaul
    assert all(not e["delivered"] and "msg" in e for e in backhaul)


def test_history_snapshot_every_ticks_thins_out_position_snapshots():
    config = _dense_config()
    history = SimulationHistory(
        area_width_m=config.area.width_m, area_height_m=config.area.height_m,
        tick_interval_s=config.mobility.tick_interval_s, snapshot_every_ticks=5,
    )
    run_simulation(config, history=history)
    tick = config.mobility.tick_interval_s
    times = [t for t, _ in history.position_snapshots]
    assert times[0] == tick
    assert all(b - a == 5 * tick for a, b in zip(times, times[1:]))


def test_compact_event_log_round_trips_events():
    log = CompactEventLog()
    plain = {"time": 2.5, "from": 2, "to": 3, "delivered": True}
    relay = {"time": 3.0, "from": 3, "to": 9, "delivered": False, "msg": 7, "hops": 2, "src": 2, "dst": 9, "created": 0.5}
    backhaul = {**relay, "time": 4.0, "backhaul": True}
    for event in (plain, relay, backhaul):
        log.append(event)
    assert len(log) == 3
    assert list(log) == [plain, relay, backhaul]
    assert log[1] == relay
    assert log[-1] == backhaul
    assert list(log)[1].keys() == relay.keys()
