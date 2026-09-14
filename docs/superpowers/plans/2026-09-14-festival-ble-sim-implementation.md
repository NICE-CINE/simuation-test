# Festival BLE Mesh Simulator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a modular, typed, SimPy-based simulator of opportunistic BLE messaging at a festival, with pluggable mobility and routing strategies, a spatial-grid contact engine, a battery/energy model, and a delivery/latency/overhead report.

**Architecture:** A `src`-layout Python package (`festival_ble_sim`) with one file per responsibility (config, models, spatial index, mobility plugin, routing plugin, nodes, beacon placement, traffic generator, BLE contact engine, metrics, orchestrator), plus a thin `main.py` CLI entry point. Built bottom-up: pure data/logic modules first (fully unit-testable without SimPy), then the SimPy-driven engines, then the orchestrator that wires everything together.

**Tech Stack:** Python 3.9+, SimPy 4.x, pytest.

**Spec:** `docs/superpowers/specs/2026-09-14-festival-ble-sim-design.md`

## Global Constraints

- Python >= 3.9 (system default is 3.9.6). Do not use 3.10+-only syntax: no `X | Y` union types, no `match` statements, no builtin-generic subscription ambiguity — use `typing.List`/`Dict`/`Set`/`Optional`/`Tuple` everywhere for type hints.
- Runtime dependency: `simpy>=4.1` only. Dev dependency: `pytest>=7.0`. No numpy — mean/percentile are computed with pure Python in this plan.
- Package layout: `src/festival_ble_sim/...`, installed editable (`pip install -e ".[dev]"`), so tests import it as `import festival_ble_sim`.
- No comments except at the two designed injection points (mobility `step()`, beacon grid placement) marked `>>> POINT D'INJECTION`, and any other place where a non-obvious WHY needs explaining. No docstrings otherwise.
- Every task ends with a git commit. Every commit message MUST end with these two lines exactly:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01UV91yjxC6QqyjBUaAFRszP
  ```
- Run the full test suite (`pytest`) before every commit that touches code; all tests must pass, not just the new ones.

---

## Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/festival_ble_sim/__init__.py`
- Create: `.gitignore`
- Test: `tests/test_package.py`

**Interfaces:**
- Produces: an installed, importable `festival_ble_sim` package; a working `pytest` command from repo root.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "festival-ble-sim"
version = "0.1.0"
description = "Simulateur SimPy de messagerie BLE mesh en festival"
requires-python = ">=3.9"
dependencies = [
    "simpy>=4.1",
]

[project.optional-dependencies]
dev = ["pytest>=7.0"]

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create the empty package marker**

Create `src/festival_ble_sim/__init__.py` with empty content (0 bytes).

- [ ] **Step 3: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
*.egg-info/
.pytest_cache/
rapport_simulation.txt
simulation_events.log
```

- [ ] **Step 4: Create the venv and install the package**

Run:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```
Expected: install succeeds, `pip show festival-ble-sim` shows the package.

- [ ] **Step 5: Write the smoke test**

```python
import festival_ble_sim


def test_package_is_importable():
    assert festival_ble_sim is not None
```

- [ ] **Step 6: Run the test suite**

Run: `pytest -v`
Expected: 1 passed.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/festival_ble_sim/__init__.py .gitignore tests/test_package.py
git commit -m "$(cat <<'EOF'
chore: scaffold festival_ble_sim package

src-layout package with pyproject.toml, venv, and a smoke test
confirming the package installs and imports.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UV91yjxC6QqyjBUaAFRszP
EOF
)"
```

---

## Task 2: Core data models

**Files:**
- Create: `src/festival_ble_sim/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing (leaf module).
- Produces:
  - `Position(x: float, y: float)` with method `distance_to(other: Position) -> float`.
  - `Message(msg_id: int, src_id: int, dst_id: int, size_bytes: int, creation_time: float, ttl_s: float, hops: int = 0, routing_state: Dict[str, Any] = {})` with method `is_expired(now: float) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
from festival_ble_sim.models import Position, Message


def test_position_distance_to():
    a = Position(0.0, 0.0)
    b = Position(3.0, 4.0)
    assert a.distance_to(b) == 5.0


def test_message_is_expired_true_after_ttl():
    msg = Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    assert msg.is_expired(now=150.0) is True


def test_message_is_expired_false_within_ttl():
    msg = Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    assert msg.is_expired(now=50.0) is False


def test_message_defaults():
    msg = Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    assert msg.hops == 0
    assert msg.routing_state == {}
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'festival_ble_sim.models'`.

- [ ] **Step 3: Implement `models.py`**

```python
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class Position:
    x: float
    y: float

    def distance_to(self, other: "Position") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


@dataclass
class Message:
    msg_id: int
    src_id: int
    dst_id: int
    size_bytes: int
    creation_time: float
    ttl_s: float
    hops: int = 0
    routing_state: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self, now: float) -> bool:
        return (now - self.creation_time) > self.ttl_s
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_models.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/festival_ble_sim/models.py tests/test_models.py
git commit -m "$(cat <<'EOF'
feat: add Message and Position data models

Message carries exactly the fields required by the spec (id, src,
dst, size, creation time, hops) plus a routing_state bag so future
algorithms (e.g. Spray & Wait) can attach per-copy state without
changing the base contract.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UV91yjxC6QqyjBUaAFRszP
EOF
)"
```

---

## Task 3: Configuration dataclasses

**Files:**
- Create: `src/festival_ble_sim/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `AreaConfig`, `BleConfig`, `MobilityConfig`, `TrafficConfig`, `EnergyConfig`, `BeaconConfig`, and the root `SimulationConfig` (fields: `duration_s`, `num_festivaliers`, `node_buffer_capacity`, `random_seed`, `area`, `ble`, `mobility`, `traffic`, `energy`, `beacons`). `SimulationConfig.__post_init__` raises `ValueError` on invalid values.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from festival_ble_sim.config import SimulationConfig, AreaConfig, TrafficConfig


def test_default_config_is_valid():
    config = SimulationConfig()
    assert config.num_festivaliers > 0
    assert config.area.width_m == 500.0


def test_rejects_non_positive_area():
    with pytest.raises(ValueError):
        SimulationConfig(area=AreaConfig(width_m=0.0, height_m=100.0))


def test_rejects_too_few_festivaliers():
    with pytest.raises(ValueError):
        SimulationConfig(num_festivaliers=1)


def test_rejects_invalid_payload_range():
    with pytest.raises(ValueError):
        SimulationConfig(traffic=TrafficConfig(payload_size_range_bytes=(100, 10)))


def test_rejects_non_positive_buffer_capacity():
    with pytest.raises(ValueError):
        SimulationConfig(node_buffer_capacity=0)
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'festival_ble_sim.config'`.

