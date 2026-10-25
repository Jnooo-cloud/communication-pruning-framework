"""Create-only Z11 tests and simulation receipts outside research-history scope.

Run from eval-harness/eval: python -m communication_pruning.bca_validation 001
Use --tests-only for stdlib regression without NumPy. Synthetic data only.
"""

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import traceback
import zipfile

from .bca import bca_report
from .inference import hypothetical_decision, interval_report, resampled_estimates

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "eval-harness/eval"


def simulation_definitions():
    sys.path.insert(0, str(ROOT / "project/dsr"))
    from run_z10_simulation import SCENARIOS, generate, moments, rate
    extra = [dict(s, name=name, g=400) for s,name in
             [(SCENARIOS[0],"study_quality_boundary"),(SCENARIOS[1],"study_cost_boundary"),
              (SCENARIOS[4],"study_unequal_boundary"),(SCENARIOS[5],"study_skew_boundary")]]
    return SCENARIOS+extra, generate, moments, rate


def summarize(s, records):
    import numpy as np
    _, _, moments, rate = simulation_definitions()
    output = dict(scenario=s, datasets=len(records), methods={})
    for method in ("percentile", "basic", "bca"):
        reports = [r["methods"][method] for r in records]
        result = dict(unassessable=rate([not r["assessable"] for r in reports]), joint={}, components={})
        for key, field, pointkey, truth, lower in [("quality","quality_bounds","quality_difference",s["delta"],True),
                                                   ("cost","cost_ratio_bounds","cost_ratio",s["rho"],False)]:
            defined = [r for r in reports if r[field] is not None]
            miss = lambda r: r[field][0] > truth if lower else r[field][1] < truth
            miss_all = rate([r[field] is not None and miss(r) for r in reports])
            conditional = rate([miss(r) for r in defined]) if defined else None
            result["components"][key] = dict(defined_count=len(defined), undefined_count=len(reports)-len(defined),
                miss_events_per_all_datasets=miss_all, miss_rate_among_defined=conditional,
                width_among_defined=moments([r[field][1]-r[field][0] for r in defined]) if len(defined)>1 else None,
                bias=moments([r[pointkey]-truth for r in reports]),
                empirical_sd=float(np.std([r[pointkey] for r in reports],ddof=1)),
                warning=conditional is not None and conditional["mc_wilson95"][0] > .025)
        for margin in (.03,.05):
            result["joint"][str(margin)] = dict(
                interpretation="false_positive_rate" if s["delta"] <= -margin or s["rho"] >= .9 else "power_under_this_scenario",
                all_datasets=rate([hypothetical_decision(r,quality_margin=margin,cost_ratio_limit=.9) is True for r in reports]))
        if method == "bca":
            reasons = Counter(c["reason"] for r in reports for c in r["components"].values() if c["reason"])
            result["component_reason_counts"] = dict(reasons)
            result["tail_warning"] = rate([any(c["tail_resolution_warning"] for c in r["components"].values()) for r in reports])
        output["methods"][method] = result
    output["paired_bca_minus_percentile"] = {}
    for key, field, truth, lower in [("quality","quality_bounds",s["delta"],True),("cost","cost_ratio_bounds",s["rho"],False)]:
        deltas=[]
        for r in records:
            b,p = r["methods"]["bca"][field],r["methods"]["percentile"][field]
            if b is not None and p is not None:
                deltas.append(int(b[0]>truth)-int(p[0]>truth) if lower else int(b[1]<truth)-int(p[1]<truth))
        output["paired_bca_minus_percentile"][key] = dict(jointly_defined_count=len(deltas),
                                                           difference=moments(deltas) if len(deltas)>1 else None)
    return output


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("run")
    parser.add_argument("--tests-only",action="store_true")
    parser.add_argument("--datasets",type=int,default=1000)
    parser.add_argument("--draws",type=int,default=1999)
    args=parser.parse_args()
    if not args.run.isdigit() or args.datasets<2 or args.draws<2:
        parser.error("numeric run and at least two datasets/draws required")
    name="Z11-"+("TEST-" if args.tests_only else "SIM-")+args.run
    folder=ARTIFACT/"runs"/name
    if folder.exists():
        parser.error("existing run cannot be overwritten")
    folder.mkdir(mode=0o700)
    files=sorted(set((ARTIFACT/"communication_pruning").glob("*.py"))|set((ARTIFACT/"tests").glob("*.py"))|
                 {ROOT/"project/dsr/Z11-PLAN.md",ROOT/"project/dsr/run_z10_simulation.py",ARTIFACT/"README.md"})
    hashes={}
    with zipfile.ZipFile(folder/"source.zip","x",compression=zipfile.ZIP_DEFLATED) as archive:
        for p in files:
            content=p.read_bytes(); relative=str(p.relative_to(ROOT))
            archive.writestr(relative,content);hashes[relative]=sha256(content).hexdigest()
    now=lambda:datetime.now(timezone.utc).isoformat()
    receipt=dict(run_id=name,started_at=now(),python=sys.version,executable=sys.executable,platform=platform.platform(),
                 command=sys.argv,status="running",data="synthetic only",model_cost_usd="0",master_seed=20260906011,
                 datasets=args.datasets,draws=args.draws,files_sha256=hashes,
                 source_bundle_sha256=sha256((folder/"source.zip").read_bytes()).hexdigest(),tests=[],results=[])
    try:
        for command in [[sys.executable,"-m","unittest","discover","-s","tests","-v"],
                        [sys.executable,"-m","communication_pruning"],[sys.executable,"-m","communication_pruning.demo"]]:
            result=subprocess.run(command,cwd=ARTIFACT,capture_output=True,text=True,timeout=120)
            receipt["tests"].append(dict(command=command,returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
        if any(t["returncode"] for t in receipt["tests"]):
            receipt["status"]="tests_failed"
            return 1
        if not args.tests_only:
            import numpy as np
            receipt["numpy"]=np.__version__
            scenarios,generate,_,_=simulation_definitions()
            with (folder/"trials.jsonl").open("x") as raw:
                for si,s in enumerate(scenarios):
                    records=[]
                    for i in range(args.datasets):
                        data_seed=[20260906011,si,i,0];boot_seed=[20260906011,si,i,1]
                        rng=np.random.default_rng(data_seed);boot=np.random.default_rng(boot_seed)
                        states=dict(data=rng.bit_generator.state,bootstrap=boot.bit_generator.state)
                        totals=generate(s,rng)
                        indices=boot.integers(0,s["g"],size=(args.draws,s["g"]))
                        samples=resampled_estimates(totals,indices,backend="numpy")
                        methods={m:interval_report(totals,samples,method=m) for m in ("percentile","basic")}
                        methods["bca"]=bca_report(totals,samples)
                        record=dict(scenario=s["name"],dataset=i,data_seed=data_seed,bootstrap_seed=boot_seed,
                                    states=states,families=[asdict(t) for t in totals],methods=methods)
                        raw.write(json.dumps(record,allow_nan=False)+"\n");raw.flush();records.append(record)
                    summary=summarize(s,records);receipt["results"].append(summary)
                    print(json.dumps(dict(scenario=s["name"],completed=args.datasets,
                        bca_miss={k:v["miss_rate_among_defined"] for k,v in summary["methods"]["bca"]["components"].items()},
                        unassessable=summary["methods"]["bca"]["unassessable"]["estimate"])),flush=True)
        receipt["status"]="completed"
    except BaseException:
        receipt["status"]="failed_or_interrupted";receipt["error"]=traceback.format_exc();raise
    finally:
        receipt["ended_at"]=now()
        receipt["source_unchanged_during_run"]=all(sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in hashes.items())
        if (folder/"trials.jsonl").exists():
            raw=folder/"trials.jsonl"
            receipt["trials_sha256"]=sha256(raw.read_bytes()).hexdigest()
            with zipfile.ZipFile(folder/"evidence.zip","x",compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(raw,"trials.jsonl")
            receipt["evidence_bundle_sha256"]=sha256((folder/"evidence.zip").read_bytes()).hexdigest()
        with (folder/"receipt.json").open("x") as output:
            json.dump(receipt,output,indent=2,allow_nan=False);output.write("\n")
        print("Evidence:",folder/"receipt.json",receipt["status"],flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
