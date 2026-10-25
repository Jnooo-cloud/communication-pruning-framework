"""Z55-Kostenzerlegung: F* und D in der GPTSwarm-Demo (Z55) gegen dieselben Arme in Z53.

Offline, 0 USD, keine API-Aufrufe. Liest die Rohantworten beider Läufe im alten Repo (nur lesend):
- Z55: runs/Z55-GPTSWARM-DEMO-001/live/blocks/R-0xxxx/provider-{F,D}/NNN-*.json
- Z53: runs/Z53-SCHNELLFORTSETZUNG-001/live/blocks/R-0xxxx/provider*/NNN-*.json
  (Zuordnung zum Arm über attempt_id = run_id des Arms; mehrere Provider-Ordner wie in
  gptswarm_musique_demo.z53_arm: der frische Ordner "provider" gewinnt).

Je Call: prompt/completion/reasoning/cached/cache_write tokens, Provider, Modell, usage.cost,
cost_details. Prüft:
1. Armkosten je Block = Summe der Callkosten, gegen ANALYSIS-001.json (demo/z53 cost_usd).
2. Preisformel je Call exakt: cost = 1e-7*(prompt-cached) + 1e-8*cached + 4e-7*completion
   (aus den Daten abgeleitet, wird für jeden Call geprüft; Abweichungen werden gezählt).
3. Zerlegung der Differenz Z55 - Z53 je Arm in Komponenten:
   a) Prompt-Volumen (1e-7 je Token), b) entgangener Cache-Rabatt (9e-8 je gecachtem Token
   weniger), c) Completion-Tokens, d) Reasoning-Tokens (Zählung), e) Kosten weiterer
   abgerechneter Versuche, f) Rest (Preisänderung/Rundung), getrennt nach Blöcken mit vollständig
   identischen Requests und Antworten (laut ANALYSIS-001 per_block) und übrigen Blöcken.
4. Ursache des Cacheunterschieds beschreibend: Gab es vor dem Call im selben Block bereits einen
   byteidentischen Request (gleiche request_sha256), und wie viele Sekunden davor?
Ausgabe: Z55-KOSTENZERLEGUNG.json neben diesem Skript.
"""
from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal, localcontext
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUNS = ROOT.parent / "Masterarbeit" / "eval-harness/eval/runs"
Z55 = RUNS / "Z55-GPTSWARM-DEMO-001"
Z53 = RUNS / "Z53-SCHNELLFORTSETZUNG-001/live/blocks"
P_UNCACHED, P_CACHED, P_OUT = Decimal("1e-7"), Decimal("1e-8"), Decimal("4e-7")
ARMS = ("F", "D")


def jl(path: Path):
    return json.loads(path.read_bytes())


def call_record(pdir: Path, stem: str, binding: dict) -> dict:
    """All physical attempts of one logical call; final = last HTTP-200 response."""
    attempts = []
    for rec in sorted(pdir.glob(f"{stem}-p*-received.json")):
        status = jl(rec)["http_status"]
        resp_path = pdir / rec.name.replace("-received.json", "-response.json")
        resp = jl(resp_path) if resp_path.exists() else None
        attempts.append((status, resp))
    finals = [r for s, r in attempts if s == 200 and r is not None]
    final = finals[-1]
    usage = final.get("usage") or {}
    ptd = usage.get("prompt_tokens_details") or {}
    ctd = usage.get("completion_tokens_details") or {}
    billed_other = Decimal(0)
    for s, r in attempts:
        if r is not None and r is not final:
            c = (r.get("usage") or {}).get("cost")
            if c:
                billed_other += Decimal(str(c))
    return {
        "attempt_id": binding["attempt_id"], "request_sha256": binding["request_sha256"],
        "physical_attempts": len(attempts),
        "provider": final.get("provider"), "model": final.get("model"), "created": final.get("created"),
        "prompt": usage.get("prompt_tokens") or 0, "completion": usage.get("completion_tokens") or 0,
        "reasoning": ctd.get("reasoning_tokens") or 0, "cached": ptd.get("cached_tokens") or 0,
        "cache_write": ptd.get("cache_write_tokens") or 0,
        "cost": Decimal(str(usage.get("cost") or 0)), "billed_other_attempts": billed_other,
        "content": ((final.get("choices") or [{}])[0].get("message") or {}).get("content"),
    }


def z55_calls(block: str, arm: str) -> dict[str, dict]:
    pdir = Z55 / "live/blocks" / block / f"provider-{arm}"
    out = {}
    for b in sorted(pdir.glob("*-binding.json")):
        binding = jl(b)
        rnd, role = binding["attempt_id"].split(":")[3:5]
        out[f"{rnd}:{role}"] = call_record(pdir, b.name[:3], binding)
    return out


