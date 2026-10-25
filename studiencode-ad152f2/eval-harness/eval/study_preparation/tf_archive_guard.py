"""Bounded, process-local reuse of successful T/F archive member checks.

Every invocation reads and hashes the complete current archive.  A cold check
uses that same immutable byte snapshot for ZIP member verification.  No path,
mtime or file-size observation substitutes for the full byte check.  Callers
remain responsible for their unchanged manifest, source and operating gates.
"""
from collections import OrderedDict
from collections.abc import Mapping
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
from zipfile import ZipFile

from .final_preflight import StudyStop


class ArchiveVerificationCache:
    """Reuse only complete successes with identical bytes and member bindings."""

    def __init__(self, max_entries=32):
        if type(max_entries) is not int or max_entries < 1:
            raise ValueError("max_entries must be a positive integer")
        self._max_entries = max_entries
        self._successes = OrderedDict()
        self._pid = os.getpid()

    def verify_archive(self, evidence, expected):
        """Return None on success; retain original archive rejection decisions.

        ZIP and file access errors propagate, as in final_preflight.  The cache
        keeps immutable names and hashes, never the caller's mutable mapping.
        It is neither serialized nor shared with another process; a fork also
        discards inherited successes before the first verification.
        """
        if self._pid != os.getpid():
            self._successes.clear()
            self._pid = os.getpid()
        if (not isinstance(evidence, dict)
                or set(evidence) != {"path", "sha256", "members"}
                or not isinstance(expected, Mapping)
                or not isinstance(evidence["members"], Mapping)):
            raise StudyStop("archive binding changed or missing")

        # Freeze both supplied bindings before touching the archive.  Strings
        # are immutable; malformed values can never become a cached success.
        wanted = dict(expected.items())
        supplied = dict(evidence["members"].items())
        if (supplied != wanted
                or any(type(name) is not str or type(checksum) is not str
                       for name, checksum in wanted.items())):
            raise StudyStop("archive binding changed or missing")
        archive_hash = evidence["sha256"]
        snapshot = Path(evidence["path"]).read_bytes()
        if sha256(snapshot).hexdigest() != archive_hash:
            raise StudyStop("archive binding changed or missing")

        key = (archive_hash, frozenset(wanted.items()))
        if key in self._successes:
            self._successes.move_to_end(key)
            return None

        # Opening the path again here could check a different file version.
        # BytesIO holds precisely the bytes whose complete hash just passed.
        with ZipFile(BytesIO(snapshot)) as archive:
            names = archive.namelist()
            if len(names) != len(wanted) or set(names) != set(wanted):
                raise StudyStop("archive member set differs")
            for name, checksum in wanted.items():
                if sha256(archive.read(name)).hexdigest() != checksum:
                    raise StudyStop("archive failed complete reread")

        self._successes[key] = None
        self._successes.move_to_end(key)
        while len(self._successes) > self._max_entries:
            self._successes.popitem(last=False)
        return None
