#!/usr/bin/env python3
"""Zusatzrechnungen für den Red-Team-Fix (K1, K2, M3), deterministisch, 0 USD, keine API-Aufrufe.

Aufruf (aus dem Schreib-Ordner):  python3 06_thesis/review/redteamfix_zahlen.py
Ausgabe: 06_thesis/review/REDTEAMFIX-ZAHLEN.json und REDTEAMFIX-ZAHLEN.md (Belegdatei für A0).

Eingaben werden nur gelesen und vor der Rechnung per SHA-256 gegen die in den
Ergebnisdateien dokumentierten Werte geprüft:
- Altordner Z39 recovery-fit/run-001: F-star.json, raw-Q-sem.json, development-means.json
  (Hashes laut Z39-R1-ERGEBNIS.md bzw. SPIELRAUM-SENSITIVITAET.md)
- Altordner Z51 STATE.json (Hash laut q_verlust.py, Hauptstudie, 18.080 Zeilen)
- Schreib-Ordner: Z55-KOSTENZERLEGUNG.json (Hash laut MANIFEST.tsv), rows-T.json (Hash laut ANALYSIS-T.json)
"""
import hashlib
import json
from collections import Counter
from decimal import Decimal, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALT = ROOT.parent / "Masterarbeit" / "eval-harness/eval/runs"
Z39 = ALT / "Z39-RAEUM-ENTWICKLUNG-001/recovery-fit/run-001"
STATE_DIR = ALT / "Z51-RETRY-EINZELERSATZ-001/operation/isolated-backup-D074/8fa92e0363674966964a48fc89d9abc1"
HASH = {
    Z39 / "F-star.json": "9050e4acd90d38cce94558c95b11c38ba667fd435e13a4f0095075711597c61b",
    Z39 / "raw-Q-sem.json": "c48fa831b8db4e9319072dd508a527944f8797c1fc647e1eea56fd050518a097",
    Z39 / "development-means.json": "9719dd0357bf15775c5b105d63361d28b6d9d58e5f79a681158873f5385d5ad7",
    STATE_DIR / "STATE.json": "960d6402c87d16c9fc9817e86f1c6a0d0cddafe8d1e66c2b665c1ea1a2f05be6",
    ROOT / "04_ergebnisse/daten/collected/rows-T.json": "752c3166618ff0d9f9bbe0e6a2220247e890af3ac109f86f27c34728545386aa",
    ROOT / "04_ergebnisse/nacharbeit-2026-10-04/Z55-KOSTENZERLEGUNG.json": "a340d6126b72d0fae0c839d805837554495164ec91888081797dc17ca41ed1d8",
}
P_UNCACHED, P_CACHED, P_OUT = Decimal("1e-7"), Decimal("1e-8"), Decimal("4e-7")


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def load(path):
    assert sha(path) == HASH[path], f"Hash weicht ab: {path}"
    return json.loads(path.read_text())


def entwicklungsmatrix():
    fstar = load(Z39 / "F-star.json")
    rawq = load(Z39 / "raw-Q-sem.json")
    means = load(Z39 / "development-means.json")
    ids = rawq["config_ids"]
    em = fstar["training_quality_em"]
    cost = [Decimal(c) for c in fstar["training_cost_usd"]]
    assert len(means) == 300 and len(ids) == 14
    # Nachrechnung der F*-Mittel aus den Aufgabenmitteln
    for k in range(14):
        m = sum(t["quality_em"][k] for t in means) / 300
        assert abs(m - em[k]) < 1e-12, (k, m, em[k])
    best = max(em)
    band = [k for k in range(14) if em[k] >= best - 0.01 - 1e-12]
    fstar_idx = min(band, key=lambda k: (cost[k], k))
    assert ids[fstar_idx] == fstar["config_id"] == "C01"
    qwahl = Counter(rawq["training_selections"])
    zeilen = []
    for k, c in enumerate(ids):
        zeilen.append({"config": c, "em_pct": round(em[k] * 100, 2), "richtig_von_300": round(em[k] * 300),
                       "abstand_pp": round((em[k] - best) * 100, 2), "kosten_usd": f"{cost[k]:.8f}",
                       "kosten_rel_C01": float(round(cost[k] / cost[0], 3)), "im_spielraum_1pp": k in band,
                       "q_wahl_300": qwahl.get(c, 0)})
    # Obergrenze: beste Konfiguration je Aufgabe (in der Stichprobe, Entwicklungsmatrix)
    binaer = all(q in (0.0, 1.0) for t in means for q in t["quality_em"])
    oracle = sum(max(t["quality_em"]) for t in means)
    keine = sum(1 for t in means if max(t["quality_em"]) == 0.0)
    alle = sum(1 for t in means if min(t["quality_em"]) == 1.0)
    c01_falsch_andere_richtig = sum(1 for t in means if t["quality_em"][0] == 0.0 and max(t["quality_em"]) == 1.0)
    with localcontext() as ctx:
        ctx.prec = 40
        orc_cost = Decimal(0)
        for t in means:
            q = t["quality_em"]
            m = max(q)
            cand = [k for k in range(14) if q[k] == m]
            orc_cost += min(Decimal(t["cost_usd"][k]) for k in cand)
        orc_cost /= 300
    return {
        "zeilen": zeilen, "beste_em_pct": round(best * 100, 2), "fstar": ids[fstar_idx],
        "q_wahl_summe": sum(qwahl.values()), "q_wahl_c01": qwahl["C01"], "q_konfigurationen_genutzt": len(qwahl),
        "obergrenze": {
            "richtig_von_300": int(oracle), "em_pct": round(oracle / 3, 2),
            "differenz_zu_fstar_pp": round(oracle / 3 - best * 100, 2),
            "keine_konfiguration_richtig": keine, "alle_14_richtig": alle,
            "c01_falsch_andere_richtig": c01_falsch_andere_richtig,
            "kosten_guenstigste_beste_je_aufgabe_usd": f"{orc_cost:.8f}",
            "kosten_rel_C01": float(round(orc_cost / cost[0], 3)),
        },
        "aufgabenmittel_alle_binaer": binaer,
    }


