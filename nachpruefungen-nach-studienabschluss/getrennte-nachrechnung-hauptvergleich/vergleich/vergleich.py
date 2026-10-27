#!/usr/bin/env python3
"""Vergleich der festgeschriebenen Ausgabe der getrennten Nachrechnung N.

Liest die Ausgabe der Implementierung (Ordner mit AUSGABE.sha256, laeufe.jsonl, aggregat.json),
prüft zuerst die Festschreibung und die Prüfsummen der Sollwertdateien und vergleicht dann
  1. jeden Lauf mit P-ROWS.json,
  2. die Kennzahlen der Ausgabe mit ihren eigenen Läufen (innere Stimmigkeit),
  3. die Kennzahlen, Grenzen, das Urteil und die Lesart mit P-ANALYSIS.json,
  4. dieselben Größen mit den Zahlen der Arbeit, Abschnitt 6.3 (rev25),
nach den Toleranzen der Vorabfestlegung (VORAB-N.md, Abschnitt 7). Jede Abweichung wird mit
Lauf bzw. Größe, Feld und beiden Werten gemeldet. Eingeordnet (Klassen a bis d) wird hier nicht.

Aufruf:
  python3 -I vergleich.py --ausgabe <ordner> --bericht <ordner> --ausgabe-sha <sha256 von AUSGABE.sha256>
Exit: 0 keine Meldung, 1 Meldungen, 2 Vorbedingung verletzt (Festschreibung oder Sollwertdatei).
Keine Netzzugriffe, keine Modellaufrufe, nur Standardbibliothek.
"""
import argparse
import csv
import hashlib
import json
import math
import re
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, getcontext
from pathlib import Path, PurePosixPath

getcontext().prec = 60

REPO = Path("/Users/jannikhiller/Desktop/ai operations/Studium OS/communication-pruning-framework")
ARBEIT = Path(__file__).resolve().parent.parent
EINGANG = ARBEIT / "eingang"
P_ROWS_STD = REPO / "ergebnisse/hauptvergleich/P-ROWS.json"
P_ANALYSIS_STD = REPO / "ergebnisse/hauptvergleich/P-ANALYSIS.json"
EINGANG_MANIFEST_SHA = "4a7ef3f82031fc0d04bdb0f80b4cb1ca8ade16b4dfbb8bcb778de83f06b2f19f"
SOLL_SHA = {
    "P-ROWS.json": "f22b12017abe4f93a89fcb29dd55728e78c31392bcc8895ebbcf47672c00fcd0",
    "P-ANALYSIS.json": "fc4be29676749d7611d7c3f0d11e912193e4588609acb5d4734a15c387dcba65",
}

# Toleranzen der Vorabfestlegung N, Abschnitt 7
TOL_F1_ABS = 1e-9
TOL_REL = 1e-9
TOL_GRENZE_DIFFERENZ = 0.0005   # 0,05 Prozentpunkte, Qualitätsdifferenz als Anteil
TOL_GRENZE_VERHAELTNIS = 0.001

SEEDS = {"S1": "142211229048427227715370149966446052232", "S2": "25293223086774291045588755186233620233"}
B = 19999
N_PAARE = 9040
N_LAEUFE = 18080

# Zahlen der Arbeit, Abschnitt 6.3 (rev25, thesis-rev25-bereinigt.md, SHA-256 023df612…)
ARBEIT_ZAEHLUNGEN = {
    "n_paare": (9040, "[N1006]"),
    "paarzahlen.gleich": (8041, "[N1006]"),
    "paarzahlen.nur_f": (690, "[N1006]"),
    "paarzahlen.nur_q": (309, "[N1006]"),
    "saldo_zugunsten_f": (381, "[N1006]"),
    "arme.Q.modellausfaelle": (228, "[N1015]"),
    "arme.F.modellausfaelle": (224, "[N1015]"),
}
# Größe: (gedruckter Wert, Skalierung, Stellen, Kennung)
ARBEIT_PUNKTWERTE = {
    "arme.Q.anteil_exakt_richtig": ("31.99", 100, 2, "[N1006]"),
    "arme.F.anteil_exakt_richtig": ("36.21", 100, 2, "[N1006]"),
    "qualitaetsdifferenz.schaetzer": ("-4.21", 100, 2, "[N1006], [N1011]"),
    "kostenverhaeltnis.schaetzer": ("1.169", 1, 3, "[N1013]"),
    "arme.Q.kosten_summe_usd": ("14.44", 1, 2, "[N1013]"),
    "arme.F.kosten_summe_usd": ("12.35", 1, 2, "[N1013]"),
    "arme.Q.f1_mittel": ("0.436", 1, 3, "[N1015]"),
    "arme.F.f1_mittel": ("0.481", 1, 3, "[N1015]"),
}
# Grenze: (gedruckter Wert, Skalierung, Stellen, Toleranz in Originaleinheit, Kennung)
ARBEIT_GRENZEN = {
    ("differenz", "untere"): ("-4.90", 100, 2, TOL_GRENZE_DIFFERENZ, "[N1011]"),
    ("differenz", "obere"): ("-3.54", 100, 2, TOL_GRENZE_DIFFERENZ, "[N1011]"),
    ("verhaeltnis", "untere"): ("1.162", 1, 3, TOL_GRENZE_VERHAELTNIS, "[N1013]"),
    ("verhaeltnis", "obere"): ("1.176", 1, 3, TOL_GRENZE_VERHAELTNIS, "[N1013]"),
}
ARBEIT_LESART = {
    "regel_erfuellt": (False, "[N1005]"),
    "qualitaet_erhalten_3pp": (False, "[N1011]"),
    "qualitaetsverlust_belegt": (True, "[N1011]"),
    "verlust_ueber_3pp_belegt": (True, "[N1011]"),
    "ersparnis_10pct_belegt": (False, "[N1013]"),
    "ersparnis_10pct_ausgeschlossen": (True, "[N1013]"),
    "mehrkosten_belegt": (True, "[N1013]"),
}
# Lesart der Ausgabe -> Aussage in P-ANALYSIS.json (report.primary.statements)
LESART_ZU_PA = {
    "qualitaet_erhalten_3pp": "quality_preserved_3pp",
    "qualitaetsverlust_belegt": "quality_loss",
    "verlust_ueber_3pp_belegt": "quality_loss_beyond_3pp",
    "ersparnis_10pct_belegt": "cost_saving_at_least_10pct",
    "ersparnis_10pct_ausgeschlossen": "cost_saving_below_10pct",
    "mehrkosten_belegt": "cost_increase",
}
LESART_FELDER = ["qualitaet_erhalten_3pp", "ersparnis_10pct_belegt", "qualitaetsverlust_belegt",
                 "verlust_ueber_3pp_belegt", "ersparnis_10pct_ausgeschlossen", "mehrkosten_belegt",
                 "grenze_nicht_berechenbar", "offen_ohne_nachteil"]