- [ ] **Step 3: Implement `config.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class AreaConfig:
    width_m: float = 500.0
    height_m: float = 500.0


@dataclass(frozen=True)
class BleConfig:
    phone_range_m: float = 30.0
    beacon_range_m: float = 60.0
    transfer_rate_bytes_per_s: float = 10_000.0
    contact_check_interval_s: float = 1.0


@dataclass(frozen=True)
class MobilityConfig:
    speed_min_mps: float = 0.5
    speed_max_mps: float = 1.4
    pause_probability: float = 0.3
    pause_duration_range_s: Tuple[float, float] = (10.0, 60.0)
    tick_interval_s: float = 1.0


@dataclass(frozen=True)
class TrafficConfig:
    mean_interval_s: float = 5.0
    payload_size_range_bytes: Tuple[int, int] = (20, 512)
    message_ttl_s: float = 1800.0


@dataclass(frozen=True)
class EnergyConfig:
    initial_battery_mah: float = 2000.0
    tx_cost_mah_per_event: float = 0.02
    tx_cost_mah_per_byte: float = 1e-4
    rx_cost_mah_per_event: float = 0.01
    rx_cost_mah_per_byte: float = 5e-5


@dataclass(frozen=True)
class BeaconConfig:
    count: int = 0
    placement: str = "grid"
    manual_positions: Optional[List[Tuple[float, float]]] = None
    unlimited_power: bool = True


@dataclass
class SimulationConfig:
    duration_s: float = 3600.0
    num_festivaliers: int = 200
    node_buffer_capacity: int = 100
    random_seed: Optional[int] = 42
    area: AreaConfig = field(default_factory=AreaConfig)
    ble: BleConfig = field(default_factory=BleConfig)
    mobility: MobilityConfig = field(default_factory=MobilityConfig)
    traffic: TrafficConfig = field(default_factory=TrafficConfig)
    energy: EnergyConfig = field(default_factory=EnergyConfig)
    beacons: BeaconConfig = field(default_factory=BeaconConfig)

    def __post_init__(self) -> None:
        if self.area.width_m <= 0 or self.area.height_m <= 0:
            raise ValueError("area dimensions must be positive")
        if self.num_festivaliers < 2:
            raise ValueError("num_festivaliers must be at least 2 (need src and dst)")
        if self.node_buffer_capacity <= 0:
            raise ValueError("node_buffer_capacity must be positive")
        lo, hi = self.traffic.payload_size_range_bytes
        if lo <= 0 or hi < lo:
            raise ValueError("payload_size_range_bytes must satisfy 0 < lo <= hi")
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/festival_ble_sim/config.py tests/test_config.py
git commit -m "$(cat <<'EOF'
feat: add SimulationConfig dataclasses with validation

One root SimulationConfig composed of sub-dataclasses per concern
(area, BLE, mobility, traffic, energy, beacons) so the whole festival
can be reconfigured by changing one object. __post_init__ rejects the
obviously-invalid combinations (non-positive dimensions, <2
festivaliers, inverted payload range).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UV91yjxC6QqyjBUaAFRszP
EOF
)"
```

---

## Task 4: Spatial index

**Files:**
- Create: `src/festival_ble_sim/spatial.py`
- Test: `tests/test_spatial.py`

**Interfaces:**
- Consumes: `Position` from `festival_ble_sim.models` (only for the test double; `spatial.py` itself only relies on any object exposing `.position: Position` and `.id`, via `TYPE_CHECKING`-only import of `BaseNode` to avoid a runtime dependency on `nodes.py`, which doesn't exist yet).
- Produces: `SpatialGrid(width_m, height_m, cell_size_m)` with `insert(node)`, `update(node, old_x, old_y)`, `get_nearby(node, radius_m) -> List[node]`.

- [ ] **Step 1: Write the failing tests**

```python
from festival_ble_sim.models import Position
from festival_ble_sim.spatial import SpatialGrid


class _FakeNode:
    def __init__(self, node_id: int, x: float, y: float):
        self.id = node_id
        self.position = Position(x, y)


def test_get_nearby_returns_nodes_within_radius():
    grid = SpatialGrid(width_m=100.0, height_m=100.0, cell_size_m=10.0)
    center = _FakeNode(1, 50.0, 50.0)
    near = _FakeNode(2, 55.0, 50.0)
    far = _FakeNode(3, 90.0, 90.0)
    for n in (center, near, far):
        grid.insert(n)
    nearby = grid.get_nearby(center, radius_m=10.0)
    assert near in nearby
    assert far not in nearby
    assert center not in nearby


def test_update_moves_node_between_cells():
    grid = SpatialGrid(width_m=100.0, height_m=100.0, cell_size_m=10.0)
    node = _FakeNode(1, 5.0, 5.0)
    grid.insert(node)
    old_x, old_y = node.position.x, node.position.y
    node.position = Position(95.0, 95.0)
    grid.update(node, old_x, old_y)
    nearby = grid.get_nearby(_FakeNode(2, 95.0, 95.0), radius_m=2.0)
    assert node in nearby


def test_get_nearby_respects_area_edges():
    grid = SpatialGrid(width_m=20.0, height_m=20.0, cell_size_m=10.0)
    corner = _FakeNode(1, 0.0, 0.0)
    grid.insert(corner)
    nearby = grid.get_nearby(_FakeNode(2, 1.0, 1.0), radius_m=5.0)
    assert corner in nearby
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_spatial.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'festival_ble_sim.spatial'`.

- [ ] **Step 3: Implement `spatial.py`**

```python
from __future__ import annotations
import math
from typing import Dict, List, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .nodes import BaseNode


class SpatialGrid:
    def __init__(self, width_m: float, height_m: float, cell_size_m: float) -> None:
        self.width_m = width_m
        self.height_m = height_m
        self.cell_size_m = cell_size_m
        self._cols = max(1, math.ceil(width_m / cell_size_m))
        self._rows = max(1, math.ceil(height_m / cell_size_m))
        self._cells: Dict[Tuple[int, int], Set["BaseNode"]] = {}

    def _cell_of(self, x: float, y: float) -> Tuple[int, int]:
        col = min(max(int(x // self.cell_size_m), 0), self._cols - 1)
        row = min(max(int(y // self.cell_size_m), 0), self._rows - 1)
        return col, row

    def insert(self, node: "BaseNode") -> None:
        cell = self._cell_of(node.position.x, node.position.y)
        self._cells.setdefault(cell, set()).add(node)

    def update(self, node: "BaseNode", old_x: float, old_y: float) -> None:
        old_cell = self._cell_of(old_x, old_y)
        new_cell = self._cell_of(node.position.x, node.position.y)
        if old_cell == new_cell:
            return
        if old_cell in self._cells:
            self._cells[old_cell].discard(node)
        self._cells.setdefault(new_cell, set()).add(node)

    def get_nearby(self, node: "BaseNode", radius_m: float) -> List["BaseNode"]:
        cx, cy = self._cell_of(node.position.x, node.position.y)
        cell_radius = max(1, math.ceil(radius_m / self.cell_size_m))
        found: List["BaseNode"] = []
        for dc in range(-cell_radius, cell_radius + 1):
            for dr in range(-cell_radius, cell_radius + 1):
                cell = (cx + dc, cy + dr)
                for other in self._cells.get(cell, ()):
                    if other is node:
                        continue
                    if node.position.distance_to(other.position) <= radius_m:
                        found.append(other)
        return found
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_spatial.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/festival_ble_sim/spatial.py tests/test_spatial.py
git commit -m "$(cat <<'EOF'
feat: add SpatialGrid for O(nearby) neighbor lookup

Cell-bucketed spatial index so the BLE contact engine can find nodes
within radio range without an O(n^2) scan of every node pair — needed
to keep the simulation usable at hundreds/thousands of festivaliers.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UV91yjxC6QqyjBUaAFRszP
EOF
)"
```


## Task 5: Energy cost model

**Files:**
- Create: `src/festival_ble_sim/energy.py`
- Test: `tests/test_energy.py`

**Interfaces:**
- Consumes: `EnergyConfig` from `festival_ble_sim.config`.
- Produces: `EnergyModel(config: EnergyConfig)` with `cost_of_tx(size_bytes: int) -> float` and `cost_of_rx(size_bytes: int) -> float`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from festival_ble_sim.config import EnergyConfig
from festival_ble_sim.energy import EnergyModel


def test_cost_of_tx():
    config = EnergyConfig(tx_cost_mah_per_event=0.02, tx_cost_mah_per_byte=0.0001)
    model = EnergyModel(config)
    assert model.cost_of_tx(100) == pytest.approx(0.02 + 100 * 0.0001)


def test_cost_of_rx():
    config = EnergyConfig(rx_cost_mah_per_event=0.01, rx_cost_mah_per_byte=0.00005)
    model = EnergyModel(config)
    assert model.cost_of_rx(200) == pytest.approx(0.01 + 200 * 0.00005)
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_energy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'festival_ble_sim.energy'`.

- [ ] **Step 3: Implement `energy.py`**

```python
from __future__ import annotations
from .config import EnergyConfig


class EnergyModel:
    def __init__(self, config: EnergyConfig) -> None:
        self._config = config

    def cost_of_tx(self, size_bytes: int) -> float:
        return self._config.tx_cost_mah_per_event + size_bytes * self._config.tx_cost_mah_per_byte

    def cost_of_rx(self, size_bytes: int) -> float:
        return self._config.rx_cost_mah_per_event + size_bytes * self._config.rx_cost_mah_per_byte
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_energy.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/festival_ble_sim/energy.py tests/test_energy.py
git commit -m "$(cat <<'EOF'
feat: add EnergyModel for BLE tx/rx cost calculation

Pure cost calculator (fixed per-event cost + per-byte cost, in mAh)
used by the network engine to drain each node's battery on every
transmission or reception.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UV91yjxC6QqyjBUaAFRszP
EOF
)"
```

---

## Task 6: Mobility plugin interface + Random Waypoint

**Files:**
- Create: `src/festival_ble_sim/mobility/__init__.py`
- Create: `src/festival_ble_sim/mobility/base.py`
- Create: `src/festival_ble_sim/mobility/random_waypoint.py`
- Test: `tests/test_mobility.py`

**Interfaces:**
- Consumes: `AreaConfig`, `MobilityConfig` from `festival_ble_sim.config`; `Position` from `festival_ble_sim.models`.
- Produces:
  - `MobilityModel` (ABC) with abstract `initial_position(area) -> Position` and `step(current, dt, area) -> Position`.
  - `move_towards(current: Position, target: Position, speed_mps: float, dt: float) -> Position` (pure helper, module-level in `random_waypoint.py`).
  - `RandomWaypointMobility(config: MobilityConfig, rng: Optional[random.Random] = None)` implementing `MobilityModel`.

- [ ] **Step 1: Write the failing tests**

```python
import random
import pytest
from festival_ble_sim.config import AreaConfig, MobilityConfig
from festival_ble_sim.models import Position
from festival_ble_sim.mobility.random_waypoint import RandomWaypointMobility, move_towards


