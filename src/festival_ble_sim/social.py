from __future__ import annotations
import random
from typing import Dict, List, Set
from .config import SocialConfig


def assign_friend_groups(people: List[int], config: SocialConfig, rng: random.Random) -> Dict[int, Set[int]]:
    people = sorted(people)
    rng.shuffle(people)
    friends: Dict[int, Set[int]] = {}
    start = round(config.no_friend_fraction * len(people))
    while start < len(people):
        size = rng.randint(*config.group_size_range)
        group = set(people[start:start + size])
        start += size
        if len(group) < 2:
            break
        for member in group:
            friends[member] = group - {member}
    return friends


def add_outside_friends(
    groups: Dict[int, Set[int]], config: SocialConfig, rng: random.Random
) -> Dict[int, Set[int]]:
    # Each member draws how many outside friends it wants; stubs are paired
    # at random and a pair within one group or already friends is dropped,
    # so nobody exceeds its draw.
    friends = {member: set(others) for member, others in groups.items()}
    stubs: List[int] = []
    for member in sorted(groups):
        stubs.extend([member] * rng.randint(*config.outside_friends_range))
    rng.shuffle(stubs)
    for a, b in zip(stubs[::2], stubs[1::2]):
        if a != b and b not in groups[a] and b not in friends[a]:
            friends[a].add(b)
            friends[b].add(a)
    return friends
