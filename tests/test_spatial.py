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
