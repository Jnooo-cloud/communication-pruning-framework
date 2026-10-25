"""Single-writer, create-only journal. Reading never resumes execution.

Checksums detect accidental changes, not an adversary rewriting the whole file.
fsync is used per record; only local process-crash behavior is currently tested.
"""

from copy import deepcopy
from hashlib import sha256
import json
import os

from .audit import audit, audit_prefix


class JournalError(ValueError):
    pass


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise JournalError("duplicate JSON key")
        result[key] = value
    return result


def _constant(value):
    raise JournalError(f"non-finite JSON number: {value}")


def _header(trace, config):
    fields = {"schema", "run_id", "task", "configuration", "rounds", "failed_role", "events"}
    if trace.get("schema") in (2, 3):
        fields.add("output_limits")
    if trace.get("schema") == 3:
        fields.add("failure_policy")
    if set(trace) != fields:
        raise JournalError("unexpected header fields")
    if trace["events"] != []:
        raise JournalError("header must have no events")
    audit_prefix(trace, config)


class Journal:
    """No append-to-existing or recovery-write API; use a new explicit run instead."""

    def __init__(self, path, header, config):
        _header(header, config)
        self._trace = deepcopy(header)
        self._config = config
        self._seq = 0
        self._previous = None
        self._sealed = False
        self._broken = False
        # Exclusive creation also rejects existing symlinks and simultaneous creators.
        self._file = open(path, "xb")
        try:
            self._write({"kind": "header", "trace": self._trace})
        except BaseException:
            self.close()
            raise

    def _write(self, payload):
        if self._sealed or self._broken or self._file.closed:
            raise JournalError("journal is sealed, failed, or closed")
        body = {"journal_schema": 1, "seq": self._seq, "run_id": self._trace["run_id"],
                "previous": self._previous, "payload": payload}
        checksum = sha256(_encode(body)).hexdigest()
        data = _encode(dict(body, checksum=checksum)) + b"\n"
        try:
            if self._file.write(data) != len(data):
                raise OSError("short journal write")
            self._file.flush()
            os.fsync(self._file.fileno())
        except BaseException:
            self._broken = True
            raise
        self._seq += 1
        self._previous = checksum

    def append(self, event):
        candidate = deepcopy(self._trace)
        candidate["events"].append(deepcopy(event))
        audit_prefix(candidate, self._config)
        self._write({"kind": "event", "event": event})
        self._trace = candidate

    def finish(self, trace):
        expected = dict(self._trace, answer=trace["answer"], status=trace["status"])
        if trace != expected:
            raise JournalError("final trace differs from stored events")
        audit(trace, self._config)
        self._write({"kind": "finished", "answer": trace["answer"], "status": trace["status"]})
        self._sealed = True

    def close(self):
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def read_journal(path, expected_config):
    """Return a checked trace and receipt; incomplete journals never acquire an answer.

    Read only after the writer stops. A complete-line truncation can look like a
    valid unfinished prefix, but never like a sealed successful run.
    """
    trace = None
    previous = None
    sealed = False
    try:
        with open(path, "rb") as source:
            for seq, line in enumerate(source):
                if not line.endswith(b"\n"):
                    raise JournalError("unterminated record; preserve file for inspection")
                record = json.loads(line, object_pairs_hook=_object, parse_constant=_constant)
                if not isinstance(record, dict) or set(record) != {
                    "journal_schema", "seq", "run_id", "previous", "payload", "checksum"
                }:
                    raise JournalError("invalid envelope")
                checksum = record.pop("checksum")
                if (type(record["journal_schema"]) is not int or record["journal_schema"] != 1
                        or type(record["seq"]) is not int or record["seq"] != seq
                        or record["previous"] != previous
                        or checksum != sha256(_encode(record)).hexdigest()):
                    raise JournalError("schema, sequence, or checksum mismatch")
                if sealed:
                    raise JournalError("records after run closure")
                payload = record["payload"]
                if seq == 0:
                    if set(payload) != {"kind", "trace"} or payload["kind"] != "header":
                        raise JournalError("missing header")
                    trace = payload["trace"]
                    _header(trace, expected_config)
                else:
                    if payload["kind"] == "event" and set(payload) == {"kind", "event"}:
                        trace["events"].append(payload["event"])
                    elif payload["kind"] == "finished" and set(payload) == {"kind", "answer", "status"}:
                        trace.update(answer=payload["answer"], status=payload["status"])
                        sealed = True
                    else:
                        raise JournalError("invalid record payload")
                if record["run_id"] != trace["run_id"]:
                    raise JournalError("run ID mismatch")
                previous = checksum
        if trace is None:
            raise JournalError("empty journal")
        result = audit(trace, expected_config) if sealed else audit_prefix(trace, expected_config)
        return {"sealed": sealed, "trace": trace, "audit": result}
    except (KeyError, TypeError, ValueError, UnicodeError) as error:
        if isinstance(error, JournalError):
            raise
        raise JournalError(f"invalid journal: {error}") from error