ZEILEN_REIHENFOLGE = ["[N0556]", "[N0558]", "[N0560]", "[N0562]", "[N0564]", "[N0566]", "[N0568]"]


class Vorbedingung(Exception):
    pass


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sicherer_relpfad(rel):
    if not rel or "\\" in rel or "\x00" in rel or re.match(r"^[A-Za-z]:", rel):
        raise Vorbedingung(f"unsicherer Manifestpfad: {rel!r}")
    p = PurePosixPath(rel)
    if p.is_absolute() or p.as_posix() != rel or any(x in ("", ".", "..") for x in rel.split("/")):
        raise Vorbedingung(f"unsicherer Manifestpfad: {rel!r}")
    return p


def lese_manifest(pfad, rolle):
    eintraege = {}
    try:
        zeilen = Path(pfad).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as e:
        raise Vorbedingung(f"{rolle} nicht lesbar: {e}") from e
    for nr, zeile in enumerate(zeilen, 1):
        if not zeile.strip():
            continue
        s, trenner, rel = zeile.partition("  ")
        if not trenner or not re.fullmatch(r"[0-9a-fA-F]{64}", s):
            raise Vorbedingung(f"unlesbare Zeile {nr} in {rolle}: {zeile!r}")
        sicherer_relpfad(rel)
        if rel == "AUSGABE.sha256":
            raise Vorbedingung(f"{rolle} darf sich nicht selbst aufführen")
        if rel in eintraege:
            raise Vorbedingung(f"doppelter Manifestpfad in {rolle}: {rel}")
        eintraege[rel] = s.lower()
    return eintraege


def js(x):
    """Wert für den Bericht (JSON-fähig, ohne Genauigkeitsverlust)."""
    if isinstance(x, Decimal):
        return format(x, "f")
    if isinstance(x, float):
        if math.isnan(x):
            return "NaN"
        if math.isinf(x):
            return "Infinity" if x > 0 else "-Infinity"
    return x


def zahl(x):
    """float aus Zahl oder Zeichenkette 'Infinity'/'-Infinity'; None bei Unlesbarem."""
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        if x in ("Infinity", "+Infinity"):
            return math.inf
        if x == "-Infinity":
            return -math.inf
        try:
            return float(x)
        except ValueError:
            return None
    return None


def dez(x):
    if isinstance(x, bool) or x is None:
        return None
    try:
        d = Decimal(str(x))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def rel_gleich(a, b, tol=TOL_REL):
    if a is None or b is None:
        return False
    if isinstance(a, Decimal) or isinstance(b, Decimal):
        a, b = Decimal(str(a)), Decimal(str(b))
        if a == b:
            return True
        return abs(a - b) <= Decimal(str(tol)) * max(abs(a), abs(b))
    if math.isinf(a) or math.isinf(b) or math.isnan(a) or math.isnan(b):
        return a == b
    if a == b:
        return True
    return abs(a - b) <= tol * max(abs(a), abs(b))


def gerundet(wert, skala, stellen):
    d = Decimal(repr(wert)) if isinstance(wert, float) else Decimal(str(wert))
    return (d * skala).quantize(Decimal(1).scaleb(-stellen), rounding=ROUND_HALF_UP)


def hole(d, pfad):
    for teil in pfad.split("."):
        if not isinstance(d, dict) or teil not in d:
            return None
        d = d[teil]
    return d


class Bericht:
    def __init__(self):
        self.meldungen = []
        self.info = []
        self.vergleich_arbeit = []

    def melde(self, ebene, groesse, feld, n_wert, soll_wert, quelle, regel, lauf=None):
        self.meldungen.append({"ebene": ebene, "lauf": lauf, "groesse": groesse, "feld": feld,
                               "n_wert": js(n_wert), "soll_wert": js(soll_wert), "quelle": quelle, "regel": regel})


# ---------------------------------------------------------------- Festschreibung und Sollwerte

def lade_ausgabe(ordner, erwartete_sha):
    ordner = Path(ordner)
    manifest = ordner / "AUSGABE.sha256"
    if ordner.is_symlink() or not ordner.is_dir():
        raise Vorbedingung("Ausgabeordner fehlt, ist kein Ordner oder ist ein symbolischer Link")
    if not manifest.is_file() or manifest.is_symlink():
        raise Vorbedingung("AUSGABE.sha256 fehlt: Ausgabe ist nicht festgeschrieben")
    manifest_sha = sha(manifest)
    if not re.fullmatch(r"[0-9a-fA-F]{64}", erwartete_sha or ""):
        raise Vorbedingung("--ausgabe-sha fehlt oder ist keine SHA-256-Prüfsumme")
    if manifest_sha != erwartete_sha.lower():
        raise Vorbedingung(f"SHA-256 von AUSGABE.sha256 ist {manifest_sha}, festgeschrieben war {erwartete_sha}")
    gelistet = lese_manifest(manifest, "AUSGABE.sha256")
    for pflicht in ("laeufe.jsonl", "aggregat.json"):
        if pflicht not in gelistet:
            raise Vorbedingung(f"{pflicht} ist nicht in AUSGABE.sha256 festgeschrieben")
    if not gelistet:
        raise Vorbedingung("AUSGABE.sha256 enthält keine Ausgabedateien")
    root = ordner.resolve()
    for rel, s in gelistet.items():
        p = ordner.joinpath(*sicherer_relpfad(rel).parts)
        if p.is_symlink() or not p.is_file():
            raise Vorbedingung(f"festgeschriebene Datei fehlt oder ist unsicher: {rel}")
        try:
            p.resolve(strict=True).relative_to(root)
        except (OSError, ValueError):
            raise Vorbedingung(f"festgeschriebener Pfad verlässt den Ausgabeordner: {rel}")
        if sha(p) != s:
            raise Vorbedingung(f"Datei nach der Festschreibung verändert: {rel}")
    vorhanden = set()
    for p in ordner.rglob("*"):
        if p.is_symlink():
            raise Vorbedingung(f"symbolischer Link im Ausgabeordner ist unzulässig: {p.relative_to(ordner).as_posix()}")
        if p.is_file():
            vorhanden.add(p.relative_to(ordner).as_posix())
    nicht_gelistet = sorted(vorhanden - set(gelistet) - {"AUSGABE.sha256"})
    if nicht_gelistet:
        raise Vorbedingung(f"nicht festgeschriebene Datei(en) in der Ausgabe: {', '.join(nicht_gelistet[:20])}")
    laeufe = []
    with open(ordner / "laeufe.jsonl", encoding="utf-8") as f:
        for nr, zeile in enumerate(f, 1):
            if zeile.strip():
                try:
                    laeufe.append(json.loads(zeile))
                except json.JSONDecodeError as e:
                    raise Vorbedingung(f"laeufe.jsonl Zeile {nr} unlesbar: {e}")
    aggregat = json.loads((ordner / "aggregat.json").read_text(encoding="utf-8"))
    return laeufe, aggregat, manifest_sha, nicht_gelistet