def test_move_towards_advances_by_speed_times_dt_when_far():
    current = Position(0.0, 0.0)
    target = Position(100.0, 0.0)
    result = move_towards(current, target, speed_mps=2.0, dt=1.0)
    assert result.x == pytest.approx(2.0)
    assert result.y == pytest.approx(0.0)


def test_move_towards_stops_at_target_when_close():
    current = Position(0.0, 0.0)
    target = Position(1.0, 0.0)
    result = move_towards(current, target, speed_mps=10.0, dt=1.0)
    assert result.x == pytest.approx(1.0)
    assert result.y == pytest.approx(0.0)


def test_move_towards_no_movement_when_already_at_target():
    current = Position(5.0, 5.0)
    target = Position(5.0, 5.0)
    result = move_towards(current, target, speed_mps=2.0, dt=1.0)
    assert result.x == pytest.approx(5.0)
    assert result.y == pytest.approx(5.0)


def test_initial_position_within_area_bounds():
    area = AreaConfig(width_m=100.0, height_m=50.0)
    mobility = RandomWaypointMobility(MobilityConfig(), rng=random.Random(1))
    for _ in range(50):
        pos = mobility.initial_position(area)
        assert 0.0 <= pos.x <= area.width_m
        assert 0.0 <= pos.y <= area.height_m


def test_step_keeps_position_within_area_bounds():
    area = AreaConfig(width_m=50.0, height_m=50.0)
    config = MobilityConfig(speed_min_mps=1.0, speed_max_mps=3.0, pause_probability=0.2, tick_interval_s=1.0)
    mobility = RandomWaypointMobility(config, rng=random.Random(2))
    pos = mobility.initial_position(area)
    for _ in range(500):
        pos = mobility.step(pos, dt=1.0, area=area)
        assert 0.0 <= pos.x <= area.width_m
        assert 0.0 <= pos.y <= area.height_m
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_mobility.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'festival_ble_sim.mobility'`.

- [ ] **Step 3: Create the subpackage marker**

Create `src/festival_ble_sim/mobility/__init__.py` with empty content.

- [ ] **Step 4: Implement `mobility/base.py`**

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from ..config import AreaConfig
from ..models import Position


class MobilityModel(ABC):
    @abstractmethod
    def initial_position(self, area: AreaConfig) -> Position:
        ...

    @abstractmethod
    def step(self, current: Position, dt: float, area: AreaConfig) -> Position:
        # >>> POINT D'INJECTION : logique spatiale/mathematique perso
        # (attraction vers une scene, densite de foule, zones interdites...)
        ...
```

- [ ] **Step 5: Implement `mobility/random_waypoint.py`**

```python
from __future__ import annotations
import math
import random
from typing import Optional
from ..config import AreaConfig, MobilityConfig
from ..models import Position
from .base import MobilityModel


def move_towards(current: Position, target: Position, speed_mps: float, dt: float) -> Position:
    dx = target.x - current.x
    dy = target.y - current.y
    dist = math.hypot(dx, dy)
    if dist == 0:
        return Position(current.x, current.y)
    step_len = min(speed_mps * dt, dist)
    return Position(current.x + dx / dist * step_len, current.y + dy / dist * step_len)


class RandomWaypointMobility(MobilityModel):
    def __init__(self, config: MobilityConfig, rng: Optional[random.Random] = None) -> None:
        self._config = config
        self._rng = rng or random.Random()
        self._target: Optional[Position] = None
        self._speed_mps: float = 0.0
        self._pause_until: float = 0.0
        self._elapsed_s: float = 0.0

    def initial_position(self, area: AreaConfig) -> Position:
        return Position(
            x=self._rng.uniform(0.0, area.width_m),
            y=self._rng.uniform(0.0, area.height_m),
        )

    def _pick_new_target(self, area: AreaConfig) -> None:
        self._target = Position(
            x=self._rng.uniform(0.0, area.width_m),
            y=self._rng.uniform(0.0, area.height_m),
        )
        self._speed_mps = self._rng.uniform(self._config.speed_min_mps, self._config.speed_max_mps)

    def step(self, current: Position, dt: float, area: AreaConfig) -> Position:
        self._elapsed_s += dt
        if self._target is None:
            self._pick_new_target(area)

        if self._elapsed_s < self._pause_until:
            return current

        if current.distance_to(self._target) < 1.0:
            if self._rng.random() < self._config.pause_probability:
                lo, hi = self._config.pause_duration_range_s
                self._pause_until = self._elapsed_s + self._rng.uniform(lo, hi)
                return current
            self._pick_new_target(area)

        return move_towards(current, self._target, self._speed_mps, dt)
```

- [ ] **Step 6: Run tests, verify they pass**

Run: `pytest tests/test_mobility.py -v`
Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add src/festival_ble_sim/mobility/ tests/test_mobility.py
git commit -m "$(cat <<'EOF'
feat: add MobilityModel interface and Random Waypoint implementation

MobilityModel is an ABC so mobility, like routing, is a pluggable
strategy — each MobileNode owns its own instance. RandomWaypointMobility
implements the requested model; move_towards() is factored out as a
pure function so speed/direction math is testable without randomness.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UV91yjxC6QqyjBUaAFRszP
EOF
)"
```

---

## Task 7: Routing plugin interface + Epidemic routing

**Files:**
- Create: `src/festival_ble_sim/routing/__init__.py`
- Create: `src/festival_ble_sim/routing/base.py`
- Create: `src/festival_ble_sim/routing/epidemic.py`
- Test: `tests/test_routing.py`

**Interfaces:**
- Consumes: `Message` from `festival_ble_sim.models`. Only type-checks against `BaseNode` (`festival_ble_sim.nodes`, not yet created) via `TYPE_CHECKING` — at runtime, `holder`/`contact` just need a `has_message(msg_id: int) -> bool` method (duck typing), which is why this task can ship before `nodes.py` exists.
- Produces:
  - `RoutingDecision` (Enum: `FORWARD`, `IGNORE`).
  - `RoutingAlgorithm` (ABC) with abstract `decide(message, holder, contact) -> RoutingDecision` and optional hook `on_delivered(message, holder) -> None`.
  - `EpidemicRouting(RoutingAlgorithm)`.

- [ ] **Step 1: Write the failing tests**

```python
from festival_ble_sim.models import Message
from festival_ble_sim.routing.base import RoutingDecision
from festival_ble_sim.routing.epidemic import EpidemicRouting


