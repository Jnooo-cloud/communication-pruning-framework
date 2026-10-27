#!/usr/bin/env python3
"""Gegenprobe zu vergleich.py mit kontrollierten Feld- und Festschreibungsfehlern.

Erzeugt eine Pseudoausgabe aus P-ROWS.json, den gebundenen Endantworten aus eingang/ und P-ANALYSIS.json.
Die Proben behalten Null-, Reihenfolge-, Änderungs- und Festschreibungsprobe bei und ergänzen Status,
run_id, paarindex, arm, unbekannte Beträge, veränderte und fehlende Endantwort, Laufduplikat und Lauflücke.
Außerdem werden fehlendes --ausgabe-sha, eine nicht gelistete Datei sowie doppelte und unsichere
Manifestpfade geprüft. Die Pseudoausgabe ist keine Nachrechnung. Schreibt nur nach vergleich/gegenprobe/.
Keine Netzzugriffe, keine Modellaufrufe.
"""
import gzip
import hashlib
import importlib.util
import json
import math
import random
import shutil
import subprocess
import sys
from decimal import Decimal, getcontext
from pathlib import Path

getcontext().prec = 60
sys.dont_write_bytecode = True
HIER = Path(__file__).resolve().parent
ZIEL = HIER / "gegenprobe"
VERGLEICH = HIER / "vergleich.py"
REPO = Path("/Users/jannikhiller/Desktop/ai operations/Studium OS/communication-pruning-framework")
P_ROWS = REPO / "ergebnisse/hauptvergleich/P-ROWS.json"
P_ANALYSIS = REPO / "ergebnisse/hauptvergleich/P-ANALYSIS.json"
ZUFALL = 20261027
SEEDS = {"S1": "142211229048427227715370149966446052232", "S2": "25293223086774291045588755186233620233"}
WERTFELDER = ["status", "em", "f1", "call_count", "cost_usd"]
FELD_N = {"status": "status", "em": "exact_match", "f1": "f1", "call_count": "gestartete_aufrufe", "cost_usd": "bekannte_kosten_usd"}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def lade_rohantworten():
    spec = importlib.util.spec_from_file_location("n_vergleich_fuer_gegenprobe", VERGLEICH)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul.lade_rohantworten()


def stabw(werte):
    n = len(werte)
    m = math.fsum(werte) / n
    return math.sqrt(math.fsum((x - m) ** 2 for x in werte) / (n - 1))