def lade_rohantworten():
    """Lädt Endantworten aus den durch Laufliste und Eingangsmanifest gebundenen Protokollen."""
    manifest = EINGANG / "MANIFEST.sha256"
    ist_manifest_sha = sha(manifest)
    if ist_manifest_sha != EINGANG_MANIFEST_SHA:
        raise Vorbedingung(f"eingang/MANIFEST.sha256: SHA-256 {ist_manifest_sha} statt Vorabbindung {EINGANG_MANIFEST_SHA}")
    gebunden = lese_manifest(manifest, "eingang/MANIFEST.sha256")
    laufliste = EINGANG / "laufliste.tsv"
    if "laufliste.tsv" not in gebunden or sha(laufliste) != gebunden["laufliste.tsv"]:
        raise Vorbedingung("eingang/laufliste.tsv fehlt im Manifest oder stimmt nicht mit ihm überein")
    antworten = {}
    try:
        with laufliste.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            erwartet = ["paarindex", "arm", "block_id", "musique_id", "lauf_kennung", "pfad"]
            if reader.fieldnames != erwartet:
                raise Vorbedingung(f"eingang/laufliste.tsv: unerwartete Spalten {reader.fieldnames}")
            for r in reader:
                kennung, rel = r["lauf_kennung"], r["pfad"]
                sicherer_relpfad(rel)
                if kennung in antworten:
                    raise Vorbedingung(f"doppelte Lauf-Kennung in eingang/laufliste.tsv: {kennung}")
                if rel not in gebunden:
                    raise Vorbedingung(f"Rohprotokoll nicht im Eingangsmanifest festgeschrieben: {rel}")
                p = EINGANG.joinpath(*sicherer_relpfad(rel).parts)
                if p.is_symlink() or not p.is_file() or sha(p) != gebunden[rel]:
                    raise Vorbedingung(f"Rohprotokoll fehlt oder weicht vom Eingangsmanifest ab: {rel}")
                finished = []
                protokoll_run_id = None
                try:
                    with p.open(encoding="utf-8") as prot:
                        for line_nr, line in enumerate(prot, 1):
                            record = json.loads(line)
                            rid = record.get("run_id")
                            if protokoll_run_id is None:
                                protokoll_run_id = rid
                            elif rid != protokoll_run_id:
                                raise Vorbedingung(f"{rel}: run_id wechselt in Zeile {line_nr}")
                            payload = record.get("payload")
                            if isinstance(payload, dict) and payload.get("kind") == "finished":
                                finished.append(payload)
                except (OSError, UnicodeError, json.JSONDecodeError) as e:
                    raise Vorbedingung(f"Rohprotokoll {rel} unlesbar: {e}") from e
                if len(finished) > 1:
                    raise Vorbedingung(f"{rel}: mehrere finished-Nutzlasten")
                if finished and "answer" not in finished[0]:
                    raise Vorbedingung(f"{rel}: finished-Nutzlast enthält kein answer-Feld")
                if not protokoll_run_id or not protokoll_run_id.endswith(":" + kennung):
                    raise Vorbedingung(f"{rel}: run_id passt nicht zur Lauf-Kennung {kennung}")
                antworten[kennung] = {
                    "endantwort": finished[0]["answer"] if finished else None,
                    "run_id": protokoll_run_id,
                    "pfad": rel,
                }
    except OSError as e:
        raise Vorbedingung(f"eingang/laufliste.tsv nicht lesbar: {e}") from e
    if len(antworten) != N_LAEUFE:
        raise Vorbedingung(f"eingang/laufliste.tsv enthält {len(antworten)} statt {N_LAEUFE} eindeutige Läufe")
    return antworten


def lade_sollwerte(p_rows, p_analysis, pruefe_sha=True):
    for p, name in ((p_rows, "P-ROWS.json"), (p_analysis, "P-ANALYSIS.json")):
        if pruefe_sha and sha(p) != SOLL_SHA[name]:
            raise Vorbedingung(f"{name}: SHA-256 {sha(p)} statt {SOLL_SHA[name]} (Vorabfestlegung)")
    return json.load(open(p_rows, encoding="utf-8")), json.load(open(p_analysis, encoding="utf-8"))


# ---------------------------------------------------------------- 1 Läufe gegen P-ROWS

