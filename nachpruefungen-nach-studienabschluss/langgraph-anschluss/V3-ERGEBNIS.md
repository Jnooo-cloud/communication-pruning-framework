<!-- status: teilergebnis Z56 V3 | Plan D-083 (project/dsr/Z56-FRAMEWORK-VALIDIERUNG-PLAN.md) | Selbstprüfung des Urhebers, getrennte Prüfung V4 offen | 2026-10-20 -->

# Z56 V3: Übertragung des Frameworks auf LangGraph nach dem Rezept aus 7.3

20.10.2026. Aufgabe Z56-FRAMEWORK-VALIDIERUNG, Teil V3. FF1, RQ-5 (Anschluss). Erprobt wird das Rezept aus N3021/N3022 (`output/pruefung-rev11-2026-10-20/thesis-rev11.txt`) an LangGraph 1.0.6 als zweitem, anders gebautem fremdem System. 0 US-Dollar, keine Modellaufrufe, 0 Netzversuche in allen Läufen.

## Ergebnis je Kriterium

| ID | Ergebnis | Kernbeleg |
|---|---|---|
| V3a | bestanden | 256/256 installierte LangGraph-/langchain-core-Dateien hashgleich zum Manifest, keine neue oder seit V3-Beginn geänderte Datei; Framework 200/200 hashgleich; nur öffentliche Schnittstelle (`out/v3a/RESULT.json`) |
| V3b | bestanden | 1.080 Läufe je Weg (14 Konfigurationen und D, 1 und 2 Runden, 12 Aufgaben, 3 Ausgabeverträge), 5.400 Aufrufe je Weg; alle 17 Gleichheitsprüfungen ohne Abweichung, Journale bytegleich (`out/v3b/SUMMARY.json`) |
| V3c | bestanden | 780 Läufe mit Vertragsfehlern und 360 Läufe mit `BlockSender` am Ersatztransport je Weg; alle Prüfungen gleich, Kosten aus den Rohdateien unabhängig nachgerechnet; 1.537 Sendeversuche, 302 unklare bleiben unbekannt (`out/v3c/SUMMARY.json`) |
| V3d | bestanden | 100 R-Blöcke × ⟦F*⟧ und D: alle Anfragen bytegleich zur neuen Z55-Wiederholung und zu Z53, Journale gleich den Z53-Journalen bis auf die Lauf-ID, 5 bzw. 9 Aufrufe je erfolgreichem Arm, Kosten gleich, 0 Wiedergabelücken (`out/v3d/SUMMARY.json`) |
| V3e | bestanden, mit Befund B3 | Muster wie Z37: V1, V5, V6, V7, V8 zurückgewiesen; V2, V3, V4 angenommen; Kontrollen K1, K3, K4 angenommen. V1 wird online beim Schreiben zurückgewiesen; das gespeicherte Journal allein zeigt nur ein offenes Präfix (`out/v3e/SUMMARY.json`) |
| V3f | protokolliert (unten) | Schnittstelle angepasst, Anbieter, Datensatzteile und Konfigurationsraum unverändert; alle vier „unverändert übernehmbaren“ Teile blieben unverändert; zwei im Rezept nicht genannte Vorbedingungen (Reihenfolge, eigener Sender) |

Netzsperre: `socket.socket.connect`, `socket.socket.connect_ex`, `socket.create_connection`, `socket.getaddrinfo` per Monkeypatch mit Zähler, in jedem Lauf vor allen Fremdimporten installiert (V3e nach dem Import von Z37 `generate.py` erneut, weil dieses die Socketfunktionen selbst ersetzt). Zähler in allen Läufen 0, Sperre am Ende jeweils noch aktiv; Selbsttest in `tests/test_v3_adapter.py` belegt, dass die Sperre zählt.

## Rahmen

- Commit `05230e09bd3ac8290d4c5cc84d919f6b838c5e4e` (`manifest/commit.txt`, unverändert HEAD). Kein Commit, kein `pip install`.
- LangGraph-Läufe: `/opt/anaconda3/bin/python3` (3.13.9), langgraph 1.0.6, langchain-core 1.2.7. Z55-Wiederholung: `runs/Z38-QSEM-001/provision/python/bin/python3.12` (3.12.14). Alle Läufe mit `PYTHONDONTWRITEBYTECODE=1` und `sys.dont_write_bytecode`.
- Schreibbereich ausschließlich `runs/Z56-FRAMEWORK-VALIDIERUNG-001/v3/`; Rauchtests vor jedem offiziellen Lauf schrieben nur ins Sitzungs-Scratchpad.
- Je Teil genau ein offizieller Lauf nach grünen eigenen Tests (8 Tests, `tests/test_v3_adapter.py`); keine Wiederholung nötig.
- Abweichung vom Arbeitsablauf: Der ProjectAtlas-Workflow aus `AGENTS.md` war in dieser Sitzung nicht verfügbar; gelesen wurde gezielt (Plan, `AGENTS.md`, Rezept N3021/N3022, `configurations.py`, `contracts.py`, `execution.py`, `journal.py`, `audit.py`, `foreign_observer.py`, `foreign_audit.py`, `gptswarm_musique_demo.py`, `run_z55.py`, `z53_fast.py`, `openrouter.py`, `failure_policy.py`, `fake_transport.py`, Z37-Ergebnis, `generate.py`, `run_instrument.py`).