class _FakeNode:
    def __init__(self, has_msg: bool):
        self._has_msg = has_msg

    def has_message(self, msg_id: int) -> bool:
        return self._has_msg


def _msg():
    return Message(msg_id=1, src_id=1, dst_id=2, size_bytes=100, creation_time=0.0, ttl_s=60.0)


def test_epidemic_forwards_when_contact_missing_message():
    algo = EpidemicRouting()
    holder = _FakeNode(has_msg=False)
    contact = _FakeNode(has_msg=False)
    assert algo.decide(_msg(), holder, contact) is RoutingDecision.FORWARD


def test_epidemic_ignores_when_contact_already_has_message():
    algo = EpidemicRouting()
    holder = _FakeNode(has_msg=False)
    contact = _FakeNode(has_msg=True)
    assert algo.decide(_msg(), holder, contact) is RoutingDecision.IGNORE


def test_on_delivered_default_hook_is_noop():
    algo = EpidemicRouting()
    holder = _FakeNode(has_msg=True)
    algo.on_delivered(_msg(), holder)
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_routing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'festival_ble_sim.routing'`.

- [ ] **Step 3: Create the subpackage marker**

Create `src/festival_ble_sim/routing/__init__.py` with empty content.

- [ ] **Step 4: Implement `routing/base.py`**

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import TYPE_CHECKING
from ..models import Message

if TYPE_CHECKING:
    from ..nodes import BaseNode


class RoutingDecision(Enum):
    FORWARD = auto()
    IGNORE = auto()


class RoutingAlgorithm(ABC):
    @abstractmethod
    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode") -> RoutingDecision:
        # >>> POINT D'INJECTION : tes propres algos de routage
        # (Spray & Wait, PRoPHET, scoring base sur les bornes...)
        ...

    def on_delivered(self, message: Message, holder: "BaseNode") -> None:
        pass
```

- [ ] **Step 5: Implement `routing/epidemic.py`**

```python
from __future__ import annotations
from typing import TYPE_CHECKING
from ..models import Message
from .base import RoutingAlgorithm, RoutingDecision

if TYPE_CHECKING:
    from ..nodes import BaseNode


class EpidemicRouting(RoutingAlgorithm):
    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode") -> RoutingDecision:
        if contact.has_message(message.msg_id):
            return RoutingDecision.IGNORE
        return RoutingDecision.FORWARD
```

- [ ] **Step 6: Run tests, verify they pass**

Run: `pytest tests/test_routing.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add src/festival_ble_sim/routing/ tests/test_routing.py
git commit -m "$(cat <<'EOF'
feat: add RoutingAlgorithm interface and Epidemic routing

Strategy pattern for routing decisions at each BLE contact.
EpidemicRouting is the naive reference implementation (flood to any
contact that doesn't already have the message) and the template for
custom algorithms.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UV91yjxC6QqyjBUaAFRszP
EOF
)"
```

---

## Task 8: Nodes — BaseNode, MobileNode, BeaconNode

**Files:**
- Create: `src/festival_ble_sim/nodes.py`
- Test: `tests/test_nodes.py`

**Interfaces:**
- Consumes: `Message`, `Position` from `festival_ble_sim.models`; `AreaConfig` from `festival_ble_sim.config`; `MobilityModel` from `festival_ble_sim.mobility.base`.
- Produces:
  - `BaseNode(node_id, position, radio_range_m, buffer_capacity, battery_mah)` with attributes `id`, `position`, `radio_range_m`, `buffer_capacity`, `battery_mah`, `initial_battery_mah`, `is_active`, `buffer: Dict[int, Message]`, `delivered_ids: Set[int]`; methods `has_message(msg_id) -> bool`, `store_message(message) -> None` (FIFO eviction), `mark_delivered(msg_id) -> None`, `consume_energy(mah) -> None`; property `energy_consumed_mah -> float`.
  - `MobileNode(node_id, mobility, radio_range_m, buffer_capacity, battery_mah, area)` — `BaseNode` subclass; method `move(dt, area) -> None`.
  - `BeaconNode(node_id, position, radio_range_m, buffer_capacity, unlimited_power=True, battery_mah=0.0)` — `BaseNode` subclass.

- [ ] **Step 1: Write the failing tests**

```python
import math
from festival_ble_sim.config import AreaConfig
from festival_ble_sim.models import Message, Position
from festival_ble_sim.nodes import BaseNode, MobileNode, BeaconNode


def _make_message(msg_id=1):
    return Message(msg_id=msg_id, src_id=1, dst_id=2, size_bytes=50, creation_time=0.0, ttl_s=100.0)


def test_store_message_evicts_oldest_when_full():
    node = BaseNode(node_id=1, position=Position(0, 0), radio_range_m=10.0, buffer_capacity=2, battery_mah=100.0)
    node.store_message(_make_message(1))
    node.store_message(_make_message(2))
    node.store_message(_make_message(3))
    assert set(node.buffer.keys()) == {2, 3}


def test_has_message_true_after_store_and_after_delivery():
    node = BaseNode(node_id=1, position=Position(0, 0), radio_range_m=10.0, buffer_capacity=5, battery_mah=100.0)
    node.store_message(_make_message(1))
    assert node.has_message(1) is True
    node.mark_delivered(1)
    assert node.has_message(1) is True
    assert 1 not in node.buffer


def test_consume_energy_deactivates_node_at_zero_battery():
    node = BaseNode(node_id=1, position=Position(0, 0), radio_range_m=10.0, buffer_capacity=5, battery_mah=1.0)
    node.consume_energy(0.5)
    assert node.is_active is True
    node.consume_energy(0.6)
    assert node.battery_mah == 0.0
    assert node.is_active is False


def test_consume_energy_never_goes_negative():
    node = BaseNode(node_id=1, position=Position(0, 0), radio_range_m=10.0, buffer_capacity=5, battery_mah=1.0)
    node.consume_energy(10.0)
    assert node.battery_mah == 0.0


def test_unlimited_power_node_never_deactivates():
    node = BaseNode(node_id=1, position=Position(0, 0), radio_range_m=10.0, buffer_capacity=5, battery_mah=math.inf)
    node.consume_energy(1_000_000.0)
    assert node.is_active is True
    assert node.energy_consumed_mah == 0.0


def test_mobile_node_uses_injected_mobility_for_initial_position_and_move():
    class _StubMobility:
        def initial_position(self, area):
            return Position(1.0, 2.0)

        def step(self, current, dt, area):
            return Position(current.x + 1.0, current.y)

    area = AreaConfig(width_m=100.0, height_m=100.0)
    node = MobileNode(node_id=1, mobility=_StubMobility(), radio_range_m=10.0, buffer_capacity=5, battery_mah=100.0, area=area)
    assert node.position.x == 1.0
    node.move(dt=1.0, area=area)
    assert node.position.x == 2.0


def test_beacon_node_has_unlimited_power_by_default():
    beacon = BeaconNode(node_id=1, position=Position(0, 0), radio_range_m=60.0, buffer_capacity=100)
    assert beacon.battery_mah == math.inf
    assert beacon.is_active is True


def test_beacon_node_can_have_limited_power():
    beacon = BeaconNode(node_id=1, position=Position(0, 0), radio_range_m=60.0, buffer_capacity=100, unlimited_power=False, battery_mah=5.0)
    beacon.consume_energy(10.0)
    assert beacon.is_active is False
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_nodes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'festival_ble_sim.nodes'`.