def hauptstudie_ausfaelle():
    state, index = STATE_DIR / "STATE.json", STATE_DIR / "STATE-INDEX.json"
    idx = json.loads(index.read_text())
    assert sha(state) == HASH[state] and idx["state_sha256"] == HASH[state]
    field = next(x for x in idx["fields"] if x["name"] == "rows")
    with state.open("rb") as f:
        f.seek(field["start"])
        rows = json.loads(f.read(field["end"] - field["start"]))
    assert len(rows) == 18080
    out = {}
    with localcontext() as ctx:
        ctx.prec = 40
        for arm in ("Q", "F", "alle"):
            sel = [r for r in rows if arm == "alle" or r["arm"] == arm]
            tot = sum(Decimal(r["cost_usd"]) for r in sel)
            fail = [r for r in sel if r["status"] != "ok"]
            fc = sum(Decimal(r["cost_usd"]) for r in fail)
            out[arm] = {"laeufe": len(sel), "modellausfaelle": len(fail), "kosten_gesamt_usd": f"{tot:.8f}",
                        "kosten_ausfaelle_usd": f"{fc:.8f}", "anteil_pct": float(round(fc / tot * 100, 2))}
    assert out["Q"]["modellausfaelle"] == 228 and out["F"]["modellausfaelle"] == 224
    return out


def z55_tokenpreis():
    d = load(ROOT / "04_ergebnisse/nacharbeit-2026-10-04/Z55-KOSTENZERLEGUNG.json")
    pm = d["price_model_usd_per_token"]
    assert Decimal(str(pm["prompt_uncached"])) == P_UNCACHED and Decimal(str(pm["prompt_cached"])) == P_CACHED
    out = {}
    for teil in ("identical", "all"):
        t = d["arms"]["F"]["tokens"][teil]
        r = {}
        for lauf in ("z53", "z55"):
            p, c, o = (Decimal(t[f"{lauf}_{x}"]) for x in ("prompt", "cached", "completion"))
            liste = P_UNCACHED * p + P_OUT * o          # Tokens mal Tarif ohne Cache-Rabatt
            gemeldet = P_UNCACHED * (p - c) + P_CACHED * c + P_OUT * o  # Formel je Call exakt geprüft
            r[lauf] = {"tokens_mal_tarif_usd": f"{liste:.8f}", "gemeldet_usd": f"{gemeldet:.8f}",
                       "gemeldet_unter_tarif_pct": float(round((1 - gemeldet / liste) * 100, 1))}
        g53, g55 = Decimal(r["z53"]["gemeldet_usd"]), Decimal(r["z55"]["gemeldet_usd"])
        r["gemeldet_mehr_z55_pct"] = float(round((g55 / g53 - 1) * 100, 1))
        r["tokens_mal_tarif_gleich"] = r["z53"]["tokens_mal_tarif_usd"] == r["z55"]["tokens_mal_tarif_usd"]
        r["calls"] = [t["calls_z53"], t["calls_z55"]]
        out[teil] = r
    assert out["all"]["gemeldet_mehr_z55_pct"] == 18.9
    return out


def rundenvergleich():
    rows = load(ROOT / "04_ergebnisse/daten/collected/rows-T.json")
    by = {}
    for r in rows:
        by.setdefault(r["draw_index"], {})[r["arm"]] = r
    assert len(by) == 2952
    out = {}
    for runden in (1, 2):
        bl = [b for b in by.values() if b["Q-ST"]["rounds"] == runden]
        st = sum(b["Q-ST"]["em"] for b in bl)
        tf = sum(b["Q-TF"]["em"] for b in bl)
        out[f"regel_{runden}_runden"] = {
            "bloecke": len(bl), "richtig_regel": int(st), "richtig_eine_runde": int(tf),
            "nur_regel_richtig": sum(1 for b in bl if b["Q-ST"]["em"] > b["Q-TF"]["em"]),
            "nur_eine_runde_richtig": sum(1 for b in bl if b["Q-ST"]["em"] < b["Q-TF"]["em"]),
            "differenz_pp": round((st - tf) / len(bl) * 100, 2)}
    assert out["regel_2_runden"]["bloecke"] == 1303
    return out


