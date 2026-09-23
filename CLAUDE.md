# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup (first time)
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run the simulator (writes rapport_simulation.txt, also prints to stdout)
python main.py

# Run all tests
pytest

# Run a single test file / test
pytest tests/test_network.py -v
pytest tests/test_network.py::test_network_engine_two_hop_relay_takes_two_intervals -v
```

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
                                 mobility_factory=None) wires everything into
                                 one SimPy env.run() and returns a SimulationReport
```

`radio.py` holds the log-distance path-loss model (`max_range_m`, `received_power_dbm`, `link_margin_db`) that both `simulation.py` (to size `SpatialGrid` and each node's `radio_range_m` from `BleConfig.phone_radio`/`beacon_radio`) and `network.py` (to derive the weak-signal component of packet loss from each sender/contact pair's link margin) build on.

`main.py` is a thin CLI: build a `SimulationConfig`, call `run_simulation`, `format_report`, print + write to `rapport_simulation.txt`.

### Extension points (Strategy pattern)

- **Routing:** subclass `routing.base.RoutingAlgorithm`, implement `decide(message, holder, contact) -> RoutingDecision`. Reference impl: `routing/epidemic.py` (naive flooding). Pass a custom instance via `run_simulation(config, routing_algorithm=MyRouting())`.
- **Mobility:** subclass `mobility.base.MobilityModel`, implement `initial_position(area)` and `step(current, dt, area)`. Reference impls: `mobility/random_waypoint.py` (uniform target) and `mobility/poi.py` (`PoiMobility`, targets weighted `MobilityConfig.points_of_interest`, requires at least one with positive weight). Each `MobileNode` owns its own instance; inject a custom one via `run_simulation(config, mobility_factory=lambda rng: MyMobility(rng))` — a *factory*, not an instance, because each node needs its own stateful model seeded from its own RNG.
- **Beacon placement:** `beacons.place_beacons(area, beacons)` — `"grid"` (regular grid, default) or `"manual"` (explicit coordinates). Not a Strategy class, just a two-branch function.

### Correctness invariants that are easy to break

- **`network.py`'s tick-snapshot ordering.** `network_engine` snapshots every node's buffer *before* processing any node that tick, and `process_node_contacts` iterates that snapshot rather than the live buffer. This is load-bearing: without it, a node processed later in the same tick would immediately relay a message it received earlier that same tick, collapsing multi-hop delivery into one timestep and making results depend on dict iteration order. `process_node_contacts` has a `messages=None` default (→ falls back to `list(sender.buffer.values())`) purely so the single-node unit tests in `tests/test_network.py` can call it directly without going through `network_engine`.
- **Message copies must be independent.** Forwarding uses `dataclasses.replace(message, hops=message.hops+1, routing_state=dict(message.routing_state))` — never mutate `message.hops` in place, and always copy `routing_state` (it's a `Dict[str, Any]` bag reserved for future per-copy algorithm state, e.g. Spray & Wait's `copies_left`). A shared/mutated original would corrupt hop counts or state in every other buffer still holding a reference to it.
- **`BaseNode.battery_mah == math.inf`** is the sentinel for unlimited power (default for beacons). `consume_energy` no-ops on it; `energy_consumed_mah` returns `0.0` for it; the final report's energy average filters these nodes out via `initial_battery_mah != math.inf`. Don't treat `inf` as a normal float in new energy-related code.

### Design docs

- Spec (binding design authority): `docs/superpowers/specs/2026-09-14-festival-ble-sim-design.md`
- Implementation plan (task-by-task, argues from the spec): `docs/superpowers/plans/2026-09-14-festival-ble-sim-implementation.md`

### Conventions

- Python 3.9 floor: no `X | Y` union syntax, no `match` statements, no bare builtin generics — use `typing.Optional/List/Dict/Set/Tuple`.
- No comments except non-obvious WHY; no docstrings. The few existing comments (e.g. in `mobility/base.py`, `beacons.py`) mark deliberate injection points — keep that convention for new ones.
- One file per responsibility; SimPy-driven modules (`network.py`, `traffic.py`) deliberately take `env` structurally rather than importing `simpy` at module level, to stay independently testable.