## Der Anschluss

`lg_adapter.py` (209 Codezeilen ohne Leerzeilen, Kommentare und Docstrings; 293 physische Zeilen), SHA256 `8ad76454137addac17a9f1d4bbd19df26f4dd2deb9529b0c6615886ace13df2b`, in allen vier Läufen derselbe Stand (`out/v3*/SOURCES.json`).

- **Graph des fremden Systems:** ein `StateGraph` mit universellem Knotensatz (jede der vier Rollen in jeder Runde plus Zusammenführung) und 20 möglichen Kanten bei zwei Runden (jede Rolle in Runde k zu jeder Rolle in Runde k+1, jede Rolle der letzten Runde zur Zusammenführung), wie der Z55-Graph. Die Konfiguration geht als feste 0/1-Maske über diese Kanten ein; nur maskierte Kanten werden mit `add_edge` angelegt (Mehrfachquellen als wartende Kante `add_edge([...], ziel)`). Nicht aktive Rollen bleiben als Knoten ohne Kante im Graphen und laufen nie.
- **Nachrichten laufen entlang der LangGraph-Kanten:** Ein Knoten liest die Ausgaben genau seiner Eingangsquellen im Graphen (`StateGraph.edges`, `StateGraph.waiting_edges`), sortiert in Protokollreihenfolge. Der Anschluss prüft Nachrichtenrechte bewusst nicht selbst; das bleibt der unveränderten Prüfroutine überlassen.
- **Sender:** Jeder Knoten übergibt seinen Aufruf an `LoggingSender`, der mit dem unveränderten `journal.Journal` (online `audit_prefix` vor jedem Eintrag), `contracts` und `failure_policy` das Ereignisformat von `execution.execute` schreibt. In V3c und V3d ist der Modellzugang dahinter der unveränderte Studiensender `z53_fast.BlockSender` bzw. `DemoSender` aus `gptswarm_musique_demo`.
- **Gate:** LangGraph führt die Knoten eines Supersteps nebenläufig in einem Threadpool aus. Das Gate reiht die Senderaufrufe in die Protokollreihenfolge (Runde für Runde, Rollen in Konfigurationsreihenfolge, Zusammenführung zuletzt), ohne zu ändern, welche Knoten laufen oder welche Nachrichten sie erhalten. Nach einem Abbruch hält es wartende Knoten vor dem Sender an.

## V3a: nur öffentliche Schnittstelle, LangGraph unverändert

Verwendet: `StateGraph`, `add_node`, `add_edge` (einfach und wartend), `START`, `END`, `compile`, `invoke`, lesend die Builder-Attribute `edges` und `waiting_edges`. Keine Patches, keine Unterklassen von LangGraph-Klassen. `get_graph()` wurde verworfen, weil es in einer Probe die Kante eines nie laufenden Knotens nicht zeigte (B6).

Befehl: `/opt/anaconda3/bin/python3 run_v3a.py` nach allen Läufen. Ergebnis `out/v3a/RESULT.json` (SHA256 `c5acd47e…f3d90c`): 256/256 Dateien hashgleich zu `manifest/langgraph-vorher.json`, keine neue `.py`-Datei, keine Datei in `langgraph/` oder `langchain_core/` mit Änderungszeit nach Beginn von V3 (auch kein Bytecode; zusätzlich `find -newermt 2026-10-20`: leer). Framework: 200/200 Dateien hashgleich zu `manifest/framework-vorher.json`, keine Datei in `communication_pruning/`, `study_preparation/`, `tests/` seit Beginn von V3 geändert.

## V3b: Differenztest

Befehl: `/opt/anaconda3/bin/python3 run_v3b.py`. Ergebnis `out/v3b/SUMMARY.json` (SHA256 `ec9ddccb…12e61a6`), Zeilen `out/v3b/rows.jsonl` (`1575ada2…7652e20`), Journale beider Wege unter `out/v3b/own/` und `out/v3b/lg/`, Aufruflisten `calls-own.jsonl`, `calls-lg.jsonl`.

