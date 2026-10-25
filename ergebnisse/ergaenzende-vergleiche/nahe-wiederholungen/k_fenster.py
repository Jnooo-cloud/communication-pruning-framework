"""K-Fenster-Auswertung der Z53-Nebenpanels (offline, 0 USD, keine API-Aufrufe).

Auflage aus Z53 DESIGN.md (Fassung 002, letzter Absatz): Paare gleicher task_id innerhalb
eines Fensters von K aufeinanderfolgenden Blöcken berichten, Kostenquotienten mit und ohne
diese Paare. Tatsächlich gewählt K = 4 (log.md 01.10. 19:20), ursprünglich vorgesehen K = 6.

Definition (vor dem Rechnen festgelegt, wie in runde3/CODEX.md beschrieben):
- Betrachtet werden nur Blöcke des parallel gelaufenen Z53-Abschnitts:
  R draw_index 2183..2951 ("R-Rest"), T und F vollständig (0..2951).
- Ein Paar ist (i, j) mit i < j, gleicher task_id und j - i < K (Indexabstand kleiner K,
  also beide Blöcke in einem Fenster von K aufeinanderfolgenden Blöcken).
- Sensitivität: Alle Blöcke, die in mindestens einem Paar vorkommen, entfallen mit sämtlichen
  Armen; die Kostenquotienten (Verhältnis der Kostenmittel, wie ANALYSIS-*.json) werden auf
  dem gesamten Panel ohne diese Blöcke neu gerechnet. Beim R-Panel bleibt der sequenzielle
  Teil 0..2182 enthalten.
- Ergänzend beschreibend: EM-Differenz je Endpunkt mit und ohne betroffene Blöcke, die
  tatsächliche Zeitlage der Paare aus den Bearbeitungsintervallen in live/events.jsonl
  ([t - seconds, t] des letzten complete-Eintrags) und Cache-Anteile aus den Rohantworten
  im alten Repo (nur lesend).

Eingaben: 04_ergebnisse/daten/collected/rows-{R,T,F}.json (SHA gegen MANIFEST.tsv geprüft),
04_ergebnisse/belege/RTF/ANALYSIS-{R,T,F}.json (Endpunktdefinition und Referenzwerte).
Ausgabe: K-FENSTER-ERGEBNIS.json neben diesem Skript.
"""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal, localcontext
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # Schreibordner
OLD = ROOT.parent / "Masterarbeit" / "eval-harness/eval/runs/Z53-SCHNELLFORTSETZUNG-001/live/blocks"
Z53_START = {"R": 2183, "T": 0, "F": 0}
KS = (4, 6)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest() -> dict[str, str]:
    out = {}
    for line in (ROOT / "MANIFEST.tsv").read_text().splitlines()[1:]:
        ziel, _quelle, digest = line.split("\t")
        out[ziel] = digest
    return out


def ratio(rows_by_block, blocks, num, den):
    with localcontext() as ctx:
        ctx.prec = 50
        n = [Decimal(rows_by_block[b][num]["cost_usd"]) for b in blocks]
        d = [Decimal(rows_by_block[b][den]["cost_usd"]) for b in blocks]
        return (sum(n) / len(n)) / (sum(d) / len(d))


CHANGE_ARMS = {"H_Q": [("Qf", "Qc")], "H_F": [("Ff", "Fc")], "H_Q_minus_H_F": [("Qf", "Qc"), ("Fc", "Ff")]}


def mean_change(rows_by_block, blocks, quantity):
    """Mittlere gepaarte Kostenänderung (F03 bis F05); H_Q_minus_H_F = (Qf-Qc) - (Ff-Fc)."""
    with localcontext() as ctx:
        ctx.prec = 50
        total = Decimal(0)
        for b in blocks:
            for a, c in CHANGE_ARMS[quantity]:
                total += Decimal(rows_by_block[b][a]["cost_usd"]) - Decimal(rows_by_block[b][c]["cost_usd"])
        return total / len(blocks)