- [ ] **Step 3: Implement `nodes.py`**

```python
from __future__ import annotations
import math
from typing import Dict, Set
from .config import AreaConfig
from .mobility.base import MobilityModel
from .models import Message, Position


class BaseNode:
    def __init__(
        self,
        node_id: int,
        position: Position,
        radio_range_m: float,
        buffer_capacity: int,
        battery_mah: float,
    ) -> None:
        self.id = node_id
        self.position = position
        self.radio_range_m = radio_range_m
        self.buffer_capacity = buffer_capacity
        self.initial_battery_mah = battery_mah
        self.battery_mah = battery_mah
        self.is_active = True
        self.buffer: Dict[int, Message] = {}
        self.delivered_ids: Set[int] = set()

    def has_message(self, msg_id: int) -> bool:
        return msg_id in self.buffer or msg_id in self.delivered_ids

    def store_message(self, message: Message) -> None:
        if message.msg_id in self.buffer:
            return
        if len(self.buffer) >= self.buffer_capacity:
            oldest_id = next(iter(self.buffer))
            del self.buffer[oldest_id]
        self.buffer[message.msg_id] = message

    def mark_delivered(self, msg_id: int) -> None:
        self.delivered_ids.add(msg_id)
        self.buffer.pop(msg_id, None)

    def consume_energy(self, mah: float) -> None:
        if self.battery_mah == math.inf:
            return
        self.battery_mah = max(0.0, self.battery_mah - mah)
        if self.battery_mah <= 0.0:
            self.is_active = False

    @property
    def energy_consumed_mah(self) -> float:
        if self.initial_battery_mah == math.inf:
            return 0.0
        return self.initial_battery_mah - self.battery_mah


class MobileNode(BaseNode):
    def __init__(
        self,
        node_id: int,
        mobility: MobilityModel,
        radio_range_m: float,
        buffer_capacity: int,
        battery_mah: float,
        area: AreaConfig,
    ) -> None:
        position = mobility.initial_position(area)
        super().__init__(node_id, position, radio_range_m, buffer_capacity, battery_mah)
        self.mobility = mobility

    def move(self, dt: float, area: AreaConfig) -> None:
        self.position = self.mobility.step(self.position, dt, area)


class BeaconNode(BaseNode):
    def __init__(
        self,
        node_id: int,
        position: Position,
        radio_range_m: float,
        buffer_capacity: int,
        unlimited_power: bool = True,
        battery_mah: float = 0.0,
    ) -> None:
        initial_battery = math.inf if unlimited_power else battery_mah
        super().__init__(node_id, position, radio_range_m, buffer_capacity, initial_battery)
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_nodes.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/festival_ble_sim/nodes.py tests/test_nodes.py
git commit -m "$(cat <<'EOF'
feat: add BaseNode, MobileNode, BeaconNode

BaseNode owns the buffer (FIFO eviction at capacity), delivery
tracking, and battery/is_active state shared by both node kinds.
MobileNode delegates all movement to its injected MobilityModel;
BeaconNode defaults to unlimited power (mains-powered) but can opt
into a finite battery.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UV91yjxC6QqyjBUaAFRszP
EOF
)"
```

---

## Task 9: Beacon placement strategies

**Files:**
- Create: `src/festival_ble_sim/beacons.py`
- Test: `tests/test_beacons.py`

**Interfaces:**
- Consumes: `AreaConfig`, `BeaconConfig` from `festival_ble_sim.config`; `Position` from `festival_ble_sim.models`.
- Produces: `place_beacons(area: AreaConfig, beacons: BeaconConfig) -> List[Position]`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from festival_ble_sim.beacons import place_beacons
from festival_ble_sim.config import AreaConfig, BeaconConfig


def test_zero_beacons_returns_empty_list():
    assert place_beacons(AreaConfig(), BeaconConfig(count=0)) == []


def test_grid_placement_returns_requested_count_within_bounds():
    area = AreaConfig(width_m=100.0, height_m=100.0)
    positions = place_beacons(area, BeaconConfig(count=4, placement="grid"))
    assert len(positions) == 4
    for p in positions:
        assert 0.0 < p.x < area.width_m
        assert 0.0 < p.y < area.height_m


def test_manual_placement_converts_tuples():
    area = AreaConfig()
    positions = place_beacons(
        area, BeaconConfig(count=2, placement="manual", manual_positions=[(10.0, 20.0), (30.0, 40.0)])
    )
    assert positions[0].x == 10.0 and positions[0].y == 20.0
    assert positions[1].x == 30.0 and positions[1].y == 40.0


def test_manual_placement_without_positions_raises():
    with pytest.raises(ValueError):
        place_beacons(AreaConfig(), BeaconConfig(count=2, placement="manual", manual_positions=None))


def test_unknown_placement_mode_raises():
    with pytest.raises(ValueError):
        place_beacons(AreaConfig(), BeaconConfig(count=2, placement="bogus"))
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_beacons.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'festival_ble_sim.beacons'`.

- [ ] **Step 3: Implement `beacons.py`**

```python
from __future__ import annotations
import math
from typing import List
from .config import AreaConfig, BeaconConfig
from .models import Position


def place_beacons(area: AreaConfig, beacons: BeaconConfig) -> List[Position]:
    if beacons.count <= 0:
        return []
    if beacons.placement == "manual":
        if not beacons.manual_positions:
            raise ValueError("beacons.manual_positions must be set when placement='manual'")
        return [Position(x, y) for x, y in beacons.manual_positions]
    if beacons.placement == "grid":
        return _place_grid(area, beacons.count)
    raise ValueError(f"unknown beacon placement mode: {beacons.placement!r}")


def _place_grid(area: AreaConfig, count: int) -> List[Position]:
    # >>> POINT D'INJECTION : remplace cette grille reguliere par un
    # placement strategique (entrees, scenes, points de forte densite...)
    cols = max(1, math.floor(math.sqrt(count)))
    rows = max(1, math.ceil(count / cols))
    dx = area.width_m / (cols + 1)
    dy = area.height_m / (rows + 1)
    positions: List[Position] = []
    for row in range(rows):
        for col in range(cols):
            if len(positions) >= count:
                return positions
            positions.append(Position(x=(col + 1) * dx, y=(row + 1) * dy))
    return positions
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_beacons.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/festival_ble_sim/beacons.py tests/test_beacons.py
git commit -m "$(cat <<'EOF'
feat: add beacon placement strategies

