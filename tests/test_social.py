from __future__ import annotations
import random
import pytest
from festival_ble_sim.config import SimulationConfig, SocialConfig
from festival_ble_sim.social import assign_friend_groups


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
