#!/usr/bin/env python3
"""Deterministische Nachrechnung der verdeckten Messabnahme Z37 (ohne Modell).

Zweck: Für jeden der zwölf künstlichen Fälle wird mit festen Regeln aus den
Rohbelegen berechnet, ob eine Verletzung vorliegt, welche, und welche Kosten
herauskommen. Danach (und erst danach) wird das vorab gesicherte Soll geladen
und verglichen.

Grundsätze
- Kein Modell, kein Netzwerk, keine Zufallszahlen. Nur Python-Standardbibliothek.
- Kein Import des Frameworks (communication_pruning). Alle Regeln sind hier
  eigenständig nachprogrammiert und mit ihrer Herkunft kommentiert:
    [V] = Schnittstellenvertrag eval-harness/eval/runs/Z37-MESSABNAHME-001/contract.md
    [A] = communication_pruning/audit.py   (Ablauf- und Sichtbarkeitsregel)
    [J] = communication_pruning/journal.py (Hüllen, Prüfsummenkette)
    [C] = communication_pruning/contracts.py (Rollen-Instruktionen)
    [E] = communication_pruning/execution.py (Reihenfolge, Aufrufkennung)
    [P] = project/dsr/Z37-MESSABNAHME-PLAN.md (Fallklassen K1-K4, V1-V8)
- Das alte Repo wird nur gelesen.
- Drei Belegstufen, kumulativ, wie in Z37:
    S1  = Konfiguration und Meldung (view1/case.json)
    S2  = + äußeres Journal, Trace, beobachtete Requests (view2)
    S2T = S2 + nur die Tarifdatei (view3/<fall>/tariff.json), ohne innere Spur
    S3  = + innere Client-Spur und Usage (view3/<fall>/client.jsonl, usage.jsonl)
  Für jeden Befund wird die erste Stufe festgehalten, ab der er feststeht.

Aufruf:  python3 nachrechnen.py            (rechnet, vergleicht, schreibt JSON)
         python3 nachrechnen.py --ohne-soll (nur rechnen, Soll nicht öffnen)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

HIER = Path(__file__).resolve().parent
RUN = (HIER / "../../../../Masterarbeit/eval-harness/eval/runs/Z37-MESSABNAHME-001").resolve()

# [C] contracts.INSTRUCTIONS: feste Systemanweisungen je Rolle (wörtlich übernommen,
# nicht importiert, damit die Nachrechnung vom Framework-Code unabhängig bleibt).
INSTRUKTIONEN = {
    "evidence": "Find evidence relevant to the question in the supplied paragraphs. Give a supported answer if possible.",
    "linking": "Connect evidence across the supplied paragraphs to answer the question. Explain the necessary links.",
    "draft": "Derive an answer independently from the supplied paragraphs. Use any supplied prior messages critically.",
    "checking": "Check possible answers against the supplied paragraphs, look for contradictions, and give the best supported answer.",
    "aggregator": "Answer the question using the supplied paragraphs and available final producer messages. Return only the answer.",
}

# Befundkategorien. Reihenfolge = feste Priorität für den "Hauptbefund", weil
# manche Verletzungen zwangsläufig Folgebefunde auslösen (z. B. ein verdeckter
# Aufruf macht auch die gemeldete Summe falsch). Die Priorität ist vorab fest
# und hängt nicht vom Soll ab.
PRIORITAET = [
    "integritaetsbruch",       # Prüfsummenkette/Hülle verletzt [J]
    "verdeckter_aufruf",       # innerer Aufruf ohne äußeren Start [V Sicht 3]
    "unerlaubte_nachricht",    # Nachricht ohne erlaubte Kante [A][V]
    "fehlende_nachricht",      # erlaubte vorhandene Nachricht nicht übergeben [A][E]
    "nachrichtenreihenfolge",  # Nachrichten nicht in roles-Reihenfolge [V][A]
    "nachricht_doppelt",       # dieselbe Nachricht mehrfach übergeben [A]
    "nachricht_veraendert",    # übergebener Text != Text des Abschlusses [A][V]
    "doppelter_ausgang",       # zwei Abschlüsse für einen Start [V]
    "falsche_zuordnung",       # Abschluss gehört nicht zum gestarteten Versuch [A]
    "fehlender_ausgang",       # Start ohne Abschluss, Lauf geht trotzdem weiter [V]
    "falscher_preis",          # gebuchter Betrag != Token x Tarif [V Zählung und Kosten]
    "falsche_meldung",         # Meldung (Status/Zahlen/Kosten) widerspricht den Belegen
]
# Nachrangige Befunde: meist Folge eines der obigen. Sie werden nur dann
# Hauptbefund, wenn kein vorrangiger Befund vorliegt. JEDER Befund, auch ein
# nachrangiger, macht den Fall zu "Verletzung ja" (Codex-Runde 1, Punkt 1).
NACHRANGIG = ["kopf_abweichend", "request_abweichung", "trace_abweichung", "unerwartetes_ereignis",
              "nachricht_ohne_ausgang", "aufruf_ohne_inneren_beleg", "innerer_request_abweichend",
              "innerer_ausgang_abweichend",
              "preisversion_abweichend", "usage_betrag_abweichend"]
PRIORITAET = PRIORITAET + NACHRANGIG

STUFEN = ["S1", "S2", "S2T", "S3"]


def lies_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def lies_jsonl(p: Path):
    return [json.loads(z) for z in p.read_text(encoding="utf-8").splitlines() if z.strip()]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def d(x):
    return None if x is None else Decimal(x)


def s(x):
    return None if x is None else str(x)


class Fall:
    def __init__(self, case_id: str):
        self.id = case_id
        self.befunde: list[dict] = []

    def befund(self, art, stufe, text):
        self.befunde.append({"art": art, "stufe": stufe, "text": text})


# ---------------------------------------------------------------- Stufe S1
def stufe1(f: Fall, case: dict) -> dict:
    """Nur Konfiguration und Meldung. Regeln [V Ausführungs-/Zählvertrag]:
    - aktive Rollen je Runde einmal, unterdrückte Rolle kein Aufruf, danach Aggregator:
      erwartete Aufrufe eines vollständigen Laufs = rounds * (aktive Rollen) + 1.
    - completed: Antwort vorhanden, Messung vollständig, gestartet == abgeschlossen ==
      erwartete Aufrufe, Gesamt == Teilsumme.
    - model_failed: Antwort null, gestartet == abgeschlossen, Gesamt == Teilsumme (bezahlt).
    - technical_stop: Messung unvollständig, gestartet > abgeschlossen, Gesamt unbekannt (null).
    """
    cfg, c = case["expected_config"], case["claimed"]
    aktiv = [r for r in cfg["roles"] if r != case["failed_role"]]
    erwartet = case["rounds"] * len(aktiv) + 1
    w = []
    st = c["status"]
    if st == "completed":
        if c["answer"] is None: w.append("completed ohne Antwort")
        if not c["measurement_complete"]: w.append("completed, aber Messung unvollständig")
        if c["started_attempts"] != c["calls"]: w.append(f"completed, aber gestartet {c['started_attempts']} != abgeschlossen {c['calls']}")
        if c["calls"] != erwartet: w.append(f"completed, aber {c['calls']} statt {erwartet} Aufrufe laut Konfiguration")
        if c["total_cost_usd"] is None or c["total_cost_usd"] != c["known_cost_subtotal_usd"]: w.append("completed, aber Gesamt != Teilsumme")
    elif st == "model_failed":
        if c["answer"] is not None: w.append("model_failed mit Antwort")
        if c["started_attempts"] != c["calls"]: w.append("model_failed mit offenem Versuch")
        if c["total_cost_usd"] != c["known_cost_subtotal_usd"]: w.append("model_failed, Gesamt != Teilsumme")
    elif st == "technical_stop":
        if c["measurement_complete"]: w.append("technical_stop, aber Messung als vollständig gemeldet")
        if c["total_cost_usd"] is not None: w.append("technical_stop mit bekannter Gesamtsumme")
        if not c["started_attempts"] > c["calls"]: w.append("technical_stop ohne offenen Versuch")
    else:
        w.append(f"unbekannter Status {st}")
    for x in w:
        f.befund("falsche_meldung", "S1", "Meldung in sich widersprüchlich: " + x)
    return {"erwartete_aufrufe_vollstaendig": erwartet, "widersprueche": w}


# ---------------------------------------------------------------- Stufe S2
def kanonisch(v) -> bytes:
    # [V Journal] / [J _encode]: sortierte Schlüssel, Separatoren , und :, ASCII-Escapes, keine NaN
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def pruefe_journal(f: Fall, pfad: Path):
    """[V Journal][J read_journal]: seq ab 0 fortlaufend, previous = vorige Prüfsumme,
    checksum = SHA-256 über die übrigen Felder kanonisch, erste Nutzlast header,
    dann event, ggf. finished; nach finished keine Zeilen; Zeilenende \\n."""
    roh = pfad.read_bytes()
    zeilen = roh.split(b"\n")
    if zeilen[-1] != b"":
        f.befund("integritaetsbruch", "S2", "letzte Journalzeile ohne Zeilenumbruch")
    zeilen = [z for z in zeilen if z]
    vorher, header, events, versiegelt, ende = None, None, [], False, None
    for seq, z in enumerate(zeilen):
        r = json.loads(z)
        cs = r.pop("checksum", None)
        if set(r) != {"journal_schema", "seq", "run_id", "previous", "payload"}:
            f.befund("integritaetsbruch", "S2", f"seq {seq}: Hülle hat falsche Felder")
        if r.get("journal_schema") != 1 or r.get("seq") != seq:
            f.befund("integritaetsbruch", "S2", f"seq {seq}: Schema/Sequenz falsch")
        # [V Journal] identische run_id in jeder Zeile, auch der Kopfzeile (Codex-Runde 2)
        kopf_id = r["payload"]["trace"].get("run_id") if seq == 0 and r.get("payload", {}).get("kind") == "header" \
            else (header or {}).get("run_id")
        if r.get("run_id") != kopf_id:
            f.befund("integritaetsbruch", "S2", f"seq {seq}: run_id der Hülle weicht vom Lauf ab")
        if r.get("previous") != vorher:
            f.befund("integritaetsbruch", "S2", f"seq {seq}: previous zeigt nicht auf vorige Prüfsumme")
        if cs != hashlib.sha256(kanonisch(r)).hexdigest():
            f.befund("integritaetsbruch", "S2", f"seq {seq}: Prüfsumme passt nicht zum Inhalt (nachträglich verändert)")
        if versiegelt:
            f.befund("integritaetsbruch", "S2", f"seq {seq}: Eintrag nach Versiegelung")
        p = r["payload"]
        if seq == 0:
            if p.get("kind") != "header":
                f.befund("integritaetsbruch", "S2", "erste Zeile ist kein header")
            header = p["trace"]
        elif p["kind"] == "event":
            events.append(p["event"])
        elif p["kind"] == "finished":
            versiegelt, ende = True, {"answer": p["answer"], "status": p["status"]}
        vorher = cs
    return header, events, versiegelt, ende


def ablauf(f: Fall, case: dict, events: list):
    """Eigener Nachvollzug des Ablaufs, Regeln aus [V Ausführungs- und Nachrichtenvertrag],
    [A _audit], [E _execute]:
    - Schritte: Runde 1..rounds, Rollen in Konfigurationsreihenfolge; failed_role -> Ereignis
      'suppressed', sonst 'started' + genau ein Abschluss ('completed' oder 'model_failed').
      Danach Aggregator in Runde rounds+1. Aufrufkennung '<run_id>:<runde>:<rolle>:1'.
    - Sichtbarkeit: Rolle R in Runde r darf Nachrichten aus Runde r-1 nur von sich selbst
      oder von Quelle Q mit gerichteter Kante [Q, R] erhalten; Aggregator alle; Reihenfolge
      nach roles. Runde 1 ohne Nachrichten.
    - model_failed stoppt die Aufgabe (F-01). Ein Start ohne Abschluss am Ende eines
      unversiegelten Journals ist ein offener Versuch (technischer Stopp, Gesamt unbekannt).
    """
    cfg = case["expected_config"]
    run_id = "run-" + case["case_id"]
    schritte = [(r, rolle) for r in range(1, case["rounds"] + 1) for rolle in cfg["roles"]]
    schritte.append((case["rounds"] + 1, "aggregator"))
    kanten = {tuple(k) for k in cfg["edges"]}
    i = 0
    ausgaben = {}         # (runde, rolle) -> attempt_id mit echtem Abschluss
    texte = {}            # attempt_id -> Antworttext des Abschlusses
    gestartet, abgeschlossen, offen = [], [], []
    kosten = []           # (attempt_id, usage) je verbuchtem Abschluss
    modell_fehler = False
    for runde, rolle in schritte:
        if i >= len(events):
            break
        ev = events[i]
        if rolle == case["failed_role"]:
            if ev == {"kind": "suppressed", "role": rolle, "round": runde}:
                i += 1
            else:
                f.befund("unerwartetes_ereignis", "S2", f"Unterdrückung von {rolle}/R{runde} fehlt")
            continue
        aid = f"{run_id}:{runde}:{rolle}:1"
        if ev.get("kind") != "started" or ev.get("attempt_id") != aid:
            f.befund("unerwartetes_ereignis", "S2", f"erwartet Start {aid}, gefunden {ev.get('kind')} {ev.get('attempt_id')}")
            i += 1
            continue
        gestartet.append(aid)
        if ev.get("role") != rolle or ev.get("round") != runde or ev.get("instruction") != INSTRUKTIONEN[rolle] \
                or ev.get("max_output_tokens") != (128 if rolle == "aggregator" else 1024):
            f.befund("unerwartetes_ereignis", "S2", f"{aid}: Rolle/Runde/Instruktion/Limit weicht ab")
        # Sichtbarkeitsregel
        erhalten = ev.get("messages", [])
        for m in erhalten:
            q = m.get("role")
            erlaubt = rolle == "aggregator" or q == rolle or (q, rolle) in kanten
            if m.get("round") != runde - 1 or not erlaubt:
                f.befund("unerlaubte_nachricht", "S2",
                         f"{aid} erhielt Nachricht von {q}/R{m.get('round')}; Kante [{q}, {rolle}] nicht in der Konfiguration")
            elif ausgaben.get((m.get("round"), q)) != m.get("attempt_id"):
                f.befund("nachricht_ohne_ausgang", "S2",
                         f"{aid} erhielt Nachricht {m.get('attempt_id')}, für die im Journal kein passender Abschluss steht")
        erhaltene_ids = [m.get("attempt_id") for m in erhalten]
        # Inhalt und Anzahl: jede Nachricht genau einmal, Text = Text des Abschlusses (Codex-Runde 2)
        if len(erhaltene_ids) != len(set(erhaltene_ids)):
            f.befund("nachricht_doppelt", "S2", f"{aid}: dieselbe Nachricht mehrfach übergeben")
        for m in erhalten:
            if m.get("attempt_id") in texte and m.get("text") != texte[m.get("attempt_id")]:
                f.befund("nachricht_veraendert", "S2", f"{aid}: Nachricht {m.get('attempt_id')} weicht im Text vom Abschluss ab")
        # Reihenfolge der Nachrichten folgt roles [V][A]
        reihenfolge = [cfg["roles"].index(m.get("role")) if m.get("role") in cfg["roles"] else 99 for m in erhalten]
        if reihenfolge != sorted(reihenfolge):
            f.befund("nachrichtenreihenfolge", "S2", f"{aid}: Nachrichten nicht in Rollenreihenfolge")
        # Nachricht enthält nur role, round, text plus Journal-Kennung attempt_id [V]
        for m in erhalten:
            if set(m) != {"attempt_id", "role", "round", "text"}:
                f.befund("unerwartetes_ereignis", "S2", f"{aid}: Nachricht mit unerwarteten Feldern")
        for q in cfg["roles"]:
            if runde > 1 and (rolle == "aggregator" or q == rolle or (q, rolle) in kanten):
                a = ausgaben.get((runde - 1, q))
                if a is not None and a not in erhaltene_ids:
                    f.befund("fehlende_nachricht", "S2", f"{aid} fehlt erlaubte Nachricht {a}")
        i += 1
        if i >= len(events):
            offen.append(aid)
            break
        t = events[i]
        if t.get("kind") not in ("completed", "model_failed"):
            # Nächstes Ereignis ist schon ein neuer Start: dieser Versuch hat keinen Abschluss.
            f.befund("fehlender_ausgang", "S2", f"{aid}: kein Abschluss im Journal, Lauf geht trotzdem weiter")
            continue
        i += 1
        if t.get("attempt_id") != aid:
            f.befund("falsche_zuordnung", "S2", f"Abschluss nach Start {aid} trägt Kennung {t.get('attempt_id')}")
        else:
            ausgaben[(runde, rolle)] = aid
            if t.get("kind") == "completed":
                texte[aid] = t.get("text")
        abgeschlossen.append(aid)
        kosten.append((aid, t.get("usage", {})))
        # weitere Abschlüsse für denselben Versuch = Doppelbuchung
        while i < len(events) and events[i].get("kind") in ("completed", "model_failed") \
                and events[i].get("attempt_id") == t.get("attempt_id"):
            f.befund("doppelter_ausgang", "S2", f"{t.get('attempt_id')}: zweiter Abschluss für denselben Start")
            kosten.append((t.get("attempt_id") + " (Duplikat)", events[i].get("usage", {})))
            i += 1
        if t.get("kind") == "model_failed":
            modell_fehler = True
            break
    if i < len(events) and not offen:
        f.befund("unerwartetes_ereignis", "S2", f"{len(events) - i} Ereignisse nach Ablaufende")
    return {"gestartet": gestartet, "abgeschlossen": abgeschlossen, "offen": offen,
            "abschlussereignisse": sum(1 for e in events if e.get("kind") in ("completed", "model_failed")),
            "kosten": kosten, "modell_fehler": modell_fehler}


def stufe2(f: Fall, case: dict, v2: Path) -> dict:
    header, events, versiegelt, ende = pruefe_journal(f, v2 / "journal.jsonl")
    trace = lies_json(v2 / "trace.json")
    # Trace muss genau dem aus dem Journal zusammengesetzten Lauf entsprechen.
    rek = dict(header, events=events)
    if ende:
        rek.update(ende)
    if trace != rek:
        f.befund("trace_abweichung", "S2", "trace.json weicht vom Journal ab")
    # Kopf gegen vorgegebene Konfiguration [V Sicht 1][A _audit][E execute]
    cfg = case["expected_config"]
    soll_kopf = {"configuration": {"config_id": cfg["config_id"], "roles": cfg["roles"], "edges": cfg["edges"]},
                 "rounds": case["rounds"], "failed_role": case["failed_role"], "schema": 3,
                 "output_limits": case["output_limits"], "failure_policy": case["failure_policy"],
                 "run_id": "run-" + case["case_id"], "events": []}
    for k, v in soll_kopf.items():
        if header.get(k) != v:
            f.befund("kopf_abweichend", "S2", f"Journalkopf: {k} weicht von der Vorgabe ab")
    if set(header.get("task", {})) != {"task_id", "question", "paragraphs"}:
        f.befund("kopf_abweichend", "S2", "Journalkopf: Aufgabe hat unerwartete Felder")
    a = ablauf(f, case, events)
    # Beobachtete Requests [V Sicht 2]: je Start genau ein Request mit denselben
    # Feldern; prior_messages im Modellkörper = Nachrichten ohne Verwaltungskennung.
    obs = lies_jsonl(v2 / "observed_requests.jsonl")
    starts = [e for e in events if e.get("kind") == "started"]
    if len(obs) != len(starts):
        f.befund("request_abweichung", "S2", f"{len(obs)} beobachtete Requests, {len(starts)} Starts im Journal")
    for o, st in zip(obs, starts):
        rq = o["request"]
        for k in ("attempt_id", "role", "round", "instruction", "max_output_tokens", "messages"):
            if rq.get(k) != st.get(k):
                f.befund("request_abweichung", "S2", f"{st['attempt_id']}: Feld {k} in Request != Journal")
        user = json.loads(o["model_body"]["messages"][1]["content"])
        pm = [{"role": m["role"], "round": m["round"], "text": m["text"]} for m in rq["messages"]]
        if rq.get("task") != header.get("task") or user.get("question") != header["task"]["question"] \
                or user.get("paragraphs") != header["task"]["paragraphs"] \
                or o["model_body"].get("max_tokens") != rq.get("max_output_tokens"):
            f.befund("request_abweichung", "S2", f"{st['attempt_id']}: Aufgabe/Frage/Absätze/Limit im Request != Journalkopf")
        if user.get("prior_messages") != pm or o["model_body"]["messages"][0]["content"] != rq["instruction"]:
            f.befund("request_abweichung", "S2", f"{st['attempt_id']}: Modellkörper != Request")
    # Kosten aus dem äußeren Journal [V Zählung und Kosten]
    bekannt, unbekannt = Decimal(0), 0
    for _, u in a["kosten"]:
        if u.get("cost_usd") is None:
            unbekannt += 1
        else:
            bekannt += Decimal(u["cost_usd"])
    if a["offen"]:
        status = "technical_stop"
    elif a["modell_fehler"]:
        status = "model_failed"
    elif versiegelt:
        status = ende["status"]
    else:
        status = "unversiegelt"
    # Gesamtkosten nur bei versiegeltem Lauf ohne offenen Versuch und ohne unbekannten
    # Betrag; model_failed wird laut [E] ebenfalls versiegelt (journal.finish).
    gesamt = bekannt if (versiegelt and not a["offen"] and not unbekannt) else None
    antwort = ende["answer"] if ende else None
    return {"journal_versiegelt": versiegelt, "status": status, "antwort": antwort,
            "gestartet": len(a["gestartet"]), "abgeschlossen": len(a["abgeschlossen"]),
            "abschlussereignisse_im_journal": a["abschlussereignisse"],
            "offene_versuche": a["offen"], "bekannte_teilsumme_usd": s(bekannt),
            "gesamtkosten_usd": s(gesamt), "beobachtete_requests": len(obs),
            "_kosten": a["kosten"], "_events": events,
            "_beobachtet": obs}


def vergleiche_meldung(f: Fall, stufe: str, c: dict, r: dict, quelle: str):
    """Meldung gegen nachgerechneten Stand: Status, Antwort, gestartet, abgeschlossen, Kosten."""
    paare = [("status", c["status"], r["status"]),
             ("answer", c["answer"], r["antwort"]),
             ("started_attempts", c["started_attempts"], r["gestartet"]),
             ("calls", c["calls"], r["abgeschlossen"]),
             ("known_cost_subtotal_usd", d(c["known_cost_subtotal_usd"]), d(r["bekannte_teilsumme_usd"])),
             ("total_cost_usd", d(c["total_cost_usd"]), d(r["gesamtkosten_usd"]))]
    for name, gemeldet, belegt in paare:
        if gemeldet != belegt:
            f.befund("falsche_meldung", stufe, f"Meldung {name}={gemeldet}, {quelle} ergibt {belegt}")


# ---------------------------------------------------------------- Stufe S2T
def tarifbetrag(t: dict, ein: int, aus: int) -> Decimal:
    # [V Zählung und Kosten]: Inputtokens x Inputpreis + Outputtokens x Outputpreis (+ Requestpreis)
    return ein * Decimal(t["input_usd_per_token"]) + aus * Decimal(t["output_usd_per_token"]) + Decimal(t["request_usd"])


def stufe2t(f: Fall, r2: dict, tarif: dict):
    """Nur Journal + Tarifdatei. Jeder im Journal gebuchte Betrag wird aus den im Journal
    stehenden Tokenzahlen neu berechnet. Freistellungen stehen im Tarif nur mit innerer
    call_id; ohne innere Spur ist ein gebuchter Nullbetrag deshalb nicht entscheidbar
    und wird hier nicht gewertet (offen bis S3)."""
    offen_null = 0
    for aid, u in r2["_kosten"]:
        if u.get("cost_usd") is None or u.get("input_tokens") is None:
            continue
        soll = tarifbetrag(tarif, u["input_tokens"], u["output_tokens"])
        ist = Decimal(u["cost_usd"])
        if ist == 0 and soll != 0:
            offen_null += 1
            continue
        if ist != soll:
            f.befund("falscher_preis", "S2T", f"{aid}: gebucht {ist}, Tokens x Tarif = {soll}")
    return {"nullbetraege_ohne_innere_zuordnung": offen_null}


# ---------------------------------------------------------------- Stufe S3
def stufe3(f: Fall, case: dict, r2: dict, v3: Path) -> dict:
    """Innere Spur [V Sicht 3]: 'started' mit call_id/attempt_id, danach genau ein
    'returned' oder 'technical_error'. Jeder innere Start hat genau einen Usage-Record;
    billing_state 'unresolved' = Betrag unbekannt. Wahrer Betrag = Tarifformel, außer
    call_id steht in waived_call_ids (bekannter Nullbetrag)."""
    client = lies_jsonl(v3 / "client.jsonl")
    usage = {u["call_id"]: u for u in lies_jsonl(v3 / "usage.jsonl")}
    tarif = lies_json(v3 / "tariff.json")
    starts = [c for c in client if c["kind"] == "started"]
    ausgaenge = {c["call_id"]: c for c in client if c["kind"] != "started"}
    aussen = {aid for aid, _ in r2["_kosten"]} | set(r2["offene_versuche"])
    aussen_starts = [e["attempt_id"] for e in r2["_events"] if e.get("kind") == "started"]
    aussen_abschluss = {}
    for e in r2["_events"]:
        if e.get("kind") in ("completed", "model_failed"):
            aussen_abschluss.setdefault(e["attempt_id"], []).append(e)
    innen_ids = [c["attempt_id"] for c in starts]
    for c in starts:
        if c["attempt_id"] not in aussen_starts:
            f.befund("verdeckter_aufruf", "S3", f"innerer Aufruf {c['call_id']} ({c['attempt_id']}) hat keinen Start im Journal")
    for aid in aussen_starts:
        if aid not in innen_ids:
            f.befund("aufruf_ohne_inneren_beleg", "S3", f"{aid} gestartet, aber kein innerer Aufruf")
    # Nachrichten innen = Nachrichten im Journal-Start
    start_ev = {e["attempt_id"]: e for e in r2["_events"] if e.get("kind") == "started"}
    beobachtet = {o["request"]["attempt_id"]: o for o in r2["_beobachtet"]}
    for c in starts:
        e = start_ev.get(c["attempt_id"])
        if e is not None and c["request"]["messages"] != e["messages"]:
            f.befund("innerer_request_abweichend", "S3", f"{c['attempt_id']}: innere Nachrichten != Journal")
        # [V Sicht 2/3] Request und Modellkörper innen = an der äußeren Grenze beobachtet (Codex-Runde 2)
        o = beobachtet.get(c["attempt_id"])
        if o is not None and (c["request"] != o["request"] or c["model_body"] != o["model_body"]):
            f.befund("innerer_request_abweichend", "S3", f"{c['attempt_id']}: innerer Request/Modellkörper != beobachteter Request")
    # Ausgänge innen gegen Abschlüsse außen
    for c in starts:
        a = ausgaenge.get(c["call_id"])
        aid = c["attempt_id"]
        if aid not in aussen_starts:
            continue
        ab = aussen_abschluss.get(aid, [])
        if a is None:
            f.befund("innerer_ausgang_abweichend", "S3", f"{aid}: innen ohne Ausgang")
        elif a["kind"] == "returned" and a.get("finish_reason") == "stop":
            if not ab:
                f.befund("fehlender_ausgang", "S3", f"{aid}: innen zurückgekehrt ('{a['text']}'), im Journal ohne passenden Abschluss")
            elif len(ab) > 1:
                f.befund("doppelter_ausgang", "S3", f"{aid}: innen eine Rückgabe, im Journal {len(ab)} Abschlüsse")
            elif ab[0]["kind"] != "completed" or ab[0]["text"] != a["text"]:
                f.befund("innerer_ausgang_abweichend", "S3", f"{aid}: Rückgabe innen != Abschluss außen")
        elif a["kind"] == "returned":  # bezahlter Modellmisserfolg (empty/length) [V F-01]
            if not ab or ab[0]["kind"] != "model_failed":
                f.befund("innerer_ausgang_abweichend", "S3", f"{aid}: innen {a.get('finish_reason')}, außen kein model_failed")
        elif a["kind"] == "technical_error":
            if ab:
                f.befund("innerer_ausgang_abweichend", "S3", f"{aid}: innen technischer Fehler, außen abgeschlossen")
    # wahre Kosten
    bekannt, unbekannt, bekannte_aufrufe, betrag = Decimal(0), 0, 0, {}
    for c in starts:
        u = usage.get(c["call_id"])
        if u is None:
            f.befund("innerer_ausgang_abweichend", "S3", f"{c['call_id']}: kein Usage-Record")
            continue
        if u["billing_state"] != "known" or u["cost_usd"] is None:
            unbekannt += 1
            betrag[c["attempt_id"]] = None
            continue
        wahr = Decimal(0) if c["call_id"] in tarif["waived_call_ids"] else tarifbetrag(tarif, u["input_tokens"], u["output_tokens"])
        if Decimal(u["cost_usd"]) != wahr:
            f.befund("usage_betrag_abweichend", "S3", f"{c['call_id']}: Usage {u['cost_usd']} != Tarif {wahr}")
        bekannt += wahr
        bekannte_aufrufe += 1
        betrag[c["attempt_id"]] = wahr
        # gebuchter Betrag im Journal gegen Tarifwahrheit
        for e in aussen_abschluss.get(c["attempt_id"], []):
            gebucht = e["usage"].get("cost_usd")
            if gebucht is not None and Decimal(gebucht) != wahr:
                f.befund("falscher_preis", "S3", f"{c['attempt_id']}: im Journal {gebucht}, Tarifwahrheit {wahr}")
            if e["usage"].get("price_version") != u["price_version"]:
                f.befund("preisversion_abweichend", "S3",
                         f"{c['attempt_id']}: Preisversion im Journal '{e['usage'].get('price_version')}', innen '{u['price_version']}'")
    technisch = any(a["kind"] == "technical_error" for a in ausgaenge.values())
    modell = any(a["kind"] == "returned" and a.get("finish_reason") in ("empty", "length") for a in ausgaenge.values())
    status = "technical_stop" if technisch else ("model_failed" if modell else "completed")
    antwort = None
    if status == "completed":
        agg = [ausgaenge[c["call_id"]] for c in starts if c["role"] == "aggregator"]
        antwort = agg[-1]["text"] if agg else None
    return {"status": status, "antwort": antwort, "gestartet_innen": len(starts),
            "bekannt_innen": bekannte_aufrufe, "unbekannt_innen": unbekannt,
            "bekannte_teilsumme_usd": str(bekannt),
            "gesamtkosten_usd": None if unbekannt else str(bekannt),
            # für den Meldungsvergleich (Meldung zählt Versuche/abgeschlossene Aufrufe)
            "gestartet": len(starts), "abgeschlossen": bekannte_aufrufe,
            "_tarif": tarif}


# ---------------------------------------------------------------- Zusammenführung
def hauptbefund(befunde, bis_stufe):
    idx = STUFEN.index(bis_stufe)
    arten = {b["art"] for b in befunde if STUFEN.index(b["stufe"]) <= idx}
    for a in PRIORITAET:
        if a in arten:
            return a
    return None


def rechne_fall(case_id: str) -> dict:
    f = Fall(case_id)
    case = lies_json(RUN / "view1" / case_id / "case.json")
    r1 = stufe1(f, case)
    r2 = stufe2(f, case, RUN / "view2" / case_id)
    vergleiche_meldung(f, "S2", case["claimed"], r2, "äußeres Journal")
    tarif = lies_json(RUN / "view3" / case_id / "tariff.json")
    r2t = stufe2t(f, r2, tarif)
    r3 = stufe3(f, case, r2, RUN / "view3" / case_id)
    vergleiche_meldung(f, "S3", case["claimed"], r3, "innere Spur mit Tarif")
    # Erste Stufe je Befundart
    erste = {}
    for b in f.befunde:
        if b["art"] not in erste or STUFEN.index(b["stufe"]) < STUFEN.index(erste[b["art"]]):
            erste[b["art"]] = b["stufe"]
    haupt = {st: hauptbefund(f.befunde, st) for st in STUFEN}
    gesamt_haupt = haupt["S3"]
    return {
        "case_id": case_id,
        "konfiguration": {"roles": case["expected_config"]["roles"], "edges": case["expected_config"]["edges"],
                          "rounds": case["rounds"], "failed_role": case["failed_role"]},
        "meldung": case["claimed"],
        "S1": r1,
        "S2": {k: v for k, v in r2.items() if not k.startswith("_")},
        "S2T": r2t,
        "S3": {k: v for k, v in r3.items() if not k.startswith("_")},
        "befunde": f.befunde,
        "erste_stufe_je_befundart": erste,
        "hauptbefund_je_stufe": haupt,
        "ergebnis": {
            "verletzung": bool(f.befunde),
            "art": gesamt_haupt,
            "noetige_stufe": erste.get(gesamt_haupt) if gesamt_haupt else None,
            "status": r3["status"],
            "gestartete_aufrufe": r3["gestartet_innen"],
            "bekannte_teilsumme_usd": r3["bekannte_teilsumme_usd"],
            "gesamtkosten_usd": r3["gesamtkosten_usd"],
            "kosten_nur_aeusseres_journal_usd": r2["gesamtkosten_usd"],
            "teilsumme_nur_aeusseres_journal_usd": r2["bekannte_teilsumme_usd"],
        },
    }


# ---------------------------------------------------------------- Sollvergleich (erst nach dem Rechnen)
# [P] Klassen -> erwartete Befundart. Kontrollen K1-K4 = keine Verletzung.
KLASSE_ZU_ART = {"K1": None, "K2": None, "K3": None, "K4": None,
                 "V1": "unerlaubte_nachricht", "V2": "verdeckter_aufruf", "V3": "falscher_preis",
                 "V4": "falsche_meldung", "V5": "fehlender_ausgang", "V6": "doppelter_ausgang",
                 "V7": "falsche_zuordnung", "V8": "integritaetsbruch"}
STATUS_SOLL = {"completed": "completed", "model_failed": "model_failed", "technical_stop": "technical_stop"}


def vergleiche_soll(ergebnisse: list[dict]) -> dict:
    pfad = RUN / "private" / "answer-key.json"
    key = lies_json(pfad)
    soll = {c["case_id"]: c for c in key["cases"]}
    for e in ergebnisse:
        k = soll[e["case_id"]]
        r = e["ergebnis"]
        nt = k["native_truth"]
        art_soll = KLASSE_ZU_ART[k["class"]]
        # tatsächlich übertragene Nachrichten: aus den beobachteten Requests
        obs = lies_jsonl(RUN / "view2" / e["case_id"] / "observed_requests.jsonl")
        uebertragen = [o["request"]["messages"] for o in obs]
        checks = {
            "verletzung": r["verletzung"] == (art_soll is not None),
            "art": r["art"] == art_soll,
            "status": r["status"] == STATUS_SOLL[k["true_status"]],
            "gestartete_innere_aufrufe": r["gestartete_aufrufe"] == nt["started_inner_calls"],
            "bekannte_innere_aufrufe": e["S3"]["bekannt_innen"] == nt["known_inner_calls"],
            "offene_innere_aufrufe": e["S3"]["unbekannt_innen"] == nt["unresolved_inner_calls"],
            "bekannte_teilsumme": d(r["bekannte_teilsumme_usd"]) == d(nt["known_cost_subtotal_usd"]),
            "gesamtkosten": d(r["gesamtkosten_usd"]) == d(nt["total_cost_usd"]),
            "antwort": e["S3"]["antwort"] == k["true_answer"],
            "beobachtete_requests": e["S2"]["beobachtete_requests"] == k["observed_request_count"],
            "uebertragene_nachrichten": uebertragen == k["actual_transferred_prior_messages"],
        }
        e["soll"] = {"klasse": k["class"], "art": art_soll, "status": k["true_status"],
                     "gestartete_innere_aufrufe": nt["started_inner_calls"],
                     "bekannte_teilsumme_usd": nt["known_cost_subtotal_usd"],
                     "gesamtkosten_usd": nt["total_cost_usd"], "antwort": k["true_answer"]}
        e["vergleich"] = checks
        e["stimmt"] = all(checks.values())
    return {"datei": "eval-harness/eval/runs/Z37-MESSABNAHME-001/private/answer-key.json",
            "sha256": sha256(pfad),
            "sha256_laut_Z37_ergebnis": "32ff0a79d298c97359aa18e6f39689a6499e293e55605d5420e420293a879e0e"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ohne-soll", action="store_true")
    ap.add_argument("--aus", default=str(HIER / "NACHRECHNUNG.json"))
    ap.add_argument("--laufordner", default=None, help="nur für Gegenproben mit veränderten Kopien")
    args = ap.parse_args()
    global RUN
    if args.laufordner:
        RUN = Path(args.laufordner).resolve()
    if not RUN.is_dir():
        sys.exit(f"Laufordner fehlt: {RUN}")
    ids = sorted(p.name for p in (RUN / "view1").iterdir() if p.is_dir())
    ergebnisse = [rechne_fall(i) for i in ids]
    eingaben = {}
    for i in ids:
        for sicht, namen in (("view1", ["case.json"]), ("view2", ["trace.json", "journal.jsonl", "observed_requests.jsonl"]),
                             ("view3", ["client.jsonl", "usage.jsonl", "tariff.json"])):
            for n in namen:
                p = RUN / sicht / i / n
                eingaben[f"{sicht}/{i}/{n}"] = sha256(p)
    aus = {"art": "deterministische Nachrechnung Z37, ohne Modell", "laufordner": str(RUN),
           "skript_sha256": sha256(Path(__file__)), "eingaben_sha256": eingaben,
           "faelle": ergebnisse}
    if not args.ohne_soll:
        aus["soll"] = vergleiche_soll(ergebnisse)
        aus["richtig"] = sum(e["stimmt"] for e in ergebnisse)
    Path(args.aus).write_text(json.dumps(aus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for e in ergebnisse:
        r = e["ergebnis"]
        print(f"{e['case_id']}  {e.get('soll', {}).get('klasse', '?'):3} art={r['art']!s:22} stufe={r['noetige_stufe']!s:4} "
              f"status={r['status']:15} gesamt={r['gesamtkosten_usd']!s:10} stimmt={e.get('stimmt', '-')}")
    if "richtig" in aus:
        print(f"richtig: {aus['richtig']} von {len(ergebnisse)}")


if __name__ == "__main__":
    main()