- Umfang: 14 Bankkonfigurationen (1.008 Läufe je Weg) plus D als Zusatz (72), Runden 1 und 2, 12 künstliche Aufgaben, drei Ausgabeverträge (Schema 1 mit 512, Schema 2 mit 1024, Schema 3 F-01 mit 1024/128). Der eigene Weg hat für jede Konfiguration eine Einrunden-Variante (`execute(rounds=1)`), verglichen wurde direkt.
- Backend: deterministischer Ersatz (`backends.SyntheticAgent`), Antworttext aus dem SHA256 der vollständigen Anfrage, sodass jede Abweichung in weitergegebenen Nachrichten in spätere Anfragen durchschlägt. Kostenherkunft gemischt (unbekannt, synthetisch, Anbieter, Tarif mit Preisversion, nur Tokens); unter F-01 nur bekannte Beträge.
- Ergebnis: 0 Abweichungen in allen 17 Prüfungen: Aufruffolge (Rolle, Runde), Anfragebytes (Dataclass und OpenRouter-Payload), weitergegebene Nachrichten, vollständiger Trace, Ereignisliste, Journalbytes, Prüfroutine (`audit`) beider Wege, `read_journal` des LangGraph-Journals versiegelt und gleich dem Trace, bekannte Teilsumme, Gesamtbetrag, Zahl unbekannter Beträge, Nachrechnung gegen die vom Backend gemeldeten Beträge, Zählregel, Senderreihenfolge gleich Protokoll.
- 650 Läufe je Weg enthalten mindestens einen unbekannten Betrag; ihr Gesamtbetrag ist in beiden Wegen `None`.
- In 1.011 der 1.080 LangGraph-Läufe kamen die Knoten in anderer Reihenfolge am Gate an, als das Protokoll vorsieht; das Gate ordnete sie (B2).

## V3c: Kosten je Sendeversuch unter Fehlern

Befehl: `/opt/anaconda3/bin/python3 run_v3c.py`. Ergebnis `out/v3c/SUMMARY.json` (`f2080000…5d83`), Zeilen `rows-a.jsonl`, `rows-b.jsonl`, alle Rohdateien beider Wege (13.796) in `out/v3c/raw.zip` (`2ecdf6bf…f29b`), Einzelhashes in `raw-manifest.json`, Archiv gegen Manifest geprüft.

**Teil A, Vertragsfehler ohne Anbieter (780 Läufe je Weg):** bezahlter Fehlversuch (`AdapterError` mit bekanntem Betrag), Fehlversuch mit unbekanntem Betrag, beides kombiniert bis zur ausgefallenen Zusammenführung, technischer Stopp, F-01-Modellausfall am Anfang, in der Mitte und bei der Zusammenführung, `AdapterError` unter F-01. Alle 10 Prüfungen ohne Abweichung: Fehler bzw. Trace, Aufrufe, Journalbytes und Prüfroutine gleich; bekannte Teilsumme gleich der Summe der protokollierten Beträge des Backends; 480 bezahlte Fehlversuche, jeder protokollierte davon in der Teilsumme; 581 Läufe mit unbekanntem Gesamtbetrag, bei allen ist er `None`. 60 bezahlte `AdapterError` unter F-01 werden in beiden Wegen nicht protokolliert, weil `execute` sie unter F-01 weiterwirft (B4).

**Teil B, Studiensender am Ersatztransport (360 Läufe je Weg):** unveränderter `BlockSender` mit `fake_transport.py`, Szenarien `clean` und `faults` (ein Transport je Szenario wie ein Z53-Worker, damit dessen späte Sonderantworten ab dem 21. und 41. Aufruf vorkommen), `flaky:1`, `flaky:3`, `systemic:2`, `systemic:5` (frischer Transport je Lauf). Ausgänge: 168 abgeschlossen, 4 Modellausfälle, 2 bezahlte Endfehler (`TerminalArmFailure`), 108 `TechnicalAbort`, 78 `GlobalStop`. Alle 11 Prüfungen ohne Abweichung: Ausnahme, Trace, Senderzustand (Kosten je Versuch, unklare Versuche, Wiederholungen, Generationskennungen, Endfehler), sämtliche Anfrage-, Antwort-, Bindungs- und Versuchslistendateien bytegleich, Journalbytes, Prüfroutine; Kosten je Aufruf aus den Rohantworten unabhängig nachgerechnet gleich der Versuchsliste, unklare Versuche aus fehlenden Antwortdateien gleich der Versuchsliste, Journalbeträge gleich den Rohantworten, bezahlte Endfehler in den Senderkosten. Summen: 1.537 Sendeversuche, 302 unklar und nicht bewertet, 34 Wiederholungen nach Ratenlimit, 225 technische Wiederholungen, bekannte Summe 0,07206 USD (synthetisch).

Die Generationskennungen von `fake_transport.py` stammen aus `uuid4`; damit beide Wege bytegleich verglichen werden können, ersetzt `run_v3c.py` im eigenen Prozess das Modulattribut `uuid` durch einen Zähler je Weg. Die Datei selbst ist unverändert (Hash in `out/study-inputs-*.json` und im Framework-Manifest).

## V3d: 100 R-Blöcke mit gespeicherten Antworten

Befehle:
1. `runs/Z38-QSEM-001/provision/python/bin/python3.12 runs/Z56-FRAMEWORK-VALIDIERUNG-001/v3/z55_replay_guarded.py runs/Z56-FRAMEWORK-VALIDIERUNG-001/v3/out/v3d/z55-replay` (unverändertes `run_z55.py replay` ohne `--record` unter Netzsperre; vorher im Code geprüft: ohne `--record` schreibt `replay()` nur in `--folder`, `guard_write` sperrt Z31/Z52/Z53/Z54). Ausgabe: `{"blocks": 100, "fully_identical": 100, "errors": 0, …}`, Netzversuche 0 (`out/v3d/z55-replay-network.json`).
2. `/opt/anaconda3/bin/python3 run_v3d.py out/v3d/z55-replay`. Ergebnis `out/v3d/SUMMARY.json` (`f9288ff2…05b7`), Zeilen `rows.jsonl` (`16b2a663…843d`), Belege je Block unter `out/v3d/lg/`.

