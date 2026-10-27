"""Baut das Eingangspaket der getrennten Nachrechnung N (nur lesend auf Quellen).

Quellen: Z56-Laufmanifest (Zuordnung Protokoll -> Paar), PLAN.json (MuSiQue-ID je Block),
Studienprotokolle journal.jsonl, MuSiQue-Dev, answer.py, Plan- und Formatdokumente.
Schreibt ausschliesslich unter <arbeitsordner>/eingang und <arbeitsordner>/zuordnung.
Kein Ergebnisfeld (row, result.json) wird gelesen oder kopiert.
"""
import gzip, hashlib, json, os, shutil, sys
from pathlib import Path

ARBEIT = Path(__file__).resolve().parent.parent
EINGANG = ARBEIT / "eingang"
ZUORD = ARBEIT / "zuordnung"
REPO = Path("/Users/jannikhiller/Desktop/ai operations/Studium OS/communication-pruning-framework")
MA = Path("/Users/jannikhiller/Desktop/ai operations/Studium OS/Masterarbeit")
RUNS = MA / "eval-harness/eval/runs"
Z56 = REPO / "nachpruefungen-nach-studienabschluss/pruefroutine-studienlaeufe"
MUSIQUE = MA / "archive/neustart-2026-08-30/legacy-artifact/eval-harness/data/vendor/musique-v1.0/data/musique_ans_v1.0_dev.jsonl"
MUSIQUE_SKRIPTE = MA / "output/quellenpruefung-2026-10-25/quellen/53-stonybrooknlp-musique"
SOLL_ANSWER_SHA = "10368f619b4d5ef5d83748c05a96c0afd332a14ab5c010740c98d58dfaefe974"


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    if EINGANG.exists() and any(EINGANG.iterdir()):
        sys.exit("eingang/ ist nicht leer; Abbruch statt Ueberschreiben")
    EINGANG.mkdir(exist_ok=True)
    ZUORD.mkdir(exist_ok=True)

    # Z56-Dateimanifest: Pruefsummen der Studienprotokolle, wie am 20.10. erfasst
    file_sha = {}
    for line in gzip.open(Z56 / "MANIFEST-FILES.jsonl.gz", "rt", encoding="utf-8"):
        r = json.loads(line)
        if r["path"].endswith("/journal.jsonl"):
            file_sha[r["path"]] = r["sha256"]

    plan = json.load(open(REPO / "auswertungsplan/PLAN.json", encoding="utf-8"))
    plan_p = plan["panels"]["P"]
    assert len(plan_p) == 9040

    runs = []
    for line in gzip.open(Z56 / "MANIFEST-RUNS.jsonl.gz", "rt", encoding="utf-8"):
        r = json.loads(line)
        if r["panel"] != "P":
            continue
        # nur Zuordnungsfelder; 'row' und 'files' (Ergebnis bzw. result.json) werden nicht verwendet
        runs.append({k: r[k] for k in ("arm", "block_id", "draw_index", "slot_id", "journal", "kind")})
    assert len(runs) == 18080, len(runs)

    seen = set()
    zeilen, herkunft = [], []
    for r in runs:
        i, arm = r["draw_index"], r["arm"]
        assert r["kind"] == "mas" and arm in ("Q", "F")
        assert (i, arm) not in seen
        seen.add((i, arm))
        pb = plan_p[i]
        assert pb["draw_index"] == i and pb["block_id"] == r["block_id"], (i, r["block_id"])
        assert r["slot_id"] == r["block_id"] + ":" + arm
        src = RUNS / r["journal"]
        rel = f"protokolle/{arm}/{i:05d}.jsonl"
        dst = EINGANG / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        s_src, s_dst = sha(src), sha(dst)
        assert s_src == s_dst == file_sha[r["journal"]], r["journal"]
        zeilen.append((i, arm, r["block_id"], pb["task_id"], r["slot_id"], rel))
        herkunft.append((rel, r["journal"], s_dst))
    assert len(seen) == 18080

    order = {"Q": 0, "F": 1}
    zeilen.sort(key=lambda z: (z[0], order[z[1]]))
    with open(EINGANG / "laufliste.tsv", "w", encoding="utf-8", newline="\n") as f:
        f.write("paarindex\tarm\tblock_id\tmusique_id\tlauf_kennung\tpfad\n")
        for z in zeilen:
            f.write("\t".join(str(x) for x in z) + "\n")
    herkunft.sort()
    with open(ZUORD / "HERKUNFT-PROTOKOLLE.tsv", "w", encoding="utf-8", newline="\n") as f:
        f.write("pfad_eingang\tquelle_relativ_zu_eval-harness/eval/runs\tsha256\n")
        for h in herkunft:
            f.write("\t".join(h) + "\n")

    # MuSiQue-Dev und Bewertungsskript
    (EINGANG / "daten").mkdir()
    shutil.copyfile(MUSIQUE, EINGANG / "daten/musique_ans_v1.0_dev.jsonl")
    ids = {json.loads(l)["id"] for l in open(EINGANG / "daten/musique_ans_v1.0_dev.jsonl", encoding="utf-8")}
    fehlend = {z[3] for z in zeilen} - ids
    assert not fehlend, fehlend
    (EINGANG / "bewertung/metrics").mkdir(parents=True)
    assert sha(MUSIQUE_SKRIPTE / "answer.py") == SOLL_ANSWER_SHA
    shutil.copyfile(MUSIQUE_SKRIPTE / "answer.py", EINGANG / "bewertung/metrics/answer.py")
    shutil.copyfile(MUSIQUE_SKRIPTE / "evaluate_v1.0.py", EINGANG / "bewertung/evaluate_v1.0.py")
    (EINGANG / "bewertung/metrics/metric.py").write_text(
        '"""Platzhalter fuer die im Original vorhandene, hier fehlende Basisklasse metrics/metric.py.\n\n'
        'Nur damit "from metrics.metric import Metric" in answer.py importierbar ist. normalize_answer,\n'
        'compute_exact, compute_f1 und metric_max_over_ground_truths haengen nicht davon ab.\n"""\n\n\n'
        'class Metric:\n    pass\n', encoding="utf-8")

    # Plan- und Formatdokumente aus dem oeffentlichen Repository (Commit 3ca3c6a)
    (EINGANG / "plan").mkdir()
    (EINGANG / "format").mkdir()
    for src, dst in [("auswertungsplan/PLAN.json", "plan/PLAN.json"),
                     ("auswertungsplan/ANALYSIS-BINDING.json", "plan/ANALYSIS-BINDING.json"),
                     ("auswertungsplan/dokumente/METHODEN-UND-INFORMATION.md", "plan/METHODEN-UND-INFORMATION.md"),
                     ("ergebnisse/messabnahme/verdeckt/contract.md", "format/contract.md")]:
        shutil.copyfile(REPO / src, EINGANG / dst)
        assert sha(REPO / src) == sha(EINGANG / dst)

    print(json.dumps({"laeufe": len(zeilen), "paare": len({z[0] for z in zeilen}),
                      "musique_ids": len({z[3] for z in zeilen})}, ensure_ascii=False))


if __name__ == "__main__":
    main()
