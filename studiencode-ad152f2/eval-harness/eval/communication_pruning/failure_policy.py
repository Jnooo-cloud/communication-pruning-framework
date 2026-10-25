"""D-052 / F-01: explicit allowlist; billing success is not answer success."""
from dataclasses import dataclass
import json

from .contracts import Response
from .openrouter import (CONTEXT, RESERVE, ProbeStop, decode_billing,
                         decode_response)

F01 = "F-01/v1"
REASONS = frozenset(("length", "empty"))


def validate_policy(policy):
    if policy is not None and policy != F01:
        raise ValueError("unknown failure policy")


@dataclass(frozen=True)
class ModelFailure(Response):
    reason: str = ""

    def __post_init__(self):
        super().__post_init__()
        if (self.text != "" or self.reason not in REASONS
                or self.usage.cost_usd is None
                or self.usage.cost_source not in ("provider", "synthetic")):
            raise ValueError("typed, priced model failure required")


def strict_json(raw):
    def pairs(values):
        obj = {}
        for key, value in values:
            if key in obj:
                raise ProbeStop("ambiguous duplicate response field")
            obj[key] = value
        return obj
    def invalid(_):
        raise ProbeStop("non-finite response value")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def decode_outcome(raw, output_limit, policy):
    """HTTP and durable/unique billing are checked by the owning study adapter.

    Do not send truncated text to execution. Keep original bytes in provider logs.
    All non-allowlisted departures propagate as a technical stop.
    """
    validate_policy(policy)
    if policy is None:
        return decode_response(raw, output_limit)[0]
    data = strict_json(raw)
    usage, _ = decode_billing(raw)
    if (type(output_limit) is not int or output_limit not in (128, 1024)
            or "error" in data or usage.output_tokens > output_limit
            or usage.cost_usd > RESERVE
            or data['usage'].get('completion_tokens_details', {}).get('reasoning_tokens', 0) != 0):
        raise ProbeStop("response exceeds F-01 execution contract")
    choices = data['choices']
    if not isinstance(choices, list) or len(choices) != 1:
        raise ProbeStop("one response required")
    choice = choices[0]
    message = choice['message']
    if ("error" in choice or message.get('role') != 'assistant'
            or message.get('tool_calls') or message.get('refusal')
            or not isinstance(message.get('content'), str)):
        raise ProbeStop("invalid plain text envelope")
    if choice.get('finish_reason') == 'length':
        return ModelFailure('', usage, 'length')
    if choice.get('finish_reason') != 'stop':
        raise ProbeStop("unclassified finish reason")
    if not message['content'].strip():
        return ModelFailure('', usage, 'empty')
    return Response(message['content'], usage)