place_beacons() supports a regular grid (default) or manually
specified coordinates, and can be disabled entirely (count=0) so the
simulation can be run with or without relay beacons.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UV91yjxC6QqyjBUaAFRszP
EOF
)"
```

---

## Task 10: Metrics collector and report

**Files:**
- Create: `src/festival_ble_sim/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `Message` from `festival_ble_sim.models`.
- Produces:
  - `SimulationReport` (dataclass): `messages_created`, `messages_delivered`, `delivery_ratio`, `avg_latency_s`, `p95_latency_s`, `avg_hops`, `overhead`, `total_transmissions`, `total_energy_consumed_mah`, `avg_energy_consumed_mah`, `dead_node_count`.
  - `MetricsCollector()` with `record_creation(message)`, `record_transmission()`, `record_delivery(message, delivered_at)`, `build_report(node_energy_consumed_mah: List[float], dead_node_count: int) -> SimulationReport`.
  - `format_report(report: SimulationReport) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from festival_ble_sim.metrics import MetricsCollector, format_report
from festival_ble_sim.models import Message


def _msg(msg_id, creation_time, hops):
    m = Message(msg_id=msg_id, src_id=1, dst_id=2, size_bytes=10, creation_time=creation_time, ttl_s=1000.0)
    m.hops = hops
    return m


def test_build_report_computes_delivery_ratio_and_latency():
    collector = MetricsCollector()
    m1 = _msg(1, creation_time=0.0, hops=1)
    m2 = _msg(2, creation_time=0.0, hops=2)
    m3 = _msg(3, creation_time=0.0, hops=0)
    for m in (m1, m2, m3):
        collector.record_creation(m)
    collector.record_transmission()
    collector.record_transmission()
    collector.record_transmission()
    collector.record_delivery(m1, delivered_at=10.0)
    collector.record_delivery(m2, delivered_at=20.0)

    report = collector.build_report(node_energy_consumed_mah=[1.0, 3.0], dead_node_count=1)

    assert report.messages_created == 3
    assert report.messages_delivered == 2
    assert report.delivery_ratio == pytest.approx(2 / 3)
    assert report.avg_latency_s == pytest.approx((10.0 + 20.0) / 2)
    assert report.avg_hops == pytest.approx((1 + 2) / 2)
    assert report.overhead == pytest.approx(3 / 2)
    assert report.total_transmissions == 3
    assert report.total_energy_consumed_mah == pytest.approx(4.0)
    assert report.avg_energy_consumed_mah == pytest.approx(2.0)
    assert report.dead_node_count == 1


def test_duplicate_delivery_is_recorded_once():
    collector = MetricsCollector()
    m1 = _msg(1, creation_time=0.0, hops=1)
    collector.record_creation(m1)
    collector.record_delivery(m1, delivered_at=5.0)
    collector.record_delivery(m1, delivered_at=6.0)
    report = collector.build_report([], 0)
    assert report.messages_delivered == 1


def test_empty_collector_reports_zero_without_division_errors():
    collector = MetricsCollector()
    report = collector.build_report([], 0)
    assert report.messages_created == 0
    assert report.delivery_ratio == 0.0
    assert report.avg_latency_s == 0.0


def test_format_report_includes_key_numbers():
    collector = MetricsCollector()
    m1 = _msg(1, creation_time=0.0, hops=1)
    collector.record_creation(m1)
    collector.record_delivery(m1, delivered_at=5.0)
    report = collector.build_report([2.0], 0)
    text = format_report(report)
    assert "100.00" in text
    assert "5.0" in text
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'festival_ble_sim.metrics'`.

- [ ] **Step 3: Implement `metrics.py`**

```python
from __future__ import annotations
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

    def record_creation(self, message: Message) -> None:
        self._messages_created += 1

    def record_transmission(self) -> None:
        self._total_transmissions += 1

    def record_delivery(self, message: Message, delivered_at: float) -> None:
        if message.msg_id in self._delivered_msg_ids:
            return
        self._delivered_msg_ids.add(message.msg_id)
        self._deliveries.append(_DeliveryRecord(latency_s=delivered_at - message.creation_time, hops=message.hops))

    def build_report(self, node_energy_consumed_mah: List[float], dead_node_count: int) -> SimulationReport:
        delivered = len(self._deliveries)
        delivery_ratio = delivered / self._messages_created if self._messages_created else 0.0
        latencies = sorted(d.latency_s for d in self._deliveries)
        avg_latency = sum(latencies) / delivered if delivered else 0.0
        p95_latency = latencies[int(0.95 * (delivered - 1))] if delivered else 0.0
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
        "===================================================================\n"
    )
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_metrics.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/festival_ble_sim/metrics.py tests/test_metrics.py
git commit -m "$(cat <<'EOF'
feat: add MetricsCollector and SimulationReport

Collects message creation/transmission/delivery events during a run
and computes delivery ratio, avg/p95 latency, avg hops, overhead
(transmissions per delivery), and energy stats. SimulationReport is a
plain dataclass; format_report() renders it as text separately so the
raw numbers stay reusable (JSON export, multi-algorithm comparison).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UV91yjxC6QqyjBUaAFRszP
EOF
)"
```

---

## Task 11: Traffic generator

**Files:**
- Create: `src/festival_ble_sim/traffic.py`
- Test: `tests/test_traffic.py`

**Interfaces:**
- Consumes: `TrafficConfig` from `festival_ble_sim.config`; `Message` from `festival_ble_sim.models`; `MetricsCollector` from `festival_ble_sim.metrics`; `MobileNode` from `festival_ble_sim.nodes` (for the type hint only — the generator only calls `.store_message()` on whatever's in the `nodes` dict, so tests may use a lightweight duck-typed stand-in).
- Produces:
  - `sample_interval_s(config: TrafficConfig, rng: random.Random) -> float`.
  - `generate_message(msg_id, now, src_id, dst_id, config, rng) -> Message`.
  - `traffic_generator(env, nodes: Dict[int, MobileNode], config: TrafficConfig, metrics: MetricsCollector, id_generator: Iterator[int], rng: random.Random)` — a SimPy process (generator function).

- [ ] **Step 1: Write the failing tests**

```python
import itertools
import random
import pytest
import simpy
from festival_ble_sim.config import TrafficConfig
from festival_ble_sim.metrics import MetricsCollector
from festival_ble_sim.traffic import generate_message, sample_interval_s, traffic_generator


def test_generate_message_payload_within_range():
    config = TrafficConfig(payload_size_range_bytes=(20, 30), message_ttl_s=60.0)
    rng = random.Random(1)
    msg = generate_message(msg_id=1, now=5.0, src_id=1, dst_id=2, config=config, rng=rng)
    assert 20 <= msg.size_bytes <= 30
    assert msg.ttl_s == 60.0
    assert msg.creation_time == 5.0
    assert msg.hops == 0


def test_sample_interval_s_average_matches_configured_mean():
    config = TrafficConfig(mean_interval_s=4.0)
    rng = random.Random(42)
    samples = [sample_interval_s(config, rng) for _ in range(5000)]
    mean = sum(samples) / len(samples)
    assert mean == pytest.approx(4.0, rel=0.15)


class _FakeNode:
    def __init__(self, node_id):
        self.id = node_id
        self.buffer = {}

    def store_message(self, message):
        self.buffer[message.msg_id] = message


def test_traffic_generator_creates_messages_over_time():
    env = simpy.Environment()
    nodes = {1: _FakeNode(1), 2: _FakeNode(2), 3: _FakeNode(3)}
    metrics = MetricsCollector()
    config = TrafficConfig(mean_interval_s=1.0, payload_size_range_bytes=(10, 10), message_ttl_s=100.0)
    id_gen = itertools.count(1)
    rng = random.Random(7)
    env.process(traffic_generator(env, nodes, config, metrics, id_gen, rng))
    env.run(until=20.0)
    total_buffered = sum(len(n.buffer) for n in nodes.values())
    report = metrics.build_report([], 0)
    assert report.messages_created > 0
    assert total_buffered == report.messages_created
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_traffic.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'festival_ble_sim.traffic'`.

- [ ] **Step 3: Implement `traffic.py`**

```python
from __future__ import annotations
import random
from typing import Dict, Iterator, List
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
    mobile_ids: List[int] = list(nodes.keys())
    while True:
        yield env.timeout(sample_interval_s(config, rng))
        src_id, dst_id = rng.sample(mobile_ids, 2)
        message = generate_message(next(id_generator), env.now, src_id, dst_id, config, rng)
        nodes[src_id].store_message(message)
        metrics.record_creation(message)
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_traffic.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/festival_ble_sim/traffic.py tests/test_traffic.py
git commit -m "$(cat <<'EOF'
feat: add Poisson traffic generator

SimPy process that creates messages at exponentially-distributed
intervals between random festivalier pairs, with payload size drawn
uniformly from the configured range. Pure helpers (sample_interval_s,
generate_message) are factored out so the traffic math is testable
without a running SimPy environment.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UV91yjxC6QqyjBUaAFRszP
EOF
)"
```

---

## Task 12: BLE contact / network engine

**Files:**
- Create: `src/festival_ble_sim/network.py`
- Test: `tests/test_network.py`

**Interfaces:**
- Consumes: `EnergyModel` from `festival_ble_sim.energy`; `MetricsCollector` from `festival_ble_sim.metrics`; `Message` from `festival_ble_sim.models`; `BaseNode` from `festival_ble_sim.nodes`; `RoutingAlgorithm`, `RoutingDecision` from `festival_ble_sim.routing.base`; `SpatialGrid` from `festival_ble_sim.spatial`.
- Produces:
  - `process_node_contacts(now, sender, grid, routing_algorithm, energy_model, metrics) -> None` (pure per-node contact processing, no SimPy dependency — this is the "logique pure" testing surface).
  - `network_engine(env, nodes: Dict[int, BaseNode], grid, routing_algorithm, energy_model, metrics, contact_check_interval_s)` — a SimPy process that calls `process_node_contacts` for every node on each tick.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
import simpy
from festival_ble_sim.config import EnergyConfig
from festival_ble_sim.energy import EnergyModel
from festival_ble_sim.metrics import MetricsCollector
from festival_ble_sim.models import Message, Position
from festival_ble_sim.network import network_engine, process_node_contacts
from festival_ble_sim.nodes import BaseNode
from festival_ble_sim.routing.epidemic import EpidemicRouting
from festival_ble_sim.spatial import SpatialGrid


def _node(node_id, x, y, buffer_capacity=10, battery=100.0):
    return BaseNode(node_id=node_id, position=Position(x, y), radio_range_m=20.0, buffer_capacity=buffer_capacity, battery_mah=battery)


def _energy_model():
    return EnergyModel(
        EnergyConfig(tx_cost_mah_per_event=1.0, tx_cost_mah_per_byte=0.0, rx_cost_mah_per_event=0.5, rx_cost_mah_per_byte=0.0)
    )


def test_direct_delivery_to_destination():
    sender = _node(1, 0.0, 0.0)
    dest = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(dest)
    msg = Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    sender.store_message(msg)
    metrics = MetricsCollector()
    process_node_contacts(now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(), energy_model=_energy_model(), metrics=metrics)
    assert dest.has_message(1) is True
    report = metrics.build_report([], 0)
    assert report.messages_delivered == 1
    assert sender.battery_mah == pytest.approx(99.0)
    assert dest.battery_mah == pytest.approx(99.5)


def test_relay_forward_increments_hops_without_mutating_senders_copy():
    sender = _node(1, 0.0, 0.0)
    relay = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(relay)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0, hops=0)
    sender.store_message(msg)
    metrics = MetricsCollector()
    process_node_contacts(now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(), energy_model=_energy_model(), metrics=metrics)
    assert relay.has_message(1) is True
    assert relay.buffer[1].hops == 1
    assert sender.buffer[1].hops == 0
    assert metrics.build_report([], 0).total_transmissions == 1


