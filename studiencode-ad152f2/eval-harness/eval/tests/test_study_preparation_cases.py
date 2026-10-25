"""Bounded technical checks for Z44; no calibration or empirical-data access."""

from fractions import Fraction as F
import hashlib
import itertools
import json
import unittest

import numpy as np

from study_preparation import cases


class PrescribedDraws:
    """Select explicitly specified atoms; verifies one draw per factor/scope."""

    def __init__(self, indices, permutations=None):
        self.indices = iter(indices)
        self.permutations = permutations

    def choice(self, values, size, p):
        indices = next(self.indices)
        if len(indices) != size:
            raise AssertionError(f"scope mismatch: requested {size}, supplied {indices}")
        return values[np.asarray(indices)]

    def permuted(self, values, axis):
        if axis != 1 or values.shape != np.asarray(self.permutations).shape:
            raise AssertionError("not one complete arm permutation per row")
        return np.asarray(self.permutations)

    def exhausted(self):
        return next(self.indices, None) is None


class CasesContractTests(unittest.TestCase):
    def test_all_groups_endpoints_events_and_controls(self):
        c = cases.catalog()
        expected_groups = {f"P/{x}" for x in [f"R{i}" for i in range(1, 9)] + ["P1", "P2", "P3"]}
        expected_groups |= {f"{t}/S{i}" for t in ("R", "T1", "T2", "F") for i in range(1, 8)}
        self.assertEqual({g["id"] for g in c["groups"]}, expected_groups)
        self.assertEqual(len(c["groups"]), 39)
        self.assertEqual({g["id"] for g in c["controls"]}, {"G-Q", "G-R", "G-T1", "G-T2", "G-F"})
        expected_events = set()
        for identifier in expected_groups:
            template = identifier.split("/")[0]
            endpoints = {"P": ["P-D", "P-C"], "R": [f"R{i:02d}" for i in range(1, 10)],
                         "T1": ["T01"], "T2": ["T01"], "F": [f"F{i:02d}" for i in range(1, 6)]}[template]
            expected_events.update(f"{identifier}/{ep}/{side}" for ep in endpoints for side in ("L", "U"))
            if template == "P" and identifier != "P/R8":
                expected_events.add(f"{identifier}/P-J/Joint")
        event_ids = [e["id"] for e in c["events"]]
        self.assertEqual(len(event_ids), 278)
        self.assertEqual(event_ids, sorted(expected_events))
        self.assertEqual(sum(x.startswith("P/") for x in event_ids), 54)
        self.assertEqual(sum(x.endswith("/Joint") for x in event_ids), 10)
        for g in c["groups"] + c["controls"]:
            self.assertEqual(g["n"], 9040 if g["template"] == "P" else 2952)
            self.assertEqual(g["repetitions"], 2000 if g["control"] else 10000)
            self.assertEqual(g["bootstraps"], 19999)
        self.assertEqual(cases.group("R/S7")["factor_combinations"], 368640)
        self.assertEqual(cases.group("P/P3")["factor_combinations"], 12)
        json.dumps(c, allow_nan=False)

    def test_exact_primary_probabilities_and_exhaustive_means(self):
        expected = {"R1": (F(-3, 100), F(4, 5)), "R2": (F(0), F(9, 10)),
                    "R3": (F(-3, 100), F(9, 10)), "R4": (F(-3, 100), F(9, 10)),
                    "R5": (F(-3, 100), F(9, 10)), "R6": (F(-1, 25), F(4, 5)),
                    "R7": (F(0), F(1)), "R8": (F(0), F(4, 5)),
                    "P1": (F(-3, 100), F(9, 10)), "P2": (F(-3, 50), F(11, 10)),
                    "P3": (F(0), F(9, 10))}
        for regime, (delta, rho) in expected.items():
            g = cases.group(f"P/{regime}")
            factors = g["distribution"]["factors"]
            d_factor = factors[0]
            d_variance = sum(F(v) ** 2 * F(p) for v, p in zip(d_factor["values"], d_factor["probabilities"])) - delta ** 2
            if regime in ("P1", "P2"):
                self.assertEqual(d_variance, F(9, 17))
            if regime == "P3":
                self.assertEqual(d_variance, 1)
            if regime == "R4":
                self.assertEqual(d_factor["probabilities"], ["7/200", "24/25", "1/200"])
            atoms = [list(zip(map(F, f["values"]), map(F, f["probabilities"]))) for f in factors]
            sums = [F(0)] * 3
            total = F(0)
            for atom in itertools.product(*atoms):
                vals, probs = zip(*atom)
                weight = F(1)
                for p in probs:
                    weight *= p
                d, z, v = vals[:3]
                a = rho * F(3, 2500) * z * v * (1 + F(3, 10) * d) / (1 + F(3, 10) * delta)
                b = F(3, 2500) * z
                if regime == "P2":
                    a *= 1 if vals[3] else F(1, 2)
                    b *= F(1, 2) if vals[3] else 1
                total += weight
                sums = [s + weight * v for s, v in zip(sums, (d, a, b))]
            self.assertEqual(total, 1)
            self.assertEqual(sums, list(map(F, g["means_fraction"])))
            self.assertEqual(sums[0], delta)
            self.assertEqual(sums[1] / sums[2], rho)

    def test_secondary_exact_means_and_all_fifteen_cost_contrasts(self):
        ordinary = {"R": [F(1), F(5), F(9), F(43, 7), F(6), F(5)],
                    "T1": [F(19, 4), F(7, 2)], "T2": [F(19, 4), F(6)],
                    "F": [F(6), F(4), F(5), F(3)]}
        early = {"R": [F(1), F(23, 5), F(41, 5), F(197, 35), F(11, 2), F(23, 5)],
                 "T1": [F(35, 8), F(13, 4)], "T2": [F(35, 8), F(11, 2)],
                 "F": [F(11, 2), F(37, 10), F(23, 5), F(14, 5)]}
        pairs = {"R": [(4, 0), (4, 1), (4, 2), (4, 3), (4, 5), (5, 0), (5, 1), (5, 2), (5, 3)],
                 "T1": [(0, 1)], "T2": [(0, 1)], "F": [(1, 0), (3, 2)]}
        seen = set()
        for template in ordinary:
            for number in range(1, 8):
                expected = list(early[template] if number == 6 else ordinary[template])
                if template == "F" and number == 2:
                    expected = [F(6), F(6), F(5), F(9, 4)]
                elif template == "F" and number == 3:
                    expected = [F(6), F(3), F(5), F(9, 2)]
                if number == 7:
                    expected = [x * F(len(expected) + 1, 2 * len(expected)) for x in expected]
                expected = [x * F(3, 12500) for x in expected]
                g = cases.group(f"{template}/S{number}")
                self.assertEqual(list(map(F, g["means_fraction"])), expected)
                truths = [expected[a] / expected[b] for a, b in pairs[template]]
                if template == "F":
                    truths += [expected[1] - expected[0], expected[3] - expected[2],
                               expected[1] - expected[0] - expected[3] + expected[2]]
                self.assertEqual([F(e["truth_fraction"]) for e in g["endpoints"]], truths)
                for endpoint, (num, den) in zip(g["endpoints"], pairs[template]):
                    expected_num, expected_den = [0] * len(expected), [0] * len(expected)
                    expected_num[num], expected_den[den] = 1, 1
                    self.assertEqual(endpoint["numerator"], expected_num)
                    self.assertEqual(endpoint["denominator"], expected_den)
                if template == "F":
                    self.assertEqual([e["numerator"] for e in g["endpoints"][2:]],
                                     [[-1, 1, 0, 0], [0, 0, -1, 1], [-1, 1, 1, -1]])
                for endpoint in g["endpoints"]:
                    seen.add(endpoint["id"])
        self.assertEqual(seen, {f"R{i:02d}" for i in range(1, 10)} | {"T01"} | {f"F{i:02d}" for i in range(1, 6)})

    def test_finite_factors_h_and_single_width_exception(self):
        exceptions = []
        for g in cases.catalog()["groups"]:
            for factor in g["distribution"]["factors"]:
                if "probabilities" in factor:
                    self.assertEqual(sum(map(F, factor["probabilities"])), 1)
                    self.assertTrue(all(F(p) > 0 for p in factor["probabilities"]))
                    if factor["name"].startswith(("U_", "T_")) or factor["name"] == "Z":
                        self.assertEqual(sum(F(x) * F(p) for x, p in zip(factor["values"], factor["probabilities"])), 1)
            means = list(map(F, g["means_fraction"]))
            for e in g["endpoints"]:
                if not e["information_width_required"]:
                    exceptions.append((g["id"], e["id"]))
                expected = (F(3, 200) if e["id"] == "P-D" else F(1, 20) if e["id"] == "P-C"
                            else means[0] / 10 if e["id"] == "F03"
                            else means[2] / 10 if e["id"] == "F04"
                            else (means[0] + means[2]) / 10 if e["id"] == "F05"
                            else F(e["truth_fraction"]) / 10)
                self.assertEqual(e["h"], float(expected))
        self.assertEqual(exceptions, [("P/P3", "P-D")])

    def test_prescribed_primary_pair_order_and_quality_cost_link(self):
        rng = PrescribedDraws([[0, 2], [0, 2], [1, 0], [1, 0]])
        rows = cases.generate("P/P2", 2, rng)
        d = np.array([-1., 1.])
        b = np.array([0.0012 * 0.75, 0.0012 * 1.25])
        a = 1.1 * b * np.array([5.5, 0.5]) * (1 + 0.3 * d) / 0.982
        expected = np.column_stack((d, a * [1, 0.5], b * [0.5, 1]))
        np.testing.assert_allclose(rows, expected, rtol=1e-14, atol=0)
        self.assertTrue(rng.exhausted())

    def test_prescribed_reference_and_temporal_couplings(self):
        rng = PrescribedDraws([[0, 1], [1, 0], [0, 1]] + [[0, 1]] * 6)
        rows = cases.generate("R/S1", 2, rng)
        k = np.array([[1, 5, 9, 5, 7, 5], [1, 5, 9, 7, 5, 5]])
        np.testing.assert_allclose(rows, 0.00024 * k * np.array([[0.75 * 0.8], [1.25 * 1.2]]))
        self.assertTrue(rng.exhausted())
        rng = PrescribedDraws([[0, 1], [1, 0], [0, 1], [0, 0], [1, 1]])
        rows = cases.generate("T2/S1", 2, rng)
        expected = 0.00024 * np.array([[5, 5], [4, 7]]) * np.array([[0.75], [1.25]]) * [0.8, 1.2]
        np.testing.assert_allclose(rows, expected)
        self.assertTrue(rng.exhausted())

    def test_prescribed_fault_tails_effects_and_early_paid_exit(self):
        for regime, normalizer, high, effects in [("S2", 1.15, 16, [1, 1.5, 1, 0.75]),
                                                  ("S3", 1.063, 64, [1, 0.75, 1, 1.5])]:
            rng = PrescribedDraws([[0, 1], [0, 1]] + [[0, 1]] * 4 + [[1, 0], [0, 1], [1, 0], [0, 1]])
            rows = cases.generate(f"F/{regime}", 2, rng)
            k = np.array([[5, 3, 5, 3], [7, 5, 5, 3]])
            tails = np.array([[high, 1, high, 1], [1, high, 1, high]]) / normalizer
            expected = 0.00024 * k * [[0.75 * 0.8], [1.25 * 1.2]] * tails * effects
            np.testing.assert_allclose(rows, expected, rtol=1e-14, atol=0)
            self.assertTrue(rng.exhausted())
        rng = PrescribedDraws([[0, 1], [0, 1]] + [[0, 1]] * 4 + [[1, 0], [0, 1], [0, 0], [1, 1]])
        rows = cases.generate("F/S6", 2, rng)
        np.testing.assert_allclose(rows, 0.00024 * np.array([[1, 3, 5, 1], [7, 1, 5, 1]]) * [[0.6], [1.5]])
        self.assertTrue((rows > 0).all())
        self.assertTrue(rng.exhausted())

    def test_prescribed_full_permutation_and_common_global_control(self):
        permutations = [np.roll(np.arange(6), -i).tolist() for i in range(6)]
        rng = PrescribedDraws([[0] * 6] * 9, permutations)
        rows = cases.generate("R/S7", 6, rng)
        base = 0.00024 * np.array([1, 5, 9, 5, 5, 5]) * 0.75 * 0.8
        expected = np.tile(base / 2, (6, 1))
        expected[np.arange(6), np.arange(6)] = base
        np.testing.assert_allclose(rows, expected)
        self.assertTrue(rng.exhausted())
        # The only dataset-wide quality draw has size 1, not n=3.
        rng = PrescribedDraws([[0], [0, 1, 2], [0, 1, 2]])
        rows = cases.generate("G-Q", 3, rng)
        np.testing.assert_array_equal(rows[:, 0], [-1, -1, -1])
        self.assertTrue(rng.exhausted())
        # j starts at one: shared S=+1 lowers Qc/Fc and raises Qf/Ff.
        rng = PrescribedDraws([[0, 1], [0, 1]] + [[0, 1]] * 4 + [[1]])
        rows = cases.generate("G-F", 2, rng)
        expected = 0.00024 * np.array([[5, 3, 5, 3], [7, 5, 5, 3]]) * [[0.6], [1.5]] * [0.5, 1.5, 0.5, 1.5]
        np.testing.assert_allclose(rows, expected)
        self.assertTrue(rng.exhausted())
        for control, regular in [("G-Q", "P/R1"), ("G-R", "R/S1"), ("G-T1", "T1/S1"), ("G-T2", "T2/S1"), ("G-F", "F/S1")]:
            self.assertEqual(cases.group(control)["means_fraction"], cases.group(regular)["means_fraction"])

    def test_seed_contract_and_small_reproducibility_only(self):
        data_seed = cases.seed("R/S7", 2952, 0, "data")
        expected = int.from_bytes(hashlib.sha256(b"SV-METHODEN-2026-09-16-v1|R/S7|2952|0|data").digest()[:16], "little")
        self.assertEqual(data_seed, expected)
        self.assertNotEqual(data_seed, cases.seed("R/S7", 2952, 0, "bootstrap"))
        self.assertNotEqual(data_seed, cases.seed("R/S7", 2952, 1, "data"))
        for g in cases.catalog()["groups"] + cases.catalog()["controls"]:
            fixed = cases.seed(g["id"], 7, 0, "data")
            x = cases.generate(g["id"], 7, np.random.Generator(np.random.PCG64(fixed)))
            y = cases.generate(g["id"], 7, np.random.Generator(np.random.PCG64(fixed)))
            np.testing.assert_array_equal(x, y)
            self.assertEqual(x.shape, (7, len(g["columns"])))
            self.assertTrue(np.isfinite(x).all())
            self.assertTrue((x[:, 1:] >= 0).all() if g["template"] == "P" else (x >= 0).all())

    def test_reject_invalid_contract_and_return_isolation(self):
        for args in [("bad", 20, 0, "data"), ("P/R1", 0, 0, "data"),
                     ("P/R1", 20, 10000, "data"), ("G-Q", 20, 2000, "data"),
                     ("P/R1", 20, -1, "data"), ("P/R1", 20, 0, "other")]:
            with self.assertRaises(ValueError):
                cases.seed(*args)
        with self.assertRaises(ValueError):
            cases.generate("P/R1", True, None)
        snapshot = cases.catalog()
        snapshot["groups"][0]["endpoints"][0]["truth"] = 999
        self.assertNotEqual(cases.catalog()["groups"][0]["endpoints"][0]["truth"], 999)


if __name__ == "__main__":
    unittest.main()