Wiederverwendet unverändert aus dem Framework-Modul von Z55: `DemoSender` (Z53-`BlockSender` mit Vorab-Prüfung der Runde-1-Bytes gegen Z53), `BrakedTransport`, `CostBrake`, `z53_arm`, `round1_bytes`, `load_task`, `parity`, `_provider`. Die Wiedergabe `Replay` hat die Logik von `run_z55.Replay` (Zeilen 194 bis 212), ist aber nachgebaut, weil der Import von `run_z55` die Python-3.12-Laufzeit von GPTSwarm vor `sys.path` setzt.

Ergebnis, 0 Abweichungen in 13 Prüfungen (einschließlich Bremsbuch): Aufrufmenge, Anfragebytes, Antworten, Abrechnung je Versuch und Armergebnis (Status, Antwort, Ausfallgrund, Aufrufzahl, Kosten, EM/F1 nur als Gleichheitsprüfung) gleich der Z55-Wiederholung; Runde 1, alle Anfragen, Antworten und Armergebnis gleich Z53; Journal jedes Arms von `read_journal` angenommen und bis auf die Lauf-ID gleich dem Z53-Journal desselben Arms; Bremsbuch gleich Z55; 0 Wiedergabelücken.

| Arm | erfolgreich | Modellausfall | Aufrufe | Kosten (wiedergegeben) | Nachrichten | abgeschaltete Graphkanten je Block | Aufrufe nicht aktiver Rollen |
|---|---|---|---|---|---|---|---|
| ⟦F*⟧ (C01) | 97 | 3 (`length`) | 491 | 0,12570271 USD | 582 | 14 von 20 | 0 |
| D | 95 | 5 (`length`) | 869 | 0,24139318 USD | 1.908 | 0 von 20 | 0 |

Jeder erfolgreiche Arm hatte 5 bzw. 9 Aufrufe. Die Beträge sind die in Z53 gemeldeten und nur wiedergegeben; ausgegeben wurde nichts. Gelesene Studiendaten vor und nach hashgleich (siehe unten).

## V3e: Fehlereinbau wie Z37

Befehl: `/opt/anaconda3/bin/python3 run_v3e.py`. Ergebnis `out/v3e/SUMMARY.json` (`c62e6175…3e`), je Fall Journal, Trace, Client-, Verbrauchs- und Anfragelisten unter `out/v3e/z56-*/`. Fallbau wie `generate.build_case` (drei Rollen evidence, linking, draft, Ring, F-01, zwei Runden); `SyntheticClient`, `manual_journal`, `reseal`, `trace_from_records`, `independently_priced` werden aus Z37 `generate.py` (SHA256 in der Zusammenfassung) unverändert importiert. Prüfroutine wie Z37 `run_instrument.py`: `audit` bzw. `audit_prefix` auf den Trace, `read_journal` auf das Journal; zusätzlich das Online-Ergebnis des Journals während des Laufs.

| Fall | Einbau in LangGraph | Z37 (Trace / Journal) | LangGraph (online / Trace / Journal) | Erwartung | Ergebnis |
|---|---|---|---|---|---|
| K1 | regulär | an / an | kein Abbruch / an / an, versiegelt | an | an |
| K3 | Modellausfall bei Aufruf 3 | an / an | kein Abbruch / an / an, versiegelt | an | an |
| K4 | technischer Stopp bei Aufruf 3 | an / an, offen | `RuntimeError` / an / an, offen | an | an |
| V1 | zusätzliche Kante `draft@1 → linking@2` im Graphen | ab / ab „invalid call or message visibility“ | `AuditError` „invalid call or message visibility“ beim Schreiben des Starts, kein Aufruf für `linking@2` / gespeichert: an, offen | ab | ab (online) |
| V2 | Knoten `aux` ruft den Client am Sender vorbei | an / an | kein Abbruch / an / an; innen 8 Aufrufe, außen 7 | an | an |
| V3 | Client meldet bei Aufruf 3 +0,00037 USD | an / an | kein Abbruch / an / an; gemeldet 0,0029312, innen 0,0025612 | an | an |
| V4 | technischer Stopp, Meldung „abgeschlossen“ | an / an, offen | `RuntimeError` / an / an, offen; Meldung widerspricht | an | an |
| V5 | Abschluss linking Runde 1 entfernt, neu versiegelt | ab / ab „terminal attempt mismatch“ | kein Abbruch / ab / ab, gleiche Meldung | ab | ab |
| V6 | erster Abschluss verdoppelt, neu versiegelt | ab / ab „invalid call or message visibility“ | kein Abbruch / ab / ab, gleiche Meldung | ab | ab |
| V7 | erster Abschluss auf checking umgehängt, neu versiegelt | ab / ab „terminal attempt mismatch“ | kein Abbruch / ab / ab, gleiche Meldung | ab | ab |
| V8 | Preisversion geändert, nicht neu versiegelt | an / ab „schema, sequence, or checksum mismatch“ | kein Abbruch / an / ab, gleiche Meldung | ab | ab |
| V1z (Zusatz) | V1 in Z37-Belegform: Start von `linking@2` beschreibt die vom V1-Graphen gelieferten Quellen, neu versiegelt | wie V1 | kein Abbruch / ab / ab „invalid call or message visibility“ | (Zusatz) | ab |

