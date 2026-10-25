"""Root's non-author cross-component checks, based on the saved Z50 review plan.

The execution fixture is reused and this is not a blind external replication.
The assertions connect generated, freshly executed blocks to actual reporting.
All prompts, references, transports and approval records are explicitly artificial.
"""
from copy import deepcopy
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from study_preparation import final_analysis as analysis
from study_preparation import final_execution as execution
from study_preparation import final_preflight as gate
from study_preparation.final_plan import make_plan
from tests.test_final_preflight import Fixture, trial_directory


def operator_module():
    path = Path(__file__).resolve().parents[1] / "runs/Z50-STUDIENSTART-001/coordination/study_operator.py"
    spec = importlib.util.spec_from_file_location("z50_study_operator", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class IndependentConnectionTests(unittest.TestCase):
    def test_executed_four_panels_feed_exact_complete_block_reports(self):
        with trial_directory() as directory:
            fixture = Fixture(directory, counts={"P": 3, "R": 2, "T": 2, "F": 2},
                              q="C07", fixed="C01", temporal=2)
            for end in fixture.candidate["section_ends"]:
                state = fixture.run(end)
            self.assertTrue(state["complete"])
            self.assertEqual(state["completed_blocks"], 9)
            reports = {}
            for panel, n in fixture.plan["counts"].items():
                rows = execution.collect_panel(fixture.candidate, fixture.plan, panel, **fixture.args())
                self.assertEqual(len({r["task_id"] for r in rows}), 1)
                self.assertEqual(len({r["block_id"] for r in rows}), n)
                self.assertEqual(len({r["slot_id"] for r in rows}), len(rows))
                reports[panel] = analysis.analyze_panel(fixture.plan, panel, rows, bootstrap_seed=90210)
                self.assertEqual(reports[panel]["n"], n)
                self.assertEqual(reports[panel]["mode"], "artificial_only")
            self.assertEqual(reports["P"]["primary"]["kernel"]["bootstrap_reps"], 19999)
            self.assertFalse(reports["P"]["primary"]["joint_positive"])
            reference = reports["R"]["descriptive_costs"]
            self.assertEqual(Decimal(reference["endpoints"]["R01"]["estimate"]), 7)
            self.assertEqual(Decimal(reference["endpoints"]["R02"]["estimate"]), Decimal("1.4"))
            fault = reports["F"]["descriptive_costs"]["endpoints"]
            self.assertEqual(Decimal(fault["F03"]["estimate"]), Decimal("-0.0000216"))
            self.assertEqual(Decimal(fault["F04"]["estimate"]), Decimal("-0.0000216"))
            self.assertEqual(Decimal(fault["F05"]["estimate"]), 0)
            self.assertEqual(sum(len(reports[p]["descriptive_costs"]["endpoints"]) for p in ("R", "T", "F")), 15)
            for metric in ("em", "f1"):
                self.assertEqual(sum(len(reports[p]["secondary_quality"][metric]) for p in ("R", "T", "F")), 13)
            total = sum(Decimal(row["cost_usd"]) for row in state["rows"])
            self.assertEqual(sum(Decimal(v) for v in state["levels"]["known_by_panel_usd"].values()), total)
            self.assertEqual(total, Decimal(state["budget"]["known_cost_usd"]))
            (fixture.root / "INDEPENDENT-REPORTS.json").write_text(json.dumps(reports, indent=2, allow_nan=False) + "\n")

    def test_same_task_cannot_substitute_missing_fresh_draw(self):
        with trial_directory() as directory:
            fixture = Fixture(directory, counts={"P": 2, "R": 1, "T": 1, "F": 1})
            fixture.run(1)
            fixture.run(2)
            rows = execution.collect_panel(fixture.candidate, fixture.plan, "P", **fixture.args())
            rows[-1] = deepcopy(rows[0])
            with self.assertRaisesRegex(ValueError, "duplicate"):
                analysis.analyze_panel(fixture.plan, "P", rows, bootstrap_seed=90210)

    def test_secondary_budget_persists_across_panel_boundary(self):
        with trial_directory() as directory:
            fixture = Fixture(directory)
            for end in (1, 2, 3):
                state = fixture.run(end)
            known = {p: Decimal(v) for p, v in state["levels"]["known_by_panel_usd"].items()}
            self.assertGreater(known["R"], 0)
            self.assertGreater(known["T"], 0)
            actual = gate.budget_view(fixture.candidate, known, panel="F", reserve_calls=24)
            self.assertEqual(Decimal(actual["available_usd"]["secondary"]), Decimal("55.88") - known["R"] - known["T"])
            self.assertEqual(Decimal(actual["block_reservation_usd"]), Decimal("3.36"))

    def test_concrete_operator_stops_before_encoder_key_and_loader(self):
        module = operator_module()
        with trial_directory() as directory:
            fixture = Fixture(directory)
            candidate = deepcopy(fixture.candidate)
            candidate.update(mode="not_authorized", test_authorized=False,
                             operator={"output_directory": str(fixture.folder),
                                       "operation_directory": str(fixture.root / "operation")})
            candidate = gate.seal(candidate)
            path = fixture.root / "UNAUTHORIZED-OPERATOR.json"
            path.write_text(json.dumps(candidate))
            with patch.object(module, "FrozenMiniLM", side_effect=AssertionError("encoder must remain closed")), \
                 patch.object(module, "load_key", side_effect=AssertionError("key must remain closed")), \
                 patch.object(module, "load_task", side_effect=AssertionError("content must remain closed")):
                with self.assertRaises(gate.StudyStop):
                    module.Session(path).run(1)
            self.assertEqual(fixture.transport.calls, 0)

    def test_artificial_candidate_cannot_reach_real_operator_clients(self):
        module = operator_module()
        with trial_directory() as directory:
            fixture = Fixture(directory)
            candidate = deepcopy(fixture.candidate)
            candidate["operator"] = {"output_directory": str(fixture.folder),
                "operation_directory": str(fixture.root / "operation"), "credential_file": "must-not-be-read"}
            path = fixture.root / "ARTIFICIAL-IS-NOT-LIVE.json"
            path.write_text(json.dumps(gate.seal(candidate)))
            session = module.Session(path)
            with patch.object(module, "FrozenMiniLM", side_effect=AssertionError("real encoder")), \
                 patch.object(module, "load_key", side_effect=AssertionError("real key")), \
                 patch.object(module, "Transport", side_effect=AssertionError("real transport")), \
                 patch.object(module, "load_task", side_effect=AssertionError("real data")):
                for call in (session.initialize, lambda: session.transport("chat/completions", b"{}"),
                             lambda: session.loader("synthetic-one")):
                    with self.assertRaises(gate.StudyStop):
                        call()

    def test_saved_analysis_uses_bound_seed_without_live_initialization(self):
        module = operator_module()
        with trial_directory() as directory:
            fixture = Fixture(directory, counts={"P": 2, "R": 1, "T": 1, "F": 1})
            contract = fixture.file("BOUND-ANALYSIS.json", {"study_id": fixture.plan["study_id"],
                "seed_base": fixture.plan["seed_base"], "primary_bootstrap_seed": 4321,
                "bootstrap_repetitions": 19999, "secondary_costs": "descriptive_only"})
            sources = fixture.candidate["source_files"]
            sources[contract["path"]] = contract["sha256"]
            sources[str(Path(module.__file__).resolve())] = module.file_hash(module.__file__)
            fixture.documents["source_manifest"] = fixture.file("source_manifest.json", {"files": sources})
            fixture.plan = make_plan(fixture.frame, seed_base=71,
                bindings={k: v["sha256"] for k, v in fixture.documents.items()}, mode="artificial_only",
                counts={"P": 2, "R": 1, "T": 1, "F": 1})
            fixture.candidate.update(plan_hash=fixture.plan["plan_hash"], bindings=fixture.plan["bindings"],
                documents=fixture.documents,
                plan_evidence=fixture.file("plan.json", fixture.plan),
                operator={"output_directory": str(fixture.folder), "operation_directory": str(fixture.root / "operation"),
                          "analysis_binding": contract})
            fixture.bind()
            fixture.run(1)
            fixture.run(2)
            candidate_path = fixture.root / "ARTIFICIAL-COMPLETED-CANDIDATE.json"
            candidate_path.write_text(json.dumps(fixture.candidate))
            calls = fixture.transport.calls
            with patch.object(module.Session, "initialize", side_effect=AssertionError("read-only analysis")), \
                 patch.object(module, "load_key", side_effect=AssertionError("no credentials")), \
                 patch.object(module, "load_task", side_effect=AssertionError("no new task loading")):
                result = module.analyze_saved_panel(candidate_path, "P", fixture.root / "BOUND-REPORT.json")
            self.assertEqual(result["primary"]["resampling"]["seed"], 4321)
            self.assertEqual(result["n"], 2)
            self.assertEqual(fixture.transport.calls, calls)

    def test_failed_selector_initialization_does_not_open_live_transport(self):
        module = operator_module()
        session = module.Session.__new__(module.Session)
        session._ready = False
        session.encoder = session.spatial = session.temporal = None
        session.settings = {"provision_manifest": {"path": "/synthetic/provision.json"}}
        session.candidate = {"documents": {"spatial_q": {"path": "/synthetic/q.json"},
                                          "temporal_qst": {"path": "/synthetic/t.json"}}}
        with patch.object(session, "metadata_gate", return_value={}), \
             patch.object(module.gate, "read_json", return_value={"model_dir_relative": "model", "files": {}, "runtime": {}}), \
             patch.object(module, "FrozenMiniLM", return_value=object()), \
             patch.object(module.SemanticSelector, "from_dict", side_effect=ValueError("invented selector rejection")), \
             patch.object(module, "load_key", side_effect=AssertionError("no credentials")):
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, "selector rejection"):
                    session.initialize()
                self.assertFalse(session._ready)
                self.assertIsNone(session.encoder)
                with self.assertRaises(gate.StudyStop):
                    session.transport("chat/completions", b"{}")


if __name__ == "__main__":
    unittest.main()
