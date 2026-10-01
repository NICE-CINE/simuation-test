# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup (first time)
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run the simulator (prints the report and archives it, see below)
python main.py

# Run all tests
pytest

# Run a single test file / test
pytest tests/test_network.py -v
pytest tests/test_network.py::test_network_engine_two_hop_relay_takes_two_intervals -v

# Compare every routing algo x {with, without beacons}, same seed, in parallel
python scripts/compare_algorithms.py --seed 42 --duration 3600 \
    --num-festivaliers 200 --beacon-count 6 --workers 2 [--csv out.csv]
```

Every run of either script is archived in `archives/` (`--archive-dir` to override; tests must pass a `tmp_path` so they don't pollute it) via `festival_ble_sim/archive.py`: `<YYYY-MM-DD_HH-MM-SS>_<algo>.txt` for `main.py`, `<...>_comparaison.csv` for the comparison, each with a same-named `.json` holding the CLI args *and* the fully resolved `SimulationConfig` (config defaults drift over time, so args alone can't reproduce a run). `--output`/`--csv` only write an extra copy. `archives/2026-09-28-comparaison.csv` predates this naming and has no `.json`.

No lint/format tooling is configured (no ruff/black/mypy config in `pyproject.toml`).

## Architecture

A discrete-event SimPy simulation of opportunistic BLE mesh messaging (`src/festival_ble_sim/`). Built bottom-up as pure, independently-testable modules that only get wired together in `simulation.py`:

```
models.py, config.py          — leaf modules, no internal deps
  ↓
spatial.py, energy.py, radio.py — depend only on models/config
  ↓
mobility/, routing/           — pluggable Strategy interfaces (ABCs).
                                 Both only reference `nodes.BaseNode` under
                                 `TYPE_CHECKING` and duck-type against it at
                                 runtime, so they have zero runtime coupling
                                 to nodes.py.
  ↓
nodes.py                      — BaseNode/MobileNode/BeaconNode; the concrete
                                 type mobility/routing were duck-typing against
  ↓
beacons.py, metrics.py, traffic.py, network.py
  ↓
simulation.py                 — run_simulation(config, routing_algorithm=None,
                                 mobility_factory=None, history=None,
                                 progress_callback=None,
                                 progress_interval_s=10.0) wires everything
                                 into one SimPy env.run() and returns a
                                 SimulationReport
  ↓
viz/history.py, viz/replay.py — optional: SimulationHistory is a plain data
                                 container simulation.py/network.py populate
                                 when a caller passes one in; replay.py
                                 renders it to a standalone HTML file. Neither
                                 is imported by the core engine unless a
                                 caller opts in.
