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