def z53_calls(block: str, arm: str) -> dict[str, dict]:
    bdir = Z53 / block
    run_id = jl(bdir / arm / "result.json")["run_id"]
    entries = defaultdict(list)
    for pdir in sorted(p for p in bdir.iterdir() if p.is_dir() and p.name.startswith("provider")):
        for b in sorted(pdir.glob("*-binding.json")):
            binding = jl(b)
            if binding["attempt_id"].startswith(run_id + ":"):
                entries[binding["attempt_id"]].append((pdir, b.name[:3], binding))
    out = {}
    for attempt_id, items in entries.items():
        names = [p.name for p, _, _ in items]
        pick = "provider" if "provider" in names else names[-1]
        pdir, stem, binding = next(x for x in items if x[0].name == pick)
        rnd, role, _ = attempt_id[len(run_id) + 1:].split(":")
        out[f"{rnd}:{role}"] = call_record(pdir, stem, binding)
    return out


def all_block_requests(run: str, block: str) -> list[tuple[int, str, str]]:
    """(created, request_sha256, attempt_id) for every final call of the whole block (all arms)."""
    if run == "Z55":
        bdir = Z55 / "live/blocks" / block
        dirs = [bdir / f"provider-{a}" for a in ARMS]
    else:
        bdir = Z53 / block
        dirs = [p for p in bdir.iterdir() if p.is_dir() and p.name.startswith("provider")]
    out = []
    for pdir in dirs:
        for b in sorted(pdir.glob("*-binding.json")):
            binding = jl(b)
            try:
                rec = call_record(pdir, b.name[:3], binding)
            except IndexError:
                continue
            out.append((rec["created"], binding["request_sha256"], binding["attempt_id"]))
    return out


def arm_of(run: str, attempt_id: str) -> str:
    parts = attempt_id.split(":")
    return parts[2] if run == "Z55" else parts[4]


def formula(c: dict) -> Decimal:
    return P_UNCACHED * (c["prompt"] - c["cached"]) + P_CACHED * c["cached"] + P_OUT * c["completion"]


