"""Z09 expected values only. No imports from the measured implementation.

Same author as implementation, not a blinded/person-independent evaluator.
Configuration membership is transcribed explicitly from the design contract.
"""
from decimal import Decimal

ROLES = ("evidence", "linking", "draft", "checking")
MEMBERS = {
    "C01": (0, 1), "C02": (0, 2), "C03": (0, 3),
    "C04": (1, 2), "C05": (1, 3), "C06": (2, 3),
    "C07": (0, 1, 2), "C08": (0, 1, 2),
    "C09": (0, 1, 3), "C10": (0, 1, 3),
    "C11": (0, 2, 3), "C12": (0, 2, 3),
    "C13": (1, 2, 3), "C14": (1, 2, 3),
    "D": (0, 1, 2, 3), "D-no-peers": (0, 1, 2, 3),
}
RINGS = {"C07", "C09", "C11", "C13"}


def policy(name):
    roles = tuple(ROLES[i] for i in MEMBERS[name])
    if name == "D-no-peers": edges = set()
    elif name in RINGS:
        a, b, c = roles
        edges = {(a, b), (b, c), (c, a)}
    else: edges = {(a, b) for a in roles for b in roles if a != b}
    return roles, edges


def expected(name, rounds, suppressed, limit, mode):
    roles, edges = policy(name)
    active = [role for role in roles if role != suppressed]
    steps = [(r, role) for r in range(1, rounds+1) for role in active] + [(rounds+1, "aggregator")]
    failed = {steps[0]} if mode != "success" else set()
    n = len(steps)
    known = Decimal(n*(n+1))/2000 - (Decimal(".001") if mode == "unknown" else 0)
    requests = []
    counts = {"peer": 0, "own": 0, "aggregator": 0}
    for r, role in steps:
        sources = [s for s in active if r > 1 and (r-1, s) not in failed
                   and (role == "aggregator" or s == role or (s, role) in edges)]
        messages = [{"role": s, "round": r-1, "text": f"output:{r-1}:{s}"} for s in sources]
        for s in sources:
            counts["aggregator" if role == "aggregator" else "own" if role == s else "peer"] += 1
        requests.append({"role": role, "round": r, "limit": 128 if role == "aggregator" else limit, "messages": messages})
    return {"requests": requests, "calls": n, "suppressed_events": rounds if suppressed else 0,
            "planned_calls_before_suppression": rounds*len(roles)+1,
            "messages": counts, "known_cost_usd": str(known),
            "total_cost_usd": None if mode == "unknown" else str(known),
            "unknown_cost_calls": int(mode == "unknown"), "failed_calls": int(mode != "success"),
            "input_tokens": 10*n*(n+1)//2, "output_tokens": n*(n+1)//2}