def vergleiche_laeufe(laeufe, prows, rohantworten, b):
    q = "P-ROWS.json"
    soll = {}
    for r in prows:
        soll[r["slot_id"]] = r
    ist = {}
    for r in laeufe:
        k = r.get("lauf_kennung")
        if k in ist:
            b.melde("lauf", "laufmenge", "lauf_kennung", k, "einmalig", "Ausgabe", "jede Lauf-Kennung genau einmal", lauf=k)
            continue
        ist[k] = r
    for k in sorted(set(soll) - set(ist)):
        b.melde("lauf", "laufmenge", "vorhanden", None, "vorhanden", q, "jeder Lauf aus P-ROWS in der Ausgabe", lauf=k)
    for k in sorted(set(ist) - set(soll)):
        b.melde("lauf", "laufmenge", "vorhanden", "vorhanden", None, q, "kein Lauf außerhalb von P-ROWS", lauf=k)
    for k in sorted(set(ist) & set(soll)):
        n, s = ist[k], soll[k]
        roh = rohantworten.get(k)
        if n.get("paarindex") != s["draw_index"] or isinstance(n.get("paarindex"), bool):
            b.melde("lauf", "lauf", "paarindex", n.get("paarindex"), s["draw_index"], q, "exakt (draw_index)", lauf=k)
        if n.get("arm") != s["arm"]:
            b.melde("lauf", "lauf", "arm", n.get("arm"), s["arm"], q, "exakt", lauf=k)
        if n.get("run_id") != s["run_id"]:
            b.melde("lauf", "lauf", "run_id", n.get("run_id"), s["run_id"], q, "exakt (Protokollkopf gegen Zeile)", lauf=k)
        if roh is not None:
            if roh["run_id"] != s["run_id"]:
                b.melde("protokoll", "lauf", "run_id", roh["run_id"], s["run_id"], roh["pfad"],
                        "Rohprotokoll aus gebundener Laufliste muss zur Sollzeile passen", lauf=k)
            if "endantwort" not in n:
                b.melde("lauf", "lauf", "endantwort", "Feld fehlt", roh["endantwort"], roh["pfad"],
                        "Feld vorhanden und exakt gleich finished.answer", lauf=k)
            elif n["endantwort"] != roh["endantwort"]:
                b.melde("lauf", "lauf", "endantwort", n["endantwort"], roh["endantwort"], roh["pfad"],
                        "exakt gleich finished.answer", lauf=k)
        else:
            b.melde("protokoll", "lauf", "endantwort", None, "Rohprotokoll vorhanden", "eingang/laufliste.tsv",
                    "jede Lauf-Kennung muss auf ein gebundenes Rohprotokoll verweisen", lauf=k)
        if n.get("status") != s["status"]:
            b.melde("lauf", "lauf", "status", n.get("status"), s["status"], q, "exakt", lauf=k)
        em = n.get("exact_match")
        if isinstance(em, bool) or not isinstance(em, (int, float)) or float(em) != float(s["em"]):
            b.melde("lauf", "lauf", "exact_match", em, s["em"], q, "exakt", lauf=k)
        f1 = zahl(n.get("f1"))
        if f1 is None or isinstance(n.get("f1"), str) or not abs(f1 - s["f1"]) <= TOL_F1_ABS:
            b.melde("lauf", "lauf", "f1", n.get("f1"), s["f1"], q, f"|Abweichung| ≤ {TOL_F1_ABS}", lauf=k)
        ga = n.get("gestartete_aufrufe")
        if isinstance(ga, bool) or not isinstance(ga, int) or ga != s["call_count"]:
            b.melde("lauf", "lauf", "gestartete_aufrufe", ga, s["call_count"], q, "exakt (call_count)", lauf=k)
        kn, ks = dez(n.get("bekannte_kosten_usd")) if isinstance(n.get("bekannte_kosten_usd"), str) else None, Decimal(s["cost_usd"])
        if kn is None or kn != ks:
            b.melde("lauf", "lauf", "bekannte_kosten_usd", n.get("bekannte_kosten_usd"), s["cost_usd"], q, "exakt als Dezimalzahl", lauf=k)
        # Plausibilität (keine Sollwerte in P-ROWS)
        if n.get("unbekannte_betraege") != 0:
            b.melde("plausibilitaet", "lauf", "unbekannte_betraege", n.get("unbekannte_betraege"), 0, "contract.md (F-01)", "Studienprotokolle ohne unbekannte Beträge erwartet", lauf=k)
        if n.get("plausibilitaet"):
            b.melde("plausibilitaet", "lauf", "plausibilitaet", n.get("plausibilitaet"), [], "AUFTRAG 3.1", "keine Befunde erwartet", lauf=k)
        if n.get("status") == "nicht_nachrechenbar":
            b.melde("vollstaendigkeit", "lauf", "status", "nicht_nachrechenbar", s["status"], q, "alle Läufe nachrechenbar", lauf=k)


# ---------------------------------------------------------------- 2 innere Stimmigkeit

def stabw(werte):
    n = len(werte)
    m = math.fsum(werte) / n
    return math.sqrt(math.fsum((x - m) ** 2 for x in werte) / (n - 1))


def aus_laeufen(laeufe):
    """Kennzahlen nach AUFTRAG 4.1 bis 4.3 aus den Läufen der Ausgabe (unabhängig vom Aggregat der Ausgabe)."""
    paare = {}
    for r in laeufe:
        if r.get("status") in ("ok", "model_failure"):
            paare.setdefault(r.get("paarindex"), {})[r.get("arm")] = r
    voll = {i: p for i, p in paare.items() if "Q" in p and "F" in p}
    idx = sorted(voll)
    n = len(idx)
    if n < 2:
        return None
    em = {a: [int(voll[i][a]["exact_match"]) for i in idx] for a in "QF"}
    f1 = {a: [float(voll[i][a]["f1"]) for i in idx] for a in "QF"}
    kd = {a: [Decimal(voll[i][a]["bekannte_kosten_usd"]) for i in idx] for a in "QF"}
    kf = {a: [float(x) for x in kd[a]] for a in "QF"}
    d = [em["Q"][k] - em["F"][k] for k in range(n)]
    out = {
        "n_paare": n,
        "paarzahlen.beide_richtig": sum(1 for k in range(n) if em["Q"][k] == 1 and em["F"][k] == 1),
        "paarzahlen.beide_falsch": sum(1 for k in range(n) if em["Q"][k] == 0 and em["F"][k] == 0),
        "paarzahlen.nur_q": sum(1 for x in d if x == 1),
        "paarzahlen.nur_f": sum(1 for x in d if x == -1),
        "summe_paarwerte": sum(d),
    }
    out["paarzahlen.gleich"] = out["paarzahlen.beide_richtig"] + out["paarzahlen.beide_falsch"]
    for a in "QF":
        out[f"arme.{a}.anteil_exakt_richtig"] = sum(em[a]) / n
        out[f"arme.{a}.f1_mittel"] = math.fsum(f1[a]) / n
        out[f"arme.{a}.modellausfaelle"] = sum(1 for i in idx if voll[i][a]["status"] == "model_failure")
        out[f"arme.{a}.kosten_summe_usd"] = sum(kd[a], Decimal(0))
        out[f"arme.{a}.kosten_mittel_usd"] = out[f"arme.{a}.kosten_summe_usd"] / n
        out[f"arme.{a}.gestartete_aufrufe_summe"] = sum(voll[i][a]["gestartete_aufrufe"] for i in idx)
        out[f"arme.{a}.unbekannte_betraege"] = sum(voll[i][a]["unbekannte_betraege"] for i in idx)
    out["qualitaetsdifferenz.schaetzer"] = sum(d) / n
    out["qualitaetsdifferenz.se"] = stabw([float(x) for x in d]) / math.sqrt(n)
    rho = float(out["arme.Q.kosten_summe_usd"] / out["arme.F.kosten_summe_usd"])
    mf = math.fsum(kf["F"]) / n
    out["kostenverhaeltnis.schaetzer"] = rho
    out["kostenverhaeltnis.se"] = stabw([kf["Q"][k] - rho * kf["F"][k] for k in range(n)]) / math.sqrt(n) / mf
    out["kostenverhaeltnis.nenner_mittel"] = mf
    out["kostenverhaeltnis.nenner_se"] = stabw(kf["F"]) / math.sqrt(n)
    out["kostenverhaeltnis.nenner_quotient"] = out["kostenverhaeltnis.nenner_mittel"] / out["kostenverhaeltnis.nenner_se"]
    return out


