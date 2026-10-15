from __future__ import annotations
import random
import pytest
from festival_ble_sim.config import SimulationConfig, SocialConfig
from festival_ble_sim.social import add_outside_friends, assign_friend_groups


def test_friend_groups_are_symmetric_and_sized():
    friends = assign_friend_groups(list(range(1, 101)), SocialConfig(no_friend_fraction=0.0), random.Random(1))
    for member, others in friends.items():
        assert member not in others
        assert 1 <= len(others) <= 7
        for other in others:
            assert friends[other] == (others | {member}) - {other}


def test_no_friend_fraction_leaves_some_people_friendless():
    friends = assign_friend_groups(list(range(1, 101)), SocialConfig(no_friend_fraction=0.5), random.Random(1))
    assert len(friends) <= 50


def test_rejects_invalid_social_config():
    with pytest.raises(ValueError):
        SimulationConfig(social=SocialConfig(group_size_range=(1, 8)))
    with pytest.raises(ValueError):
        SimulationConfig(social=SocialConfig(no_friend_fraction=1.5))


def test_outside_friends_are_symmetric_bounded_and_from_other_groups():
    config = SocialConfig(no_friend_fraction=0.2, outside_friends_range=(0, 2))
    groups = assign_friend_groups(list(range(1, 201)), config, random.Random(1))
    friends = add_outside_friends(groups, config, random.Random(2))
    assert set(friends) == set(groups)
    outside_total = 0
    for member, others in friends.items():
        assert groups[member] <= others
        outside = others - groups[member]
        assert len(outside) <= 2 and member not in others
        outside_total += len(outside)
        for other in outside:
            assert member in friends[other] and other not in groups[member]
    assert outside_total > 0


def test_no_outside_friends_keeps_the_groups():
    config = SocialConfig(outside_friends_range=(0, 0))
    groups = assign_friend_groups(list(range(1, 101)), config, random.Random(1))
    assert add_outside_friends(groups, config, random.Random(2)) == groups
