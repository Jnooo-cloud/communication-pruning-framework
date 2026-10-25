"""Narrow, fail-closed OpenRouter transport for the authorized Z06 probe.

No retries, redirects, auto-routing, credential logging, or resumable spending.
This is a technical probe adapter, not a general study scheduler.
"""

from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request

from .contracts import Request, Response, Usage

MODEL = "google/gemini-2.5-flash-lite"
PROVIDER = "google-vertex/eu"
BASE = "https://openrouter.ai/api/v1/"
RESERVE = Decimal("0.14")
MAX_CALLS = 5
LIMIT = Decimal("2")
CONTEXT = 1048576
MODEL_OUTPUT = 65535


class ProbeStop(RuntimeError):
    """Must propagate through execution: no continuation after uncertain billing."""


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()


def save_new(path, data):
    """Create-only, private local evidence; failures prevent further work."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    with os.fdopen(os.open(path, flags, 0o600), "wb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())


def load_key(path, *, source="file"):
    if source == "environment":
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    elif source == "file":
        matches = re.findall(r"(?m)^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*([^\r\n]*)$",
                             Path(path).read_text())
        if len(matches) != 1:
            raise ProbeStop("one local OpenRouter key required")
        key = matches[0].strip()
        if len(key) >= 2 and key[0] == key[-1] and key[0] in "\"'":
            key = key[1:-1]
    else:
        raise ProbeStop("explicit file or environment credential source required")
    if not key or any(c.isspace() for c in key) or "$" in key or "`" in key:
        raise ProbeStop("invalid local key configuration")
    return key


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Transport:
    def __init__(self, key):
        self._key = key
        # Do not inherit proxy settings that could receive the credential.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def __call__(self, endpoint, body=None):
        if endpoint not in {"key", "models/google/gemini-2.5-flash-lite/endpoints", "chat/completions"}:
            raise ProbeStop("endpoint outside authorized transport")
        headers = {"Content-Type": "application/json"}
        if endpoint != "models/google/gemini-2.5-flash-lite/endpoints":
            headers["Authorization"] = "Bearer " + self._key
        request = urllib.request.Request(BASE + endpoint, data=body, headers=headers)
        try:
            with self._opener.open(request, timeout=45) as response:
                status, raw = response.status, response.read(2_000_001)
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read(2_000_001)
        except (OSError, ValueError):
            raise ProbeStop("transport failed; billing may be unknown") from None
        if len(raw) > 2_000_000 or self._key.encode() in raw:
            raise ProbeStop("response cannot be safely recorded")
        return status, raw


def parse_json(raw):
    def invalid(_):
        raise ValueError("nonfinite JSON")
    return json.loads(raw, parse_float=Decimal, parse_constant=invalid)


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal)):
        raise ValueError("invalid decimal")
    value = Decimal(value)
    if not value.is_finite() or value < 0:
        raise ValueError("invalid decimal")
    return value


def validate_endpoint(raw):
    data = parse_json(raw)["data"]
    if data["id"] != MODEL:
        raise ProbeStop("model catalog mismatch")
    matches = [e for e in data["endpoints"] if e["tag"] == PROVIDER]
    if len(matches) != 1:
        raise ProbeStop("pinned endpoint unavailable")
    e = matches[0]
    p = e["pricing"]
    if (e["model_id"] != MODEL or e["status"] != 0
            or e["context_length"] != CONTEXT or e["max_completion_tokens"] != MODEL_OUTPUT
            or number(p["prompt"]) != Decimal("0.0000001")
            or number(p["completion"]) != Decimal("0.0000004")
            or number(p.get("request", "0")) != 0
            or number(p.get("internal_reasoning", "0")) > Decimal("0.0000004")
            or not {"reasoning", "temperature", "max_tokens"} <= set(e["supported_parameters"])):
        raise ProbeStop("endpoint or pricing changed; review required")
    if CONTEXT * number(p["prompt"]) + MODEL_OUTPUT * number(p["completion"]) > RESERVE:
        raise ProbeStop("reservation does not cover model limits")
    return e


def payload(request: Request, *, producer_limit=512):
    if (type(producer_limit) is not int or producer_limit not in (512, 1024)
            or type(request.max_output_tokens) is not int
            or not 1 <= request.max_output_tokens <= (128 if request.role == "aggregator" else producer_limit)):
        raise ProbeStop("output limit outside technical plan")
    # Keep provenance IDs in the journal, outside the model's task input.
    content = {"question": request.task.question, "paragraphs": list(request.task.paragraphs),
               "prior_messages": [{"role": m.role, "round": m.round, "text": m.text}
                                  for m in request.messages]}
    return {"model": MODEL, "stream": False, "temperature": 0,
            "max_tokens": request.max_output_tokens, "reasoning": {"enabled": False},
            "provider": {"only": [PROVIDER], "order": [PROVIDER], "allow_fallbacks": False,
                         "require_parameters": True,
                         "max_price": {"prompt": 0.1, "completion": 0.4, "request": 0}},
            "messages": [{"role": "system", "content": request.instruction},
                         {"role": "user", "content": encoded(content).decode()}]}


def decode_billing(raw):
    """Validate identifiable provider usage without accepting the answer text."""
    data = parse_json(raw)
    usage = data["usage"]
    inp, out = usage["prompt_tokens"], usage["completion_tokens"]
    cost = number(usage["cost"])
    if (data["model"] != MODEL or data.get("provider") != "Google"
            or not isinstance(data["id"], str) or not data["id"]
            or usage.get("is_byok") is not False
            or type(inp) is not int or type(out) is not int or not 0 <= inp <= CONTEXT
            or not 0 <= out <= MODEL_OUTPUT
            or type(usage["total_tokens"]) is not int or usage["total_tokens"] != inp + out):
        raise ProbeStop("response identity, token bounds or billing mismatch")
    return Usage(inp, out, cost, "provider"), data["id"]


def decode_response(raw, output_limit):
    usage, generation = decode_billing(raw)
    data = parse_json(raw)
    if (data.get("error") or usage.output_tokens > output_limit or usage.cost_usd > RESERVE
            or data["usage"].get("completion_tokens_details", {}).get("reasoning_tokens", 0) != 0):
        raise ProbeStop("response exceeds execution contract")
    choices = data["choices"]
    if len(choices) != 1 or choices[0].get("finish_reason") != "stop":
        raise ProbeStop("response did not finish normally")
    msg = choices[0]["message"]
    if (choices[0].get("error") or msg.get("role") != "assistant" or msg.get("tool_calls")
            or not isinstance(msg.get("content"), str) or not msg["content"].strip()):
        raise ProbeStop("missing plain text response")
    return Response(msg["content"], usage), generation


class ProbeAdapter:
    """Owns one exclusive, sequential reservation ledger. Never resumes."""
    def __init__(self, folder, transport, *, producer_limit=512):
        if type(producer_limit) is not int or producer_limit not in (512, 1024):
            raise ProbeStop("unapproved producer limit")
        self.producer_limit = producer_limit
        self.folder, self.transport = Path(folder), transport
        self.ids, self.generations = set(), set()
        self.calls, self.cost, self.poisoned = 0, Decimal("0"), False
        self.billed_calls = 0
        self._ledger = self.folder / "provider-ledger.jsonl"
        save_new(self._ledger, b"")

    def event(self, value):
        try:
            with self._ledger.open("ab") as out:
                out.write(encoded({"time": now(), **value}) + b"\n")
                out.flush()
                os.fsync(out.fileno())
        except BaseException:
            self.poisoned = True
            raise

    def __call__(self, request):
        if (self.poisoned or request.attempt_id in self.ids or self.calls >= MAX_CALLS
                or (self.calls + 1) * RESERVE > LIMIT):
            self.poisoned = True
            raise ProbeStop("probe stopped: duplicate, exhausted or unresolved attempt")
        # Poison before any operation; clear only after all evidence is durable.
        self.poisoned = True
        body = encoded(payload(request, producer_limit=self.producer_limit))
        slot = self.calls + 1
        save_new(self.folder / f"{slot:02}-request.json", body)
        self.event({"kind": "reserved", "attempt_id": request.attempt_id, "slot": slot,
                    "reservation_usd": str(RESERVE), "request_sha256": sha256(body).hexdigest()})
        self.ids.add(request.attempt_id)
        self.calls = slot
        try:
            status, raw = self.transport("chat/completions", body)
            save_new(self.folder / f"{slot:02}-response.json", raw)
            self.event({"kind": "received", "slot": slot, "http_status": status,
                        "response_sha256": sha256(raw).hexdigest()})
            if status != 200:
                raise ProbeStop("non-success HTTP status; no retry")
            usage, generation = decode_billing(raw)
            if generation in self.generations:
                raise ProbeStop("duplicate provider generation ID")
            self.event({"kind": "billed", "slot": slot, "attempt_id": request.attempt_id,
                        "generation_id": generation, "response_sha256": sha256(raw).hexdigest(),
                        "usage": usage.to_dict()})
            # Count only after the cost evidence is durable, even if text is rejected.
            self.generations.add(generation)
            self.cost += usage.cost_usd
            self.billed_calls += 1
            response, _ = decode_response(raw, request.max_output_tokens)
            self.event({"kind": "accepted", "slot": slot, "generation_id": generation,
                        "usage": response.usage.to_dict()})
            self.poisoned = False
            return response
        except Exception as error:
            self.event({"kind": "stopped", "slot": slot, "error_type": type(error).__name__,
                        "cost_status": "provider" if self.billed_calls == self.calls else "requires_review"})
            raise ProbeStop("technical probe stopped; inspect saved evidence, do not retry") from None