def main():
    analysis = jl(Z55 / "ANALYSIS-001.json")
    per_block = {row["block"]: row for row in analysis["per_block"]}
    out = {"price_model_usd_per_token": {"prompt_uncached": "1e-7", "prompt_cached": "1e-8", "completion": "4e-7"},
           "arms": {}}
    with localcontext() as ctx:
        ctx.prec = 40
        for arm in ARMS:
            comp = {g: defaultdict(Decimal) for g in ("identical", "divergent", "all")}
            tok = {g: defaultdict(int) for g in ("identical", "divergent", "all")}
            checks = defaultdict(int)
            providers, models = defaultdict(int), defaultdict(int)
            prior = {"Z55": defaultdict(int), "Z53": defaultdict(int)}
            cached_by_prior = {"Z55": defaultdict(lambda: [0, 0]), "Z53": defaultdict(lambda: [0, 0])}
            per_role = defaultdict(lambda: defaultdict(Decimal))
            prior_src = {"Z55": defaultdict(int), "Z53": defaultdict(int)}
            gaps = {"Z55": [], "Z53": []}
            order = defaultdict(int)
            for block, pb in sorted(per_block.items()):
                group = "identical" if (pb[arm]["requests"] and pb[arm]["answers"]) else "divergent"
                c55, c53 = z55_calls(block, arm), z53_calls(block, arm)
                arm_order = jl(Z53 / block / "started.json")["block"]["arm_order"]
                order["Z53:" + ("F_before_D" if arm_order.index("F") < arm_order.index("D") else "D_before_F")] += 1
                s55 = sum((c["cost"] + c["billed_other_attempts"] for c in c55.values()), Decimal(0))
                s53 = sum((c["cost"] + c["billed_other_attempts"] for c in c53.values()), Decimal(0))
                checks["arm_cost_match_z55"] += s55 == Decimal(pb[arm]["demo"]["cost_usd"])
                checks["arm_cost_match_z53"] += s53 == Decimal(pb[arm]["z53"]["cost_usd"])
                checks["blocks"] += 1
                for run, calls in (("Z55", c55), ("Z53", c53)):
                    reqs = all_block_requests(run, block)
                    for key, c in calls.items():
                        checks[f"calls_{run}"] += 1
                        checks[f"formula_exact_{run}"] += formula(c) == c["cost"]
                        checks[f"billed_other_{run}"] += c["billed_other_attempts"] != 0
                        providers[f"{run}:{c['provider']}"] += 1
                        models[f"{run}:{c['model']}"] += 1
                        earlier = [t for t, sha, aid in reqs
                                   if sha == c["request_sha256"] and aid != c["attempt_id"] and t is not None
                                   and c["created"] is not None and t <= c["created"]]
                        label = "prior_identical_request_in_block" if earlier else "no_prior_identical_request"
                        if earlier:
                            src = sorted({arm_of(run, aid) for t, sha, aid in reqs
                                          if sha == c["request_sha256"] and aid != c["attempt_id"]
                                          and t is not None and t <= c["created"]})
                            prior_src[run]["+".join(src)] += 1
                            gaps[run].append(c["created"] - max(earlier))
                        prior[run][label] += 1
                        cached_by_prior[run][label][0] += c["cached"]
                        cached_by_prior[run][label][1] += c["prompt"]
                for key in sorted(set(c55) | set(c53)):
                    a, b = c55.get(key), c53.get(key)
                    zero = {"prompt": 0, "cached": 0, "completion": 0, "reasoning": 0, "cost": Decimal(0),
                            "billed_other_attempts": Decimal(0)}
                    a, b = a or zero, b or zero
                    # Zerlegung: Prompt-Volumen zum vollen Satz, Cache-Rabatt (9e-8 je gecachtem Token
                    # weniger), Completion; algebraisch gleich der Preisformel.
                    parts = {
                        "prompt_volume": P_UNCACHED * (a["prompt"] - b["prompt"]),
                        "cache_discount_lost": (P_UNCACHED - P_CACHED) * (b["cached"] - a["cached"]),
                        "completion": P_OUT * (a["completion"] - b["completion"]),
                        "billed_other_attempts": a["billed_other_attempts"] - b["billed_other_attempts"],
                    }
                    total = (a["cost"] + a["billed_other_attempts"]) - (b["cost"] + b["billed_other_attempts"])
                    parts["residual_price_or_rounding"] = total - sum(parts.values())
                    parts["total"] = total
                    for g in (group, "all"):
                        for k, v in parts.items():
                            comp[g][k] += v
                        for k in ("prompt", "cached", "completion", "reasoning"):
                            tok[g][f"z55_{k}"] += a[k]
                            tok[g][f"z53_{k}"] += b[k]
                        tok[g]["calls_z55"] += key in c55
                        tok[g]["calls_z53"] += key in c53
                    if group == "identical":
                        per_role[key]["delta_cost"] += total
                        per_role[key]["delta_cached_tokens"] += a["cached"] - b["cached"]
                        per_role[key]["calls"] += 1
                        if key in c55 and key in c53:
                            same_answer = c55[key]["content"] == c53[key]["content"]
                            per_role[key]["same_answer"] += int(same_answer)
                            per_role[key]["same_prompt_tokens"] += int(a["prompt"] == b["prompt"])
                            per_role[key]["same_completion_tokens"] += int(a["completion"] == b["completion"])
                comp_ = {g: {k: str(v) for k, v in d.items()} for g, d in comp.items()}
            out["arms"][arm] = {
                "checks": dict(checks), "providers": dict(providers), "models": dict(models),
                "components_usd": comp_, "tokens": {g: dict(d) for g, d in tok.items()},
                "prior_identical_request": {r: dict(d) for r, d in prior.items()},
                "prior_identical_request_source_arms": {r: dict(d) for r, d in prior_src.items()},
                "prior_gap_seconds": {r: ({"n": len(g), "min": min(g), "median": sorted(g)[len(g) // 2], "max": max(g)}
                                          if g else None) for r, g in gaps.items()},
                "z53_arm_order_F_vs_D": dict(order),
                "cached_share_by_prior": {r: {k: {"cached": v[0], "prompt": v[1],
                                                  "share": round(v[0] / v[1], 4) if v[1] else None}
                                              for k, v in d.items()} for r, d in cached_by_prior.items()},
                "identical_blocks_by_call": {k: {x: (str(y) if isinstance(y, Decimal) else y) for x, y in v.items()}
                                             for k, v in sorted(per_role.items())},
            }
    (HERE / "Z55-KOSTENZERLEGUNG.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str) + "\n")
    for arm, v in out["arms"].items():
        print(arm, v["checks"])
        print("  providers", v["providers"], "models", v["models"])
        for g, d in v["components_usd"].items():
            print("  ", g, {k: float(x) for k, x in d.items()})
        print("   tokens identical", v["tokens"]["identical"])
        print("   prior", v["prior_identical_request"], v["prior_identical_request_source_arms"], v["prior_gap_seconds"], v["z53_arm_order_F_vs_D"])
        print("   cached share", v["cached_share_by_prior"])
        for k, r in v["identical_blocks_by_call"].items():
            print("   call", k, r)


if __name__ == "__main__":
    main()
