"""Deterministic substitute backends for V3b/V3c. No model, no network, no randomness.

The answer text depends on the full request bytes, so any difference in delivered messages
propagates into later requests and into the journal.
"""
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
import json

from communication_pruning.contracts import AdapterError, Response, Usage
from communication_pruning.failure_policy import ModelFailure
from communication_pruning.openrouter import encoded, payload

PRICE = "Z56-V3-synthetic-price"


def request_bytes(request):
    return json.dumps(asdict(request), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


class Technical(RuntimeError):
    """Synthetic technical stop (not an AdapterError): must propagate like in execute()."""


class SyntheticAgent:
    """Deterministic agent. `faults` maps a 1-based call ordinal to a fault kind:
    paid_fail (AdapterError, known synthetic cost), unknown_fail (AdapterError, Usage()),
    model_failed (F-01 ModelFailure, priced), technical (Technical), adapter_error (AdapterError, known)."""

    def __init__(self, *, f01, producer_limit, faults=None):
        self.f01, self.producer_limit, self.faults = f01, producer_limit, dict(faults or {})
        self.calls = []
        self.billed = []          # every Usage this backend reported, incl. failed attempts

    def usage(self, h, request):
        tokens_in = 40 + h % 900
        limit = request.max_output_tokens
        tokens_out = 1 + (h >> 12) % limit
        amount = Decimal(h % 9973) / Decimal(10 ** 8)
        if self.f01:
            source = ("provider", "synthetic")[(h >> 20) % 2]
            return Usage(tokens_in, tokens_out, amount, source)
        kind = (h >> 20) % 5
        if kind == 0:
            return Usage()
        if kind == 1:
            return Usage(tokens_in, tokens_out, amount, "synthetic")
        if kind == 2:
            return Usage(tokens_in, tokens_out, amount, "provider")
        if kind == 3:
            return Usage(tokens_in, tokens_out, amount, "token_price", PRICE)
        return Usage(tokens_in, tokens_out)

    def __call__(self, request):
        raw = request_bytes(request)
        ordinal = len(self.calls) + 1
        self.calls.append({"ordinal": ordinal, "attempt_id": request.attempt_id, "role": request.role,
                           "round": request.round, "request_sha256": sha256(raw).hexdigest(),
                           "payload_sha256": sha256(encoded(payload(request, producer_limit=self.producer_limit))).hexdigest(),
                           "messages": [asdict(m) for m in request.messages],
                           "request": raw.decode()})
        h = int(sha256(raw).hexdigest(), 16)
        fault = self.faults.get(ordinal)
        if fault == "paid_fail":
            usage = Usage(50 + ordinal, 0, Decimal("0.00011"), "synthetic")
            self.billed.append(usage)
            raise AdapterError("synthetic billed failure", usage)
        if fault == "unknown_fail":
            self.billed.append(Usage())
            raise AdapterError("synthetic failure with unknown billing", Usage())
        if fault == "adapter_error":
            usage = Usage(60, 0, Decimal("0.00007"), "synthetic")
            self.billed.append(usage)
            raise AdapterError("synthetic adapter error under F-01", usage)
        if fault == "technical":
            raise Technical("synthetic technical stop before billing receipt")
        if fault == "model_failed":
            usage = Usage(70 + ordinal, request.max_output_tokens, Decimal("0.00013"), "synthetic")
            self.billed.append(usage)
            return ModelFailure("", usage, "length")
        usage = self.usage(h, request)
        self.billed.append(usage)
        return Response(f"{request.role}|{request.round}|{h % 16 ** 12:012x}", usage)
