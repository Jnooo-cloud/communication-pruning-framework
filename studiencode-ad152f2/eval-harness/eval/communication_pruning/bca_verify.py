"""Verify and replay preserved Z11 evidence; creates one new receipt only."""

from dataclasses import asdict
from hashlib import sha256
from itertools import groupby
import json
import math
from pathlib import Path
import sys
import zipfile

import numpy as np

from .bca import bca_report, family_jackknife
from .bca_validation import ARTIFACT, ROOT, simulation_definitions, summarize
from .inference import FamilyTotal, estimate, interval_report, resampled_estimates


def main():
    out=ARTIFACT/"runs/Z11-VERIFICATION.json"
    if out.exists():
        raise SystemExit("existing verification cannot be overwritten")
    receipts=[]
    for folder in sorted((ARTIFACT/"runs").glob("Z11-*")):
        path=folder/"receipt.json"
        if not path.is_file():
            continue
        r=json.loads(path.read_text())
        assert r["status"]=="completed" and r["source_unchanged_during_run"]
        assert all(t["returncode"]==0 for t in r["tests"])
        assert sha256((folder/"source.zip").read_bytes()).hexdigest()==r["source_bundle_sha256"]
        with zipfile.ZipFile(folder/"source.zip") as z:
            assert z.testzip() is None and set(z.namelist())==set(r["files_sha256"])
            for p,h in r["files_sha256"].items():
                assert sha256(z.read(p)).hexdigest()==h
        if "trials_sha256" in r:
            raw=folder/"trials.jsonl"
            assert sha256(raw.read_bytes()).hexdigest()==r["trials_sha256"]
            assert sha256((folder/"evidence.zip").read_bytes()).hexdigest()==r["evidence_bundle_sha256"]
            with zipfile.ZipFile(folder/"evidence.zip") as z:
                assert z.testzip() is None and z.read("trials.jsonl")==raw.read_bytes()
        receipts.append(dict(path=str(path.relative_to(ROOT)),sha256=sha256(path.read_bytes()).hexdigest()))
    folder=ARTIFACT/"runs/Z11-SIM-002"
    receipt=json.loads((folder/"receipt.json").read_text())
    scenarios,generate,_,_=simulation_definitions()
    counts={};parity=[]
    with (folder/"trials.jsonl").open() as raw:
        for name,group in groupby((json.loads(line) for line in raw),lambda r:r["scenario"]):
            assert name not in counts
            records=list(group);counts[name]=len(records)
            assert {r["dataset"] for r in records}==set(range(1000))
            s=next(s for s in scenarios if s["name"]==name)
            expected=next(r for r in receipt["results"] if r["scenario"]==s)
            assert summarize(s,records)==expected
            # Independent counts of decisions and defined endpoints.
            for method in ("percentile","basic","bca"):
                for margin in (.03,.05):
                    hits=sum(r["methods"][method]["assessable"] and r["methods"][method]["quality_bounds"][0]>-margin
                             and r["methods"][method]["cost_ratio_bounds"][1]<.9 for r in records)
                    assert hits==expected["methods"][method]["joint"][str(margin)]["all_datasets"]["hits"]
                for key,field in [("quality","quality_bounds"),("cost","cost_ratio_bounds")]:
                    assert sum(r["methods"][method][field] is not None for r in records)==expected["methods"][method]["components"][key]["defined_count"]
            r=records[0];rng=np.random.default_rng();rng.bit_generator.state=r["states"]["data"]
            totals=generate(s,rng)
            assert [asdict(t) for t in totals]==r["families"]
            rng.bit_generator.state=r["states"]["bootstrap"]
            ix=rng.integers(0,s["g"],size=(1999,s["g"]))
            samples=resampled_estimates(totals,ix,backend="numpy")
            assert bca_report(totals,samples)==r["methods"]["bca"]
            for m in ("percentile","basic"):
                assert interval_report(totals,samples,method=m)==r["methods"][m]
            # Direct deletion reference for every family in the replayed dataset.
            for i,fast in enumerate(family_jackknife(totals)):
                slow=estimate(totals[:i]+totals[i+1:])
                assert all(math.isclose(x,y,abs_tol=1e-12,rel_tol=1e-12) for x,y in zip(fast,slow))
            scalar=resampled_estimates(totals,ix.tolist())
            max_error=max(abs(a-b) for left,right in zip(samples,scalar) for a,b in zip(left,right))
            assert max_error<1e-10
            scalar_bca=bca_report(totals,scalar)
            # Observe rank/interval sensitivity to floating-point tie handling.
            differences={}
            for key in ("quality","cost"):
                a=scalar_bca["components"][key];b=r["methods"]["bca"]["components"][key]
                differences[key]=dict(scalar_reason=a["reason"],numpy_reason=b["reason"],
                    z0_difference=None if a["z0"] is None or b["z0"] is None else a["z0"]-b["z0"],
                    max_bound_difference=None if a["bounds"] is None or b["bounds"] is None else max(abs(x-y) for x,y in zip(a["bounds"],b["bounds"])))
            parity.append(dict(scenario=name,max_point_difference=max_error,bca_backend_sensitivity=differences))
    assert counts=={s["name"]:1000 for s in scenarios}
    result=dict(receipts=receipts,counts=counts,total=12000,exact_rng_replays=12,
                summaries_recomputed=True,independent_decision_counts=True,jackknife_direct_deletion_checked=True,
                backend_checks=parity,verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                scope="same-agent self-check; no independent review",python=sys.version,numpy=np.__version__)
    with out.open("x") as f:
        json.dump(result,f,indent=2,allow_nan=False);f.write("\n")
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