EXAKT = {"n_paare", "paarzahlen.beide_richtig", "paarzahlen.beide_falsch", "paarzahlen.nur_q", "paarzahlen.nur_f",
         "paarzahlen.gleich", "summe_paarwerte", "arme.Q.modellausfaelle", "arme.F.modellausfaelle",
         "arme.Q.gestartete_aufrufe_summe", "arme.F.gestartete_aufrufe_summe", "arme.Q.unbekannte_betraege",
         "arme.F.unbekannte_betraege", "arme.Q.kosten_summe_usd", "arme.F.kosten_summe_usd"}


def lesart_aus_grenzen(dl, du, rl, ru, stat_d, stat_r):
    nb = stat_d != "ok" or stat_r != "ok"
    le = {
        "qualitaet_erhalten_3pp": dl > -0.03,
        "ersparnis_10pct_belegt": ru < 0.90,
        "qualitaetsverlust_belegt": du < 0,
        "verlust_ueber_3pp_belegt": du < -0.03,
        "ersparnis_10pct_ausgeschlossen": rl > 0.90,
        "mehrkosten_belegt": rl > 1,
        "grenze_nicht_berechenbar": nb,
    }
    regel = le["qualitaet_erhalten_3pp"] and le["ersparnis_10pct_belegt"]
    le["offen_ohne_nachteil"] = (not regel and not le["qualitaetsverlust_belegt"]
                                 and not le["ersparnis_10pct_ausgeschlossen"] and not le["mehrkosten_belegt"] and not nb)
    zeilen = []
    if regel:
        zeilen.append("[N0556]")
    if le["offen_ohne_nachteil"]:
        zeilen.append("[N0558]")
    for feld, z in (("qualitaetsverlust_belegt", "[N0560]"), ("verlust_ueber_3pp_belegt", "[N0562]"),
                    ("ersparnis_10pct_ausgeschlossen", "[N0564]"), ("mehrkosten_belegt", "[N0566]"),
                    ("grenze_nicht_berechenbar", "[N0568]")):
        if le[feld]:
            zeilen.append(z)
    return regel, le, zeilen


def bootstrap_eintraege(agg, b, quelle_ebene="intern"):
    eintraege = {}
    liste = agg.get("bootstrap")
    if not isinstance(liste, list):
        b.melde(quelle_ebene, "bootstrap", "bootstrap", liste, "Liste mit S1 und S2", "AUFTRAG 5.2", "Format")
        return eintraege
    for e in liste:
        if isinstance(e, dict) and e.get("name") in SEEDS:
            eintraege[e["name"]] = e
    for name, seed in SEEDS.items():
        e = eintraege.get(name)
        if e is None:
            b.melde("intern", f"bootstrap.{name}", "vorhanden", None, "vorhanden", "AUFTRAG 4.4", "beide Seeds gerechnet")
            continue
        if str(e.get("seed")) != seed:
            b.melde("intern", f"bootstrap.{name}", "seed", e.get("seed"), seed, "AUFTRAG 4.4", "exakt")
        if e.get("wiederholungen") != B:
            b.melde("intern", f"bootstrap.{name}", "wiederholungen", e.get("wiederholungen"), B, "AUFTRAG 4.4", "exakt")
        if name == "S1" and e.get("seedregel_reproduziert_s1") is not True:
            b.melde("intern", "bootstrap.S1", "seedregel_reproduziert_s1", e.get("seedregel_reproduziert_s1"), True, "AUFTRAG 4.4", "Seedregel ergibt S1")
    return eintraege