Beobachtetes Muster gleich dem vorab festgelegten: zurückgewiesen V1, V5, V6, V7, V8; angenommen V2, V3, V4. Bei V5 bis V8 und V1z stimmen auch die Meldungen der Prüfroutine wörtlich mit Z37 überein. V2, V3 und V4 zeigen dieselbe Grenze wie in Z37: Erst die innere Belegstufe (8 statt 7 Aufrufe; 0,0025612 statt 0,0029312 USD) bzw. die Meldung des Laufs (V4) deckt sie auf.

Abweichung im Belegweg bei V1 (B3): Im LangGraph-Weg entsteht die verbotene Nachricht im fremden Graphen vor dem Sender. Das unveränderte Journal prüft den Start vor dem Schreiben und bricht mit `AuditError` ab; der Aufruf findet nicht statt, und `draft@2` wird vor dem Sender angehalten. Das gespeicherte Journal enthält deshalb nur die vier vorherigen Aufrufe, ohne offenen Versuch, und wird nachträglich als unversiegeltes Präfix angenommen. Der Grund des Abbruchs steht nur in der Ausnahme (`out/v3e/z56-v1/run-exception.log`), nicht im Journal. Die Zurückweisung durch die Prüfroutine findet also statt, früher als in Z37, ist aber in den gespeicherten Belegen allein nicht sichtbar. In Z37 war V1 nachträglich ins Journal geschrieben worden; diese Belegform (V1z) weist die Prüfroutine wie in Z37 zurück.

## V3f: Rezeptprotokoll

### Die vier Teile aus N3021/N3022

| Teil | angepasst | wie |
|---|---|---|
| 1. Schnittstelle | ja | Graphaufbau mit Maske, Zustellregel entlang der Graphkanten, Knotenfunktionen, Gate, Sender. Der Sender ist im Framework für das Journalformat nicht als eigener Baustein vorhanden: Kopf des Traces und die Aufruflogik von `execute` (`execution.py` Zeilen 20 bis 39 und 59 bis 86) wurden als `header` (17 Codezeilen) und `LoggingSender` (34) nachgebildet und per Differenztest gegen `execute` abgesichert (B1). `ArmContext` aus Z55 ist nicht wiederverwendbar: zwei Runden und GPTSwarm-Knotennamen fest verdrahtet, eigenes Belegformat, das `audit` nicht liest. |
| 2. Anbieter | nein | Derselbe Vertrag wie in der Studie: Payload und `decode_billing` aus `openrouter.py`, `BlockSender`/`DemoSender` unverändert (V3c Ersatztransport, V3d Wiedergabe). Die Herkunft `token_price` mit Preisversion lief nur über synthetische Beträge (V3b) durch die Prüfroutine. Ein anderer realer Anbieter ist nicht erprobt. |
| 3. Datensatzabhängige Teile | nein | Nicht berührt: keine Auswahl, keine Familienregel, keine Textmerkmale von ⟦Q⟧. V3d nutzt MuSiQue-Blöcke und `score_answer` nur zur Gleichheitsprüfung mit Z55/Z53. |
| 4. Konfigurationsraum | nein | `bank()` (14) und `dense()` unverändert; Maske nach der Regel von `execute`; möglicher Graph mit 20 Kanten wie in Z55. Fünf Rollen nicht erprobt. |

### Die als unverändert übernehmbar bezeichneten Teile

| Teil | tatsächlich unverändert | Beleg |
|---|---|---|
| Zählregel | ja | V3b: Aufrufe = aktive Rollen × Runden + 1 in allen 1.080 Läufen; abgeschaltete Graphkanten getrennt gezählt (C01 bis C06: 14, Ringe: 11, volle Dreiergruppen: 8, D: 0 von 20) und ohne Einfluss auf die Aufrufzahl; 0 Aufrufe nicht aktiver Rollen; V3d 5 bzw. 9. |
| Zurechnung je Sendeversuch | ja | Unveränderter `BlockSender`: V3c Teil B 1.537 Versuche, Kosten je Aufruf aus Rohantworten gleich der Versuchsliste; V3d Bremsbuch gleich Z55. |
| Führung unbekannter Beträge | ja | Unveränderte `Usage`/`audit`/`BlockSender`: unbekannt bleibt `None` (V3b 650, V3c-A 581 Läufe), 302 unklare Versuche gezählt, nicht bewertet. |
| Belegstufen des Prüfwegs | ja, mit B3 | Meldung, Journal mit Anfragen, innere Belege wie Z37; Muster und Meldungen gleich Z37. Bei einer im fremden Graphen entstehenden Rechteverletzung greift die Prüfroutine bereits beim Schreiben; die gespeicherte zweite Stufe zeigt dann nur einen abgebrochenen Lauf. |

