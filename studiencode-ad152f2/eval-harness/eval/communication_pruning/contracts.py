"""Immutable public inputs and explicit accounting; no benchmark labels or client."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


ROLES = ("evidence", "linking", "draft", "checking")
INSTRUCTIONS = {
    "evidence": "Find evidence relevant to the question in the supplied paragraphs. Give a supported answer if possible.",
    "linking": "Connect evidence across the supplied paragraphs to answer the question. Explain the necessary links.",
    "draft": "Derive an answer independently from the supplied paragraphs. Use any supplied prior messages critically.",
    "checking": "Check possible answers against the supplied paragraphs, look for contradictions, and give the best supported answer.",
    "aggregator": "Answer the question using the supplied paragraphs and available final producer messages. Return only the answer.",
}


@dataclass(frozen=True)
class TaskInput:
    task_id: str
    question: str
    paragraphs: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.task_id, str) or not self.task_id:
            raise ValueError("task_id must be a nonempty string")
        if not isinstance(self.question, str) or not isinstance(self.paragraphs, tuple):
            raise ValueError("question and immutable paragraphs required")
        if not all(isinstance(p, str) for p in self.paragraphs):
            raise ValueError("paragraphs must contain strings")


@dataclass(frozen=True)
class Configuration:
    config_id: str
    roles: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]

    def __post_init__(self):
        if not self.config_id or not isinstance(self.roles, tuple) or not isinstance(self.edges, tuple):
            raise ValueError("immutable named configuration required")
        if not self.roles or len(set(self.roles)) != len(self.roles):
            raise ValueError("roles must be nonempty and unique")
        if any(role not in ROLES for role in self.roles):
            raise ValueError("unknown role")
        if any(not isinstance(e, tuple) or len(e) != 2 for e in self.edges):
            raise ValueError("edges must be immutable pairs")
        if len(set(self.edges)) != len(self.edges):
            raise ValueError("duplicate edge")
        if any(a == b or a not in self.roles or b not in self.roles for a, b in self.edges):
            raise ValueError("edges must connect distinct active roles")


@dataclass(frozen=True)
class Message:
    attempt_id: str
    role: str
    round: int
    text: str


@dataclass(frozen=True)
class Request:
    attempt_id: str
    task: TaskInput
    role: str
    round: int
    instruction: str
    messages: tuple[Message, ...]
    max_output_tokens: int


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: Decimal | None = None
    cost_source: str = "unknown"
    price_version: str | None = None

    def __post_init__(self):
        for count in (self.input_tokens, self.output_tokens):
            if count is not None and (type(count) is not int or count < 0):
                raise ValueError("token counts must be nonnegative integers or unknown")
        if self.cost_source not in {"unknown", "synthetic", "provider", "token_price"}:
            raise ValueError("unsupported cost source")
        if self.cost_usd is None:
            if self.cost_source != "unknown":
                raise ValueError("missing cost must remain unknown")
        elif not isinstance(self.cost_usd, Decimal) or not self.cost_usd.is_finite() or self.cost_usd < 0:
            raise ValueError("cost must be a finite nonnegative Decimal")
        elif self.cost_source == "unknown":
            raise ValueError("known cost needs provenance")
        if self.cost_source == "token_price" and (not self.price_version or self.input_tokens is None or self.output_tokens is None):
            raise ValueError("token pricing requires counts and a price version")

    def to_dict(self):
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "cost_usd": None if self.cost_usd is None else str(self.cost_usd),
                "cost_source": self.cost_source, "price_version": self.price_version}


@dataclass(frozen=True)
class Response:
    text: str
    usage: Usage = Usage()

    def __post_init__(self):
        if not isinstance(self.text, str) or not isinstance(self.usage, Usage):
            raise ValueError("typed response required")


class AdapterError(Exception):
    """A failed attempted call can still have incurred a known or unknown cost."""

    def __init__(self, message: str, usage: Usage = Usage()):
        super().__init__(message)
        self.usage = usage


class Agent(Protocol):
    def __call__(self, request: Request) -> Response: ...
