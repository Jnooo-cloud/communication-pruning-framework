"""Stable fourteen-member spatial bank; time and failure remain separate factors."""

from itertools import combinations
from .contracts import Configuration, ROLES


def bank() -> tuple[Configuration, ...]:
    configs = []
    for roles in combinations(ROLES, 2):
        configs.append(Configuration(f"C{len(configs) + 1:02}", roles,
                                     ((roles[0], roles[1]), (roles[1], roles[0]))))
    for roles in combinations(ROLES, 3):
        ring = tuple((role, roles[(i + 1) % 3]) for i, role in enumerate(roles))
        full = tuple((a, b) for a in roles for b in roles if a != b)
        for edges in (ring, full):
            configs.append(Configuration(f"C{len(configs) + 1:02}", roles, edges))
    return tuple(configs)


def dense() -> Configuration:
    return Configuration("D", ROLES, tuple((a, b) for a in ROLES for b in ROLES if a != b))


def without_peers(config: Configuration) -> Configuration:
    return Configuration(config.config_id + "-no-peers", config.roles, ())