def innere_stimmigkeit(laeufe, agg, b):
    q = "eigene Läufe der Ausgabe"
    if len(laeufe) != N_LAEUFE:
        b.melde("vollstaendigkeit", "laeufe", "anzahl", len(laeufe), N_LAEUFE, "Vorabfestlegung", "alle 18.080 Läufe")
    if agg.get("vollstaendig") is not True:
        b.melde("vollstaendigkeit", "aggregat", "vollstaendig", agg.get("vollstaendig"), True, "Vorabfestlegung", "Grenzen nur bei vollständiger Rechnung nachgerechnet")
    try:
        r = aus_laeufen(laeufe)
    except (KeyError, TypeError, ValueError, InvalidOperation) as e:
        b.melde("intern", "aggregat", "neuberechnung", f"nicht möglich: {e}", "möglich", q, "Läufe im Format 5.1")
        return
    if r is None:
        b.melde("intern", "aggregat", "neuberechnung", "weniger als zwei vollständige Paare", "9.040 Paare", q, "Format 5.1")
        return
    for groesse, wert in r.items():
        ist = hole(agg, groesse)
        if groesse in EXAKT:
            ok = (dez(ist) == wert) if isinstance(wert, Decimal) else (ist == wert and not isinstance(ist, bool))
            regel = "exakt"
        elif isinstance(wert, Decimal):
            ok = dez(ist) is not None and rel_gleich(dez(ist), wert)
            regel = f"relativ ≤ {TOL_REL}"
        else:
            ok = rel_gleich(zahl(ist), wert)
            regel = f"relativ ≤ {TOL_REL}"
        if not ok:
            b.melde("intern", groesse, "wert", ist, wert, q, regel)
    if agg.get("n_laeufe") != len(laeufe):
        b.melde("intern", "n_laeufe", "wert", agg.get("n_laeufe"), len(laeufe), q, "exakt")
    for name, e in bootstrap_eintraege(agg, b).items():
        try:
            dl, du = zahl(e["differenz"]["untere"]), zahl(e["differenz"]["obere"])
            rl, ru = zahl(e["verhaeltnis"]["untere"]), zahl(e["verhaeltnis"]["obere"])
            sd, sr = e["differenz"]["status"], e["verhaeltnis"]["status"]
        except (KeyError, TypeError):
            b.melde("intern", f"bootstrap.{name}", "format", "unvollständig", "AUFTRAG 5.2", "AUFTRAG 5.2", "Format")
            continue
        if None in (dl, du, rl, ru):
            b.melde("intern", f"bootstrap.{name}", "grenzen", [dl, du, rl, ru], "vier Zahlen", "AUFTRAG 5.2", "Format")
            continue
        regel, le, zeilen = lesart_aus_grenzen(dl, du, rl, ru, sd, sr)
        if e.get("regel_erfuellt") is not regel:
            b.melde("intern", f"bootstrap.{name}", "regel_erfuellt", e.get("regel_erfuellt"), regel, "eigene Grenzen, AUFTRAG 4.5", "identisch")
        for feld in LESART_FELDER:
            if hole(e, f"lesart.{feld}") is not le[feld]:
                b.melde("intern", f"bootstrap.{name}", f"lesart.{feld}", hole(e, f"lesart.{feld}"), le[feld], "eigene Grenzen, AUFTRAG 4.6", "identisch")
        if e.get("zeilen_tabelle_4_5") != zeilen:
            b.melde("intern", f"bootstrap.{name}", "zeilen_tabelle_4_5", e.get("zeilen_tabelle_4_5"), zeilen, "eigene Grenzen, AUFTRAG 4.6", "identisch")


# ---------------------------------------------------------------- 3 gegen P-ANALYSIS

def gegen_panalysis(agg, pa, b, abstaende):
    q = "P-ANALYSIS.json"
    rep = pa["report"]
    kern = rep["primary"]["kernel"]["endpoints"]
    if agg.get("n_paare") != rep["n"]:
        b.melde("p-analysis", "n_paare", "wert", agg.get("n_paare"), rep["n"], q, "exakt")
    for a in "QF":
        est, desc = rep["estimates"][a], rep["descriptive_costs"]["arms"][a]
        pr = [(f"arme.{a}.anteil_exakt_richtig", est["em"], "rel"),
              (f"arme.{a}.f1_mittel", est["f1"], "rel"),
              (f"arme.{a}.modellausfaelle", est["model_failures"], "exakt"),
              (f"arme.{a}.kosten_summe_usd", Decimal(desc["total"]), "dez_exakt"),
              (f"arme.{a}.kosten_mittel_usd", Decimal(est["mean_cost_usd"]), "dez_rel")]
        for groesse, soll, art in pr:
            ist = hole(agg, groesse)
            if art == "rel":
                ok, regel = rel_gleich(zahl(ist), soll), f"relativ ≤ {TOL_REL}"
            elif art == "exakt":
                ok, regel = (ist == soll and not isinstance(ist, bool)), "exakt"
            elif art == "dez_exakt":
                ok, regel = dez(ist) == soll, "exakt als Dezimalzahl"
            else:
                ok, regel = dez(ist) is not None and rel_gleich(dez(ist), soll), f"relativ ≤ {TOL_REL}"
            if not ok:
                b.melde("p-analysis", groesse, "wert", ist, soll, q, regel)
    for groesse, ep in (("qualitaetsdifferenz", "P-D"), ("kostenverhaeltnis", "P-C")):
        for feld, pf in (("schaetzer", "estimate"), ("se", "se")):
            ist = hole(agg, f"{groesse}.{feld}")
            if not rel_gleich(zahl(ist), kern[ep][pf]):
                b.melde("p-analysis", f"{groesse}.{feld}", "wert", ist, kern[ep][pf], q, f"relativ ≤ {TOL_REL}")
    statements = rep["primary"]["statements"]
    for name, e in bootstrap_eintraege(agg, Bericht()).items():
        for teil, ep, tol in (("differenz", "P-D", TOL_GRENZE_DIFFERENZ), ("verhaeltnis", "P-C", TOL_GRENZE_VERHAELTNIS)):
            for seite, pf in (("untere", "lower"), ("obere", "upper")):
                ist = zahl(hole(e, f"{teil}.{seite}"))
                soll = kern[ep][pf]
                abst = abs(ist - soll) if ist is not None and math.isfinite(ist) else math.inf
                abstaende.setdefault(f"{teil}.{seite}", []).append({"seed": name, "n_wert": js(ist), "soll": soll, "abstand": js(abst)})
                if not abst <= tol:
                    b.melde("p-analysis", f"bootstrap.{name}.{teil}.{seite}", "grenze", ist, soll, q, f"|Abweichung| ≤ {tol}")
            st_ist, st_soll = hole(e, f"{teil}.status"), kern[ep]["status"]
            if (st_ist == "ok") != (st_soll == "ok"):
                b.melde("p-analysis", f"bootstrap.{name}.{teil}.status", "status", st_ist, st_soll, q, "identisch (ok gegen nicht ok)")
            uw_ist, uw_soll = hole(e, f"{teil}.undefinierte_wiederholungen"), kern[ep]["undefined_resamples"]
            if (uw_ist == 0) != (uw_soll == 0):
                b.melde("p-analysis", f"bootstrap.{name}.{teil}.undefinierte_wiederholungen", "anzahl", uw_ist, uw_soll, q, "beide null oder beide nicht null")
        for feld, aussage in LESART_ZU_PA.items():
            soll = statements[aussage] == "established"
            if hole(e, f"lesart.{feld}") is not soll:
                b.melde("p-analysis", f"bootstrap.{name}.lesart.{feld}", "aussage", hole(e, f"lesart.{feld}"), statements[aussage], q, "identisch")
        if e.get("regel_erfuellt") is not rep["primary"]["joint_positive"]:
            b.melde("p-analysis", f"bootstrap.{name}.regel_erfuellt", "urteil", e.get("regel_erfuellt"), rep["primary"]["joint_positive"], q, "identisch")


