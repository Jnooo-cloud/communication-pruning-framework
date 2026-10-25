"""Nachträgliche Beschreibung zur Cluster-Sensitivität P (NICHT vorab festgelegt, keine Inferenz).

Erklärt die Intervallverbreiterung beschreibend: Ziehungsrahmen aus PLAN.json, beobachtete und unter
gleichwahrscheinlicher Ziehung mit Zurücklegen erwartete Mehrfachziehungen, Gleichheit der
Paardifferenzen innerhalb wiederholter Aufgaben (ICC nach Einweg-ANOVA). Liest STATE.json und
PLAN.json im alten Repo nur lesend. Ausgabe: P-CLUSTER-BESCHREIBUNG.json.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
from collections import defaultdict  # noqa: E402
from decimal import Decimal  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from p_cluster import EVAL, load_rows, sha_file  # noqa: E402

PLAN = EVAL / "runs/Z50-NACHARBEIT-001/coordination/final-candidate-001/PLAN.json"
PLAN_SHA = "42a55ddd7dc71738d39fbdb546b0bb60ca19a0d6485f47688de32c893f47f61f"


def icc(groups):
    """Einweg-ANOVA-ICC mit unbalancierten Gruppen (Gruppen mit m >= 1)."""
    values = [x for g in groups for x in g]
    n, k = len(values), len(groups)
    grand = math.fsum(values) / n
    ssb = math.fsum(len(g) * (math.fsum(g) / len(g) - grand) ** 2 for g in groups)
    ssw = math.fsum((x - math.fsum(g) / len(g)) ** 2 for g in groups for x in g)
    msb, msw = ssb / (k - 1), ssw / (n - k)
    m0 = (n - math.fsum(len(g) ** 2 for g in groups) / n) / (k - 1)
    return {"icc": (msb - msw) / (msb + (m0 - 1) * msw), "msb": msb, "msw": msw, "m0": m0}


def main():
    assert sha_file(PLAN) == PLAN_SHA
    plan = json.loads(PLAN.read_text())
    frame = plan["frame"]
    n_frame = len(frame)
    fam_frame = len({x["family_id"] for x in frame})
    rows = load_rows()
    draws = defaultdict(dict)
    for r in rows:
        draws[r["draw_index"]][r["arm"]] = r
    n = len(draws)
    d_by_task, r_by_task = defaultdict(list), defaultdict(list)
    fam_count, task_count = defaultdict(int), defaultdict(int)
    cq = math.fsum(float(Decimal(draws[i]["Q"]["cost_usd"])) for i in range(n))
    cf = math.fsum(float(Decimal(draws[i]["F"]["cost_usd"])) for i in range(n))
    rho = cq / cf
    for i in range(n):
        q, f = draws[i]["Q"], draws[i]["F"]
        d_by_task[q["task_id"]].append(q["em"] - f["em"])
        r_by_task[q["task_id"]].append(float(Decimal(q["cost_usd"])) - rho * float(Decimal(f["cost_usd"])))
        task_count[q["task_id"]] += 1
        fam_count[q["family_id"]] += 1
    m_task = list(task_count.values())
    m_fam = list(fam_count.values())
    repeated = [g for g in d_by_task.values() if len(g) >= 2]
    out = {
        "post_hoc": True,
        "frame": {"tasks": n_frame, "families": fam_frame, "plan_sha256": PLAN_SHA,
                  "replacement": plan["randomization"]["replacement"]},
        "draws": n,
        "observed_distinct_tasks": len(task_count),
        "expected_distinct_tasks_uniform_wr": n_frame * (1 - (1 - 1 / n_frame) ** n),
        "observed_distinct_families": len(fam_count),
        "sum_m2_over_n_task": math.fsum(m * m for m in m_task) / n,
        "expected_sum_m2_over_n_task_uniform_wr": 1 + (n - 1) / n_frame,
        "sum_m2_over_n_family": math.fsum(m * m for m in m_fam) / n,
        "repeated_tasks": len(repeated),
        "draws_in_repeated_tasks": sum(len(g) for g in repeated),
        "share_repeated_tasks_all_em_diffs_equal": sum(len(set(g)) == 1 for g in repeated) / len(repeated),
        "icc_em_diff_task": icc(list(d_by_task.values())),
        "icc_cost_residual_task": icc(list(r_by_task.values())),
    }
    (HERE / "P-CLUSTER-BESCHREIBUNG.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