def test_expired_message_is_purged_before_contact_check():
    sender = _node(1, 0.0, 0.0)
    relay = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(relay)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=10.0)
    sender.store_message(msg)
    metrics = MetricsCollector()
    process_node_contacts(now=100.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(), energy_model=_energy_model(), metrics=metrics)
    assert 1 not in sender.buffer
    assert relay.has_message(1) is False


def test_inactive_contact_is_skipped():
    sender = _node(1, 0.0, 0.0)
    relay = _node(2, 5.0, 0.0)
    relay.is_active = False
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(relay)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    sender.store_message(msg)
    metrics = MetricsCollector()
    process_node_contacts(now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(), energy_model=_energy_model(), metrics=metrics)
    assert relay.has_message(1) is False


def test_inactive_sender_is_skipped():
    sender = _node(1, 0.0, 0.0)
    sender.is_active = False
    relay = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(relay)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    sender.buffer[1] = msg
    metrics = MetricsCollector()
    process_node_contacts(now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(), energy_model=_energy_model(), metrics=metrics)
    assert relay.has_message(1) is False


def test_network_engine_delivers_after_one_interval():
    env = simpy.Environment()
    sender = _node(1, 0.0, 0.0)
    dest = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(dest)
    msg = Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=1000.0)
    sender.store_message(msg)
    nodes = {1: sender, 2: dest}
    metrics = MetricsCollector()
    env.process(network_engine(env, nodes, grid, EpidemicRouting(), _energy_model(), metrics, contact_check_interval_s=5.0))
    env.run(until=4.0)
    assert dest.has_message(1) is False
    env.run(until=6.0)
    assert dest.has_message(1) is True
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_network.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'festival_ble_sim.network'`.

- [ ] **Step 3: Implement `network.py`**

```python
from __future__ import annotations
from dataclasses import replace
from typing import Dict
from .energy import EnergyModel
from .metrics import MetricsCollector
from .nodes import BaseNode
from .routing.base import RoutingAlgorithm, RoutingDecision
from .spatial import SpatialGrid


def process_node_contacts(
    now: float,
    sender: BaseNode,
    grid: SpatialGrid,
    routing_algorithm: RoutingAlgorithm,
    energy_model: EnergyModel,
    metrics: MetricsCollector,
) -> None:
    expired_ids = [mid for mid, m in sender.buffer.items() if m.is_expired(now)]
    for mid in expired_ids:
        del sender.buffer[mid]

    if not sender.buffer or not sender.is_active:
        return

    neighbors = grid.get_nearby(sender, sender.radio_range_m)
    for contact in neighbors:
        if not contact.is_active:
            continue

        for message in list(sender.buffer.values()):
            if contact.id == message.dst_id:
                if not contact.has_message(message.msg_id):
                    delivered_msg = replace(message, hops=message.hops + 1)
                    contact.mark_delivered(delivered_msg.msg_id)
                    sender.consume_energy(energy_model.cost_of_tx(message.size_bytes))
                    contact.consume_energy(energy_model.cost_of_rx(message.size_bytes))
                    metrics.record_transmission()
                    metrics.record_delivery(delivered_msg, now)
                continue

            decision = routing_algorithm.decide(message, sender, contact)
            if decision is RoutingDecision.FORWARD:
                forwarded = replace(message, hops=message.hops + 1)
                contact.store_message(forwarded)
                sender.consume_energy(energy_model.cost_of_tx(message.size_bytes))
                contact.consume_energy(energy_model.cost_of_rx(message.size_bytes))
                metrics.record_transmission()


def network_engine(
    env,
    nodes: Dict[int, BaseNode],
    grid: SpatialGrid,
    routing_algorithm: RoutingAlgorithm,
    energy_model: EnergyModel,
    metrics: MetricsCollector,
    contact_check_interval_s: float,
):
    while True:
        yield env.timeout(contact_check_interval_s)
        now = env.now
        for sender in list(nodes.values()):
            process_node_contacts(now, sender, grid, routing_algorithm, energy_model, metrics)
```

Note on `replace(message, hops=message.hops + 1)`: each node must hold its own independent copy of a message once forwarded, so a later hop increment on the receiving copy doesn't retroactively change the hop count of the copy still sitting in the sender's buffer. `dataclasses.replace` creates that independent copy; the shared `routing_state` dict is copied by reference, which is fine for `EpidemicRouting` (it never writes to `routing_state`) but a future algorithm that mutates per-copy state there must copy that dict explicitly.

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_network.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/festival_ble_sim/network.py tests/test_network.py
git commit -m "$(cat <<'EOF'
feat: add BLE contact/network engine

process_node_contacts() is the pure per-tick logic (TTL purge, direct
delivery, routing-algorithm-driven forwarding, energy accounting,
overhead tracking) and is fully testable without SimPy; network_engine()
is the thin periodic SimPy process that drives it. Forwarded messages
are independent copies (dataclasses.replace) so hop counts don't leak
back into the sender's own buffered copy.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UV91yjxC6QqyjBUaAFRszP
EOF
)"
```

---

## Task 13: Orchestration, CLI entry point, and README

**Files:**
- Create: `src/festival_ble_sim/simulation.py`
- Modify: `main.py` (repo root — replace the previous monolithic prototype entirely)
- Create: `README.md`
- Test: `tests/test_simulation.py`

**Interfaces:**
- Consumes: everything produced by Tasks 2–12.
- Produces: `run_simulation(config: SimulationConfig, routing_algorithm: Optional[RoutingAlgorithm] = None) -> SimulationReport`.

