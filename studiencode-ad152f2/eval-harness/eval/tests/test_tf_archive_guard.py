"""Synthetic P2 counterexamples; no network, provider or study contents.

Set TF_ARCHIVE_TEST_EVIDENCE_DIR to retain every fixture and failed attempt.
The coordinator/author archives this source before a decisive execution.
"""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory, mkdtemp
import unittest
from unittest.mock import patch
import warnings
from zipfile import BadZipFile, ZipFile, ZipInfo, ZIP_DEFLATED

from study_preparation import final_preflight as original
from study_preparation import tf_archive_guard as candidate


@contextmanager
def trial_directory():
    retained = os.environ.get("TF_ARCHIVE_TEST_EVIDENCE_DIR")
    if retained:
        Path(retained).mkdir(parents=True, exist_ok=True)
        yield Path(mkdtemp(prefix="synthetic-", dir=retained))
    else:
        with TemporaryDirectory() as root:
            yield Path(root)


def make_archive(root, members=None, *, name="archive.zip", timestamp=(2020, 1, 1, 0, 0, 0)):
    """Create a deterministic synthetic ZIP and the original public arguments."""
    members = members if members is not None else {"a.txt": b"synthetic a", "b.txt": b"synthetic b"}
    path = Path(root) / name
    with ZipFile(path, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for member, data in members.items():
            info = ZipInfo(member, date_time=timestamp)
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, data, compress_type=ZIP_DEFLATED, compresslevel=6)
    expected = {member: sha256(data).hexdigest() for member, data in members.items()}
    return {"path": str(path.resolve()), "sha256": sha256(path.read_bytes()).hexdigest(), "members": expected.copy()}, expected