def pseudo_aggregat(zeilen, pa):
    paare = {}
    for r in zeilen:
        paare.setdefault(r["draw_index"], {})[r["arm"]] = r
    idx = sorted(paare)
    n = len(idx)
    em = {a: [int(paare[i][a]["em"]) for i in idx] for a in "QF"}
    d = [em["Q"][k] - em["F"][k] for k in range(n)]
    kd = {a: [Decimal(paare[i][a]["cost_usd"]) for i in idx] for a in "QF"}
    kf = {a: [float(x) for x in kd[a]] for a in "QF"}
    arme = {}
    for a in "QF":
        s = sum(kd[a], Decimal(0))
        arme[a] = {"anteil_exakt_richtig": sum(em[a]) / n,
                   "f1_mittel": math.fsum(paare[i][a]["f1"] for i in idx) / n,
                   "modellausfaelle": sum(1 for i in idx if paare[i][a]["status"] == "model_failure"),
                   "kosten_summe_usd": format(s, "f"), "kosten_mittel_usd": format(s / n, "f"),
                   "gestartete_aufrufe_summe": sum(paare[i][a]["call_count"] for i in idx), "unbekannte_betraege": 0}
    rho = float(sum(kd["Q"], Decimal(0)) / sum(kd["F"], Decimal(0)))
    mf = math.fsum(kf["F"]) / n
    nse = stabw(kf["F"]) / math.sqrt(n)
    kern = pa["report"]["primary"]["kernel"]["endpoints"]
    boot = []
    for name, seed in SEEDS.items():
        dl, du, rl, ru = kern["P-D"]["lower"], kern["P-D"]["upper"], kern["P-C"]["lower"], kern["P-C"]["upper"]
        sd = "ok" if kern["P-D"]["status"] == "ok" else "nicht_aussagekraeftig"
        sr = "ok" if kern["P-C"]["status"] == "ok" else "nicht_aussagekraeftig"
        nb = sd != "ok" or sr != "ok"
        le = {"qualitaet_erhalten_3pp": dl > -0.03, "ersparnis_10pct_belegt": ru < 0.90,
              "qualitaetsverlust_belegt": du < 0, "verlust_ueber_3pp_belegt": du < -0.03,
              "ersparnis_10pct_ausgeschlossen": rl > 0.90, "mehrkosten_belegt": rl > 1, "grenze_nicht_berechenbar": nb}
        regel = le["qualitaet_erhalten_3pp"] and le["ersparnis_10pct_belegt"]
        le["offen_ohne_nachteil"] = (not regel and not le["qualitaetsverlust_belegt"] and not le["ersparnis_10pct_ausgeschlossen"]
                                     and not le["mehrkosten_belegt"] and not nb)
        zeilen_t = ([z for z, w in (("[N0556]", regel), ("[N0558]", le["offen_ohne_nachteil"]),
                                     ("[N0560]", le["qualitaetsverlust_belegt"]), ("[N0562]", le["verlust_ueber_3pp_belegt"]),
                                     ("[N0564]", le["ersparnis_10pct_ausgeschlossen"]), ("[N0566]", le["mehrkosten_belegt"]),
                                     ("[N0568]", nb)) if w])
        boot.append({"name": name, "seed": seed, "wiederholungen": 19999, "seedregel_reproduziert_s1": True,
                     "differenz": {"untere": dl, "obere": du, "status": sd, "undefinierte_wiederholungen": kern["P-D"]["undefined_resamples"], "grund": None},
                     "verhaeltnis": {"untere": rl, "obere": ru, "status": sr, "undefinierte_wiederholungen": kern["P-C"]["undefined_resamples"], "grund": None},
                     "regel_erfuellt": regel, "lesart": le, "zeilen_tabelle_4_5": zeilen_t})
    return {
        "schema": "n-nachrechnung-aggregat/v1", "n_paare": n, "n_laeufe": len(zeilen), "vollstaendig": True,
        "nicht_nachrechenbar": {"laeufe": 0, "ausgelassene_paare": 0, "lauf_kennungen": []},
        "paarzahlen": {"beide_richtig": sum(1 for k in range(n) if em["Q"][k] == em["F"][k] == 1),
                       "beide_falsch": sum(1 for k in range(n) if em["Q"][k] == em["F"][k] == 0),
                       "nur_q": d.count(1), "nur_f": d.count(-1), "gleich": d.count(0)},
        "summe_paarwerte": sum(d), "arme": arme,
        "qualitaetsdifferenz": {"schaetzer": sum(d) / n, "se": stabw([float(x) for x in d]) / math.sqrt(n)},
        "kostenverhaeltnis": {"schaetzer": rho, "se": stabw([kf["Q"][k] - rho * kf["F"][k] for k in range(n)]) / math.sqrt(n) / mf,
                              "nenner_mittel": mf, "nenner_se": nse, "nenner_quotient": mf / nse},
        "bootstrap": boot,
        "umgebung": {"python": sys.version.split()[0], "numpy": None, "plattform": "Pseudoausgabe der Gegenprobe"},
        "festlegungen_ohne_plantext": ["Pseudoausgabe aus P-ROWS.json und P-ANALYSIS.json, keine Nachrechnung"],
    }