# ---------------------------------------------------------------- 4 gegen die Arbeit (6.3)

def gegen_arbeit(agg, b):
    q = "Arbeit rev25, 6.3"
    werte = {
        "n_paare": agg.get("n_paare"),
        "paarzahlen.gleich": hole(agg, "paarzahlen.gleich"),
        "paarzahlen.nur_f": hole(agg, "paarzahlen.nur_f"),
        "paarzahlen.nur_q": hole(agg, "paarzahlen.nur_q"),
        "saldo_zugunsten_f": (-agg["summe_paarwerte"]) if isinstance(agg.get("summe_paarwerte"), int) else None,
        "arme.Q.modellausfaelle": hole(agg, "arme.Q.modellausfaelle"),
        "arme.F.modellausfaelle": hole(agg, "arme.F.modellausfaelle"),
    }
    for groesse, (soll, kennung) in ARBEIT_ZAEHLUNGEN.items():
        if werte[groesse] != soll:
            b.melde("arbeit", groesse, "wert", werte[groesse], soll, f"{q} {kennung}", "exakt")
    for groesse, (gedruckt, skala, stellen, kennung) in ARBEIT_PUNKTWERTE.items():
        ist = hole(agg, groesse)
        if "kosten_summe" in groesse:
            ist_d = dez(ist)
        else:
            ist_d = zahl(ist)
        if ist_d is None:
            b.vergleich_arbeit.append({"groesse": groesse, "quelle": kennung, "soll_gedruckt": gedruckt,
                                       "nachrechnung_ungerundet": js(ist), "nachrechnung_gerundet": None,
                                       "stellen": stellen, "toleranz_pruefung": "nicht festgelegt",
                                       "rundung_pruefung": "nicht bestanden"})
            b.melde("arbeit", groesse, "gedruckt", ist, gedruckt, f"{q} {kennung}", f"auf {stellen} Stellen gleich")
            continue
        r = gerundet(ist_d, skala, stellen)
        ungerundet = (ist_d if isinstance(ist_d, Decimal) else Decimal(repr(ist_d))) * Decimal(str(skala))
        rundung_ok = r == Decimal(gedruckt)
        b.vergleich_arbeit.append({"groesse": groesse, "quelle": kennung, "soll_gedruckt": gedruckt,
                                   "nachrechnung_ungerundet": format(ungerundet, "f"),
                                   "nachrechnung_gerundet": format(r, "f"), "stellen": stellen,
                                   "toleranz_pruefung": "nicht festgelegt",
                                   "rundung_pruefung": "bestanden" if rundung_ok else "nicht bestanden"})
        if r != Decimal(gedruckt):
            b.melde("arbeit", groesse, "rundung", {"ungerundet": format(ungerundet, "f"), "gerundet": format(r, "f")},
                    gedruckt, f"{q} {kennung}", f"kaufmännisch auf {stellen} Stellen gerundet, dann exakt verglichen")
    for name, e in bootstrap_eintraege(agg, Bericht()).items():
        for (teil, seite), (gedruckt, skala, stellen, tol, kennung) in ARBEIT_GRENZEN.items():
            ist = zahl(hole(e, f"{teil}.{seite}"))
            groesse = f"bootstrap.{name}.{teil}.{seite}"
            soll = Decimal(gedruckt)
            if ist is None or not math.isfinite(ist):
                b.vergleich_arbeit.append({"groesse": groesse, "quelle": kennung, "soll_gedruckt": gedruckt,
                                           "nachrechnung_ungerundet": js(ist), "nachrechnung_gerundet": None,
                                           "stellen": stellen, "toleranz": tol, "toleranz_pruefung": "nicht bestanden",
                                           "rundung_pruefung": "nicht bestanden"})
                b.melde("arbeit", groesse, "toleranz", {"ungerundet": js(ist), "gerundet": None}, gedruckt,
                        f"{q} {kennung}", f"Toleranz ±{tol} in Originaleinheit")
                continue
            ist_d = Decimal(repr(ist))
            ungerundet = ist_d * Decimal(str(skala))
            gerundet_wert = gerundet(ist, skala, stellen)
            toleranz_ok = abs(ist_d - soll / Decimal(str(skala))) <= Decimal(str(tol))
            rundung_ok = gerundet_wert == soll
            b.vergleich_arbeit.append({"groesse": groesse, "quelle": kennung, "soll_gedruckt": gedruckt,
                                       "nachrechnung_ungerundet": format(ungerundet, "f"),
                                       "nachrechnung_gerundet": format(gerundet_wert, "f"), "stellen": stellen,
                                       "toleranz": tol,
                                       "toleranz_pruefung": "bestanden" if toleranz_ok else "nicht bestanden",
                                       "rundung_pruefung": "bestanden" if rundung_ok else "nicht bestanden"})
            werte = {"ungerundet": format(ungerundet, "f"), "gerundet": format(gerundet_wert, "f")}
            if not toleranz_ok:
                b.melde("arbeit", groesse, "toleranz", werte, gedruckt, f"{q} {kennung}",
                        f"|Abweichung| ≤ {tol} in Originaleinheit")
            if not rundung_ok:
                b.melde("arbeit", groesse, "rundung", werte, gedruckt, f"{q} {kennung}",
                        f"kaufmännisch auf {stellen} Stellen gerundet, dann exakt verglichen")
        for feld, (soll, kennung) in ARBEIT_LESART.items():
            ist = e.get("regel_erfuellt") if feld == "regel_erfuellt" else hole(e, f"lesart.{feld}")
            if ist is not soll:
                b.melde("arbeit", f"bootstrap.{name}.{feld}", "aussage", ist, soll, f"{q} {kennung}", "identisch")


# ---------------------------------------------------------------- Bericht

