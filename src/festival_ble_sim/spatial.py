from __future__ import annotations
import math
from typing import Dict, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .nodes import BaseNode


class SpatialGrid:
    def __init__(self, width_m: float, height_m: float, cell_size_m: float) -> None:
        self.width_m = width_m
        self.height_m = height_m
        self.cell_size_m = cell_size_m
        self._cols = max(1, math.ceil(width_m / cell_size_m))
        self._rows = max(1, math.ceil(height_m / cell_size_m))
        # Dicts as ordered sets: a set of nodes iterates in id()-hash order,
        # i.e. memory layout, which made neighbor order (and bitchat's
        # first-arrival BFS) differ between runs with the same seed.
        self._cells: Dict[Tuple[int, int], Dict["BaseNode", None]] = {}

    def _cell_of(self, x: float, y: float) -> Tuple[int, int]:
        col = min(max(int(x // self.cell_size_m), 0), self._cols - 1)
        row = min(max(int(y // self.cell_size_m), 0), self._rows - 1)
        return col, row

    def insert(self, node: "BaseNode") -> None:
        cell = self._cell_of(node.position.x, node.position.y)
        self._cells.setdefault(cell, {})[node] = None

    def update(self, node: "BaseNode", old_x: float, old_y: float) -> None:
        old_cell = self._cell_of(old_x, old_y)
        new_cell = self._cell_of(node.position.x, node.position.y)
        if old_cell == new_cell:
            return
        if old_cell in self._cells:
            self._cells[old_cell].pop(node, None)
        self._cells.setdefault(new_cell, {})[node] = None

    def get_nearby(self, node: "BaseNode", radius_m: float) -> List["BaseNode"]:
        px, py = node.position.x, node.position.y
        cx, cy = self._cell_of(px, py)
        cell_radius = max(1, math.ceil(radius_m / self.cell_size_m))
        radius_squared = radius_m * radius_m
        found: List["BaseNode"] = []
        # Inlined distance: with ~1000 neighbors per node in a packed crowd,
        # the method call alone was half the run time.
        for dc in range(-cell_radius, cell_radius + 1):
            for dr in range(-cell_radius, cell_radius + 1):
                cell = (cx + dc, cy + dr)
                for other in self._cells.get(cell, ()):
                    if other is node:
                        continue
                    p = other.position
                    dx = p.x - px
                    dy = p.y - py
                    if dx * dx + dy * dy <= radius_squared:
                        found.append(other)
        return found
