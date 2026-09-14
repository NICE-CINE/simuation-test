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