def value(rows_by_block, blocks, ep):
    if ep["kind"] == "ratio_of_means":
        return ratio(rows_by_block, blocks, ep["numerator_arm"], ep["denominator_arm"])
    assert ep["kind"] == "mean_paired_change", ep["kind"]
    return mean_change(rows_by_block, blocks, ep["quantity"])


def em_diff(rows_by_block, blocks, num, den):
    return math.fsum(rows_by_block[b][num]["em"] - rows_by_block[b][den]["em"] for b in blocks) / len(blocks)


def load_events():
    """Bearbeitungsintervall je Block aus live/events.jsonl: letzter "complete"-Eintrag, [t - seconds, t]."""
    spans = {}
    for line in (OLD.parent / "events.jsonl").read_text().splitlines():
        e = json.loads(line)
        if e.get("kind") == "complete":
            spans[e["block"]] = (e["t"] - e["seconds"], e["t"], e.get("attempt"), bool(e.get("resumed_arms")))
    return spans


EVENTS = None


def block_times(panel: str, idx: int):
    """Bearbeitungsintervall (events.jsonl) und Cache-Anteil der Prompt-Tokens über alle gewerteten Calls.

    Gewertete Calls: je attempt_id die finale HTTP-200-Antwort; bei mehreren Provider-Ordnern
    (provider, provider-*.a1 aus fortgesetzten Blöcken) gewinnt der frische Ordner "provider",
    sonst der letzte (gleiche Regel wie z53_fast._pick).
    """
    global EVENTS
    if EVENTS is None:
        EVENTS = load_events()
    bdir = OLD / f"{panel}-{idx:05d}"
    entries = {}
    for pdir in sorted(p for p in bdir.iterdir() if p.is_dir() and p.name.startswith("provider")):
        for b in sorted(pdir.glob("*-binding.json")):
            aid = json.loads(b.read_text())["attempt_id"]
            entries.setdefault(aid, []).append((pdir, b.name[:3]))
    prompt = cached = 0
    for aid, items in entries.items():
        names = [p.name for p, _ in items]
        pick = "provider" if "provider" in names else names[-1]
        pdir, stem = next(x for x in items if x[0].name == pick)
        finals = [pdir / r.name.replace("-received.json", "-response.json")
                  for r in sorted(pdir.glob(f"{stem}-p*-received.json"))
                  if json.loads(r.read_text())["http_status"] == 200]
        if not finals:
            continue
        usage = json.loads(finals[-1].read_text()).get("usage") or {}
        prompt += usage.get("prompt_tokens") or 0
        cached += ((usage.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0
    ev = EVENTS.get(f"{panel}-{idx:05d}")
    span = (ev[0], ev[1]) if ev else None  # ungerundet; erst Endwerte runden
    return span, (round(cached / prompt, 4) if prompt else None), (ev[2:] if ev else None)


def main():
    man = manifest()
    result = {"definition": __doc__.strip().splitlines()[0], "ks": list(KS), "panels": {}}
    for panel in "RTF":
        rel = f"04_ergebnisse/daten/collected/rows-{panel}.json"
        digest = sha(ROOT / rel)
        assert digest == man[rel], f"{rel}: SHA weicht vom MANIFEST ab"
        rows = json.loads((ROOT / rel).read_text())
        analysis = json.loads((ROOT / f"04_ergebnisse/belege/RTF/ANALYSIS-{panel}.json").read_text())["report"]
        endpoints = analysis["descriptive_costs"]["endpoints"]
        by_block: dict[int, dict[str, dict]] = {}
        task_of: dict[int, str] = {}
        for r in rows:
            by_block.setdefault(r["draw_index"], {})[r["arm"]] = r
            task_of[r["draw_index"]] = r["task_id"]
        all_blocks = sorted(by_block)
        assert all_blocks == list(range(len(all_blocks)))
        full = {}
        for name, ep in endpoints.items():
            q = value(by_block, all_blocks, ep)
            ref = Decimal(ep["estimate"])
            assert abs(q - ref) < Decimal("1e-40"), (panel, name, q, ref)
            full[name] = q
        pres = {"rows_sha256": digest, "n_blocks": len(all_blocks), "z53_start": Z53_START[panel],
                "reproduced_full_ratios": {k: str(v) for k, v in full.items()}, "by_k": {}}
        z53_blocks = [b for b in all_blocks if b >= Z53_START[panel]]
        for k in KS:
            pairs = []
            for pos, i in enumerate(z53_blocks):
                for j in z53_blocks[pos + 1:]:
                    if j - i >= k:
                        break
                    if task_of[i] == task_of[j]:
                        pairs.append((i, j))
            affected = sorted({b for p in pairs for b in p})
            kept = [b for b in all_blocks if b not in set(affected)]
            eps = {}
            for name, ep in endpoints.items():
                q_wo = value(by_block, kept, ep)
                fmt = ".6f" if ep["kind"] == "ratio_of_means" else ".8f"
                entry = {"kind": ep["kind"], "full": format(full[name], fmt), "without": format(q_wo, fmt),
                         "change": format(q_wo - full[name], fmt)}
                if ep["kind"] == "ratio_of_means":
                    num, den = ep["numerator_arm"], ep["denominator_arm"]
                    entry.update({"numerator_arm": num, "denominator_arm": den,
                                  "em_diff_full": round(em_diff(by_block, all_blocks, num, den), 6),
                                  "em_diff_without": round(em_diff(by_block, kept, num, den), 6)})
                else:
                    entry["quantity"] = ep["quantity"]
                eps[name] = entry
            pair_info = []
            for i, j in pairs:
                (ti, ci, ai), (tj, cj, aj) = block_times(panel, i), block_times(panel, j)
                overlap = gap = shared = None
                if ti and tj:
                    overlap = not (ti[1] < tj[0] or tj[1] < ti[0])
                    gap = round(max(0.0, max(ti[0], tj[0]) - min(ti[1], tj[1])), 3)
                    shared = round(max(0.0, min(ti[1], tj[1]) - max(ti[0], tj[0])), 3)
                pair_info.append({"blocks": [i, j], "distance": j - i, "task_id": task_of[i],
                                  "family_id": by_block[i][next(iter(by_block[i]))]["family_id"],
                                  "processing_span_i": ti, "processing_span_j": tj,
                                  "attempt_resumed_i": ai, "attempt_resumed_j": aj,
                                  "time_overlap": overlap, "overlap_seconds": shared, "gap_seconds": gap,
                                  "cached_share_i": ci, "cached_share_j": cj})
            pres["by_k"][str(k)] = {"pairs": len(pairs), "affected_blocks": len(affected),
                                    "kept_blocks": len(kept), "pair_details": pair_info,
                                    "endpoints": eps}
        shares = [block_times(panel, b)[1] for b in z53_blocks]
        shares = [x for x in shares if x is not None]
        pres["z53_block_cached_share"] = {"n": len(shares), "mean": round(sum(shares) / len(shares), 4),
                                          "share_blocks_with_cache": round(sum(x > 0 for x in shares) / len(shares), 4)}
        result["panels"][panel] = pres
    out = HERE / "K-FENSTER-ERGEBNIS.json"
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    for panel, p in result["panels"].items():
        print(panel, "Cache-Basis", p["z53_block_cached_share"])
        for k, v in p["by_k"].items():
            print(panel, "K", k, "Paare", v["pairs"], "betroffen", v["affected_blocks"])
            for name, e in v["endpoints"].items():
                print("   ", name, e["full"], "->", e["without"], "EM", e.get("em_diff_full"), "->", e.get("em_diff_without"))
            for d in v["pair_details"]:
                print("    Paar", d["blocks"], "overlap", d["time_overlap"], d["overlap_seconds"], "gap", d["gap_seconds"], "cache", d["cached_share_i"], d["cached_share_j"], d["attempt_resumed_i"], d["attempt_resumed_j"])


if __name__ == "__main__":
    main()