- [ ] **Step 1: Write the failing test**

```python
from festival_ble_sim.config import SimulationConfig, TrafficConfig
from festival_ble_sim.simulation import run_simulation


def test_run_simulation_smoke():
    config = SimulationConfig(
        duration_s=120.0,
        num_festivaliers=10,
        random_seed=7,
        traffic=TrafficConfig(mean_interval_s=2.0, payload_size_range_bytes=(20, 100), message_ttl_s=600.0),
    )
    report = run_simulation(config)
    assert report.messages_created > 0
    assert 0.0 <= report.delivery_ratio <= 1.0
    assert report.total_transmissions >= 0
    assert report.total_energy_consumed_mah >= 0.0
```

- [ ] **Step 2: Run test, verify it fails**

Run: `pytest tests/test_simulation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'festival_ble_sim.simulation'`.

- [ ] **Step 3: Implement `simulation.py`**

```python
from __future__ import annotations
import itertools
import math
import random
from typing import Dict, Optional
import simpy
from .beacons import place_beacons
from .config import SimulationConfig
from .energy import EnergyModel
from .metrics import MetricsCollector, SimulationReport
from .mobility.random_waypoint import RandomWaypointMobility
from .network import network_engine
from .nodes import BaseNode, BeaconNode, MobileNode
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
) -> SimulationReport:
    rng = random.Random(config.random_seed)
    routing_algorithm = routing_algorithm or EpidemicRouting()
    energy_model = EnergyModel(config.energy)
    metrics = MetricsCollector()
    env = simpy.Environment()

    max_range = max(config.ble.phone_range_m, config.ble.beacon_range_m)
    grid = SpatialGrid(config.area.width_m, config.area.height_m, cell_size_m=max_range)

    nodes: Dict[int, BaseNode] = {}
    id_counter = itertools.count(1)

    for position in place_beacons(config.area, config.beacons):
        node_id = next(id_counter)
        beacon = BeaconNode(
            node_id=node_id,
            position=position,
            radio_range_m=config.ble.beacon_range_m,
            buffer_capacity=config.node_buffer_capacity,
            unlimited_power=config.beacons.unlimited_power,
            battery_mah=config.energy.initial_battery_mah,
        )
        nodes[node_id] = beacon
        grid.insert(beacon)

    mobile_nodes: Dict[int, MobileNode] = {}
    for _ in range(config.num_festivaliers):
        node_id = next(id_counter)
        mobility = RandomWaypointMobility(config.mobility, rng=random.Random(rng.randrange(1 << 30)))
        mobile = MobileNode(
            node_id=node_id,
            mobility=mobility,
            radio_range_m=config.ble.phone_range_m,
            buffer_capacity=config.node_buffer_capacity,
            battery_mah=config.energy.initial_battery_mah,
            area=config.area,
        )
        nodes[node_id] = mobile
        mobile_nodes[node_id] = mobile
        grid.insert(mobile)
        env.process(_mobile_process(env, mobile, config, grid))

    msg_id_counter = itertools.count(1)
    env.process(traffic_generator(env, mobile_nodes, config.traffic, metrics, msg_id_counter, rng))
    env.process(
        network_engine(env, nodes, grid, routing_algorithm, energy_model, metrics, config.ble.contact_check_interval_s)
    )

    env.run(until=config.duration_s)

    energy_samples = [n.energy_consumed_mah for n in nodes.values() if n.initial_battery_mah != math.inf]
    dead_count = sum(1 for n in nodes.values() if not n.is_active)
    return metrics.build_report(energy_samples, dead_count)
```

- [ ] **Step 4: Run test, verify it passes**

Run: `pytest tests/test_simulation.py -v`
Expected: 1 passed. (Runs near-instantly: SimPy is discrete-event, not wall-clock, and the scenario is tiny.)

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: every test from Tasks 1–13 passes (all green, no regressions).

- [ ] **Step 6: Replace `main.py`**

Overwrite the existing root `main.py` (the old monolithic prototype) entirely with:

```python
from __future__ import annotations
from festival_ble_sim.config import SimulationConfig
from festival_ble_sim.metrics import format_report
from festival_ble_sim.simulation import run_simulation


def main() -> None:
    config = SimulationConfig()
    report = run_simulation(config)
    text = format_report(report)
    print(text)
    with open("rapport_simulation.txt", "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Write `README.md`**

```markdown
# Festival BLE Mesh Simulator

Simulateur SimPy de messagerie opportuniste (mesh MANET) via Bluetooth
Low Energy entre les participants d'un festival.

## Installation

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev]"

## Lancer une simulation

    python main.py

Le rapport est affiche dans le terminal et ecrit dans
`rapport_simulation.txt`.

## Lancer les tests

    pytest

## Architecture

Voir `docs/superpowers/specs/2026-09-14-festival-ble-sim-design.md`
pour le design complet. Points d'injection pour tes propres
algorithmes :
- `src/festival_ble_sim/routing/` — nouveaux algorithmes de routage
  (implemente `RoutingAlgorithm`).
- `src/festival_ble_sim/mobility/` — nouveaux modeles de mobilite
  (implemente `MobilityModel`).
- `src/festival_ble_sim/beacons.py` — placement strategique des bornes.
```

- [ ] **Step 8: Run the simulator end-to-end**

Run: `python main.py`
Expected: prints the report to the terminal and writes `rapport_simulation.txt`, with no exceptions. Sanity-check the numbers: `delivery_ratio` between 0 and 1, `messages_created > 0`.

- [ ] **Step 9: Commit**

```bash
git add src/festival_ble_sim/simulation.py main.py README.md tests/test_simulation.py
git commit -m "$(cat <<'EOF'
feat: add simulation orchestrator and CLI entry point

run_simulation() wires config, beacon placement, mobile/beacon node
creation, mobility processes, traffic generation, and the network
engine into one SimPy run and returns a SimulationReport. main.py
replaces the old monolithic prototype as the runnable entry point.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UV91yjxC6QqyjBUaAFRszP
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- Architecture/environnement (§2–3): Task 1.
- Modèle de données (§4): Task 2.
- Configuration (§5): Task 3.
- Index spatial (§6): Task 4.
- Mobilité (§7): Task 6.
- Routage (§8): Task 7.
- Nœuds (§9): Task 8.
- Placement des bornes (§10): Task 9.
- Trafic (§11): Task 11.
- Moteur de contacts BLE (§12): Task 12.
- Énergie (§13): Task 5 (model) + Tasks 8/12 (integration into nodes and the network engine).
- Métriques et rapport (§14): Task 10.
- Orchestration (§15): Task 13.
- Tests (§16): every task ships its own test file; `test_config.py`, `test_nodes.py`, `test_beacons.py`, and `test_simulation.py` go beyond the spec's minimum list for coverage of logic the spec itself calls out as needing validation (buffer eviction, config bounds, beacon math, end-to-end wiring).
- Gestion des erreurs (§17): `SimulationConfig.__post_init__` (Task 3) and FIFO buffer eviction (Task 8) are the only two error/limit mechanisms called for, and both are covered.

No spec requirement without a task.

**Placeholder scan:** no "TBD"/"TODO" and no step describing behavior without code — checked against every task above.

**Type consistency:** cross-checked signatures used across tasks — `Message`, `Position`, all config dataclasses, `MobilityModel.step`, `RoutingAlgorithm.decide`/`RoutingDecision`, `BaseNode.has_message`/`store_message`/`mark_delivered`/`consume_energy`/`energy_consumed_mah`, `MobileNode.move`, `place_beacons`, `MetricsCollector.record_creation`/`record_transmission`/`record_delivery`/`build_report`, `traffic_generator`, `process_node_contacts`/`network_engine`, and `run_simulation` are each defined once and referenced identically (same parameter names, same order) everywhere they're consumed by a later task.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-14-festival-ble-sim-implementation.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
