import pytest
from festival_ble_sim.config import AreaConfig, ChurnConfig, EnergyConfig, SimulationConfig, TrafficConfig
from festival_ble_sim.routing.epidemic import EpidemicRouting
from festival_ble_sim.simulation import run_simulation


class _Recorder(EpidemicRouting):
    def __init__(self):
        self.nodes = {}
        self.seen = set()

    def on_simulation_start(self, nodes):
        self.nodes = nodes

    def on_tick(self, now, neighbors_by_node):
        self.seen.update(neighbors_by_node)
        for neighbors in neighbors_by_node.values():
            self.seen.update(n.id for n in neighbors)


def _config(**kwargs):
    base = dict(
        duration_s=300.0, num_festivaliers=40, random_seed=3, area=AreaConfig(width_m=60.0, height_m=60.0),
        traffic=TrafficConfig(messages_per_hour_range=(60.0, 120.0), payload_size_range_bytes=(20, 100)),
        energy=EnergyConfig(background_current_ma=36.0, phone_current_ma=0.0),
    )
    base.update(kwargs)
    return SimulationConfig(**base)


def test_only_the_adopters_join_the_network():
    routing = _Recorder()
    report = run_simulation(_config(adoption_fraction=0.25), routing_algorithm=routing)
    users = {i for i, n in routing.nodes.items() if n.has_app}
    others = [n for n in routing.nodes.values() if not n.has_app]
    assert len(users) == 10 and len(others) == 30
    assert routing.seen <= users
    assert report.messages_delivered > 0
    for node in others:
        assert not node.is_active and node.on_site
        assert node.energy_consumed_mah == 0.0 and not node.buffer and not node.friends
    for node_id in users:
        assert routing.nodes[node_id].friends <= users
    # The energy average covers the phones that run the app: 36 mA for 300 s
    # is 3 mAh of baseline each, which 30 idle phones would dilute to < 1.
    assert report.avg_mesh_energy_consumed_mah >= 2.9


def test_people_without_the_app_still_walk():
    routing = _Recorder()
    config = _config(adoption_fraction=0.25, duration_s=600.0)
    run_simulation(config, routing_algorithm=routing)
    others = [n for n in routing.nodes.values() if not n.has_app]
    start = {n.id: (n.position.x, n.position.y) for n in others}
    again = _Recorder()
    run_simulation(_config(adoption_fraction=0.25, duration_s=1.0), routing_algorithm=again)
    moved = sum(
        1 for n in again.nodes.values()
        if not n.has_app and (n.position.x, n.position.y) != start[n.id]
    )
    assert moved > len(others) / 2


def test_full_adoption_is_the_run_without_the_option():
    small = dict(duration_s=60.0, num_festivaliers=12)
    assert run_simulation(_config(adoption_fraction=1.0, **small)) == run_simulation(_config(**small))


def test_churn_never_activates_someone_without_the_app():
    routing = _Recorder()
    config = _config(
        adoption_fraction=0.5,
        churn=ChurnConfig(enabled=True, arrival_window_s=(10.0, 60.0), session_duration_range_s=(100.0, 150.0)),
    )
    run_simulation(config, routing_algorithm=routing)
    assert routing.seen <= {i for i, n in routing.nodes.items() if n.has_app}


@pytest.mark.parametrize("fraction", [0.0, -0.1, 1.5, 0.01])
def test_adoption_fraction_is_validated(fraction):
    with pytest.raises(ValueError, match="adoption_fraction"):
        _config(adoption_fraction=fraction)
