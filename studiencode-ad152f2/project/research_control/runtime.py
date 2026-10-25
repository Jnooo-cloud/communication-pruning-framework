"""Artificial, offline execution ledger; Python standard library, POSIX only.

Runtime(directory).initialize(installation_id) explicitly creates a NEW directory.
grant(work) records synthetic rights, acquire(instance) returns an owner capability.
reserve(owner, action) holds a shared root budget; dispatch(owner, action_id)
durably admits and computes a deterministic LOCAL receipt. settle(id, receipt)
accounts only that exact recorded receipt. No callback, shell or network adapter
exists. admit() alone models the crash boundary: dispatch will NEVER retry it.

Work fields: id, revision, root, root_revision, parent, parent_revision, actions
(['simulate'] only), paths, recipients, purposes, budget (decimal string).
Action fields: id, work, revision, kind ('simulate'), path, recipient, purpose,
amount (decimal string), payload (JSON object). Paths are synthetic relative names,
never read or written. Each ancestor's rights and cumulative budget apply.

Owner tokens authorize synthetic transitions, NOT researcher decisions. Handoff
requires the current token and records its evidence reference; that reference is
not an authenticated external claim. Stops are monotonic root/task/action events.
The journal is the original evidence, not a second real study cost ledger.

Copied directories fail location binding. mark_restored(reason) permanently locks
an in-place restore. reconcile(current_journal_bytes) retains an evidenced newer
chain without reactivation. There is deliberately no activation/unlock API: a
separately reviewed production workflow and independent current-state evidence
would be required. Complete in-place rollback, malicious filesystem owners and
recomputed hashes cannot be detected from this local ledger alone.
"""

from contextlib import contextmanager
from decimal import Decimal
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat


class RuntimeFault(RuntimeError):
    """Invalid request, uncertain state or failed integrity check; fail closed."""


def _require(condition, message):
    if not condition:
        raise RuntimeFault(message)


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RuntimeFault("Expected finite JSON values") from exc


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _label(value):
    _require(isinstance(value, str) and 0 < len(value) <= 200
             and not any(ord(c) < 32 for c in value), "Invalid identifier")
    return value


def _money(value):
    # At most 18 integer and 8 fractional digits: exact in Decimal's 28 places.
    _require(isinstance(value, str) and re.fullmatch(
        r"(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,8})?", value),
        "Budget must be a finite nonnegative decimal string")
    return Decimal(value)


def _path(value):
    _label(value)
    p = PurePosixPath(value)
    _require(not p.is_absolute() and ".." not in p.parts and "\\" not in value
             and value == p.as_posix() and value != ".", "Unsafe synthetic path")
    return value


def _within(path, scopes):
    return any(path == scope or path.startswith(scope + "/") for scope in scopes)


