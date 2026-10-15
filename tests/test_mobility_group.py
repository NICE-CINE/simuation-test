import random
from dataclasses import replace
from festival_ble_sim.config import AreaConfig, GroupConfig, MobilityConfig, PointOfInterest, SimulationConfig
from festival_ble_sim.mobility.group import GroupMobility
from festival_ble_sim.models import Position

AREA = AreaConfig(width_m=200.0, height_m=200.0)
POIS = (PointOfInterest(x=30.0, y=30.0, radius_m=10.0), PointOfInterest(x=170.0, y=170.0, radius_m=10.0))


class _Walker:
    def __init__(self, mobility, position):
        self.mobility = mobility
        self.position = position
        self.on_site = True

    def step(self, dt=1.0):
        self.position = self.mobility.step(self.position, dt, AREA)


def _group(seed=0, **group_kw):
    config = MobilityConfig(points_of_interest=POIS, group=replace(GroupConfig(), **group_kw))
    leader = _Walker(GroupMobility(config, random.Random(seed)), Position(30.0, 30.0))
    member = _Walker(GroupMobility(config, random.Random(seed + 1)), None)
    leader.mobility.join_group(leader, [leader, member])
    member.position = member.mobility.join_group(member, [leader, member])
    return leader, member


def test_member_starts_and_stays_around_its_leader():
    leader, member = _group(short_trips_per_hour=0.0, long_trips_per_hour=0.0)
    assert member.position.distance_to(leader.position) <= 5.0
    for _ in range(3000):
        leader.step()
        member.step()
        assert member.position.distance_to(leader.position) <= 5.0 + 2.0


def test_member_on_a_trip_comes_back_to_the_rendezvous_where_the_leader_waits():
    leader, member = _group(short_trips_per_hour=3600.0, short_trip_s=(60.0, 60.0), long_trips_per_hour=0.0)
    member.step()
    meeting = member.mobility._meeting
    assert not member.mobility.is_with_group and meeting is not None
    member.mobility._group = replace(member.mobility._group, short_trips_per_hour=0.0)
    for _ in range(1200):
        leader.step()
        member.step()
        if member.mobility.is_with_group:
            break
    assert member.mobility.is_with_group
    assert leader.position.distance_to(meeting) < 15.0


def test_member_who_misses_the_rendezvous_searches_until_it_sees_the_group():
    leader, member = _group(
        short_trips_per_hour=3600.0, short_trip_s=(60.0, 60.0), long_trips_per_hour=0.0, rendezvous_max_wait_s=0.0,
    )
    member.step()
    member.mobility._group = replace(member.mobility._group, short_trips_per_hour=0.0)
    for _ in range(100):
        member.step()
    # The leader never came back (no wait): it is somewhere else by now.
    leader.position = Position(170.0, 170.0)
    for _ in range(4000):
        member.step()
        if member.mobility.is_with_group:
            break
    assert member.mobility.is_with_group


def test_run_simulation_starts_friend_groups_together():
    from festival_ble_sim.simulation import run_simulation
    from festival_ble_sim.viz.history import SimulationHistory
    config = SimulationConfig(
        duration_s=2.0, num_festivaliers=30, random_seed=2, area=AREA, mobility=MobilityConfig(points_of_interest=POIS),
    )
    models = []

    def factory(rng):
        models.append(GroupMobility(config.mobility, rng))
        return models[-1]

    history = SimulationHistory(area_width_m=200.0, area_height_m=200.0, tick_interval_s=1.0)
    run_simulation(config, mobility_factory=factory, history=history)
    _, positions = history.position_snapshots[0]
    # No beacons: the i-th model belongs to node i + 1.
    pairs = [(i + 1, m._team.nodes[0].id) for i, m in enumerate(models) if m._team is not None]
    assert pairs
    for member_id, leader_id in pairs:
        (mx, my), (lx, ly) = positions[member_id], positions[leader_id]
        assert ((mx - lx) ** 2 + (my - ly) ** 2) ** 0.5 <= 5.0 + 2.5


def test_group_follows_the_next_member_when_the_leader_is_away():
    config = MobilityConfig(
        points_of_interest=POIS, group=replace(GroupConfig(), short_trips_per_hour=0.0, long_trips_per_hour=0.0),
    )
    walkers = [_Walker(GroupMobility(config, random.Random(i)), Position(30.0, 30.0)) for i in range(3)]
    for w in walkers:
        start = w.mobility.join_group(w, walkers)
        if start is not None:
            w.position = start
    leader, a, b = walkers
    leader.on_site = False
    for _ in range(3000):
        a.step()
        b.step()
        assert b.position.distance_to(a.position) <= 2 * 5.0 + 2.0
    assert a.mobility._team.current_leader() is a


def test_member_arriving_after_its_group_searches_for_it():
    leader, member = _group(short_trips_per_hour=0.0, long_trips_per_hour=0.0)
    member.on_site = False
    for _ in range(100):
        leader.step()
    leader.position = Position(170.0, 170.0)
    member.on_site = True
    member.step()
    assert not member.mobility.is_with_group
    for _ in range(4000):
        member.step()
        if member.mobility.is_with_group:
            break
    assert member.mobility.is_with_group