### Nötige Vorbedingungen an das fremde System

1. Jeder Modellaufruf muss an einer Stelle abgreifbar sein, an der Rolle, Runde und die tatsächlich weitergegebenen Nachrichten bekannt sind (in LangGraph: eigene Knotenfunktionen). Aufrufe am Sender vorbei sieht die Prüfroutine nicht (V2).
2. Die Aufrufe müssen den Sender in der strengen Protokollreihenfolge erreichen, die Journal und `audit` verlangen. LangGraph rechnet einen Superstep nebenläufig; ohne Gate wären die Journale nicht annehmbar (B2).
3. Synchrone Runden als geschichteter Graph (Runde k nur zu Runde k+1, Zusammenführung zuletzt), je Rolle und Runde genau ein Aufruf. Schleifen, Wiederholungsregeln (`RetryPolicy`) oder Wiederaufnahme per Checkpointer müssten ausgeschlossen bzw. ausgerollt werden (nicht erprobt).
4. Weitergegebene Nachrichten müssen ihren Erzeuger tragen (Kennung, Rolle, Runde), damit die Prüfroutine sie zuordnen kann.
5. Ein Modellausfall muss den fremden Lauf beenden. LangGraph reicht Knotenausnahmen weiter; GPTSwarm verschluckte sie und brauchte deshalb Sperren in `ArmContext`.
6. Rollen und Anweisungen kommen aus `contracts.ROLES`/`INSTRUCTIONS`; andere Rollen verlangen eine Anpassung des Konfigurationsraums.

### Umfang des Anschlusscodes

`lg_adapter.py`: 209 Codezeilen. Davon Nachbildung von `execute` 52 (Kopf 17, Sender 34, Ausnahme 1), Maske und Reihenfolge 21, Gate mit Ausnahmen 27, Graphaufbau und Zustellung 38, Laufsteuerung 59, Importe und Konstanten 12. Für V3d zusätzlich 55 Zeilen Rahmen in `run_v3d.py` (`Replay` 15, `run_arm` 25, `run_block` 15). Zum Vergleich der GPTSwarm-spezifische Teil von `gptswarm_musique_demo.py`: `build_original` 66, `ArmContext` 76, `run_arm` 36, Hilfsfunktionen 19.

### Was an LangGraph anders ist als an GPTSwarm

- Keine eingebaute Kantenmaske: GPTSwarm realisiert die Maske über `EdgeWiseDistribution.realize` mit festen Logits; in LangGraph wird sie beim Aufbau angewendet (nur maskierte Kanten werden angelegt).
- Kanten tragen keine Daten: GPTSwarm gibt Vorgängerausgaben als Eingabe weiter; in LangGraph sind Kanten Auslöser, Daten liegen im Zustand. Die Zustellregel „Ausgaben der Eingangsquellen im Graphen“ legt der Anschluss fest.
- Nebenläufigkeit: GPTSwarm lief in topologischer Reihenfolge nacheinander; LangGraph rechnet Supersteps im Threadpool, daher das Gate.
- Ausnahmen: GPTSwarm (`Node.execute`) verschluckt sie; LangGraph reicht sie weiter, der Anschluss holt die ursprüngliche Ausnahme aus dem Gate zurück.
- Vereinigung mehrerer Vorgänger über wartende Kanten (`add_edge([..], ziel)`); in GPTSwarm implizit.
- Prüfweg: Z55 prüfte mit dem eigenen `verify_block` auf einem eigenen Belegformat; der LangGraph-Anschluss schreibt das Journalformat, sodass die generische Prüfroutine `audit`/`read_journal` unverändert gilt.
- `get_graph()` zeigt Kanten nie laufender Knoten nicht; zur Zustellung dienen die Builder-Attribute (B6).

## Befunde

- **B1 Kein eigenständiger Sender für das Journalformat.** Das Rezept spricht vom „protokollierenden Sender des Frameworks“. Für das generische Journalformat existiert er nur als innere Funktion `call` in `execution._execute`; der Anschluss musste 52 Zeilen nachbilden. Gleichheit ist per Differenztest belegt, nicht durch gemeinsame Nutzung. Kleinste Änderung (nicht ausgeführt): Kopf und `call` als öffentliche Klasse in `execution.py` herauslösen, die `execute` selbst verwendet.
- **B2 Reihenfolge als Vorbedingung.** Journal und `audit` verlangen eine strenge sequenzielle Aufrufreihenfolge; LangGraph lieferte in 1.011 von 1.080 Läufen eine andere Ankunftsreihenfolge. Ohne Gate (oder eine gleichwertige Serialisierung) ist der Anschluss nicht annehmbar. Im Rezept nicht genannt.
- **B3 Online-Zurückweisung wird nicht gespeichert.** Eine im fremden Graphen entstandene Rechteverletzung weist das Journal beim Schreiben zurück; im gespeicherten Journal bleibt nur ein unversiegeltes Präfix ohne offenen Versuch, das `read_journal` annimmt. Den Grund kennt nur die Ausnahme. Kleinste Änderung (nicht ausgeführt): beim Abbruch durch `AuditError` einen abschließenden Eintrag mit Grund schreiben oder die Ausnahme im Laufbeleg sichern.
- **B4 Bezahlter `AdapterError` unter F-01 nicht im Journal.** `execute` wirft einen `AdapterError` unter F-01 weiter, auch mit bekanntem Betrag; der Betrag steht dann nur beim Sender (60 Fälle in V3c-A, in beiden Wegen gleich). In der Studie trat das nicht auf, weil `BlockSender` keinen `AdapterError` wirft; ein neuer Anbieteranschluss müsste bezahlte Fehlversuche in der Versuchsliste halten.
- **B5 Bezahlter Endfehler nur in der Versuchsliste.** Bei `TerminalArmFailure` bleibt das Journal offen, der Betrag steht in der Versuchsliste (V3c-B, 2 Fälle), wie im eigenen Weg und in Z53 vorgesehen.
- **B6** `get_graph()` von LangGraph unterschlägt Kanten von Knoten ohne Eingang; für Zustellung und Belege werden `StateGraph.edges`/`waiting_edges` genutzt.

