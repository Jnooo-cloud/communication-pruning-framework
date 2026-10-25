"""Sequential phase reservation; completed-ledger replay requires a caller lock.

Budget enforcement is conditional on an actually sufficient request reservation
and no hidden calls inside the wrapped operation. No account-wide spending claim.
"""
from decimal import Decimal
import json
import os
from pathlib import Path
from datetime import datetime, timezone

from .contracts import AdapterError, Response, Usage
from .data import digest


class BudgetStop(RuntimeError):
    pass


class PhaseBudget:
    @classmethod
    def read_completed(cls, path, *, cap, reserve, max_calls, binding, allow_synthetic=False):
        """Read only. Reject even known-cost failures; never release an open call.

        The study owns the exclusive lock for inspection and subsequent appends.
        Hash chains detect damage, not a malicious rewrite of all evidence.
        """
        from .journal import _object, _constant
        raw = Path(path).read_bytes()
        if not raw or not raw.endswith(b"\n"):
            raise BudgetStop("missing or partial ledger")
        rows = []
        previous = "0" * 64
        for sequence, line in enumerate(raw.splitlines()):
            row = json.loads(line, object_pairs_hook=_object, parse_constant=_constant)
            checksum = row.pop("sha256")
            if (type(row["sequence"]) is not int or row["sequence"] != sequence
                    or row["previous"] != previous or digest(row) != checksum):
                raise BudgetStop("ledger chain mismatch")
            previous = checksum
            rows.append({k: v for k, v in row.items() if k not in ("sequence", "previous", "time")})
        header = {"kind": "header", "cap_usd": str(cap), "reserve_usd": str(reserve),
                  "max_calls": max_calls, "binding": binding, "allow_synthetic": allow_synthetic}
        if rows[0] != header or len(rows) % 2 != 1:
            raise BudgetStop("changed budget binding or open reservation")
        obj = cls.__new__(cls)
        obj.path, obj.cap, obj.reserve, obj.max_calls = Path(path), cap, reserve, max_calls
        obj.allow_synthetic = allow_synthetic
        obj.cost, obj.calls, obj.ids = Decimal(0), 0, set()
        obj.pending, obj.poisoned = None, False
        obj.previous, obj.sequence = previous, len(rows)
        obj.settlements = []
        for reserved, settled in zip(rows[1::2], rows[2::2]):
            attempt = reserved.get("attempt_id")
            if (not isinstance(attempt, str) or not attempt or attempt in obj.ids
                    or obj.calls >= max_calls or obj.cost + reserve > cap
                    or reserved != {"kind": "reserved", "attempt_id": attempt,
                                    "reservation_usd": str(reserve), "known_before_usd": str(obj.cost)}):
                raise BudgetStop("invalid prior reservation")
            value = settled.get("usage", {})
            usage = Usage(**{**value, "cost_usd": Decimal(value["cost_usd"])
                             if value.get("cost_usd") is not None else None})
            if (usage.cost_usd is None or usage.cost_usd > reserve
                    or usage.cost_source == "synthetic" and not allow_synthetic
                    or settled != {"kind": "settled", "attempt_id": attempt,
                                   "usage": usage.to_dict(), "failed": False, "over_reservation": False}):
                raise BudgetStop("failed or unresolved prior settlement")
            obj.cost += usage.cost_usd
            obj.calls += 1
            obj.ids.add(attempt)
            obj.settlements.append((attempt, usage.to_dict()))
        return obj

    def __init__(self, path, *, cap, reserve, max_calls, binding, allow_synthetic=False):
        if (any(not isinstance(v, Decimal) or not v.is_finite() or v <= 0 for v in (cap, reserve))
                or reserve > cap or type(max_calls) is not int or max_calls < 1
                or not isinstance(binding, str) or len(binding) != 64
                or any(c not in "0123456789abcdef" for c in binding)
                or type(allow_synthetic) is not bool):
            raise ValueError("positive decimal budget, call limit and binding required")
        self.path = Path(path)
        self.cap, self.reserve, self.max_calls = cap, reserve, max_calls
        self.allow_synthetic = allow_synthetic
        self.cost, self.calls = Decimal(0), 0
        self.ids, self.pending, self.poisoned = set(), None, False
        self.previous, self.sequence = "0" * 64, 0
        with self.path.open("x"):
            pass
        self._append({"kind": "header", "cap_usd": str(cap), "reserve_usd": str(reserve),
                      "max_calls": max_calls, "binding": binding, "allow_synthetic": allow_synthetic})

    def _append(self, data):
        row = {"sequence": self.sequence, "previous": self.previous,
               "time": datetime.now(timezone.utc).isoformat(), **data}
        row["sha256"] = digest(row)
        try:
            with self.path.open("a") as out:
                out.write(json.dumps(row, sort_keys=True) + "\n")
                out.flush(); os.fsync(out.fileno())
        except BaseException:
            self.poisoned = True
            raise
        self.previous = row["sha256"]
        self.sequence += 1

    def start(self, attempt_id):
        if (self.poisoned or self.pending is not None or not isinstance(attempt_id, str)
                or not attempt_id or attempt_id in self.ids or self.calls >= self.max_calls
                or self.cost + self.reserve > self.cap):
            self.poisoned = True
            raise BudgetStop("blocked, duplicate, unresolved or insufficient phase budget")
        self.pending = attempt_id
        self._append({"kind": "reserved", "attempt_id": attempt_id,
                      "reservation_usd": str(self.reserve), "known_before_usd": str(self.cost)})
        self.ids.add(attempt_id)
        self.calls += 1

    def settle(self, usage, *, failed=False):
        if self.pending is None:
            self.poisoned = True
            raise BudgetStop("no active reserved attempt")
        if not isinstance(usage, Usage):
            usage, failed = Usage(), True
        rejected_source = usage.cost_source == "synthetic" and not self.allow_synthetic
        if rejected_source:
            # Retain the returned object, but do not count fictional money as real.
            self._append({"kind": "rejected_usage", "attempt_id": self.pending, "usage": usage.to_dict()})
            usage, failed = Usage(), True
        unknown = usage.cost_usd is None
        over = not unknown and usage.cost_usd > self.reserve
        self._append({"kind": "settled", "attempt_id": self.pending, "usage": usage.to_dict(),
                      "failed": failed, "over_reservation": over})
        if not unknown:
            self.cost += usage.cost_usd
            self.pending = None
        if failed or unknown or over:
            self.poisoned = True
            raise BudgetStop("attempt failed, unpriced or exceeded reserved bound")

    def run(self, attempt_id, operation):
        self.start(attempt_id)
        try:
            result = operation()
            if not isinstance(result, Response):
                raise TypeError("typed response required")
        except AdapterError as error:
            self.settle(error.usage, failed=True)
            raise AssertionError("failed settlement must stop")
        except Exception:
            self.settle(Usage(), failed=True)
            raise AssertionError("failed settlement must stop")
        self.settle(result.usage)
        return result

    def snapshot(self):
        return {"calls": self.calls, "known_cost_usd": str(self.cost),
                "total_cost_usd": None if self.pending is not None else str(self.cost),
                "held_reservation_usd": str(self.reserve if self.pending is not None else Decimal(0)),
                "poisoned": self.poisoned, "pending": self.pending}