```

`radio.py` holds the log-distance path-loss model (`max_range_m`, `received_power_dbm`, `link_margin_db`) that both `simulation.py` (to size `SpatialGrid` and each node's `radio_range_m` from `BleConfig.phone_radio`/`beacon_radio`) and `network.py` (to derive the weak-signal/shadowing component of packet loss from each sender/contact pair's link margin) build on. `RadioParams.shadowing_std_db` makes `received_power_dbm`/`link_margin_db` stochastic per call when given an `rng` — 0.0 (the dataclass default, though not `BleConfig`'s actual phone/beacon radio defaults) reproduces the old deterministic behavior.

`main.py` is a thin CLI: build a `SimulationConfig`, call `run_simulation`, `format_report`, print + archive it (see above), optionally `render_replay_html` when `--replay-html` is set. Algorithms are selected via its `ROUTING_FACTORIES` dict (`--routing`).

`scripts/compare_algorithms.py` runs the {algorithm} x {with/without beacons} matrix through a `ProcessPoolExecutor` (`--workers`), using `run_simulation`'s `progress_callback` for a live status line, and appends each finished row to the CSV as it completes. It has its own `ALGORITHMS` dict (no-arg constructors) separate from `main.py`'s.

### Traffic

Each `MobileNode` gets its own `traffic.traffic_process` with a fixed personal rate drawn once from `TrafficConfig.messages_per_hour_range` (default `(0.0, 2.0)`; a node drawing 0 never sends). Total load therefore scales with `num_festivaliers` — there is no network-wide `mean_interval_s` anymore. Destination is a uniformly random other active node.

### Extension points (Strategy pattern)

- **Routing:** subclass `routing.base.RoutingAlgorithm`, implement `decide(message, holder, contact, now) -> RoutingDecision`. Optional hooks (all no-op by default): `on_simulation_start(nodes)`, `on_tick(now, neighbors_by_node)` (every in-range pair each tick, even with nothing to send — needed by contact-history algorithms; only fired when the engine has a `ble_config`, which `run_simulation` always passes), `on_delivered(message, holder)`, `on_forward(message, holder, contact, forwarded_copy)` (split per-copy `routing_state`, e.g. Spray & Wait tokens), `choose_eviction(node, now) -> Optional[int]` (victim when a forwarded copy lands in a full buffer; `None`/unknown id falls back to `BaseNode.store_message`'s FIFO). Pass a custom instance via `run_simulation(config, routing_algorithm=MyRouting())`, and register it in both `main.py`'s `ROUTING_FACTORIES` and `scripts/compare_algorithms.py`'s `ALGORITHMS`.
  - Implemented: `epidemic` (reference, naive flooding), `spray_wait`, `prophet`, `beacon_priority`, `dasfv` (DASF-V, density-aware spray-and-focus + network-wide purge), `gossip_a` (GOSSIP-A, density-adaptive probabilistic gossip + purge tokens + replicated-first eviction), `bubble_f` (BUBBLE-F, social bubble routing seeded from a generated friend graph), `managed_flood` (Bluetooth Mesh managed flooding: TTL + per-node message cache + relay window, no store-carry-forward — it drops PDUs from `node.buffer` itself, including in `on_tick`, which needs `on_simulation_start`'s node dict). `tide` (TIDE, the NICE candidate: utility-weighted tokens, island delivery, density/energy relay election, source reinjection), `fresh_spray` (spray + replicate to contacts that met dst within `met_dst_window_s` + FRESH last-copy handoff + one beacon replica + global ACK purge in `on_tick`). `dasfv`, `gossip_a`, `bubble_f`, `managed_flood` and `tide` are network-level reductions of fuller protocol specs; `README.md` lists exactly what each one models and omits (crypto, Bloom, SOS, RSSI, ack airtime…).
  - One instance is shared by every node for the whole run, so an algorithm can hold global observation state (contact tables, density, communities) instead of simulating beacon/bloom wire formats — that's by design, not a leak. `gossip_a`/`bubble_f`/`tide` take a `seed` for their own RNG; keep them deterministic from it.
  - Algorithms may `pop` from `holder.buffer` (purges, copy-exhausted handoff) inside `decide`/`on_forward`/`on_tick`. Safe only because the engine iterates the tick snapshot, not the live buffer (see invariants below).
- **Mobility:** subclass `mobility.base.MobilityModel`, implement `initial_position(area)` and `step(current, dt, area)`. Reference impls: `mobility/random_waypoint.py` (uniform target) and `mobility/poi.py` (`PoiMobility`, targets weighted `MobilityConfig.points_of_interest`, requires at least one with positive weight). Each `MobileNode` owns its own instance; inject a custom one via `run_simulation(config, mobility_factory=lambda rng: MyMobility(rng))` — a *factory*, not an instance, because each node needs its own stateful model seeded from its own RNG.
- **Beacon placement:** `beacons.place_beacons(area, beacons)` — `"grid"` (regular grid, default) or `"manual"` (explicit coordinates). Not a Strategy class, just a two-branch function.

### Network engine realism layers (`network.py`)

All opt-in/no-op when the relevant config/param is `None` or its default, so existing callers (including most tests) are unaffected. Every layer is engine-level — applies uniformly to whatever `RoutingAlgorithm` is plugged in, not something each algorithm has to implement itself:

- **Contention (`_compute_contention_counts`):** once per tick, counts how many other nodes each node can itself hear with something to send. Drives both a sender-side CSMA backoff (skip the tick entirely before spending energy) and a receiver-side hidden-terminal collision loss (extra loss on top of congestion/weak-signal loss).
- **Hop-count TTL (`Message.ttl_hops`/`hop_limit_reached()`):** gates the `FORWARD` branch only, never the direct-delivery-to-destination branch — a hop-exhausted message stops spreading but can still reach its destination in one more hop, matching Spray & Wait's existing "wait phase" pattern.
- **Shadowing-driven outage:** `link_margin_db(..., rng)` can sample negative even inside the deterministic max range; treated as `loss_prob=1.0`, bypassing `packet_loss_max_probability` (a true outage isn't a "soft" loss source).
- **Beacon backhaul latency/loss (`beacon_backhaul_relay`):** per-tick attempt probability (`contact_check_interval_s / backhaul_latency_s`) instead of a delivery queue, so a message not attempted (or lost) this tick is retried automatically next tick — no extra state to track.

### Churn

`ChurnConfig` (`SimulationConfig.churn`, disabled by default) staggers each mobile node's arrival/departure via `simulation._churn_process`, toggling the *same* `is_active` flag that battery depletion, network participation, and traffic src/dst eligibility already gate — not a parallel "presence" mechanism. `BaseNode.battery_depleted` is a separate flag (set only by `consume_energy` hitting zero) so the report's `dead_node_count` isn't inflated by ordinary churn departures; don't compute it from `not is_active` again.

### Correctness invariants that are easy to break

- **`network.py` computes neighbors once per tick.** `_compute_neighbors` does one `SpatialGrid.get_nearby` per active node and the result is shared by `on_tick`, `_compute_contention_counts`, and each `process_node_contacts` call (via its `neighbors` param). Don't re-query the grid per node — it roughly doubled runtime at scale. Likewise `SpatialGrid` cells are sized to the *phone* range (not max(phone, beacon)), and threshold/sort comparisons use `Position.distance_squared_to` to skip the sqrt.
- **`network.py`'s tick-snapshot ordering.** `network_engine` snapshots every node's buffer *before* processing any node that tick, and `process_node_contacts` iterates that snapshot rather than the live buffer. This is load-bearing: without it, a node processed later in the same tick would immediately relay a message it received earlier that same tick, collapsing multi-hop delivery into one timestep and making results depend on dict iteration order. `process_node_contacts` has a `messages=None` default (→ falls back to `list(sender.buffer.values())`) purely so the single-node unit tests in `tests/test_network.py` can call it directly without going through `network_engine`.
- **Message copies must be independent.** Forwarding uses `dataclasses.replace(message, hops=message.hops+1, routing_state=dict(message.routing_state))` — never mutate `message.hops` in place, and always copy `routing_state` (it's a `Dict[str, Any]` bag reserved for future per-copy algorithm state, e.g. Spray & Wait's `copies_left`). A shared/mutated original would corrupt hop counts or state in every other buffer still holding a reference to it.
- **`BaseNode.battery_mah == math.inf`** is the sentinel for unlimited power (default for beacons). `consume_energy` no-ops on it; `energy_consumed_mah` returns `0.0` for it; the final report's energy average filters these nodes out via `initial_battery_mah != math.inf`. Don't treat `inf` as a normal float in new energy-related code.
- **`is_active` has multiple causes, `battery_depleted` has one.** `is_active=False` means "not currently eligible for BLE/traffic" for any reason — battery death, not-yet-arrived, or departed (churn). `battery_depleted=True` means specifically "died from battery". The report's `dead_node_count` must read `battery_depleted`, not `not is_active`, or churn departures get miscounted as battery deaths.

### Design docs

- Spec (binding design authority): `docs/superpowers/specs/2026-09-14-festival-ble-sim-design.md`
- Implementation plan (task-by-task, argues from the spec): `docs/superpowers/plans/2026-09-14-festival-ble-sim-implementation.md`

### Conventions

- Python 3.9 floor: no `X | Y` union syntax, no `match` statements, no bare builtin generics — use `typing.Optional/List/Dict/Set/Tuple`.
- No comments except non-obvious WHY; no docstrings. The few existing comments (e.g. in `mobility/base.py`, `beacons.py`) mark deliberate injection points — keep that convention for new ones.
- One file per responsibility; SimPy-driven modules (`network.py`, `traffic.py`) deliberately take `env` structurally rather than importing `simpy` at module level, to stay independently testable.
