"""Leckprüfung des Eingangspakets der getrennten Nachrechnung N.

Prüft, dass eingang/ weder Ergebnisdateien noch Framework-/Auswertungscode noch Ergebniszahlen
des Hauptvergleichs enthält (außer in den Laufprotokollen selbst, die die Rohdaten sind).
Schreibt pruefung/LECKPRUEFUNG.json und pruefung/LECKPRUEFUNG.md. Exit 0 nur bei bestanden.
"""
import csv, gzip, hashlib, json, re, sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ARBEIT = Path(__file__).resolve().parent.parent
EINGANG = ARBEIT / "eingang"
REPO = Path("/Users/jannikhiller/Desktop/ai operations/Studium OS/communication-pruning-framework")
P_ANALYSIS = REPO / "ergebnisse/hauptvergleich/P-ANALYSIS.json"
ARBEIT_MD = Path("/Users/jannikhiller/Desktop/ai operations/Studium OS/Masterarbeit/output/council-feedback-rev25-2026-10-27/quellen/thesis-rev25-bereinigt.md")
Z56_FILES = REPO / "nachpruefungen-nach-studienabschluss/pruefroutine-studienlaeufe/MANIFEST-FILES.jsonl.gz"

# Unveränderte Fremd- bzw. Vorstudiendateien: Prüfsumme gegen das Original statt Zahlensuche als Kriterium
ORIGINALE = {
    "daten/musique_ans_v1.0_dev.jsonl": "15fa63794d18a94ce12411aca6e2327e65b6e83b0b1490efab3f1962e48abf3b",
    "bewertung/metrics/answer.py": "10368f619b4d5ef5d83748c05a96c0afd332a14ab5c010740c98d58dfaefe974",
    "bewertung/evaluate_v1.0.py": "f5fe66ae61dbea5172cba9d428d9924a5811f3457edc945fc1d81369c30e74b7",
    "plan/PLAN.json": "42a55ddd7dc71738d39fbdb546b0bb60ca19a0d6485f47688de32c893f47f61f",
    "plan/ANALYSIS-BINDING.json": "283c02def99e0fb2c88de66a1dd0e8ac2feebaf737bb058981b2be46d5c7ce0a",
    "plan/METHODEN-UND-INFORMATION.md": "c316809305d5eeef11ec9406ed474e6bb0058c47716130737627f8ce8e47623d",
    "format/contract.md": "3f96117f930839c25afc33bafa0b98bfb1e1e73984ab47fad170f36fff7674e9",
}
SELBST_GESCHRIEBEN = ["AUFTRAG.md", "METHODENAUSZUG.md", "laufliste.tsv", "bewertung/metrics/metric.py"]
ERLAUBTE_DATEIEN = set(ORIGINALE) | set(SELBST_GESCHRIEBEN) | {"MANIFEST.sha256"}

VERBOTENE_NAMEN = {"result.json", "reference.json", "selection.json", "STATE.json", "P-ROWS.json",
                   "P-ANALYSIS.json", "intervals.py", "final_analysis.py", "nachrechnen.py", "audit_v2.py",
                   "RESULTS.jsonl", "build_manifest.py", "MANIFEST-RUNS.jsonl.gz", "MANIFEST-FILES.jsonl.gz"}
VERBOTENE_TEILE = ["communication_pruning", "study_preparation", "nachrechnen", "nachpruefungen",
                   "studiencode", "eval-harness", "ergebnisse"]