## Abweichungen vom Plan

- ProjectAtlas nicht verfügbar (siehe Rahmen).
- V3b: D zusätzlich zu den 14 Konfigurationen; drei Ausgabeverträge statt eines.
- V3c: `uuid4` des Ersatztransports im Prozess deterministisch ersetzt (Datei unverändert); für `clean` und `faults` ein Transport je Szenario, für `flaky` und `systemic` je Lauf. Zusätzlich Vertragsfehler ohne Anbieter (Teil A).
- V3d: `Replay` nachgebaut statt importiert (Grund oben); die Z55-Wiederholung wurde neu in `out/v3d/z55-replay` erzeugt, nicht `REPLAY-001.json` verwendet.
- V3e: V3 und V4 wie in Z37 über die Client-Modi (falscher Adapterbetrag, falsche Abschlussmeldung), V5 bis V8 als Bearbeitung der erzeugten Journaleinträge. Der verdeckte Aufruf in V2 liegt nach Runde 1 (eigener Superstep), nicht direkt nach Aufruf 2 wie in Z37, damit die Reihenfolge deterministisch bleibt. K2 (unterdrückte Rolle) nicht gebaut, weil der Anschluss `failed_role` nicht umsetzt; K1, K3, K4 und V1z sind Zusätze.
- V3b: Quellbindung `out/v3b/SOURCES.json` nachträglich geschrieben (Dateien zwischen Lauf und Bindung nicht verändert, ab V3c wird vor dem Lauf gebunden). Alle vier Bindungen stimmen mit dem Ist-Stand überein.
- Hashstand der Studiendaten vor V3d/V3e aufgenommen; V3b und V3c lasen keine Studiendaten außer `fake_transport.py`, das im Framework-Manifest steht.

Gelesene Studiendaten (`out/study-inputs-before.json`, `bcc00363…cd32`; `out/study-inputs-after.json`, `a875b01a…858c`; Vergleich `out/study-inputs-compare.json`): Z53-Blöcke R-02183 bis R-02282 (15.338 Dateien), Z55-Ordner (6.622), GPTSwarm-Original Z31 (29), Z37-Ordner (405), `fake_transport.py`: alle hashgleich, keine neue, fehlende oder geänderte Datei.

## Grenzen

- Selbstprüfung des Urhebers; die getrennte Prüfung (V4) steht aus, eine externe Begutachtung gibt es nicht.
- Nur Ersatz-Backends und Wiedergabe gespeicherter Antworten; kein echtes Sprachmodell, kein anderer Anbieter.
- Nur synchrones `invoke`; nicht erprobt: `ainvoke`, Streaming, Checkpointer und Wiederaufnahme, `RetryPolicy`, vorgefertigte Agenten, Werkzeugaufrufe, Schleifen, fünf Rollen, unterdrückte Rolle (`failed_role`).
- Der Differenztest vergleicht zwei Wege, die Journal, Verträge und Prüfroutine teilen; er belegt Gleichheit des Anschlusses mit `execute`, nicht die Richtigkeit dieser gemeinsamen Teile (dafür V1, V2, V4).
- Das Gate nimmt LangGraph für die Modellaufrufe die Nebenläufigkeit; Laufzeitfolgen sind nicht untersucht.
- Aussagen gelten für LangGraph 1.0.6 in der beschriebenen Bauweise (eigene Knotenfunktionen, geschichteter Graph).

## Folgerung für N3021/N3022 (Vorschlag, keine Änderung der Arbeit)

Das Rezept trägt an LangGraph: Mit angepasster Schnittstelle und sonst unveränderten Teilen entstehen dieselben Anfragen, Protokolle, Kosten und Prüfurteile wie im eigenen Weg und wie in Z53/Z55. Zwei Ergänzungen lägen nahe: (1) die Vorbedingung einer sequenziellen Aufrufreihenfolge (bei nebenläufigen Systemen eine Serialisierung vor dem Sender) und (2) der Hinweis, dass der protokollierende Sender für das Journalformat bisher Teil der eigenen Ausführung ist und beim Anschluss nachgebildet werden muss. Der Satz „durchgeführt ist bisher der Anschluss an GPTSwarm“ ließe sich um eine Offline-Übertragung auf LangGraph mit Ersatz-Backend und Wiedergabe ergänzen. Für die Belegstufen wäre B3 zu erwähnen, falls die Arbeit die Rechteprüfung beim Schreiben beschreibt.