class ArchiveVerificationCacheTests(unittest.TestCase):
    def assert_both_reject(self, evidence, expected, error=Exception, cache=None):
        with self.assertRaises(error):
            original.verify_archive(evidence, expected)
        with self.assertRaises(error):
            (cache or candidate.ArchiveVerificationCache()).verify_archive(evidence, expected)

    def test_every_warm_call_hashes_complete_bytes_but_reuses_members(self):
        with trial_directory() as root:
            evidence, expected = make_archive(root)
            archive_bytes = Path(evidence["path"]).read_bytes()
            cache = candidate.ArchiveVerificationCache()
            with patch.object(candidate, "sha256", wraps=sha256) as hashes, patch.object(candidate, "ZipFile", wraps=ZipFile) as zips:
                for _ in range(4):
                    self.assertIsNone(cache.verify_archive(evidence, expected))
                full_hashes = [call for call in hashes.call_args_list if call.args == (archive_bytes,)]
                self.assertEqual(len(full_hashes), 4)
                self.assertEqual(hashes.call_count, 4 + len(expected))
                self.assertEqual(zips.call_count, 1)
            self.assertIsNone(original.verify_archive(evidence, expected))

    def test_mapping_mutation_missing_extra_and_renamed_members_are_rechecked(self):
        with trial_directory() as root:
            evidence, expected = make_archive(root)
            evidence["members"] = expected
            baseline = expected.copy()
            cache = candidate.ArchiveVerificationCache()
            cache.verify_archive(evidence, expected)
            for changed in ({"a.txt": "0" * 64, "b.txt": baseline["b.txt"]},
                            {"a.txt": baseline["a.txt"]},
                            {**baseline, "extra.txt": "0" * 64},
                            {"renamed.txt": baseline["a.txt"], "b.txt": baseline["b.txt"]}):
                expected.clear()
                expected.update(changed)
                self.assert_both_reject(evidence, expected, original.StudyStop, cache)
            expected.clear()
            expected.update(baseline)
            self.assertIsNone(cache.verify_archive(evidence, expected))
            self.assertEqual(len(cache._successes), 1)

    def test_current_bytes_checked_even_with_same_size_and_mtime(self):
        with trial_directory() as root:
            evidence, expected = make_archive(root)
            path = Path(evidence["path"])
            stat = path.stat()
            cache = candidate.ArchiveVerificationCache()
            cache.verify_archive(evidence, expected)
            changed = bytearray(path.read_bytes())
            changed[12] ^= 1
            path.write_bytes(changed)
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            self.assertEqual(path.stat().st_size, stat.st_size)
            self.assertEqual(path.stat().st_mtime_ns, stat.st_mtime_ns)
            self.assert_both_reject(evidence, expected, original.StudyStop, cache)

    def test_missing_or_unreadable_file_never_uses_warm_success(self):
        with trial_directory() as root:
            evidence, expected = make_archive(root)
            cache = candidate.ArchiveVerificationCache()
            cache.verify_archive(evidence, expected)
            with patch.object(candidate.Path, "read_bytes", side_effect=PermissionError("synthetic denied")):
                with self.assertRaises(PermissionError):
                    cache.verify_archive(evidence, expected)
            Path(evidence["path"]).unlink()
            self.assert_both_reject(evidence, expected, FileNotFoundError, cache)

    def test_exact_reference_and_member_binding_required_after_warming(self):
        with trial_directory() as root:
            evidence, expected = make_archive(root)
            cache = candidate.ArchiveVerificationCache()
            cache.verify_archive(evidence, expected)
            cases = [None, [], {**evidence, "extra": 1}, {k: v for k, v in evidence.items() if k != "members"},
                     {**evidence, "members": {}}, {**evidence, "sha256": "f" * 64}]
            for changed in cases:
                self.assert_both_reject(changed, expected, original.StudyStop, cache)

    def test_duplicate_names_and_missing_members_reject(self):
        with trial_directory() as root:
            evidence, expected = make_archive(root, {"a.txt": b"synthetic"})
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with ZipFile(evidence["path"], "a") as archive:
                    archive.writestr("a.txt", b"synthetic")
            evidence["sha256"] = sha256(Path(evidence["path"]).read_bytes()).hexdigest()
            self.assert_both_reject(evidence, expected, original.StudyStop)
            evidence, expected = make_archive(root, {"a.txt": b"synthetic"}, name="missing.zip")
            expected["missing.txt"] = "0" * 64
            evidence["members"] = expected.copy()
            self.assert_both_reject(evidence, expected, original.StudyStop)

    def test_bad_zip_and_wrong_member_hash_never_create_success(self):
        with trial_directory() as root:
            evidence, expected = make_archive(root)
            path = Path(evidence["path"])
            path.write_bytes(b"synthetic non-zip")
            evidence["sha256"] = sha256(path.read_bytes()).hexdigest()
            cache = candidate.ArchiveVerificationCache()
            with patch.object(candidate, "ZipFile", wraps=ZipFile) as zips:
                for _ in range(2):
                    self.assert_both_reject(evidence, expected, BadZipFile, cache)
                self.assertEqual(zips.call_count, 2)
            self.assertFalse(cache._successes)
            evidence, expected = make_archive(root)
            expected["b.txt"] = "0" * 64
            evidence["members"] = expected.copy()
            with patch.object(candidate, "ZipFile", wraps=ZipFile) as zips:
                for _ in range(2):
                    self.assert_both_reject(evidence, expected, original.StudyStop, cache)
                self.assertEqual(zips.call_count, 2)
            self.assertFalse(cache._successes)

    def test_interrupted_member_read_is_not_cached(self):
        with trial_directory() as root:
            evidence, expected = make_archive(root)
            cache = candidate.ArchiveVerificationCache()
            real_read = ZipFile.read
            calls = []
            def interrupted(archive, name, *args, **kwargs):
                calls.append(name)
                if name == "b.txt":
                    raise OSError("synthetic interrupted member read")
                return real_read(archive, name, *args, **kwargs)
            with patch.object(ZipFile, "read", interrupted):
                with self.assertRaises(OSError):
                    cache.verify_archive(evidence, expected)
            self.assertEqual(calls, ["a.txt", "b.txt"])
            self.assertFalse(cache._successes)
            with patch.object(candidate, "ZipFile", wraps=ZipFile) as zips:
                cache.verify_archive(evidence, expected)
                self.assertEqual(zips.call_count, 1)

    def test_hash_and_cold_members_use_identical_snapshot_after_path_replacement(self):
        with trial_directory() as root:
            evidence, expected = make_archive(root)
            replacement, _ = make_archive(root, {"different.txt": b"replacement"}, name="replacement.zip")
            initial = Path(evidence["path"]).read_bytes()
            other = Path(replacement["path"]).read_bytes()
            def replace_after_hash(data):
                digest = sha256(data)
                if data == initial:
                    Path(evidence["path"]).write_bytes(other)
                return digest
            cache = candidate.ArchiveVerificationCache()
            with patch.object(candidate, "sha256", side_effect=replace_after_hash):
                self.assertIsNone(cache.verify_archive(evidence, expected))
            self.assert_both_reject(evidence, expected, original.StudyStop, cache)

    def test_replacement_cannot_rescue_wrong_members_from_hashed_snapshot(self):
        with trial_directory() as root:
            evidence, _ = make_archive(root, {"a.txt": b"wrong"})
            replacement, expected = make_archive(root, {"a.txt": b"right"}, name="right.zip")
            evidence["members"] = expected.copy()
            initial = Path(evidence["path"]).read_bytes()
            other = Path(replacement["path"]).read_bytes()
            def replace_after_hash(data):
                digest = sha256(data)
                if data == initial:
                    Path(evidence["path"]).write_bytes(other)
                return digest
            cache = candidate.ArchiveVerificationCache()
            with patch.object(candidate, "sha256", side_effect=replace_after_hash):
                with self.assertRaisesRegex(original.StudyStop, "complete reread"):
                    cache.verify_archive(evidence, expected)
            self.assertFalse(cache._successes)

    def test_new_archive_hash_for_same_members_forces_new_member_check(self):
        with trial_directory() as root:
            evidence, expected = make_archive(root)
            cache = candidate.ArchiveVerificationCache()
            cache.verify_archive(evidence, expected)
            evidence, expected = make_archive(root, timestamp=(2021, 1, 1, 0, 0, 0))
            with patch.object(candidate, "ZipFile", wraps=ZipFile) as zips:
                self.assertIsNone(cache.verify_archive(evidence, expected))
                self.assertEqual(zips.call_count, 1)
            self.assertIsNone(original.verify_archive(evidence, expected))

    def test_cache_is_bounded_and_evicted_success_is_checked_again(self):
        with trial_directory() as root:
            cache = candidate.ArchiveVerificationCache(max_entries=2)
            fixtures = [make_archive(root, {"a": bytes([i])}, name=f"{i}.zip") for i in range(3)]
            for evidence, expected in fixtures:
                cache.verify_archive(evidence, expected)
            self.assertEqual(len(cache._successes), 2)
            with patch.object(candidate, "ZipFile", wraps=ZipFile) as zips:
                cache.verify_archive(*fixtures[0])
                self.assertEqual(zips.call_count, 1)
            self.assertEqual(len(cache._successes), 2)
            for value in (0, -1, True, 1.5):
                with self.assertRaises(ValueError):
                    candidate.ArchiveVerificationCache(value)

    def test_fresh_process_and_fork_identity_have_no_inherited_success(self):
        with trial_directory() as root:
            evidence, expected = make_archive(root)
            cache = candidate.ArchiveVerificationCache()
            cache.verify_archive(evidence, expected)
            with patch.object(candidate.os, "getpid", return_value=cache._pid + 1), patch.object(candidate, "ZipFile", wraps=ZipFile) as zips:
                cache.verify_archive(evidence, expected)
                self.assertEqual(zips.call_count, 1)
            arguments = root / "process-input.json"
            arguments.write_text(json.dumps({"evidence": evidence, "expected": expected}))
            script = """import json,sys
from unittest.mock import patch
from zipfile import ZipFile
from study_preparation import tf_archive_guard as m
v=json.load(open(sys.argv[1])); c=m.ArchiveVerificationCache()
assert not c._successes
with patch.object(m,'ZipFile',wraps=ZipFile) as z:
 c.verify_archive(v['evidence'],v['expected'])
 assert z.call_count==1
print('fresh_process_full_member_check_passed')
"""
            result = subprocess.run([sys.executable, "-B", "-E", "-c", script, str(arguments)],
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
            (root / "process-stdout.txt").write_text(result.stdout)
            (root / "process-stderr.txt").write_text(result.stderr)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("fresh_process_full_member_check_passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
