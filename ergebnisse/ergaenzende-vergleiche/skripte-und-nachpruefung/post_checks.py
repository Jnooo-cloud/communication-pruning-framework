"""Post-run checks, no model calls.

1. Second complete recomputation of every Z53 block with verify_block.
2. Drift per R arm: pre-Z53 (R 0-2182, rows from the bound prior inspect) vs Z53 (R 2183-2951):
   model-failure rate, mean EM/F1, mean cost; cached-token share from raw provider
   answers (pre: R1589-2182 dispatch answers still on disk; Z53: all R answers).
T and F have no pre-Z53 data, so they get level summaries only.
"""
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from decimal import Decimal
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from study_preparation import z53_fast as z  # noqa: E402

LIVE = HERE / "live"
_CTX = None


def verify(name):
    global _CTX
    if _CTX is None:
        _CTX = z.Context(with_selectors=False)
    try:
        z.verify_block(_CTX, LIVE / "blocks" / name)
        return name, None
    except Exception as error:
        return name, f"{type(error).__name__}: {error}"


def cached_share(paths):
    cached = prompt = 0
    for p in paths:
        try:
            u = json.loads(Path(p).read_bytes()).get("usage", {})
        except Exception:
            continue
        if not u.get("prompt_tokens"):
            continue
        prompt += u["prompt_tokens"]
        cached += (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
    return round(cached / prompt, 4) if prompt else None


def levels(rows):
    by = defaultdict(list)
    for r in rows:
        by[r["arm"]].append(r)
    out = {}
    for arm, rs in sorted(by.items()):
        n = len(rs)
        out[arm] = {"n": n, "failure_rate": round(sum(r["status"] == "model_failure" for r in rs) / n, 4),
                    "em": round(sum(r["em"] for r in rs) / n, 4), "f1": round(sum(r["f1"] for r in rs) / n, 4),
                    "mean_cost_usd": round(float(sum(Decimal(r["cost_usd"]) for r in rs) / n), 7)}
    return out


def main():
    names = sorted(p.name for p in (LIVE / "blocks").iterdir())
    with ProcessPoolExecutor(8) as pool:
        results = list(pool.map(verify, names, chunksize=40))
    failed = [(n, e) for n, e in results if e]
    rows = {p: json.loads((LIVE / "collected" / f"rows-{p}.json").read_bytes()) for p in z.PANELS}
    r_pre = [r for r in rows["R"] if r["draw_index"] < 2183]
    r_post = [r for r in rows["R"] if r["draw_index"] >= 2183]
    pre_answers = list((z.PRIOR / "live" / "dispatch").glob("*-response.json"))
    post_answers = [p for p in (LIVE / "blocks").glob("R-*/provider/*-response.json")]
    report = {"reverified_blocks": len(names), "reverify_failures": failed,
              "R_drift": {"pre_Z53": levels(r_pre), "Z53": levels(r_post)},
              "R_cached_token_share": {"pre_Z53_R1589_2182": cached_share(pre_answers), "Z53": cached_share(post_answers)},
              "T_levels": levels(rows["T"]), "F_levels": levels(rows["F"]),
              "T_cached_token_share": cached_share(LIVE.glob("blocks/T-*/provider/*-response.json")),
              "F_cached_token_share": cached_share(LIVE.glob("blocks/F-*/provider/*-response.json"))}
    (HERE / "POST-CHECKS.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps({"reverified": len(names), "failures": len(failed)}))


if __name__ == "__main__":
    main()