## Reproduktion und Dateien

Arbeitsverzeichnis `eval-harness/eval/runs/Z56-FRAMEWORK-VALIDIERUNG-001/v3`, Umgebung `PYTHONDONTWRITEBYTECODE=1`:

```
/opt/anaconda3/bin/python3 -m unittest discover -s tests
/opt/anaconda3/bin/python3 run_v3b.py
/opt/anaconda3/bin/python3 run_v3c.py
/opt/anaconda3/bin/python3 hash_inputs.py snapshot out/study-inputs-before.json
(cd ../../.. && runs/Z38-QSEM-001/provision/python/bin/python3.12 runs/Z56-FRAMEWORK-VALIDIERUNG-001/v3/z55_replay_guarded.py runs/Z56-FRAMEWORK-VALIDIERUNG-001/v3/out/v3d/z55-replay)
/opt/anaconda3/bin/python3 run_v3d.py out/v3d/z55-replay
/opt/anaconda3/bin/python3 run_v3e.py
/opt/anaconda3/bin/python3 run_v3a.py
/opt/anaconda3/bin/python3 hash_inputs.py snapshot out/study-inputs-after.json
/opt/anaconda3/bin/python3 hash_inputs.py compare out/study-inputs-before.json out/study-inputs-after.json
```

| Datei | SHA256 |
|---|---|
| `lg_adapter.py` | `8ad76454137addac17a9f1d4bbd19df26f4dd2deb9529b0c6615886ace13df2b` |
| `backends.py` | `4a7f11d2d36fbdaff05d8c796bc7a97c86d5d70152a75a1b7bfb2fc0f9a90c23` |
| `common.py` | `ca08dd61339c9999e1ba48759a99af35db1833b5cb85130b26ac2d79aa007b2c` |
| `netguard.py` | `26268f84acf4eca2dc623c803e9b02242a35751e127d2f73b95f274092af1164` |
| `binding.py` | `b4c2a3b7dc91bc45346ca254027956c54e258b06489fb6238145cbecbd018fe1` |
| `tests/test_v3_adapter.py` | `9c32b577aa242b1b098ffdd3399939b8c57c2ae9a60777aed53c1cbf5fd1fdd4` |
| `run_v3a.py` | `08b2afae5b47165f04a19e7363a52015565cbd48fb540acc396ae7fd93557f8f` |
| `run_v3b.py` | `f03193019369f17ad444b8cbaeae61b34e7a4a42c5debc7ff2bb8ce4948a80ac` |
| `run_v3c.py` | `26ff3146938d4db02c3f8019894e4139b5419303799c34cd50251b062f7f4429` |
| `run_v3d.py` | `b917326478995e714e70a7ed3ff0b210e928f7c24aceae1b8727a4879a5ce887` |
| `run_v3e.py` | `c064593099d41fea9e530093b348582e4f330653cfc28ee7142897aae489b2a2` |
| `z55_replay_guarded.py` | `7af6faf2e4a583894781092b3b8eb8e4ea54e994839d29e8589c9d12bf991072` |
| `hash_inputs.py` | `8230a47a521ee5084270cf9b3449844c429f247b376f3b8c176af212f7cced03` |
| `out/v3a/RESULT.json` | `c5acd47ebc1228f367ab8e731467e4de2bc803155398aa592bf56f8bfee3d90c` |
| `out/v3b/SUMMARY.json` | `ec9ddccb966222106b4218c4c99d4f1b1ac1131f6bf1ebc206f3d88b812e61a6` |
| `out/v3c/SUMMARY.json` | `f20800008196865e6f9f467bae1b97d1461ab374e53acbdaefbb2b032f4d5e83` |
| `out/v3c/raw.zip` | `2ecdf6bf23936035f981b781a78ae4356966e99c1d3f6568efb41445ce29f79b` |
| `out/v3d/SUMMARY.json` | `f9288ff21a7412751bb4971563334dc12b8fdcc54fad2467770d8b4e56a105b7` |
| `out/v3d/z55-replay-network.json` | `f0194e83675ef4b77b0b9454cde42577246b4e492ff21acd65cbd2152a2e7820` |
| `out/v3e/SUMMARY.json` | `c62e61755728cb72d03fd8f9aafd970f4171cdb135f05d819187f1a430208e3b` |
| `out/study-inputs-compare.json` | `c042697eec874e44f2d586727991c8c9c1ff5638a7f5251b2a796a881e36128f` |

Nächster gebundener Schritt: getrennte Prüfung von Anschlusscode und Ergebnissen durch Codex (V4b); danach Übernahme in `project/dsr/Z56-FRAMEWORK-VALIDIERUNG-ERGEBNIS.md` durch die Koordination.