def main():
    res = {"entwicklungsmatrix": entwicklungsmatrix(), "hauptstudie_modellausfaelle": hauptstudie_ausfaelle(),
           "z55_tokens_mal_tarif": z55_tokenpreis(), "rundenvergleich_nach_rundenwahl": rundenvergleich(),
           "eingaben_sha256": {str(k.relative_to(ROOT.parent)): v for k, v in HASH.items()}}
    out = Path(__file__).with_name("REDTEAMFIX-ZAHLEN.json")
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    e, h, z, t = (res[k] for k in ("entwicklungsmatrix", "hauptstudie_modellausfaelle", "z55_tokens_mal_tarif",
                                   "rundenvergleich_nach_rundenwahl"))
    o = e["obergrenze"]
    md = ["<!-- status: Rechenergebnis | Skript 06_thesis/review/redteamfix_zahlen.py | Eingaben hashgeprüft | 0 USD -->",
          "# Zusatzrechnungen Red-Team-Fix", "",
          "## Entwicklungsmatrix je Konfiguration (300 Entwicklungsaufgaben, zwei Runden)", "",
          "| Konfiguration | exakt richtig (%) | richtig von 300 | Abstand zur besten (Pp.) | mittlere bekannte Kosten (USD) | Kosten relativ zu C01 | im Spielraum 1 Pp. | Wahl von Q (abschließend gelernt, 300) |",
          "|---|---:|---:|---:|---:|---:|---|---:|"]
    for r in e["zeilen"]:
        md.append(f"| {r['config']} | {r['em_pct']:.2f} | {r['richtig_von_300']} | {r['abstand_pp']:.2f} | {r['kosten_usd']} | "
                  f"{r['kosten_rel_C01']:.3f} | {'ja' if r['im_spielraum_1pp'] else 'nein'} | {r['q_wahl_300']} |")
    md += ["", f"Feste Referenz nach der Regel: {e['fstar']}. Q nutzt {e['q_konfigurationen_genutzt']} Konfigurationen, C01 {e['q_wahl_c01']}-mal von {e['q_wahl_summe']}.", "",
           "## Obergrenze: beste Konfiguration je Aufgabe (in der Stichprobe)", "",
           f"- mindestens eine Konfiguration exakt richtig: {o['richtig_von_300']} von 300 Aufgaben ({o['em_pct']:.2f} %)",
           f"- Abstand zu F* (40,33 %): {o['differenz_zu_fstar_pp']:.2f} Prozentpunkte",
           f"- keine der 14 Konfigurationen richtig: {o['keine_konfiguration_richtig']} Aufgaben; alle 14 richtig: {o['alle_14_richtig']} Aufgaben",
           f"- C01 falsch, aber mindestens eine andere Konfiguration richtig: {o['c01_falsch_andere_richtig']} Aufgaben",
           f"- mittlere Kosten der je Aufgabe günstigsten besten Konfiguration: {o['kosten_guenstigste_beste_je_aufgabe_usd']} USD ({o['kosten_rel_C01']:.3f}-fach C01)",
           f"- alle 300 Aufgabenmittel binär (0 oder 1): {e['aufgabenmittel_alle_binaer']}", "",
           "## Hauptstudie: Kosten der Läufe mit Modellausfall", ""]
    for arm, v in h.items():
        md.append(f"- {arm}: {v['modellausfaelle']} von {v['laeufe']} Läufen, {v['kosten_ausfaelle_usd']} von {v['kosten_gesamt_usd']} USD, {v['anteil_pct']:.2f} %")
    md += ["", "## Z55 F*: Tokens mal Tarif ohne Cache-Rabatt gegen gemeldete Beträge", ""]
    for teil, v in z.items():
        md.append(f"- {teil}: Z53 Tarif {v['z53']['tokens_mal_tarif_usd']} / gemeldet {v['z53']['gemeldet_usd']} ({v['z53']['gemeldet_unter_tarif_pct']:.1f} % darunter); "
                  f"Z55 Tarif {v['z55']['tokens_mal_tarif_usd']} / gemeldet {v['z55']['gemeldet_usd']} ({v['z55']['gemeldet_unter_tarif_pct']:.1f} % darunter); "
                  f"gemeldet Z55 über Z53: {v['gemeldet_mehr_z55_pct']:.1f} %; Tarifwerte gleich: {v['tokens_mal_tarif_gleich']}")
    md += ["", "## Rundenvergleich nach Wahl der Rundenregel", ""]
    for k, v in t.items():
        md.append(f"- {k}: {v['bloecke']} Blöcke; richtig mit Regel {v['richtig_regel']}, mit einer Runde {v['richtig_eine_runde']}; "
                  f"nur Regel richtig {v['nur_regel_richtig']}, nur eine Runde richtig {v['nur_eine_runde_richtig']}; Differenz {v['differenz_pp']:.2f} Pp.")
    import re as _re
    md = [_re.sub(r"(?<=\d)\.(?=\d)", ",", z) if not z.startswith("<!--") else z for z in md]
    Path(__file__).with_name("REDTEAMFIX-ZAHLEN.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