# Design- und Planwerte, die in Plan und Methodentext legitim vorkommen (keine Ergebnisse)
DESIGNWERTE = {"9040", "19999", "142211229048427227715370149966446052232", "1", "0", "3", "30", "60", "120",
               "2", "100",
               # Schwellen und Quantile der Entscheidungsregel (Plan, Methodenauszug), keine Ergebnisse
               "97.5", "2.5", "0.90", "95", "0.03"}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def blaetter(x, pfad=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from blaetter(v, f"{pfad}.{k}" if pfad else k)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from blaetter(v, f"{pfad}[{i}]")
    else:
        yield pfad, x


def zahl_varianten(wert):
    """Textformen einer Zahl, wie sie in Text oder Daten auftauchen könnten (mindestens 3 signifikante Ziffern)."""
    out = set()
    if isinstance(wert, bool) or wert is None:
        return out
    if isinstance(wert, int) or (isinstance(wert, str) and re.fullmatch(r"-?\d+", wert)):
        i = int(wert)
        s = str(abs(i))
        if len(s) >= 3:
            out.add(s)
            if len(s) >= 4:
                out.add(f"{abs(i):,}".replace(",", "."))
                out.add(f"{abs(i):,}")
        return out
    try:
        d = Decimal(str(wert))
    except Exception:
        return out
    if not d.is_finite():
        return out
    for skala in (Decimal(1), Decimal(100)):
        v = abs(d * skala)
        for stellen in range(1, 9):
            r = v.quantize(Decimal(1).scaleb(-stellen), rounding=ROUND_HALF_UP)
            s = format(r, "f")
            ziffern = s.replace(".", "").lstrip("0")
            if len(ziffern) < 3:
                continue
            out.add(s)
            out.add(s.replace(".", ","))
    s = format(abs(d), "f")
    if len(s.replace(".", "").lstrip("0")) >= 3:
        out.add(s)
        out.add(s.replace(".", ","))
    return out


def ergebniszahlen():
    pa = json.load(open(P_ANALYSIS, encoding="utf-8"))
    werte = {}
    for pfad, w in blaetter(pa):
        if isinstance(w, bool) or w is None:
            continue
        if isinstance(w, str) and not re.fullmatch(r"-?\d+(\.\d+)?", w):
            continue
        roh = str(w)
        if roh.lstrip("-") in DESIGNWERTE:
            continue
        werte.setdefault(roh, pfad)
    # Zahlen aus Abschnitt 6.3 der Arbeit (Hauptvergleich), ohne Abschnitts-, Tabellen- und Abbildungsnummern
    zeilen = ARBEIT_MD.read_text(encoding="utf-8").split("\n")
    i = next(k for k, z in enumerate(zeilen) if z.startswith("## 6.3 "))
    j = next(k for k in range(i + 1, len(zeilen)) if zeilen[k].startswith("## 6.4 "))
    text63 = "\n".join(zeilen[i:j])
    text63 = re.sub(r"\[[NX]\d+\]", " ", text63)
    text63 = re.sub(r"(Abschnitt(?:e|s)?|Tabelle|Abbildung|Kapitel)\s+\d+\.\d+", " ", text63)
    for m in re.finditer(r"-?\d{1,3}(?:\.\d{3})+(?:,\d+)?|-?\d+,\d+|-?\d+", text63):
        t = m.group(0)
        norm = t.replace(".", "").replace(",", ".")
        if norm.lstrip("-") in DESIGNWERTE:
            continue
        werte.setdefault(norm, "Arbeit 6.3: " + t)
    return werte, text63


def main():
    befunde, info = [], []
    dateien = sorted(p.relative_to(EINGANG).as_posix() for p in EINGANG.rglob("*") if p.is_file())
    protokolle = [d for d in dateien if d.startswith("protokolle/")]
    andere = [d for d in dateien if not d.startswith("protokolle/")]

    # A Dateibestand
    for d in dateien:
        name = d.rsplit("/", 1)[-1]
        if name in VERBOTENE_NAMEN or re.fullmatch(r"ANALYSIS-.*\.json", name) and name != "ANALYSIS-BINDING.json":
            befunde.append(f"verbotener Dateiname: {d}")
        for teil in VERBOTENE_TEILE:
            if teil in d:
                befunde.append(f"verbotener Pfadteil '{teil}': {d}")
        if name.endswith(".pyc") or "__pycache__" in d or name == ".DS_Store":
            befunde.append(f"Cache-/Systemdatei: {d}")
    for d in andere:
        if d not in ERLAUBTE_DATEIEN:
            befunde.append(f"unerwartete Datei außerhalb protokolle/: {d}")
    py = [d for d in dateien if d.endswith(".py")]
    if sorted(py) != sorted(["bewertung/metrics/answer.py", "bewertung/metrics/metric.py", "bewertung/evaluate_v1.0.py"]):
        befunde.append(f"unerwartete Python-Dateien: {py}")

    # B Originale unverändert
    for rel, soll in ORIGINALE.items():
        ist = sha(EINGANG / rel)
        if ist != soll:
            befunde.append(f"{rel}: SHA-256 {ist} statt Original {soll}")

    # C Protokolle: genau die 18.080 Studienprotokolle, unverändert, je einmal in der Laufliste
    z56 = {}
    for line in gzip.open(Z56_FILES, "rt", encoding="utf-8"):
        r = json.loads(line)
        if r["path"].endswith("/journal.jsonl"):
            z56[r["path"]] = r["sha256"]
    herkunft = {}
    with open(ARBEIT / "zuordnung/HERKUNFT-PROTOKOLLE.tsv", encoding="utf-8") as f:
        for z in csv.DictReader(f, delimiter="\t"):
            herkunft[z["pfad_eingang"]] = (z["quelle_relativ_zu_eval-harness/eval/runs"], z["sha256"])
    if len(protokolle) != 18080:
        befunde.append(f"{len(protokolle)} Protokolle statt 18.080")
    for d in protokolle:
        if not re.fullmatch(r"protokolle/[QF]/\d{5}\.jsonl", d):
            befunde.append(f"unerwarteter Protokollpfad: {d}")
            continue
        quelle, s = herkunft.get(d, (None, None))
        ist = sha(EINGANG / d)
        if quelle is None or ist != s or z56.get(quelle) != ist:
            befunde.append(f"Protokoll nicht bytegleich mit dem Studienprotokoll laut Z56-Dateimanifest: {d}")
    with open(EINGANG / "laufliste.tsv", encoding="utf-8") as f:
        kopf = f.readline().rstrip("\n").split("\t")
        if kopf != ["paarindex", "arm", "block_id", "musique_id", "lauf_kennung", "pfad"]:
            befunde.append(f"Laufliste: unerwartete Spalten {kopf}")
        pfade = [z.rstrip("\n").split("\t")[5] for z in f]
    if sorted(pfade) != sorted(protokolle) or len(set(pfade)) != len(pfade):
        befunde.append("Laufliste und Protokollordner decken sich nicht eins zu eins")

    # D Zahlensuche
    werte, _ = ergebniszahlen()
    muster = {}
    for roh, herkunft_wert in werte.items():
        for v in zahl_varianten(roh):
            muster.setdefault(v, (roh, herkunft_wert))
    # Jede Zahl im Text als ganze Ziffernfolge (Ziffern mit . und , dazwischen) gegen die Menge der Textformen;
    # so trifft "1.169" nicht in "1.1692" und "31.99" nicht in "131.99".
    ziffernfolge = re.compile(r"\d[\d.,]*\d|\d")

    def suche(text):
        treffer = []
        for m in ziffernfolge.finditer(text):
            v = m.group(0)
            if v in muster:
                roh, hk = muster[v]
                a, b = max(0, m.start() - 60), min(len(text), m.end() + 60)
                treffer.append({"wert": v, "ergebniszahl": roh, "herkunft": hk, "kontext": text[a:b].replace("\n", " ")})
        return treffer

    zahl_treffer = {}
    for rel in SELBST_GESCHRIEBEN + list(ORIGINALE):
        if rel == "laufliste.tsv":
            # Paarindizes und MuSiQue-IDs sind Zuordnungsdaten; geprüft wird die Spaltenstruktur (oben)
            continue
        text = (EINGANG / rel).read_text(encoding="utf-8")
        t = suche(text)
        if t:
            zahl_treffer[rel] = t
    for rel, liste in zahl_treffer.items():
        if rel in SELBST_GESCHRIEBEN:
            for t in liste:
                befunde.append(f"Ergebniszahl in selbst geschriebener Datei {rel}: {t['wert']} ({t['herkunft']}) … {t['kontext']} …")
        else:
            info.append(f"{rel}: {len(liste)} Zahlentreffer in unveränderter Originaldatei (Prüfsumme gleich Original, vor der Studie bzw. extern entstanden)")

    # E Methodenauszug: keine Ergebnisverweise
    ma = (EINGANG / "METHODENAUSZUG.md").read_text(encoding="utf-8")
    koerper = ma.split("\n---\n", 1)[1]  # Wortlaut der Arbeit, ohne den Kopf mit der Auslassungsliste
    for wort in ["6.3", "Kapitel 6", "[X0570]", "[N4004]", "[N4005]", "[N4006]", "[X1695]",
                 "nicht erreicht", "lohnt sich nicht", "verfehlt die", "schon die Qualitätsbedingung"]:
        for m in re.finditer(re.escape(wort), koerper):
            kontext = koerper[max(0, m.start() - 80):m.end() + 40].replace("\n", " ")
            befunde.append(f"Methodenauszug: '{wort}' im Wortlaut: … {kontext} …")

    # F Textverweise auf Framework-Code (Information, kein Befund: Pfad und Hash bzw. Funktionsnamen)
    for rel in list(ORIGINALE) + SELBST_GESCHRIEBEN:
        if rel.startswith("daten/") or rel == "laufliste.tsv":
            continue
        text = (EINGANG / rel).read_text(encoding="utf-8")
        for teil in ["communication_pruning", "study_preparation", "intervals.py", "final_analysis.py"]:
            n = text.count(teil)
            if n:
                info.append(f"{rel}: {n}× Textverweis '{teil}' (Name bzw. Pfad, keine Datei im Paket)")

    # G Vorabdatei und README dieses Ordners (nicht im Paket): keine Ergebniszahl außerhalb von Prüfsummen und Seeds
    for name in ("VORAB-N.md", "README.md"):
        p = ARBEIT / name
        if not p.exists():
            befunde.append(f"{name} fehlt")
            continue
        text = p.read_text(encoding="utf-8")
        text = re.sub(r"\b(?=[0-9a-f]*[a-f])[0-9a-f]{7,64}\b", " ", text)  # Hex-Prüfsummen und Commit-Kennungen
        text = re.sub(r"\b\d{30,}\b", " ", text)  # Seeds
        for t in suche(text):
            befunde.append(f"Ergebniszahl in {name}: {t['wert']} ({t['herkunft']}) … {t['kontext']} …")

    ergebnis = {
        "bestanden": not befunde,
        "dateien": len(dateien),
        "protokolle": len(protokolle),
        "bytes": sum((EINGANG / d).stat().st_size for d in dateien),
        "gepruefte_ergebniszahlen": len(werte),
        "gepruefte_textformen": len(muster),
        "befunde": befunde,
        "information": info,
        "zahlentreffer_in_originaldateien": {k: v[:20] for k, v in zahl_treffer.items() if k not in SELBST_GESCHRIEBEN},
        "manifest_sha256": sha(EINGANG / "MANIFEST.sha256"),
    }
    (ARBEIT / "pruefung").mkdir(exist_ok=True)
    (ARBEIT / "pruefung/LECKPRUEFUNG.json").write_text(json.dumps(ergebnis, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: ergebnis[k] for k in ("bestanden", "dateien", "protokolle", "bytes", "gepruefte_ergebniszahlen", "gepruefte_textformen", "manifest_sha256")}, ensure_ascii=False))
    for b in befunde[:40]:
        print("BEFUND", b)
    for i_ in info:
        print("INFO", i_)
    return 0 if not befunde else 1


if __name__ == "__main__":
    sys.exit(main())