def _dirfd(path):
    """Traverse every component without following symlinks, including parents."""
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                          dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def _filefd(directory, name, flags):
    fd = os.open(name, flags | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise RuntimeFault("Journal and lock must be unlinked regular files")
    return fd


def _decode(raw):
    _require(raw and raw.endswith(b"\n"), "Missing or truncated journal")
    events, previous = [], "0" * 64
    try:
        for line in raw.splitlines():
            event = json.loads(line)
            _require(set(event) == {"seq", "prev", "kind", "data", "hash"},
                     "Invalid journal envelope")
            digest = event["hash"]
            body = {k: v for k, v in event.items() if k != "hash"}
            _require(type(event["seq"]) is int and event["seq"] == len(events)
                     and event["prev"] == previous and digest == _digest(body)
                     and _json(event) == line, "Journal integrity failure")
            events.append(event)
            previous = digest
        _require(events[0]["kind"] == "initialize", "Missing genesis")
        return events
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise RuntimeFault("Invalid journal") from exc


def _state(events):
    state = {"works": {}, "actions": {}, "denies": [], "owner": None,
             "locked": False, "reconciliations": []}
    try:
        for event in events:
            kind, data = event["kind"], event["data"]
            if kind == "initialize":
                _require(event["seq"] == 0, "Duplicate genesis")
                state["installation"] = data
            elif kind == "grant":
                state["works"][data["id"]] = data
            elif kind == "owner":
                state["owner"] = data
            elif kind == "deny":
                state["denies"].append(data)
            elif kind == "reserve":
                state["actions"][data["id"]] = {
                    "action": data, "execution": "prepared", "billing": "unknown",
                    "reservation": "held", "receipt": None, "charged": None}
            elif kind in {"admit", "receipt", "uncertain", "settle"}:
                action = state["actions"][data["id"]]
                if kind == "admit":
                    action["execution"] = "possibly_dispatched"
                elif kind == "receipt":
                    action.update(execution="response_received", receipt=data["receipt"])
                elif kind == "uncertain":
                    action["execution"] = "unknown"
                else:
                    action.update(billing="evidenced", reservation="accounted",
                                  charged=data["charged"])
            elif kind == "restore":
                state["locked"] = True
            elif kind == "reconcile":
                state["reconciliations"].append(data)
            else:
                raise RuntimeFault("Unknown event; runtime locked")
        return state
    except (KeyError, TypeError) as exc:
        raise RuntimeFault("Invalid journal state") from exc


class _Journal:
    def __init__(self, fd, events):
        self.fd, self.events = fd, events
        self.state = _state(events) if events else {}

    def emit(self, kind, data):
        body = {"seq": len(self.events), "prev": self.events[-1]["hash"]
                if self.events else "0" * 64, "kind": kind, "data": data}
        event = dict(body, hash=_digest(body))
        raw = _json(event) + b"\n"
        while raw:
            written = os.write(self.fd, raw)
            _require(written > 0, "Journal write failed")
            raw = raw[written:]
        os.fsync(self.fd)
        self.events.append(event)
        self.state = _state(self.events)


class Runtime:
    def __init__(self, directory):
        raw = Path(directory)
        _require(".." not in raw.parts, "Unsafe runtime directory")
        self.directory = Path(os.path.abspath(raw))

    def initialize(self, installation_id):
        """Create artificial genesis once. Existing directories are never reset."""
        _label(installation_id)
        parent = lock = journal = directory = None
        try:
            parent = _dirfd(self.directory.parent)
            os.mkdir(self.directory.name, mode=0o700, dir_fd=parent)
            os.fsync(parent)
            directory = _dirfd(self.directory)
            lock = _filefd(directory, "lock", os.O_RDWR | os.O_CREAT | os.O_EXCL)
            fcntl.flock(lock, fcntl.LOCK_EX)
            journal = _filefd(directory, "events.jsonl",
                              os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_EXCL)
            info = os.fstat(directory)
            _Journal(journal, []).emit("initialize", {
                "id": installation_id, "artificial_only": True,
                "path": str(self.directory), "device": info.st_dev, "inode": info.st_ino})
            os.fsync(directory)
        except OSError as exc:
            raise RuntimeFault("Initialization failed; existing state is never reset") from exc
        finally:
            for fd in (journal, lock, directory, parent):
                if fd is not None:
                    os.close(fd)

    @contextmanager
    def _transaction(self):
        directory = lock = journal = None
        try:
            directory = _dirfd(self.directory)
            lock = _filefd(directory, "lock", os.O_RDWR)
            fcntl.flock(lock, fcntl.LOCK_EX)
            journal = _filefd(directory, "events.jsonl", os.O_RDWR | os.O_APPEND)
            with os.fdopen(os.dup(journal), "rb") as stream:
                events = _decode(stream.read())
            item = _Journal(journal, events)
            installation, info = item.state["installation"], os.fstat(directory)
            item.state["location_matches"] = (
                installation["path"] == str(self.directory)
                and installation["device"] == info.st_dev
                and installation["inode"] == info.st_ino)
            yield item
        except OSError as exc:
            raise RuntimeFault("Runtime storage unavailable or unsafe") from exc
        finally:
            for fd in (journal, lock, directory):
                if fd is not None:
                    os.close(fd)

    @staticmethod
    def _active(journal):
        _require(not journal.state["locked"] and journal.state["location_matches"],
                 "Restored runtime is permanently inert")

    @staticmethod
    def _owner(journal, owner):
        actual = journal.state["owner"]
        _require(isinstance(owner, dict) and actual is not None, "Owner required")
        token = owner.get("token")
        _require(isinstance(token, str) and owner.get("instance") == actual["instance"]
                 and type(owner.get("generation")) is int
                 and owner["generation"] == actual["generation"]
                 and hmac.compare_digest(_digest(token), actual["token_hash"]),
                 "Stale or invalid owner capability")

    @staticmethod
    def _chain(state, work_id):
        chain, seen = [], set()
        while work_id is not None:
            _require(work_id in state["works"] and work_id not in seen,
                     "Missing or cyclic delegation chain")
            work = state["works"][work_id]
            chain.append(work)
            seen.add(work_id)
            work_id = work["parent"]
        return chain

    @staticmethod
    def _allowed(state, chain, action_id=None):
        for stop in state["denies"]:
            denied = ((stop["scope"] == "root" and stop["target"] == chain[-1]["id"])
                      or (stop["scope"] == "task"
                          and stop["target"] in {w["id"] for w in chain})
                      or (stop["scope"] == "action" and stop["target"] == action_id))
            denied = denied or (stop["scope"] == "resource" and any(
                stop["target"] in w.get("resources", []) for w in chain))
            denied = denied or (stop["scope"] == "activation" and any(
                stop["target"] == w.get("activation", w["id"] + "@" + w["revision"]) for w in chain))
            _require(not denied, "Current stop blocks this scope")

    def grant(self, work):
        work = json.loads(_json(work))
        fields = {"id", "revision", "root", "root_revision", "parent",
                  "parent_revision", "actions", "paths", "recipients", "purposes", "budget"}
        _require(isinstance(work, dict) and fields <= set(work)
                 and set(work) <= fields | {"resources", "activation"}, "Invalid work fields")
        resources = work.get("resources", [])
        _require(isinstance(resources, list) and all(isinstance(x, str) for x in resources)
                 and len(set(resources)) == len(resources), "Invalid resources")
        for resource in resources:
            _label(resource)
        if "activation" in work:
            _label(work["activation"])
        for key in ("id", "revision", "root", "root_revision"):
            _label(work[key])
        _money(work["budget"])
        _require(work["actions"] == ["simulate"], "Only local simulation is supported")
        for key in ("paths", "recipients", "purposes"):
            _require(isinstance(work[key], list) and work[key], "Explicit rights required")
            for value in work[key]:
                (_path if key == "paths" else _label)(value)
        with self._transaction() as journal:
            self._active(journal)
            state = journal.state
            if work["id"] in state["works"]:
                _require(work == state["works"][work["id"]], "Work ID content conflict")
                return work
            if work["parent"] is None:
                _require(work["parent_revision"] is None and work["root"] == work["id"]
                         and work["root_revision"] == work["revision"], "Invalid root binding")
                _require(not any(set(resources) & set(w.get("resources", []))
                                 for w in state["works"].values() if w["parent"] is None),
                         "Independent roots share an exclusive resource")
            else:
                _label(work["parent"])
                chain = self._chain(state, work["parent"])
                self._allowed(state, chain)
                _require(work["parent_revision"] == chain[0]["revision"]
                         and work["root"] == chain[-1]["id"]
                         and work["root_revision"] == chain[-1]["revision"],
                         "Delegation version mismatch")
                for ancestor in chain:
                    _require(set(resources) <= set(ancestor.get("resources", [])),
                             "Delegation expands resources")
                    _require(_money(work["budget"]) <= _money(ancestor["budget"])
                             and all(_within(p, ancestor["paths"]) for p in work["paths"])
                             and all(set(work[k]) <= set(ancestor[k])
                                     for k in ("actions", "recipients", "purposes")),
                             "Delegation expands ancestor rights")
            self._allowed(state, [work])
            journal.emit("grant", work)
            return work

    def acquire(self, instance):
        _label(instance)
        with self._transaction() as journal:
            self._active(journal)
            _require(journal.state["owner"] is None, "Owner exists; no timeout takeover")
            return self._new_owner(journal, instance, 1, None)

    @staticmethod
    def _new_owner(journal, instance, generation, evidence):
        token = secrets.token_hex(32)
        journal.emit("owner", {"instance": instance, "generation": generation,
                              "token_hash": _digest(token), "handoff_evidence": evidence})
        return {"instance": instance, "generation": generation, "token": token}

    def handoff(self, owner, next_instance, evidence_ref):
        _label(next_instance)
        _label(evidence_ref)
        with self._transaction() as journal:
            self._active(journal)
            self._owner(journal, owner)
            return self._new_owner(journal, next_instance, owner["generation"] + 1,
                                   {"from": owner["instance"], "reference": evidence_ref})

    def deny(self, scope, target, reason):
        _require(scope in {"root", "task", "action", "resource", "activation"}, "Unknown stop scope")
        _label(target)
        _label(reason)
        with self._transaction() as journal:
            if scope in {"root", "task"}:
                chain = self._chain(journal.state, target)
                _require(scope != "root" or len(chain) == 1, "Target is not a root")
            journal.emit("deny", {"scope": scope, "target": target, "reason": reason})

    def reserve(self, owner, action):
        action = json.loads(_json(action))
        required = {
            "id", "work", "revision", "kind", "path", "recipient", "purpose",
            "amount", "payload"}
        _require(isinstance(action, dict) and required <= set(action)
                 and set(action) <= required | {"replaces", "replacement_authority"},
                 "Invalid action fields")
        for key in ("id", "work", "revision", "recipient", "purpose"):
            _label(action[key])
        _path(action["path"])
        amount = _money(action["amount"])
        _require(action["kind"] == "simulate" and isinstance(action["payload"], dict),
                 "Only explicit local simulation supported")
        with self._transaction() as journal:
            self._active(journal)
            self._owner(journal, owner)
            state = journal.state
            existing = state["actions"].get(action["id"])
            if existing:
                _require(existing["action"] == action, "Action ID content conflict")
                return existing
            chain = self._chain(state, action["work"])
            if "replaces" in action or "replacement_authority" in action:
                _label(action.get("replaces"))
                _label(action.get("replacement_authority"))
                prior = state["actions"].get(action["replaces"])
                _require(prior is not None and prior["execution"] == "unknown"
                         and prior["action"]["id"] != action["id"]
                         and self._chain(state, prior["action"]["work"])[-1]["id"] == chain[-1]["id"],
                         "Replacement needs an unknown attempt in the same root")
                _require(not any(x["action"].get("replaces") == action["replaces"]
                                 for x in state["actions"].values()), "Replacement already reserved")
            self._allowed(state, chain, action["id"])
            _require(action["revision"] == chain[0]["revision"], "Wrong work revision")
            for ancestor in chain:
                _require(_within(action["path"], ancestor["paths"])
                         and action["recipient"] in ancestor["recipients"]
                         and action["purpose"] in ancestor["purposes"]
                         and action["kind"] in ancestor["actions"], "Action exceeds rights")
                used = Decimal(0)
                for entry in state["actions"].values():
                    if ancestor["id"] in {w["id"] for w in self._chain(
                            state, entry["action"]["work"])}:
                        used += _money(entry["charged"] if entry["reservation"] == "accounted"
                                       else entry["action"]["amount"])
                _require(used + amount <= _money(ancestor["budget"]), "Shared budget exceeded")
            journal.emit("reserve", action)
            return journal.state["actions"][action["id"]]

    def _admission(self, journal, owner, action_id):
        self._active(journal)
        self._owner(journal, owner)
        _require(action_id in journal.state["actions"], "Unknown action")
        entry = journal.state["actions"][action_id]
        self._allowed(journal.state, self._chain(journal.state, entry["action"]["work"]),
                      action_id)
        _require(entry["execution"] == "prepared", "Already admitted; never redispatch")
        journal.emit("admit", {"id": action_id, "instance": owner["instance"],
                               "generation": owner["generation"]})

    def admit(self, owner, action_id):
        """Persist possibly-dispatched state without executing (crash test boundary)."""
        with self._transaction() as journal:
            self._admission(journal, owner, action_id)
            return journal.state["actions"][action_id]

    def dispatch(self, owner, action_id):
        """Admit + deterministic in-memory simulation; duplicates return saved receipt."""
        with self._transaction() as journal:
            self._active(journal)
            self._owner(journal, owner)
            entry = journal.state["actions"].get(action_id)
            _require(entry is not None, "Unknown action")
            if entry["receipt"] is not None:
                return entry["receipt"]
            self._admission(journal, owner, action_id)
            action = entry["action"]
            receipt = {"action_id": action_id, "action_hash": _digest(action),
                       "result_hash": _digest(action["payload"]),
                       "simulated_cost": action["amount"], "artificial_only": True}
            journal.emit("receipt", {"id": action_id, "receipt": receipt})
            return receipt

    def mark_unknown(self, owner, action_id, reason):
        _label(reason)
        with self._transaction() as journal:
            self._owner(journal, owner)
            entry = journal.state["actions"].get(action_id)
            _require(entry is not None and entry["execution"] == "possibly_dispatched",
                     "Only an admitted, unresolved action may be unknown")
            journal.emit("uncertain", {"id": action_id, "reason": reason})

    def settle(self, action_id, receipt):
        """Only an exact saved local receipt releases a reservation into accounting."""
        with self._transaction() as journal:
            self._active(journal)
            entry = journal.state["actions"].get(action_id)
            _require(entry is not None and entry["receipt"] is not None
                     and _json(receipt) == _json(entry["receipt"]), "Receipt evidence mismatch")
            if entry["reservation"] != "accounted":
                journal.emit("settle", {"id": action_id,
                                        "charged": entry["receipt"]["simulated_cost"]})
            return journal.state["actions"][action_id]

    def mark_restored(self, reason):
        _label(reason)
        with self._transaction() as journal:
            journal.emit("restore", {"reason": reason})

    def reconcile(self, current_journal_bytes):
        """Retain a verified newer chain, without treating it as authority or unlocking."""
        _require(isinstance(current_journal_bytes, bytes), "Original journal bytes required")
        newer = _decode(current_journal_bytes)
        _state(newer)
        with self._transaction() as journal:
            _require(journal.state["locked"] or not journal.state["location_matches"],
                     "Reconciliation is only for inert restores")
            baseline = next((i for i, e in enumerate(journal.events)
                             if e["kind"] in {"restore", "reconcile"}), len(journal.events))
            _require(len(newer) >= baseline and newer[:baseline] == journal.events[:baseline],
                     "Current evidence must extend the exact restored chain")
            prior = journal.state["reconciliations"]
            if prior:
                old = prior[-1]["events"]
                _require(len(newer) >= len(old) and newer[:len(old)] == old,
                         "Reconciliation must not regress or fork")
            journal.emit("reconcile", {"events": newer, "watermark": newer[-1]["hash"],
                                       "status": "evidence_only_permanently_inert"})
            return {"watermark": newer[-1]["hash"], "reactivated": False}

    def snapshot(self):
        with self._transaction() as journal:
            state = journal.state
            state["inert"] = state["locked"] or not state["location_matches"]
            state["watermark"] = journal.events[-1]["hash"]
            state["event_count"] = len(journal.events)
            return state
