"""Current-state witness outside the execution tree; no monetary ledger or sends.

The concrete POSIX backend assumes its separate directory has NOT been rolled
back together with the execution tree. Hash chains and read-only files do not
protect against a malicious filesystem owner or a whole-machine rollback.
Applications publish checked source bindings while holding their original
execution lock. A successful reconciliation is technical eligibility for a NEW
session, never researcher authorization, a budget grant, or permission to retry.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import secrets
from typing import Protocol

from .core import ControlError, canonical, digest, identifier, valid_hash
from .runtime import _dirfd, _filefd
from .workspace import _root, _read, _write


class RecoveryFault(ControlError):
    pass


def _need(condition, code):
    if not condition:
        raise RecoveryFault(code)


FIELDS = {"incarnation", "activation_sha256", "stop_sha256", "stop_active",
          "owner_generation", "original_journal_sha256", "admission_journal_sha256",
          "admissions"}
TRANSITIONS = {
    "admitted": {"admitted", "response_received", "unknown", "settled"},
    "response_received": {"response_received", "unknown", "settled"},
    "unknown": {"unknown", "settled"},
    "settled": {"settled"},
}


def _binding(value):
    _need(isinstance(value, dict) and set(value) in (FIELDS, FIELDS | {"stop_denies"}), "witness_binding_fields")
    if "stop_denies" in value:
        denies = value["stop_denies"]
        _need(isinstance(denies, list) and all(valid_hash(x) for x in denies)
              and denies == sorted(set(denies)), "witness_stop_denies_invalid")
    identifier(value["incarnation"])
    _need(all(valid_hash(value[key]) for key in FIELDS if key.endswith("sha256")),
          "witness_binding_hash")
    _need(type(value["stop_active"]) is bool and type(value["owner_generation"]) is int
          and value["owner_generation"] >= 1, "witness_binding_state")
    _need(isinstance(value["admissions"], dict), "witness_admissions")
    for action_id, state in value["admissions"].items():
        identifier(action_id)
        _need(isinstance(state, str) and state in TRANSITIONS, "witness_admission_state")
    return json.loads(canonical(value))


class WitnessBackend(Protocol):
    """Stronger backends must provide the same atomic, durable freshness contract.

    This protocol is documentation for reviewed backends, not a runtime bypass:
    an arbitrary object implementing these names does not establish trust.
    """
    def current(self): ...
    def assert_current(self, binding): ...
    def checkpoint(self, expected_generation, binding, *, reconciliation=None): ...
    def challenge(self): ...
    def reconcile(self, challenge, binding, proposed_session_id): ...


class FileWitness:
    """Explicitly initialized append-only witness in a separate local directory."""

    def __init__(self, directory, execution_root):
        self.execution_root = _root(execution_root)
        path = Path(directory).absolute()
        self.directory = _root(path.parent) / path.name
        _need(not path.is_symlink() and self.directory != self.execution_root
              and self.execution_root not in self.directory.parents
              and self.directory not in self.execution_root.parents,
              "witness_must_be_outside_execution_tree")

    def _put(self, name, value):
        _write(self.directory, name, canonical(value) + b"\n", 0o444)
        for parent in (self.directory / name).parents:
            fd = _dirfd(parent)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            if parent == self.directory:
                break

    def _get(self, name):
        value = _read(self.directory, name)
        _need(value is not None, "witness_evidence_missing")
        try:
            result = json.loads(value[1])
            _need(value[1] == canonical(result) + b"\n", "witness_evidence_noncanonical")
            return result
        except (ValueError, TypeError) as exc:
            raise RecoveryFault("witness_evidence_invalid") from exc

    def initialize(self, binding):
        """Create a NEW store explicitly; never repair/reinitialize a missing history."""
        binding = _binding(binding)
        try:
            self.directory.mkdir(mode=0o700)
            fd = _dirfd(self.directory)
            try:
                identity = os.fstat(fd)
                lock = _filefd(fd, "LOCK", os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.fsync(lock)
                os.close(lock)
                self._put("identity.json", {"schema": 1, "directory": str(self.directory),
                          "device": identity.st_dev, "inode": identity.st_ino,
                          "execution_root": str(self.execution_root)})
                result = self._append(0, "0" * 64, binding, None)
                os.fsync(fd)
            finally:
                os.close(fd)
            parent = _dirfd(self.directory.parent)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
            return result
        except (OSError, ValueError) as exc:
            raise RecoveryFault("witness_initialization_failed") from exc

    @contextmanager
    def _locked(self):
        directory = lock = None
        try:
            directory = _dirfd(self.directory)
            lock = _filefd(directory, "LOCK", os.O_RDWR)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            identity = self._get("identity.json")
            actual = os.fstat(directory)
            _need(identity == {"schema": 1, "directory": str(self.directory),
                  "device": actual.st_dev, "inode": actual.st_ino,
                  "execution_root": identity.get("execution_root")},
                  "witness_location_changed")
            yield identity
        except RecoveryFault:
            raise
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise RecoveryFault("witness_unavailable_or_corrupt") from exc
        finally:
            for fd in (lock, directory):
                if fd is not None:
                    os.close(fd)

    @staticmethod
    def _record(envelope):
        return {"generation": envelope["generation"], "checkpoint": envelope["checkpoint"],
                "sha256": envelope["sha256"]}

    def _current(self):
        folder = self.directory / "checkpoints"
        _root(folder)
        names = sorted(p.name for p in folder.iterdir())
        _need(bool(names), "witness_checkpoint_missing")
        previous = "0" * 64
        prior = None
        for generation, name in enumerate(names):
            _need(name == f"{generation:020d}.json", "witness_checkpoint_gap")
            value = self._get("checkpoints/" + name)
            _need(isinstance(value, dict) and set(value) == {
                "generation", "previous", "checkpoint", "reconciliation", "sha256"},
                "witness_checkpoint_invalid")
            body = {k: v for k, v in value.items() if k != "sha256"}
            _need(type(value["generation"]) is int and value["generation"] == generation
                  and value["previous"] == previous and value["sha256"] == digest(body),
                  "witness_checkpoint_corrupt")
            cp = _binding(value["checkpoint"])
            if prior is not None:
                self._transition(prior["checkpoint"], cp)
                delta = cp["owner_generation"] - prior["checkpoint"]["owner_generation"]
                _need(delta in {0, 1} and (delta == 0 or value["reconciliation"] is not None),
                      "witness_owner_transition")
                if delta:
                    self._decision(value["reconciliation"], self._record(prior))
            previous, prior = value["sha256"], value
        return self._record(prior)

    def _append(self, generation, previous, binding, reconciliation):
        body = {"generation": generation, "previous": previous, "checkpoint": binding,
                "reconciliation": reconciliation}
        value = dict(body, sha256=digest(body))
        self._put(f"checkpoints/{generation:020d}.json", value)
        return self._record(value)

    @staticmethod
    def _transition(old, new):
        _need(new["incarnation"] == old["incarnation"], "witness_incarnation_changed")
        _need(new["activation_sha256"] == old["activation_sha256"], "witness_activation_changed")
        if "stop_denies" in old:
            _need("stop_denies" in new and set(old["stop_denies"]) <= set(new["stop_denies"]),
                  "witness_scoped_stop_cannot_be_cleared")
        _need(new["owner_generation"] >= old["owner_generation"], "witness_owner_regression")
        _need(not old["stop_active"] or new["stop_active"], "witness_stop_cannot_be_cleared")
        for action_id, state in old["admissions"].items():
            _need(new["admissions"].get(action_id) in TRANSITIONS[state],
                  "witness_admission_removed_or_regressed")

    def current(self):
        with self._locked():
            return self._current()

    def assert_current(self, binding):
        binding = _binding(binding)
        with self._locked() as identity:
            _need(identity["execution_root"] == str(self.execution_root), "restored_location_inert")
            current = self._current()
            _need(current["checkpoint"] == binding, "witness_stale_execution_state")
            return current

    def _decision(self, decision, current):
        _need(isinstance(decision, dict), "witness_reconciliation_required")
        token = identifier(decision.get("decision_id"))
        saved = self._get("decisions/" + token + ".json")
        _need(saved == decision and saved["eligible_new_session"] is True
              and saved["witness_generation"] == current["generation"]
              and saved["witness_sha256"] == current["sha256"],
              "witness_reconciliation_stale")
        return saved

    def checkpoint(self, expected_generation, binding, *, reconciliation=None):
        binding = _binding(binding)
        with self._locked() as identity:
            _need(identity["execution_root"] == str(self.execution_root), "restored_location_inert")
            current = self._current()
            _need(type(expected_generation) is int and current["generation"] == expected_generation,
                  "witness_generation_conflict")
            self._transition(current["checkpoint"], binding)
            delta = binding["owner_generation"] - current["checkpoint"]["owner_generation"]
            _need(delta in {0, 1}, "witness_owner_transition")
            if delta:
                self._decision(reconciliation, current)
            else:
                _need(reconciliation is None, "witness_unexpected_reconciliation")
            return self._append(expected_generation + 1, current["sha256"], binding, reconciliation)

    def challenge(self):
        """Persist a random one-use challenge against the presently observed generation."""
        with self._locked():
            current = self._current()
            value = {"nonce": secrets.token_hex(32), "witness_generation": current["generation"],
                     "witness_sha256": current["sha256"]}
            self._put("challenges/" + value["nonce"] + ".json", value)
            return value

    def reconcile(self, challenge, binding, proposed_session_id):
        """Consume freshness proof; return eligibility only, leaving old execution inert.

        The caller must supply checked ORIGINAL-source bindings under its execution
        lock. No date, boolean 'current', or arbitrary callback substitutes for the
        durable witness comparison. Any further activation uses its separate rights.
        """
        binding = _binding(binding)
        identifier(proposed_session_id)
        _need(isinstance(challenge, dict), "witness_challenge_required")
        nonce = identifier(challenge.get("nonce"))
        with self._locked() as identity:
            current = self._current()
            _need(self._get("challenges/" + nonce + ".json") == challenge
                  and challenge == {"nonce": nonce, "witness_generation": current["generation"],
                                    "witness_sha256": current["sha256"]},
                  "witness_challenge_stale")
            _need(_read(self.directory, "decisions/" + nonce + ".json") is None,
                  "witness_challenge_consumed")
            # A proposed ID is consumed even when reconciliation is denied.
            session = "sessions/" + proposed_session_id + ".json"
            _need(_read(self.directory, session) is None, "witness_session_reused")
            cp = current["checkpoint"]
            reasons = []
            if identity["execution_root"] != str(self.execution_root):
                reasons.append("restored_location_inert")
            if cp != binding:
                reasons.append("original_evidence_not_current")
            if cp["stop_active"]:
                reasons.append("stop_active")
            if any(state != "settled" for state in cp["admissions"].values()):
                reasons.append("unresolved_original_admissions")
            if proposed_session_id in cp["admissions"]:
                reasons.append("historic_action_id")
            decision = {"decision_id": nonce, "proposed_session_id": proposed_session_id,
                        "eligible_new_session": not reasons, "reactivated": False,
                        "execution_authorized": False, "reasons": reasons,
                        "witness_generation": current["generation"], "witness_sha256": current["sha256"],
                        "next_owner_generation": cp["owner_generation"] + 1,
                        "old_ids_forbidden": sorted(cp["admissions"]),
                        "independence": "separate_local_store_not_whole_machine_rollback_proof"}
            self._put(session, {"decision_id": nonce})
            self._put("decisions/" + nonce + ".json", decision)
            return decision