def schreibe_ausgabe(ordner, zeilen, pa, antworten, vertausche_reihenfolge=False):
    if ordner.exists():
        shutil.rmtree(ordner)
    ordner.mkdir(parents=True)
    rang = {"Q": 0, "F": 1}
    sortiert = sorted(zeilen, key=lambda r: (r["draw_index"], rang[r["arm"]]))
    zeilen_txt = []
    for r in sortiert:
        zeilen_txt.append(json.dumps({
            "paarindex": r["draw_index"], "arm": r["arm"], "lauf_kennung": r["slot_id"], "run_id": r["run_id"],
            "status": r["status"], "grund": None, "endantwort": antworten[r["slot_id"]]["endantwort"],
            "exact_match": int(r["em"]), "f1": r["f1"],
            "gestartete_aufrufe": r["call_count"], "bekannte_kosten_usd": r["cost_usd"], "unbekannte_betraege": 0,
            "plausibilitaet": []}, ensure_ascii=False))
    if vertausche_reihenfolge:
        zeilen_txt[10], zeilen_txt[11001] = zeilen_txt[11001], zeilen_txt[10]
    (ordner / "laeufe.jsonl").write_text("\n".join(zeilen_txt) + "\n", encoding="utf-8")
    (ordner / "aggregat.json").write_text(json.dumps(pseudo_aggregat(zeilen, pa), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (ordner / "ZUGRIFFSPROTOKOLL.md").write_text("Pseudoausgabe der Gegenprobe zu vergleich.py, erzeugt aus P-ROWS.json und P-ANALYSIS.json.\n", encoding="utf-8")
    return versiegle_ausgabe(ordner)


def versiegle_ausgabe(ordner):
    manifest = ordner / "AUSGABE.sha256"
    manifest.unlink(missing_ok=True)
    dateien = sorted(p.relative_to(ordner).as_posix() for p in ordner.rglob("*") if p.is_file())
    manifest.write_text("".join(f"{sha(ordner / d)}  {d}\n" for d in dateien), encoding="utf-8")
    return sha(manifest)


def schreibe_zeilen(ordner, zeilen):
    (ordner / "laeufe.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in zeilen), encoding="utf-8")


def vergleiche(ausgabe, bericht, ausgabe_sha=None):
    cmd = [sys.executable, "-I", str(VERGLEICH), "--ausgabe", str(ausgabe), "--bericht", str(bericht)]
    if ausgabe_sha:
        cmd += ["--ausgabe-sha", ausgabe_sha]
    lauf = subprocess.run(cmd, capture_output=True, text=True)
    erg = None
    if (Path(bericht) / "VERGLEICH-ERGEBNIS.json").exists():
        erg = json.loads((Path(bericht) / "VERGLEICH-ERGEBNIS.json").read_text(encoding="utf-8"))
    return lauf.returncode, erg, lauf.stdout.strip(), lauf.stderr.strip()


def waehle_aenderungen(zeilen):
    rnd = random.Random(ZUFALL)
    reihenfolge = list(range(len(zeilen)))
    rnd.shuffle(reihenfolge)
    belegt = set()

    def nimm(bedingung):
        for i in reihenfolge:
            r = zeilen[i]
            if r["draw_index"] not in belegt and bedingung(r):
                belegt.add(r["draw_index"])
                return i
        raise RuntimeError("keine passende Zeile")

    i1 = nimm(lambda r: r["status"] == "ok")
    i2 = nimm(lambda r: r["status"] == "ok" and 0 < r["f1"] < 1 - 1e-6)
    i3 = nimm(lambda r: True)
    i4 = nimm(lambda r: True)
    i5a = nimm(lambda r: r["status"] == "ok" and 0 < r["f1"] < 1)
    a = zeilen[i5a]
    i5b = nimm(lambda r: r["arm"] == a["arm"] and r["status"] == "ok" and r["em"] == a["em"]
               and r["f1"] != a["f1"] and Decimal(r["cost_usd"]) != Decimal(a["cost_usd"]))
    ik = nimm(lambda r: r["status"] == "ok" and 0 < r["f1"] < 1 - 1e-6)
    return i1, i2, i3, i4, i5a, i5b, ik


def aenderungsprobe(prows, pa, antworten, ordner):
    zeilen = json.loads(json.dumps(prows))  # tiefe Kopie
    i1, i2, i3, i4, i5a, i5b, ik = waehle_aenderungen(zeilen)
    aend, erwartet = [], []

    def notiere(nr, art, i, feld, alt, neu):
        r = zeilen[i]
        aend.append({"nr": nr, "art": art, "lauf": r["slot_id"], "arm": r["arm"], "paarindex": r["draw_index"],
                     "feld_p_rows": feld, "feld_ausgabe": FELD_N[feld], "alt": alt, "neu": neu})

    r = zeilen[i1]; alt = r["em"]; r["em"] = 1.0 - alt
    notiere(1, "EM gedreht", i1, "em", alt, r["em"]); erwartet.append((r["slot_id"], "exact_match"))
    r = zeilen[i2]; alt = r["f1"]; r["f1"] = alt + 1e-8
    notiere(2, "F1 verändert (+1e-8, Toleranz 1e-9)", i2, "f1", alt, r["f1"]); erwartet.append((r["slot_id"], "f1"))
    r = zeilen[i3]; alt = r["call_count"]; r["call_count"] = alt + 1
    notiere(3, "Aufrufzahl +1", i3, "call_count", alt, r["call_count"]); erwartet.append((r["slot_id"], "gestartete_aufrufe"))
    r = zeilen[i4]; alt = r["cost_usd"]; r["cost_usd"] = format(Decimal(alt) + Decimal("0.0000001"), "f")
    notiere(4, "Betrag +0,0000001 US-Dollar", i4, "cost_usd", alt, r["cost_usd"]); erwartet.append((r["slot_id"], "bekannte_kosten_usd"))
    a, b = zeilen[i5a], zeilen[i5b]
    alt_a, alt_b = {f: a[f] for f in WERTFELDER}, {f: b[f] for f in WERTFELDER}
    for f in WERTFELDER:
        a[f], b[f] = alt_b[f], alt_a[f]
    for z, alt_z, neu_z in ((a, alt_a, alt_b), (b, alt_b, alt_a)):
        geaendert = [f for f in WERTFELDER if (Decimal(alt_z[f]) != Decimal(neu_z[f]) if f == "cost_usd" else alt_z[f] != neu_z[f])]
        aend.append({"nr": 5, "art": "Werte zweier Zeilen vertauscht", "lauf": z["slot_id"], "arm": z["arm"], "paarindex": z["draw_index"],
                     "feld_p_rows": geaendert, "feld_ausgabe": [FELD_N[f] for f in geaendert],
                     "alt": {f: alt_z[f] for f in geaendert}, "neu": {f: neu_z[f] for f in geaendert}})
        erwartet += [(z["slot_id"], FELD_N[f]) for f in geaendert]
    r = zeilen[ik]; alt = r["f1"]; r["f1"] = alt + 1e-10
    kontrolle = {"art": "Kontrolle: F1 um 1e-10 verändert (unter der Toleranz), keine Meldung erwartet", "lauf": r["slot_id"],
                 "arm": r["arm"], "paarindex": r["draw_index"], "alt": alt, "neu": r["f1"]}

    # abhängige Kennzahlen, in denen Folgemeldungen zulässig sind
    x1, x2, x4 = zeilen[i1]["arm"], zeilen[i2]["arm"], zeilen[i4]["arm"]
    xk = zeilen[ik]["arm"]
    zulaessig = {f"arme.{x1}.anteil_exakt_richtig", "qualitaetsdifferenz.schaetzer", "qualitaetsdifferenz.se",
                 "paarzahlen.gleich", "paarzahlen.nur_q", "paarzahlen.nur_f", "saldo_zugunsten_f",
                 f"arme.{x2}.f1_mittel", f"arme.{xk}.f1_mittel",
                 f"arme.{x4}.kosten_summe_usd", f"arme.{x4}.kosten_mittel_usd", "kostenverhaeltnis.schaetzer", "kostenverhaeltnis.se"}
    pflicht = {f"arme.{x1}.anteil_exakt_richtig", f"arme.{x4}.kosten_summe_usd"}

    ordner.mkdir(parents=True, exist_ok=True)
    versiegelt = ordner / "versiegelt"
    versiegelt.mkdir(exist_ok=True)
    roh = json.dumps(zeilen, ensure_ascii=False, sort_keys=True).encode("utf-8")
    with open(versiegelt / "P-ROWS-VERAENDERT.json.gz", "wb") as f:
        with gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as g:
            g.write(roh)
    (versiegelt / "AENDERUNGEN.json").write_text(json.dumps({
        "zufall": ZUFALL, "quelle": str(P_ROWS), "quelle_sha256": sha(P_ROWS), "aenderungen": aend, "kontrolle": kontrolle,
        "erwartete_meldungen_laufebene": sorted([list(e) for e in set(erwartet)]),
        "zulaessige_folgemeldungen": sorted(zulaessig), "pflicht_folgemeldungen": sorted(pflicht)},
        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    siegel = {p.name: sha(p) for p in sorted(versiegelt.iterdir()) if p.name != "VERSIEGELUNG.sha256"}
    (versiegelt / "VERSIEGELUNG.sha256").write_text("".join(f"{s}  {n}\n" for n, s in siegel.items()), encoding="utf-8")

    # erst jetzt vergleichen
    sha_aus = schreibe_ausgabe(ordner / "ausgabe", zeilen, pa, antworten)
    code, erg, out, err = vergleiche(ordner / "ausgabe", ordner / "bericht", sha_aus)
    siegel_danach = {n: sha(versiegelt / n) for n in siegel}
    lauf_ist = sorted({(m["lauf"], m["feld"]) for m in erg["meldungen"] if m["ebene"] == "lauf"})
    lauf_soll = sorted(set(erwartet))
    andere = [m for m in erg["meldungen"] if m["ebene"] != "lauf"]
    folge_unzulaessig = [m for m in andere if m["groesse"] not in zulaessig]
    folge_fehlend = sorted(pflicht - {m["groesse"] for m in andere})
    kontrolle_gemeldet = [m for m in erg["meldungen"] if m["lauf"] == kontrolle["lauf"]]
    meldungen_je_lauf = {}
    for l, f in lauf_ist:
        meldungen_je_lauf.setdefault(l, []).append(f)
    bestanden = (code == 1 and [tuple(x) for x in lauf_ist] == lauf_soll and not folge_unzulaessig and not folge_fehlend
                 and not kontrolle_gemeldet and siegel_danach == siegel and len(meldungen_je_lauf) == 6)
    return {"probe": "C Änderungsprobe", "bestanden": bestanden, "exit": code, "siegel": siegel,
            "siegel_unveraendert": siegel_danach == siegel,
            "aenderungen": aend, "kontrolle": kontrolle,
            "laufebene_erwartet": [list(x) for x in lauf_soll], "laufebene_gemeldet": [list(x) for x in lauf_ist],
            "gemeldete_laeufe": len(meldungen_je_lauf), "gemeldete_aenderungen": len({a_["nr"] for a_ in aend if a_["lauf"] in meldungen_je_lauf}),
            "folgemeldungen": [{k: m[k] for k in ("ebene", "groesse", "feld", "n_wert", "soll_wert", "regel")} for m in andere],
            "folgemeldungen_unzulaessig": folge_unzulaessig, "pflicht_folgemeldungen_fehlend": folge_fehlend,
            "kontrolle_gemeldet": kontrolle_gemeldet, "stdout": out, "stderr": err}


def feldprobe(prows, pa, antworten, ordner):
    ausgabe = ordner / "ausgabe"
    schreibe_ausgabe(ausgabe, prows, pa, antworten)
    datei = ausgabe / "laeufe.jsonl"
    laeufe = [json.loads(z) for z in datei.read_text(encoding="utf-8").splitlines() if z.strip()]
    rnd = random.Random(ZUFALL + 1)
    reihenfolge = list(range(len(laeufe)))
    rnd.shuffle(reihenfolge)
    belegte_paare = set()

    def nimm(bedingung):
        for i in reihenfolge:
            r = laeufe[i]
            if r["paarindex"] not in belegte_paare and bedingung(r):
                belegte_paare.add(r["paarindex"])
                return i
        raise RuntimeError("keine passende Zeile für Feldprobe")

    i_status = nimm(lambda r: r["status"] == "ok")
    i_run = nimm(lambda r: True)
    i_paar = nimm(lambda r: True)
    i_arm = nimm(lambda r: True)
    i_unknown = nimm(lambda r: r["unbekannte_betraege"] == 0)
    i_answer_changed = nimm(lambda r: isinstance(r["endantwort"], str))
    i_answer_missing = nimm(lambda r: isinstance(r["endantwort"], str))
    i_duplicate = nimm(lambda r: True)
    i_missing = nimm(lambda r: True)
    ids = {}

    r = laeufe[i_status]; ids["status"] = r["lauf_kennung"]; r["status"] = "model_failure"
    r = laeufe[i_run]; ids["run_id"] = r["lauf_kennung"]; r["run_id"] = "GEGENPROBE-FALSCHE-RUN-ID"
    r = laeufe[i_paar]; ids["paarindex"] = r["lauf_kennung"]; r["paarindex"] += 100000
    r = laeufe[i_arm]; ids["arm"] = r["lauf_kennung"]; r["arm"] = "F" if r["arm"] == "Q" else "Q"
    r = laeufe[i_unknown]; ids["unbekannte_betraege"] = r["lauf_kennung"]; r["unbekannte_betraege"] = 1
    r = laeufe[i_answer_changed]; ids["endantwort_geaendert"] = r["lauf_kennung"]; r["endantwort"] = "GEGENPROBE-ANTWORT-GEAENDERT"
    r = laeufe[i_answer_missing]; ids["endantwort_fehlt"] = r["lauf_kennung"]; del r["endantwort"]
    ids["doppelter_lauf"] = laeufe[i_duplicate]["lauf_kennung"]
    ids["fehlender_lauf"] = laeufe[i_missing]["lauf_kennung"]
    laeufe.append(dict(laeufe[i_duplicate]))
    laeufe = [r for r in laeufe if r["lauf_kennung"] != ids["fehlender_lauf"]]
    schreibe_zeilen(ausgabe, laeufe)
    sha_aus = versiegle_ausgabe(ausgabe)
    code, erg, out, err = vergleiche(ausgabe, ordner / "bericht", sha_aus)
    meldungen = erg["meldungen"] if erg else []

    erwartet = [
        ("status", ids["status"], "lauf", "lauf", "status", "model_failure"),
        ("run_id", ids["run_id"], "lauf", "lauf", "run_id", "GEGENPROBE-FALSCHE-RUN-ID"),
        ("paarindex", ids["paarindex"], "lauf", "lauf", "paarindex", laeufe[i_paar]["paarindex"]),
        ("arm", ids["arm"], "lauf", "lauf", "arm", laeufe[i_arm]["arm"]),
        ("unbekannte_betraege", ids["unbekannte_betraege"], "plausibilitaet", "lauf", "unbekannte_betraege", 1),
        ("endantwort_geaendert", ids["endantwort_geaendert"], "lauf", "lauf", "endantwort", "GEGENPROBE-ANTWORT-GEAENDERT"),
        ("endantwort_fehlt", ids["endantwort_fehlt"], "lauf", "lauf", "endantwort", "Feld fehlt"),
        ("doppelter_lauf", ids["doppelter_lauf"], "lauf", "laufmenge", "lauf_kennung", ids["doppelter_lauf"]),
        ("fehlender_lauf", ids["fehlender_lauf"], "lauf", "laufmenge", "vorhanden", None),
    ]
    gefunden = {}
    for name, lauf, ebene, groesse, feld, n_wert in erwartet:
        kandidaten = [m for m in meldungen if m["lauf"] == lauf and m["ebene"] == ebene and
                      m["groesse"] == groesse and m["feld"] == feld and m["n_wert"] == n_wert]
        gefunden[name] = bool(kandidaten)
    return {"probe": "D Feldänderungen und Laufmenge", "bestanden": code == 1 and all(gefunden.values()),
            "exit": code, "ids": ids, "erwartete_felder": [x[0] for x in erwartet], "gefunden": gefunden,
            "erwartete_meldungen": [{"mutation": n, "lauf": l, "ebene": e, "groesse": g, "feld": f,
                                     "erwarteter_n_wert": w} for n, l, e, g, f, w in erwartet],
            "meldungen_gesamt": len(meldungen), "stdout": out, "stderr": err}


def festschreibungsproben(prows, pa, antworten, ordner):
    ausgabe = ordner / "ausgabe"
    sha_aus = schreibe_ausgabe(ausgabe, prows, pa, antworten)
    code_ohne, _, _, err_ohne = vergleiche(ausgabe, ordner / "bericht-ohne-sha", None)

    extra = ausgabe / "nicht-gelistet.txt"
    extra.write_text("nicht festgeschrieben\n", encoding="utf-8")
    code_extra, _, _, err_extra = vergleiche(ausgabe, ordner / "bericht-extra", sha_aus)
    extra.unlink()

    manifest = ausgabe / "AUSGABE.sha256"
    original = manifest.read_text(encoding="utf-8")
    erste = original.splitlines()[0]
    manifest.write_text(original + erste + "\n", encoding="utf-8")
    sha_doppelt = sha(manifest)
    code_doppelt, _, _, err_doppelt = vergleiche(ausgabe, ordner / "bericht-doppelt", sha_doppelt)

    manifest.write_text(original + "0" * 64 + "  ../unsicher.txt\n", encoding="utf-8")
    sha_unsicher = sha(manifest)
    code_unsicher, _, _, err_unsicher = vergleiche(ausgabe, ordner / "bericht-unsicher", sha_unsicher)
    return {"probe": "E Festschreibungsregeln",
            "bestanden": code_ohne == 2 and "--ausgabe-sha" in err_ohne and
                         code_extra == 2 and "nicht festgeschriebene Datei" in err_extra and
                         code_doppelt == 2 and "doppelter Manifestpfad" in err_doppelt and
                         code_unsicher == 2 and "unsicherer Manifestpfad" in err_unsicher,
            "ohne_ausgabe_sha": {"exit": code_ohne, "erwartet": 2, "fehler": err_ohne},
            "extra_datei": {"exit": code_extra, "erwartet": 2, "fehler": err_extra},
            "doppelter_manifestpfad": {"exit": code_doppelt, "erwartet": 2, "fehler": err_doppelt},
            "unsicherer_manifestpfad": {"exit": code_unsicher, "erwartet": 2, "fehler": err_unsicher}}


def main():
    if ZIEL.exists():
        shutil.rmtree(ZIEL)
    ZIEL.mkdir()
    prows = json.load(open(P_ROWS, encoding="utf-8"))
    pa = json.load(open(P_ANALYSIS, encoding="utf-8"))
    antworten = lade_rohantworten()
    ergebnisse = []

    s = schreibe_ausgabe(ZIEL / "A-null/ausgabe", prows, pa, antworten)
    code, erg, out, err = vergleiche(ZIEL / "A-null/ausgabe", ZIEL / "A-null/bericht", s)
    ergebnisse.append({"probe": "A Nullprobe", "bestanden": code == 0 and erg["meldungen_gesamt"] == 0, "exit": code,
                       "meldungen": erg["meldungen"][:50], "stdout": out, "stderr": err})

    s = schreibe_ausgabe(ZIEL / "B-reihenfolge/ausgabe", prows, pa, antworten, vertausche_reihenfolge=True)
    code, erg, out, err = vergleiche(ZIEL / "B-reihenfolge/ausgabe", ZIEL / "B-reihenfolge/bericht", s)
    ergebnisse.append({"probe": "B Reihenfolgeprobe (Zeilen 11 und 11.002 von laeufe.jsonl vertauscht)",
                       "bestanden": code == 0 and erg["meldungen_gesamt"] == 0, "exit": code,
                       "meldungen": erg["meldungen"][:50], "stdout": out, "stderr": err})

    ergebnisse.append(aenderungsprobe(prows, pa, antworten, ZIEL / "C-aenderung"))
    ergebnisse.append(feldprobe(prows, pa, antworten, ZIEL / "D-feldprobe"))
    ergebnisse.append(festschreibungsproben(prows, pa, antworten, ZIEL / "E-vorbedingungen"))

    f = ZIEL / "F-nachtraegliche-aenderung"
    s = schreibe_ausgabe(f / "ausgabe", prows, pa, antworten)
    code_falsch, _, _, err_falsch = vergleiche(f / "ausgabe", f / "bericht-falsche-sha", "0" * 64)
    with open(f / "ausgabe/aggregat.json", "a", encoding="utf-8") as f_agg:
        f_agg.write(" ")
    code_veraendert, _, _, err_veraendert = vergleiche(f / "ausgabe", f / "bericht-veraendert", s)
    ergebnisse.append({"probe": "F Änderung nach Festschreibung", "bestanden": code_falsch == 2 and code_veraendert == 2,
                       "exit_falsche_sha": code_falsch, "meldung_falsche_sha": err_falsch,
                       "exit_nach_festschreibung_veraendert": code_veraendert, "meldung_veraendert": err_veraendert})

    gesamt = all(e["bestanden"] for e in ergebnisse)
    kopf = {"schema": "n-gegenprobe/v1", "bestanden": gesamt, "vergleich_py_sha256": sha(VERGLEICH),
            "gegenprobe_py_sha256": sha(Path(__file__)), "p_rows_sha256": sha(P_ROWS), "p_analysis_sha256": sha(P_ANALYSIS),
            "eingang_manifest_sha256": sha(HIER.parent / "eingang/MANIFEST.sha256")}
    (ZIEL / "GEGENPROBE-ERGEBNIS.json").write_text(json.dumps({**kopf, "proben": ergebnisse}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    c = ergebnisse[2]
    d = ergebnisse[3]
    e = ergebnisse[4]
    f = ergebnisse[5]
    z = ["<!-- status: Gegenprobe zu vergleich.py, maschinell | 2026-10-27 -->", "", "# Gegenprobe des Vergleichsskripts", "",
         f"Gesamt: **{'bestanden' if gesamt else 'NICHT bestanden'}**", "",
         f"- vergleich.py SHA-256 `{kopf['vergleich_py_sha256']}`", f"- gegenprobe.py SHA-256 `{kopf['gegenprobe_py_sha256']}`",
         f"- P-ROWS.json SHA-256 `{kopf['p_rows_sha256']}`, P-ANALYSIS.json SHA-256 `{kopf['p_analysis_sha256']}`",
         f"- eingang/MANIFEST.sha256 SHA-256 `{kopf['eingang_manifest_sha256']}`", "",
         "| Probe | erwartet | Ergebnis |", "|---|---|---|",
         f"| A Nullprobe | keine Meldung, Exit 0 | Exit {ergebnisse[0]['exit']}, {len(ergebnisse[0]['meldungen'])} Meldungen, {'bestanden' if ergebnisse[0]['bestanden'] else 'nicht bestanden'} |",
         f"| B Reihenfolgeprobe | keine Meldung, Exit 0 | Exit {ergebnisse[1]['exit']}, {len(ergebnisse[1]['meldungen'])} Meldungen, {'bestanden' if ergebnisse[1]['bestanden'] else 'nicht bestanden'} |",
         f"| C Änderungsprobe | genau die 5 Änderungen auf Laufebene (6 Läufe), Kontrolle ungemeldet | Exit {c['exit']}, {c['gemeldete_aenderungen']} Änderungen in {c['gemeldete_laeufe']} Läufen gemeldet, Kontrolle {'gemeldet' if c['kontrolle_gemeldet'] else 'ungemeldet'}, {'bestanden' if c['bestanden'] else 'nicht bestanden'} |",
         f"| D Feldprobe | Status, run_id, paarindex, arm, unbekannte Beträge, beide Endantwortfehler, Duplikat und Lücke gemeldet | Exit {d['exit']}, erwartete Meldungen {sum(d['gefunden'].values())}/{len(d['gefunden'])}, {'bestanden' if d['bestanden'] else 'nicht bestanden'} |",
         f"| E Festschreibungsregeln | fehlender Hash, Zusatzdatei, doppelter und unsicherer Manifestpfad blockieren | Exit {e['ohne_ausgabe_sha']['exit']}/{e['extra_datei']['exit']}/{e['doppelter_manifestpfad']['exit']}/{e['unsicherer_manifestpfad']['exit']}, {'bestanden' if e['bestanden'] else 'nicht bestanden'} |",
         f"| F Änderung nach Festschreibung | falsche Prüfsumme und geänderte Datei: Exit 2 | Exit {f['exit_falsche_sha']}/{f['exit_nach_festschreibung_veraendert']}, {'bestanden' if f['bestanden'] else 'nicht bestanden'} |",
         "", "## Änderungsprobe im Einzelnen", "", "| Nr. | Art | Lauf | Feld | alt | neu |", "|---|---|---|---|---|---|"]
    for a in c["aenderungen"]:
        z.append(f"| {a['nr']} | {a['art']} | {a['lauf']} | {a['feld_ausgabe']} | {a['alt']} | {a['neu']} |")
    z += ["", f"Kontrolle: {c['kontrolle']['art']}; Lauf {c['kontrolle']['lauf']}.", "",
          "Gemeldet auf Laufebene (Lauf, Feld):", ""] + [f"- {l}, {f}" for l, f in c["laufebene_gemeldet"]]
    z += ["", "## Feldprobe und erwartete Meldungen", "", "| Mutation | Lauf | Erwartete Meldung | Ergebnis |", "|---|---|---|---|"]
    for name in d["erwartete_felder"]:
        zeile = next(x for x in d["erwartete_meldungen"] if x["mutation"] == name)
        z.append(f"| {name} | {zeile['lauf']} | {zeile['ebene']}/{zeile['feld']} | {'gemeldet' if d['gefunden'][name] else 'FEHLT'} |")
    z += ["", "## Festschreibungsregeln", ""]
    for name in ("ohne_ausgabe_sha", "extra_datei", "doppelter_manifestpfad", "unsicherer_manifestpfad"):
        probe = e[name]
        z.append(f"- {name}: Exit {probe['exit']}, erwartet {probe['erwartet']}; {probe['fehler'].splitlines()[-1] if probe['fehler'] else 'keine Fehlermeldung'}")
    z += ["", "Folgemeldungen in abhängigen Kennzahlen (zulässig, weil die Pseudoausgabe ihre Punktwerte aus den veränderten Zeilen rechnet):", ""]
    z += [f"- {m['ebene']}: {m['groesse']} ({m['feld']}): {m['n_wert']} statt {m['soll_wert']}" for m in c["folgemeldungen"]]
    z += ["", f"Unzulässige Folgemeldungen: {len(c['folgemeldungen_unzulaessig'])}; fehlende Pflichtfolgemeldungen: {c['pflicht_folgemeldungen_fehlend'] or 'keine'}; Siegel unverändert: {c['siegel_unveraendert']}."]
    (ZIEL / "GEGENPROBE-ERGEBNIS.md").write_text("\n".join(z) + "\n", encoding="utf-8")
    print(json.dumps({"bestanden": gesamt, "proben": [(e["probe"], e["bestanden"]) for e in ergebnisse]}, ensure_ascii=False))
    return 0 if gesamt else 1


if __name__ == "__main__":
    sys.exit(main())