def schreibe_bericht(ordner, kopf, b, abstaende):
    ordner = Path(ordner)
    ordner.mkdir(parents=True, exist_ok=True)
    nach_ebene = {}
    for m in b.meldungen:
        nach_ebene[m["ebene"]] = nach_ebene.get(m["ebene"], 0) + 1
    laeufe_mit_meldung = sorted({m["lauf"] for m in b.meldungen if m["ebene"] == "lauf" and m["lauf"]})
    max_abst = {}
    for k, v in abstaende.items():
        endl = [x for x in v if x["abstand"] != "Infinity"]
        max_abst[k] = max((x["abstand"] for x in endl), default="Infinity") if len(endl) == len(v) else "Infinity"
    ergebnis = dict(kopf)
    ergebnis.update({"meldungen_gesamt": len(b.meldungen), "meldungen_nach_ebene": nach_ebene,
                     "laeufe_mit_meldung": laeufe_mit_meldung, "groesste_grenzabweichung_ueber_seeds": max_abst,
                     "grenzabweichungen": abstaende, "vergleich_arbeit": b.vergleich_arbeit,
                     "information": b.info, "meldungen": b.meldungen})
    (ordner / "VERGLEICH-ERGEBNIS.json").write_text(json.dumps(ergebnis, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    z = [f"<!-- status: Vergleich N, maschinell | {kopf['zeitpunkt_utc']} -->", "", "# Vergleich der getrennten Nachrechnung N", "",
         "| Eingabe | SHA-256 |", "|---|---|"]
    for k, v in kopf["eingaben"].items():
        z.append(f"| {k} | `{v}` |")
    z += ["", f"Meldungen gesamt: **{len(b.meldungen)}**", ""]
    for k in ("lauf", "plausibilitaet", "vollstaendigkeit", "intern", "p-analysis", "arbeit"):
        z.append(f"- {k}: {nach_ebene.get(k, 0)}")
    z += ["", f"Läufe mit Meldung: {len(laeufe_mit_meldung)}", "", "Größte Abweichung der Bootstrapgrenzen über beide Seeds (Originaleinheit):", ""]
    for k, v in max_abst.items():
        z.append(f"- {k}: {v}")
    if b.info:
        z += ["", "Hinweise:", ""] + [f"- {i}" for i in b.info]
    z += ["", "## Gedruckte Werte gegen Arbeit 6.3", "",
          "Die Toleranzprüfung der Bootstrapgrenzen und der exakte Vergleich ihrer kaufmännischen Rundung sind getrennt.", "",
          "| Größe | Sollwert | Nachrechnung ungerundet | Kaufmännisch gerundet | Toleranz | Rundung | Quelle |",
          "|---|---:|---:|---:|---|---|---|"]
    for x in b.vergleich_arbeit:
        z.append("| " + " | ".join(str(x.get(k, "nicht festgelegt")) for k in (
            "groesse", "soll_gedruckt", "nachrechnung_ungerundet", "nachrechnung_gerundet",
            "toleranz_pruefung", "rundung_pruefung", "quelle")) + " |")
    z += ["", "## Meldungen", "", "| Ebene | Lauf | Größe | Feld | Wert N | Sollwert | Quelle | Regel |", "|---|---|---|---|---|---|---|---|"]
    for m in b.meldungen[:2000]:
        z.append("| " + " | ".join(str(m[k]).replace("|", "/") for k in ("ebene", "lauf", "groesse", "feld", "n_wert", "soll_wert", "quelle", "regel")) + " |")
    if len(b.meldungen) > 2000:
        z.append(f"| … | {len(b.meldungen) - 2000} weitere in VERGLEICH-ERGEBNIS.json | | | | | | |")
    (ordner / "VERGLEICH-ERGEBNIS.md").write_text("\n".join(z) + "\n", encoding="utf-8")
    return ergebnis


def main(argv=None):
    import datetime
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ausgabe", required=True)
    ap.add_argument("--bericht", required=True)
    ap.add_argument("--ausgabe-sha", required=True, help="festgeschriebene SHA-256 von AUSGABE.sha256")
    ap.add_argument("--p-rows", default=str(P_ROWS_STD))
    ap.add_argument("--p-analysis", default=str(P_ANALYSIS_STD))
    a = ap.parse_args(argv)
    b = Bericht()
    try:
        laeufe, agg, manifest_sha, nicht_gelistet = lade_ausgabe(a.ausgabe, a.ausgabe_sha)
        rohantworten = lade_rohantworten()
        prows, pa = lade_sollwerte(Path(a.p_rows), Path(a.p_analysis))
    except Vorbedingung as e:
        print(f"VORBEDINGUNG VERLETZT: {e}", file=sys.stderr)
        Path(a.bericht).mkdir(parents=True, exist_ok=True)
        (Path(a.bericht) / "VORBEDINGUNG-VERLETZT.txt").write_text(str(e) + "\n", encoding="utf-8")
        return 2
    abstaende = {}
    vergleiche_laeufe(laeufe, prows, rohantworten, b)
    innere_stimmigkeit(laeufe, agg, b)
    gegen_panalysis(agg, pa, b, abstaende)
    gegen_arbeit(agg, b)
    kopf = {"schema": "n-vergleich/v1",
            "zeitpunkt_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "eingaben": {"AUSGABE.sha256": manifest_sha, "eingang/MANIFEST.sha256": EINGANG_MANIFEST_SHA,
                         "P-ROWS.json": sha(a.p_rows), "P-ANALYSIS.json": sha(a.p_analysis),
                         "vergleich.py": sha(Path(__file__))},
            "toleranzen": {"f1_abs": TOL_F1_ABS, "relativ": TOL_REL, "grenze_differenz_abs": TOL_GRENZE_DIFFERENZ,
                           "grenze_verhaeltnis_abs": TOL_GRENZE_VERHAELTNIS}}
    erg = schreibe_bericht(a.bericht, kopf, b, abstaende)
    print(json.dumps({"meldungen_gesamt": erg["meldungen_gesamt"], "nach_ebene": erg["meldungen_nach_ebene"],
                      "laeufe_mit_meldung": len(erg["laeufe_mit_meldung"])}, ensure_ascii=False))
    return 0 if not b.meldungen else 1


if __name__ == "__main__":
    sys.exit(main())
