#!/usr/bin/env python3
"""Read-only token/cost reconciliation for the saved R-panel runs.

Usage: python3 -B tokens_referenzvergleich.py /path/to/project-root

Only the three reports next to this script are written. All study inputs are
read as saved; no network or model calls are made.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path
from typing import Any, Iterable


N_TASKS = 2952
PANEL = "R"
ARMS = ("S", "S-k", "F", "Q", "Z", "D")
TABLE_ARMS = ("S", "S-k", "F", "Q", "Z", "D")
EXPECTED_COST_PER_1000 = {
    "S": Decimal("0.19"),
    "S-k": Decimal("0.79"),
    "F": Decimal("1.26"),
    "Q": Decimal("1.46"),
    "Z": Decimal("1.53"),
    "D": Decimal("2.36"),
}
PRICE_INPUT = Decimal("0.10")
PRICE_CACHE = Decimal("0.01")
PRICE_OUTPUT = Decimal("0.40")
PRICE_TOLERANCE = Decimal("0.000000001")

ROWS_MAIN_REL = Path(
    "eval-harness/eval/runs/Z53-SCHNELLFORTSETZUNG-001/live/collected/rows-R.json"
)
ROWS_SK_REL = Path(
    "eval-harness/eval/runs/Z54-SK-KORREKTUR-001/live/collected/rows-R-SK.json"
)

# Current, relevant R-panel live roots. Successor folders intentionally overlap
# at recovery boundaries; records are deduplicated by (source version, attempt_id).
Z52_LIVE_RELS = (
    "Z52-NEBENPANEL-ANSCHLUSS-001/live",
    "Z52-NEBENPANEL-ANSCHLUSS-001/recovery-R00038/live",
    "Z52-NEBENPANEL-ANSCHLUSS-001/recovery-R00038/continuation-R00087/live",
    "Z52-NEBENPANEL-ANSCHLUSS-001/recovery-R00038/continuation-R00087/recovery-R00125/live",
    "Z52-NEBENPANEL-ANSCHLUSS-001/recovery-R00038/continuation-R00087/recovery-R00125/technical-R00203/live",
    "Z52-NEBENPANEL-ANSCHLUSS-001/recovery-R00038/continuation-R00087/recovery-R00125/technical-R00203/coverage-R01462/live",
    "Z52-NEBENPANEL-ANSCHLUSS-001/recovery-R00038/continuation-R00087/recovery-R00125/technical-R00203/coverage-R01462/rate-stop-R01589/live",
    "Z52-NEBENPANEL-ANSCHLUSS-001/recovery-R00038/continuation-R00087/recovery-R00125/technical-R00203/coverage-R01462/rate-stop-R01589/r2183-overlimit/live",
)
Z53_LIVE_REL = "Z53-SCHNELLFORTSETZUNG-001/live"
Z54_LIVE_REL = "Z54-SK-KORREKTUR-001/live"


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def decimal_value(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def int_value(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def ratio_text(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    with localcontext() as ctx:
        ctx.prec = 40
        return format((Decimal(numerator) / Decimal(denominator)), ".12f")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_usage(usage: dict[str, Any]) -> dict[str, Any]:
    """Keep only the accounting fields, normalizing numeric types."""
    return {
        "input_tokens": int_value(usage.get("input_tokens")),
        "output_tokens": int_value(usage.get("output_tokens")),
        "cost_usd": decimal_text(decimal_value(usage.get("cost_usd"))),
    }


def usage_signature(usage: dict[str, Any]) -> tuple[Any, Any, Any]:
    normalized = canonical_usage(usage)
    return (
        normalized["input_tokens"],
        normalized["output_tokens"],
        normalized["cost_usd"],
    )


def cache_response_usage(response: dict[str, Any]) -> dict[str, Any]:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    prompt_details = usage.get("prompt_tokens_details")
    if not isinstance(prompt_details, dict):
        prompt_details = {}
    completion_details = usage.get("completion_tokens_details")
    if not isinstance(completion_details, dict):
        completion_details = {}
    return {
        "prompt_tokens": int_value(usage.get("prompt_tokens")),
        "completion_tokens": int_value(usage.get("completion_tokens")),
        "cached_tokens": int_value(prompt_details.get("cached_tokens")),
        "cache_write_tokens": int_value(prompt_details.get("cache_write_tokens")),
        "reasoning_tokens": int_value(completion_details.get("reasoning_tokens")),
        "reported_cost_usd": decimal_text(decimal_value(usage.get("cost"))),
    }


def arm_version(arm: str, source_kind: str) -> str:
    if arm == "S-k":
        return "neu" if source_kind == "z54_sk" else "alt"
    return "haupt"


def add_attempt(
    attempts: dict[tuple[str, str], dict[str, dict[str, Any]]],
    duplicate_usage_records: Counter[str],
    conflicting_usage: list[dict[str, Any]],
    *,
    version: str,
    run_id: str,
    attempt_id: str,
    usage: dict[str, Any] | None,
    source_label: str,
    event_kind: str | None = None,
) -> None:
    key = (version, run_id)
    row_attempts = attempts.setdefault(key, {})
    item = row_attempts.setdefault(
        attempt_id,
        {"usage": None, "sources": set(), "usage_sources": [], "event_kinds": set()},
    )
    item["sources"].add(source_label)
    if event_kind:
        item["event_kinds"].add(event_kind)
    if usage is None:
        return
    normalized = canonical_usage(usage)
    if item["usage"] is None:
        item["usage"] = normalized
        item["usage_sources"].append(source_label)
    else:
        prior = item["usage"]
        merged = dict(prior)
        differences = {}
        for field, new_value in normalized.items():
            old_value = merged.get(field)
            if old_value is None and new_value is not None:
                merged[field] = new_value
            elif new_value is not None and old_value is not None and new_value != old_value:
                differences[field] = {"first": old_value, "other": new_value}
        if differences:
            conflicting_usage.append(
                {
                    "version": version,
                    "run_id": run_id,
                    "attempt_id": attempt_id,
                    "differences": differences,
                }
            )
        else:
            duplicate_usage_records[version] += 1
            item["usage"] = merged
        item["usage_sources"].append(source_label)


def collect_live_records(
    project_root: Path,
    source_roots: list[tuple[str, str, str]],
    expected_run_ids: dict[str, set[str]],
) -> tuple[
    dict[tuple[str, str], dict[str, dict[str, Any]]],
    Counter[str],
    list[dict[str, Any]],
    list[dict[str, Any]],
    Counter[str],
]:
    attempts: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    duplicate_usage_records: Counter[str] = Counter()
    conflicting_usage: list[dict[str, Any]] = []
    unmapped_records: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()

    for source_label, source_rel, source_kind in source_roots:
        live_root = project_root / source_rel
        block_root = live_root / "blocks"
        source_counts[f"live_roots:{source_kind}"] += int(live_root.is_dir())
        if not block_root.is_dir():
            continue
        block_dirs = sorted(path for path in block_root.iterdir() if path.is_dir())
        source_counts[f"block_dirs:{source_kind}"] += len(block_dirs)
        for block_dir in block_dirs:
            for arm_dir in sorted(path for path in block_dir.iterdir() if path.is_dir()):
                arm = arm_dir.name
                if arm not in ARMS:
                    continue
                if source_kind == "z54_sk" and arm != "S-k":
                    continue
                result_path = arm_dir / "result.json"
                if not result_path.is_file():
                    source_counts[f"arm_dirs_without_result:{source_kind}"] += 1
                    continue
                try:
                    result = read_json(result_path)
                except (OSError, json.JSONDecodeError):
                    source_counts[f"unreadable_results:{source_kind}"] += 1
                    continue
                if not isinstance(result, dict):
                    source_counts[f"invalid_results:{source_kind}"] += 1
                    continue
                run_id = result.get("run_id") or result.get("slot_id")
                if not isinstance(run_id, str):
                    source_counts[f"missing_run_id_results:{source_kind}"] += 1
                    continue
                version = arm_version(arm, source_kind)
                if run_id not in expected_run_ids.get(version, set()):
                    source_counts[f"unmapped_result_rows:{version}"] += 1
                    unmapped_records.append(
                        {
                            "version": version,
                            "arm": arm,
                            "run_id": run_id,
                            "record_type": "result.json",
                        }
                    )

                journal_path = arm_dir / "journal.jsonl"
                if journal_path.is_file():
                    source_counts[f"journal_files:{source_kind}"] += 1
                    try:
                        with journal_path.open("r", encoding="utf-8") as stream:
                            for line_number, line in enumerate(stream, 1):
                                if not line.strip():
                                    continue
                                try:
                                    envelope = json.loads(line)
                                except json.JSONDecodeError:
                                    source_counts[f"malformed_journal_lines:{source_kind}"] += 1
                                    continue
                                payload = envelope.get("payload", {})
                                event = payload.get("event", {}) if isinstance(payload, dict) else {}
                                if not isinstance(event, dict):
                                    continue
                                attempt_id = event.get("attempt_id")
                                if not isinstance(attempt_id, str):
                                    continue
                                event_run_id = envelope.get("run_id") or run_id
                                if event_run_id != run_id:
                                    source_counts[f"journal_run_id_disagreements:{source_kind}"] += 1
                                if run_id not in expected_run_ids.get(version, set()):
                                    continue
                                usage = event.get("usage")
                                if not isinstance(usage, dict):
                                    usage = None
                                add_attempt(
                                    attempts,
                                    duplicate_usage_records,
                                    conflicting_usage,
                                    version=version,
                                    run_id=run_id,
                                    attempt_id=attempt_id,
                                    usage=usage,
                                    source_label=source_label,
                                    event_kind=str(event.get("kind", "")),
                                )
                                source_counts[f"journal_attempt_events:{source_kind}"] += 1
                                if usage is not None:
                                    source_counts[f"journal_usage_events:{source_kind}"] += 1
                    except OSError:
                        source_counts[f"unreadable_journals:{source_kind}"] += 1

                for direct_path in sorted(arm_dir.glob("direct-[0-9]*.json")):
                    if not re.fullmatch(r"direct-[0-9]+\.json", direct_path.name):
                        continue
                    source_counts[f"direct_files:{source_kind}"] += 1
                    try:
                        direct = read_json(direct_path)
                    except (OSError, json.JSONDecodeError):
                        source_counts[f"unreadable_direct_files:{source_kind}"] += 1
                        continue
                    outcome = direct.get("outcome", {}) if isinstance(direct, dict) else {}
                    if not isinstance(outcome, dict):
                        continue
                    attempt_id = outcome.get("attempt_id")
                    if not isinstance(attempt_id, str):
                        source_counts[f"direct_files_without_attempt_id:{source_kind}"] += 1
                        continue
                    usage = outcome.get("usage")
                    if not isinstance(usage, dict):
                        usage = None
                    if run_id in expected_run_ids.get(version, set()):
                        add_attempt(
                            attempts,
                            duplicate_usage_records,
                            conflicting_usage,
                            version=version,
                            run_id=run_id,
                            attempt_id=attempt_id,
                            usage=usage,
                            source_label=source_label,
                            event_kind=str(outcome.get("kind", "")),
                        )
                    source_counts[f"direct_attempts:{source_kind}"] += 1
                    if usage is not None:
                        source_counts[f"direct_usage_events:{source_kind}"] += 1

                # Some terminal over-limit calls have no completed journal event.
                # Their durable record carries the provider usage under adoption.usage.
                terminal_path = arm_dir / "terminal-overlimit.json"
                if terminal_path.is_file():
                    source_counts[f"terminal_overlimit_files:{source_kind}"] += 1
                    try:
                        terminal = read_json(terminal_path)
                    except (OSError, json.JSONDecodeError):
                        source_counts[f"unreadable_terminal_overlimit:{source_kind}"] += 1
                    else:
                        adoption = terminal.get("adoption", {}) if isinstance(terminal, dict) else {}
                        if not isinstance(adoption, dict):
                            adoption = {}
                        dispatch = adoption.get("dispatch", {})
                        if not isinstance(dispatch, dict):
                            dispatch = {}
                        attempt_id = dispatch.get("logical_id")
                        usage = adoption.get("usage")
                        if isinstance(attempt_id, str):
                            if isinstance(usage, dict):
                                add_attempt(
                                    attempts,
                                    duplicate_usage_records,
                                    conflicting_usage,
                                    version=version,
                                    run_id=run_id,
                                    attempt_id=attempt_id,
                                    usage=usage,
                                    source_label=source_label + ":terminal-overlimit",
                                    event_kind="terminal_overlimit_provider_booking",
                                )
                                source_counts[f"terminal_overlimit_usage_events:{source_kind}"] += 1
                            else:
                                source_counts[f"terminal_overlimit_without_usage:{source_kind}"] += 1
                        else:
                            source_counts[f"terminal_overlimit_without_attempt_id:{source_kind}"] += 1

    return attempts, duplicate_usage_records, conflicting_usage, unmapped_records, source_counts


def provider_dirs_for_live(live_root: Path) -> Iterable[Path]:
    central = live_root / "provider"
    if central.is_dir():
        yield central
    block_root = live_root / "blocks"
    if block_root.is_dir():
        for block_dir in sorted(path for path in block_root.iterdir() if path.is_dir()):
            for child in sorted(path for path in block_dir.iterdir() if path.is_dir()):
                if child.name == "provider" or child.name.startswith("provider-"):
                    yield child
    interrupted_root = live_root / "interrupted"
    if interrupted_root.is_dir():
        for current, dirs, _files in __import__("os").walk(interrupted_root):
            dirs[:] = sorted(
                directory
                for directory in dirs
                if directory not in {"__pycache__", "node_modules", "tests", "fixtures"}
            )
            current_path = Path(current)
            if current_path.name == "provider" or current_path.name.startswith("provider-"):
                yield current_path
                dirs[:] = []


def collect_provider_responses(
    project_root: Path,
    source_roots: list[tuple[str, str, str]],
    attempts: dict[tuple[str, str], dict[str, dict[str, Any]]],
) -> tuple[
    dict[tuple[str, str], dict[str, Any]],
    Counter[str],
    list[dict[str, Any]],
    Counter[str],
]:
    candidates: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    provider_counts: Counter[str] = Counter()
    conflicts: list[dict[str, Any]] = []
    resolved_conflicts: Counter[str] = Counter()

    expected_attempt_keys: set[tuple[str, str]] = set()
    for (version, _run_id), row_attempts in attempts.items():
        for attempt_id, item in row_attempts.items():
            expected_attempt_keys.add((version, attempt_id))

    seen_provider_dirs: set[tuple[str, str]] = set()
    for source_label, source_rel, source_kind in source_roots:
        live_root = project_root / source_rel
        for provider_dir in provider_dirs_for_live(live_root):
            if not provider_dir.is_dir():
                continue
            try:
                rel_key = provider_dir.relative_to(live_root).as_posix()
            except ValueError:
                rel_key = provider_dir.name
            dedup_dir_key = (source_kind, str(provider_dir.resolve()))
            if dedup_dir_key in seen_provider_dirs:
                continue
            seen_provider_dirs.add(dedup_dir_key)

            bindings: dict[str, str] = {}
            for binding_path in sorted(provider_dir.glob("*-binding.json")):
                provider_counts[f"binding_files:{source_kind}"] += 1
                try:
                    binding = read_json(binding_path)
                except (OSError, json.JSONDecodeError):
                    provider_counts[f"unreadable_bindings:{source_kind}"] += 1
                    continue
                attempt_id = binding.get("attempt_id") if isinstance(binding, dict) else None
                if isinstance(attempt_id, str):
                    prefix = binding_path.name[: -len("-binding.json")]
                    bindings[prefix] = attempt_id
                else:
                    provider_counts[f"bindings_without_attempt_id:{source_kind}"] += 1

            response_paths: list[tuple[str, Path]] = []
            for response_path in sorted(provider_dir.glob("*-response.json")):
                stem = response_path.name[: -len("-response.json")]
                prefix = re.sub(r"-p[0-9]+$", "", stem)
                response_paths.append((prefix, response_path))
            found_prefixes: set[str] = set()
            for prefix, response_path in response_paths:
                provider_counts[f"response_files:{source_kind}"] += 1
                attempt_id = bindings.get(prefix)
                if attempt_id is None:
                    provider_counts[f"responses_without_binding:{source_kind}"] += 1
                    continue
                found_prefixes.add(prefix)
                try:
                    response = read_json(response_path)
                except (OSError, json.JSONDecodeError):
                    provider_counts[f"unreadable_responses:{source_kind}"] += 1
                    continue
                detail = cache_response_usage(response)
                version = "neu" if source_kind == "z54_sk" else ("alt" if ":S-k" in attempt_id else "haupt")
                key = (version, attempt_id)
                detail["source_label"] = source_label
                detail["source_relative"] = (Path(source_rel) / rel_key / response_path.name).as_posix()
                detail["response_sha256"] = sha256_file(response_path)
                detail["response_created"] = int_value(response.get("created"))
                part_match = re.search(r"-p([0-9]+)-response\.json$", response_path.name)
                detail["response_sequence"] = int(part_match.group(1)) if part_match else 0
                if key not in expected_attempt_keys:
                    provider_counts[f"responses_for_unselected_attempts:{source_kind}"] += 1
                    continue
                candidates[key].append(detail)
            for prefix in bindings:
                if prefix not in found_prefixes:
                    provider_counts[f"bindings_without_response:{source_kind}"] += 1

        # The over-limit recovery branch stores provider bindings and raw responses
        # in live/dispatch rather than in per-block provider directories.
        dispatch_dir = live_root / "dispatch"
        if dispatch_dir.is_dir():
            bindings: dict[str, str] = {}
            for binding_path in sorted(dispatch_dir.glob("*-binding.json")):
                provider_counts[f"dispatch_binding_files:{source_kind}"] += 1
                try:
                    binding = read_json(binding_path)
                except (OSError, json.JSONDecodeError):
                    provider_counts[f"unreadable_dispatch_bindings:{source_kind}"] += 1
                    continue
                logical_id = binding.get("logical_id") if isinstance(binding, dict) else None
                if isinstance(logical_id, str):
                    bindings[binding_path.name[: -len("-binding.json")]] = logical_id
                else:
                    provider_counts[f"dispatch_bindings_without_logical_id:{source_kind}"] += 1
            for response_path in sorted(dispatch_dir.glob("*-response.json")):
                provider_counts[f"dispatch_response_files:{source_kind}"] += 1
                prefix = response_path.name[: -len("-response.json")]
                attempt_id = bindings.get(prefix)
                if attempt_id is None:
                    provider_counts[f"dispatch_responses_without_binding:{source_kind}"] += 1
                    continue
                try:
                    response = read_json(response_path)
                except (OSError, json.JSONDecodeError):
                    provider_counts[f"unreadable_dispatch_responses:{source_kind}"] += 1
                    continue
                detail = cache_response_usage(response)
                version = "neu" if source_kind == "z54_sk" else ("alt" if ":S-k:" in attempt_id else "haupt")
                detail["source_label"] = source_label + ":dispatch"
                detail["source_relative"] = (Path(source_rel) / "dispatch" / response_path.name).as_posix()
                detail["response_sha256"] = sha256_file(response_path)
                detail["response_created"] = int_value(response.get("created"))
                detail["response_sequence"] = 0
                if (version, attempt_id) not in expected_attempt_keys:
                    provider_counts[f"dispatch_responses_for_unselected_attempts:{source_kind}"] += 1
                    continue
                candidates[(version, attempt_id)].append(detail)
                provider_counts[f"dispatch_responses_bound:{source_kind}"] += 1

    responses: dict[tuple[str, str], dict[str, Any]] = {}
    for key, items in candidates.items():
        def candidate_score(detail: dict[str, Any]) -> tuple[int, int, int]:
            # Resolve multiple saved responses without consulting logged tokens or
            # cost: use provider creation time, then part sequence, then field
            # completeness. Equal-ranked conflicting records remain ambiguous.
            present = sum(
                detail.get(field) is not None
                for field in (
                    "prompt_tokens", "completion_tokens", "cached_tokens",
                    "cache_write_tokens", "reasoning_tokens", "reported_cost_usd",
                )
            )
            return (
                detail.get("response_created") if detail.get("response_created") is not None else -1,
                detail.get("response_sequence") or 0,
                present,
            )

        best_score = max(candidate_score(item) for item in items)
        best_items = [item for item in items if candidate_score(item) == best_score]
        usage_fields = (
            "prompt_tokens", "completion_tokens", "cached_tokens",
            "cache_write_tokens", "reasoning_tokens", "reported_cost_usd",
        )
        distinct_best = {
            tuple(item.get(field) for field in usage_fields)
            for item in best_items
        }
        if len(items) > 1:
            provider_counts[f"attempts_with_multiple_response_candidates:{key[0]}"] += 1
            all_distinct = {
                tuple(item.get(field) for field in usage_fields)
                for item in items
            }
            if len(all_distinct) > 1 and len(distinct_best) == 1 and len(best_items) < len(items):
                resolved_conflicts[key[0]] += 1
        if len(distinct_best) > 1:
            first = best_items[0]
            other = best_items[1]
            differences = {
                field: {"first": first.get(field), "other": other.get(field)}
                for field in usage_fields
                if first.get(field) != other.get(field)
            }
            conflicts.append(
                {
                    "version": key[0],
                    "attempt_id": key[1],
                    "differences": differences,
                    "tied_best_candidates": len(best_items),
                    "first_source": first.get("source_relative"),
                    "other_source": other.get("source_relative"),
                }
            )
        # Deterministic choice among usage-identical copies.
        best_items.sort(key=lambda item: (item.get("source_relative", ""), item.get("response_sha256", "")))
        responses[key] = best_items[0]

    return responses, provider_counts, conflicts, resolved_conflicts


def rows_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        run_id = row.get("run_id") or row.get("slot_id")
        if isinstance(run_id, str):
            index[run_id] = row
    return index


def mean_text(total: int, denominator: int = N_TASKS) -> str:
    with localcontext() as ctx:
        ctx.prec = 40
        return format(Decimal(total) / Decimal(denominator), ".12f")


def build_reports(project_root: Path, output_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    rows_main_path = project_root / ROWS_MAIN_REL
    rows_sk_path = project_root / ROWS_SK_REL
    rows_main = read_json(rows_main_path)
    rows_sk = read_json(rows_sk_path)
    if not isinstance(rows_main, list) or not isinstance(rows_sk, list):
        raise ValueError("Die beiden Ergebnisdateien müssen JSON-Listen enthalten.")
    main_index = rows_index(rows_main)
    sk_index_all = rows_index(rows_sk)
    old_sk_rows = [row for row in rows_main if row.get("panel") == PANEL and row.get("arm") == "S-k"]
    new_sk_rows = [row for row in rows_sk if row.get("panel") == PANEL and row.get("arm") == "S-k"]
    selected_rows: dict[str, list[dict[str, Any]]] = {
        "haupt": [row for row in rows_main if row.get("panel") == PANEL and row.get("arm") != "S-k"],
        "alt": old_sk_rows,
        "neu": new_sk_rows,
    }
    selected_index = {
        version: rows_index(items) for version, items in selected_rows.items()
    }
    expected_run_ids = {
        version: set(index) for version, index in selected_index.items()
    }

    z54_non_sk = [row for row in rows_sk if row.get("panel") == PANEL and row.get("arm") != "S-k"]
    z53_non_sk = [row for row in rows_main if row.get("panel") == PANEL and row.get("arm") != "S-k"]
    z54_non_sk_exact = Counter(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in z54_non_sk)
    z53_non_sk_exact = Counter(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in z53_non_sk)
    z54_sk_by_run = rows_index(new_sk_rows)
    old_sk_by_run = rows_index(old_sk_rows)
    new_old_sk_differences = sum(
        1
        for run_id, new_row in z54_sk_by_run.items()
        if run_id not in old_sk_by_run or new_row != old_sk_by_run.get(run_id)
    )

    source_roots: list[tuple[str, str, str]] = []
    for index, rel in enumerate(Z52_LIVE_RELS, 1):
        source_roots.append((f"Z52-{index:02d}", str(Path("eval-harness/eval/runs") / rel), "z52"))
    source_roots.append(("Z53", str(Path("eval-harness/eval/runs") / Z53_LIVE_REL), "z53"))
    source_roots.append(("Z54-S-k", str(Path("eval-harness/eval/runs") / Z54_LIVE_REL), "z54_sk"))

    attempts, duplicate_usage_records, conflicting_usage, unmapped_source_rows, source_counts = collect_live_records(
        project_root, source_roots, expected_run_ids
    )
    responses, provider_counts, provider_conflicts, resolved_provider_conflicts = collect_provider_responses(
        project_root, source_roots, attempts
    )

    # The response set uses the same version labels as the result/run data.
    # No raw response text is retained in any output.
    usage_event_duplicates = sum(duplicate_usage_records.values())
    cost_mismatches: list[dict[str, Any]] = []
    missing_result_costs: list[dict[str, Any]] = []
    missing_source_rows: list[dict[str, Any]] = []
    attempt_row_mismatches: list[dict[str, Any]] = []
    token_mismatches: list[dict[str, Any]] = []
    provider_cost_mismatches: list[dict[str, Any]] = []
    missing_usage_costs: list[dict[str, Any]] = []
    price_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    arm_summaries: list[dict[str, Any]] = []
    output_rows: list[dict[str, Any]] = []
    arm_key_order = {"S": 0, "S-k": 1, "F": 2, "Q": 3, "Z": 4, "D": 5}
    attempt_locations: dict[tuple[str, str], set[str]] = defaultdict(set)
    for (version, run_id), row_attempts in attempts.items():
        for attempt_id in row_attempts:
            attempt_locations[(version, attempt_id)].add(run_id)
    attempt_row_mismatches.extend(
        {"version": version, "attempt_id": attempt_id, "run_ids": sorted(run_ids)}
        for (version, attempt_id), run_ids in sorted(attempt_locations.items())
        if len(run_ids) > 1
    )

    for version in ("haupt", "alt", "neu"):
        rows = selected_rows[version]
        for row in rows:
            run_id = row.get("run_id") or row.get("slot_id")
            if not isinstance(run_id, str):
                continue
            arm = str(row.get("arm"))
            per_attempt = attempts.get((version, run_id), {})
            row_usage_total = {"input_tokens": 0, "output_tokens": 0}
            known_cost = Decimal("0")
            known_cost_count = 0
            usage_attempt_count = 0
            attempt_ids = set(per_attempt)
            raw_attempts = 0
            raw_usage_attempts = 0
            raw_cache_attempts = 0
            raw_prompt_covered = 0
            raw_completion_covered = 0
            raw_prompt_attempts = 0
            raw_completion_attempts = 0
            raw_token_match_attempts = 0
            cached_known = 0
            cache_input_covered = 0
            cache_write_known = 0
            cache_write_unknown_attempts = 0
            reasoning_known = 0
            reasoning_unknown_attempts = 0
            no_raw_response_attempts = 0
            usage_missing_tokens_attempts = 0
            usage_missing_cost_attempts = 0
            attempt_call_counts: Counter[str] = Counter()
            for attempt_id, item in per_attempt.items():
                usage = item.get("usage")
                raw_detail = responses.get((version, attempt_id))
                if raw_detail is not None:
                    raw_attempts += 1
                else:
                    no_raw_response_attempts += 1
                if usage is None:
                    continue
                usage_attempt_count += 1
                if raw_detail is not None:
                    raw_usage_attempts += 1
                input_tokens = int_value(usage.get("input_tokens"))
                output_tokens = int_value(usage.get("output_tokens"))
                cost = decimal_value(usage.get("cost_usd"))
                if input_tokens is None or output_tokens is None:
                    usage_missing_tokens_attempts += 1
                if input_tokens is not None:
                    row_usage_total["input_tokens"] += input_tokens
                if output_tokens is not None:
                    row_usage_total["output_tokens"] += output_tokens
                if cost is None:
                    usage_missing_cost_attempts += 1
                    missing_usage_costs.append(
                        {"version": version, "arm": arm, "block_id": row.get("block_id"), "attempt_id": attempt_id}
                    )
                else:
                    known_cost += cost
                    known_cost_count += 1
                if raw_detail is None:
                    cache_write_unknown_attempts += 1
                    reasoning_unknown_attempts += 1
                    continue
                raw_prompt = raw_detail.get("prompt_tokens")
                raw_completion = raw_detail.get("completion_tokens")
                prompt_matches = raw_prompt is not None and input_tokens is not None and raw_prompt == input_tokens
                completion_matches = raw_completion is not None and output_tokens is not None and raw_completion == output_tokens
                if raw_prompt is not None:
                    raw_prompt_attempts += 1
                    raw_prompt_covered += int(raw_prompt)
                if raw_completion is not None:
                    raw_completion_attempts += 1
                    raw_completion_covered += int(raw_completion)
                if prompt_matches and completion_matches:
                    raw_token_match_attempts += 1
                if raw_prompt is not None and input_tokens is not None and raw_prompt != input_tokens:
                    token_mismatches.append(
                        {
                            "version": version,
                            "arm": arm,
                            "block_id": row.get("block_id"),
                            "attempt_id": attempt_id,
                            "journal_input_tokens": input_tokens,
                            "response_prompt_tokens": raw_detail.get("prompt_tokens"),
                        }
                    )
                if raw_completion is not None and output_tokens is not None and raw_completion != output_tokens:
                    token_mismatches.append(
                        {
                            "version": version,
                            "arm": arm,
                            "block_id": row.get("block_id"),
                            "attempt_id": attempt_id,
                            "journal_output_tokens": output_tokens,
                            "response_completion_tokens": raw_detail.get("completion_tokens"),
                        }
                    )
                cached = raw_detail.get("cached_tokens")
                if cached is not None and input_tokens is not None:
                    raw_cache_attempts += 1
                    cache_input_covered += input_tokens
                    cached_known += cached
                    if cached > input_tokens:
                        token_mismatches.append(
                            {
                                "version": version,
                                "arm": arm,
                                "block_id": row.get("block_id"),
                                "attempt_id": attempt_id,
                                "cached_tokens_exceed_input": {"cached": cached, "input": input_tokens},
                            }
                        )
                cache_write = raw_detail.get("cache_write_tokens")
                if cache_write is None:
                    cache_write_unknown_attempts += 1
                else:
                    cache_write_known += cache_write
                reasoning = raw_detail.get("reasoning_tokens")
                if reasoning is None:
                    reasoning_unknown_attempts += 1
                else:
                    reasoning_known += reasoning
                    completion = raw_detail.get("completion_tokens")
                    if completion is not None and reasoning > completion:
                        token_mismatches.append(
                            {
                                "version": version,
                                "arm": arm,
                                "block_id": row.get("block_id"),
                                "attempt_id": attempt_id,
                                "reasoning_tokens_exceed_completion": {"reasoning": reasoning, "completion": completion},
                            }
                        )
                provider_cost = decimal_value(raw_detail.get("reported_cost_usd"))
                if provider_cost is not None and cost is not None and provider_cost != cost:
                    provider_cost_mismatches.append(
                        {
                            "version": version,
                            "arm": arm,
                            "block_id": row.get("block_id"),
                            "attempt_id": attempt_id,
                            "provider_reported_cost_usd": decimal_text(provider_cost),
                            "usage_log_cost_usd": decimal_text(cost),
                            "difference_usd": decimal_text(provider_cost - cost),
                        }
                    )
                if raw_detail.get("cached_tokens") is not None and provider_cost is not None:
                    prompt = raw_prompt
                    completion = raw_completion
                    cached_value = raw_detail.get("cached_tokens")
                    if prompt is not None and completion is not None and cached_value <= prompt:
                        with localcontext() as ctx:
                            ctx.prec = 40
                            calculated = (
                                Decimal(prompt - cached_value) * PRICE_INPUT
                                + Decimal(cached_value) * PRICE_CACHE
                                + Decimal(completion) * PRICE_OUTPUT
                            ) / Decimal(1_000_000)
                        delta = provider_cost - calculated
                        price_records[version].append(
                            {
                                "arm": arm,
                                "block_id": row.get("block_id"),
                                "attempt_id": attempt_id,
                                "reported_cost_usd": decimal_text(provider_cost),
                                "usage_log_cost_usd": decimal_text(cost),
                                "calculated_cost_usd": decimal_text(calculated),
                                "difference_usd": decimal_text(delta),
                                "absolute_difference_usd": abs(delta),
                            }
                        )

            total_attempts = len(attempt_ids)
            if total_attempts == 0:
                missing_source_rows.append(
                    {"version": version, "arm": arm, "block_id": row.get("block_id"), "slot_id": row.get("slot_id")}
                )
            result_cost = decimal_value(row.get("cost_usd"))
            if result_cost is None:
                missing_result_costs.append(
                    {"version": version, "arm": arm, "block_id": row.get("block_id"), "slot_id": row.get("slot_id")}
                )
            elif result_cost != known_cost:
                cost_mismatches.append(
                    {
                        "version": version,
                        "arm": arm,
                        "block_id": row.get("block_id"),
                        "slot_id": row.get("slot_id"),
                        "result_cost_usd": decimal_text(result_cost),
                        "sum_usage_cost_usd": decimal_text(known_cost),
                        "difference_usd": decimal_text(known_cost - result_cost),
                        "attempts": total_attempts,
                        "attempts_with_usage_cost": known_cost_count,
                    }
                )

            attempts_without_usage = sum(1 for item in per_attempt.values() if item.get("usage") is None)
            call_count = int_value(row.get("call_count"))
            if call_count is not None and call_count != usage_attempt_count:
                attempt_call_counts["call_count_vs_usage_attempts"] += 1
            input_sum = row_usage_total["input_tokens"]
            output_sum = row_usage_total["output_tokens"]
            cache_split_complete = (
                raw_cache_attempts == usage_attempt_count
                and usage_missing_tokens_attempts == 0
            )
            input_without_cache_known = cache_input_covered - cached_known
            if cache_split_complete:
                input_without_cache: int | None = input_without_cache_known
                input_cached: int | None = cached_known
            else:
                input_without_cache = None
                input_cached = None
            row_report = {
                "panel": row.get("panel"),
                "arm": arm,
                "source_version": version,
                "block_id": row.get("block_id"),
                "slot_id": row.get("slot_id"),
                "tokens": {
                    "input_tokens_total": input_sum,
                    "input_tokens_without_cache": input_without_cache,
                    "input_tokens_from_cache": input_cached,
                    "input_tokens_without_cache_known": input_without_cache_known,
                    "input_tokens_from_cache_known": cached_known,
                    "input_tokens_cache_field_covered": cache_input_covered,
                    "input_tokens_cache_unclassified": max(0, input_sum - cache_input_covered),
                    "output_tokens": output_sum,
                    "reasoning_tokens_known": reasoning_known,
                    "reasoning_tokens_unknown_attempts": reasoning_unknown_attempts,
                    "cache_write_tokens_known": cache_write_known,
                    "cache_write_tokens_unknown_attempts": cache_write_unknown_attempts,
                },
                "attempts": total_attempts,
                "attempts_with_usage": usage_attempt_count,
                "attempts_without_usage": attempts_without_usage,
                "attempts_without_raw_response": no_raw_response_attempts,
                "attempts_with_raw_response": raw_attempts,
                "attempts_with_usage_and_raw_response": raw_usage_attempts,
                "attempts_with_cache_field": raw_cache_attempts,
                "attempts_with_usage_missing_token_fields": usage_missing_tokens_attempts,
                "attempts_with_usage_missing_cost": usage_missing_cost_attempts,
                "raw_prompt_tokens": raw_prompt_covered,
                "raw_completion_tokens": raw_completion_covered,
                "attempts_with_raw_prompt_tokens": raw_prompt_attempts,
                "attempts_with_raw_completion_tokens": raw_completion_attempts,
                "attempts_with_matching_prompt_and_completion_tokens": raw_token_match_attempts,
                "known_cost_usd": decimal_text(known_cost),
                "result_cost_usd": decimal_text(result_cost),
                "cost_match": result_cost == known_cost if result_cost is not None else None,
            }
            output_rows.append(row_report)

    # Summaries and controls by arm/version.
    for version in ("haupt", "alt", "neu"):
        rows = selected_rows[version]
        arms_here = ("S-k",) if version in ("alt", "neu") else ("S", "F", "Q", "Z", "D")
        for arm in arms_here:
            arm_rows = [record for record in output_rows if record["source_version"] == version and record["arm"] == arm]
            total_input = sum(record["tokens"]["input_tokens_total"] for record in arm_rows)
            total_output = sum(record["tokens"]["output_tokens"] for record in arm_rows)
            total_cached_known = sum(record["tokens"]["input_tokens_from_cache_known"] for record in arm_rows)
            total_noncache_known = sum(record["tokens"]["input_tokens_without_cache_known"] for record in arm_rows)
            total_cache_covered_input = sum(record["tokens"]["input_tokens_cache_field_covered"] for record in arm_rows)
            total_unclassified = sum(record["tokens"]["input_tokens_cache_unclassified"] for record in arm_rows)
            total_reasoning = sum(record["tokens"]["reasoning_tokens_known"] for record in arm_rows)
            total_reasoning_unknown = sum(record["tokens"]["reasoning_tokens_unknown_attempts"] for record in arm_rows)
            total_cache_write = sum(record["tokens"]["cache_write_tokens_known"] for record in arm_rows)
            total_cache_write_unknown = sum(record["tokens"]["cache_write_tokens_unknown_attempts"] for record in arm_rows)
            all_attempts = sum(record["attempts"] for record in arm_rows)
            usage_attempts = sum(record["attempts_with_usage"] for record in arm_rows)
            attempts_without_raw = sum(record["attempts_without_raw_response"] for record in arm_rows)
            response_attempts = sum(record["attempts_with_raw_response"] for record in arm_rows)
            usage_response_attempts = sum(record["attempts_with_usage_and_raw_response"] for record in arm_rows)
            cache_attempts = sum(record["attempts_with_cache_field"] for record in arm_rows)
            usage_attempts_missing_tokens = sum(record["attempts_with_usage_missing_token_fields"] for record in arm_rows)
            usage_attempts_missing_cost = sum(record["attempts_with_usage_missing_cost"] for record in arm_rows)
            raw_prompt_tokens = sum(record["raw_prompt_tokens"] for record in arm_rows)
            raw_completion_tokens = sum(record["raw_completion_tokens"] for record in arm_rows)
            raw_prompt_attempts = sum(record["attempts_with_raw_prompt_tokens"] for record in arm_rows)
            raw_completion_attempts = sum(record["attempts_with_raw_completion_tokens"] for record in arm_rows)
            raw_token_match_attempts = sum(record["attempts_with_matching_prompt_and_completion_tokens"] for record in arm_rows)
            known_costs = [decimal_value(record["known_cost_usd"]) or Decimal("0") for record in arm_rows]
            total_cost = sum(known_costs, Decimal("0"))
            expected_total = sum(
                (decimal_value(row.get("cost_usd")) or Decimal("0")) for row in rows if row.get("arm") == arm
            )
            expected_cost_per_1000 = (total_cost / Decimal(N_TASKS) * Decimal(1000)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            result_cost_per_1000 = (expected_total / Decimal(N_TASKS) * Decimal(1000)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            total_attempts_in_rows = all_attempts
            price_list = [item for item in price_records[version] if item["arm"] == arm]
            exact = sum(1 for item in price_list if Decimal(item["difference_usd"]) == 0)
            within_nonexact = sum(
                1
                for item in price_list
                if Decimal(item["difference_usd"]) != 0
                and abs(Decimal(item["difference_usd"])) <= PRICE_TOLERANCE
            )
            outside = sum(1 for item in price_list if abs(Decimal(item["difference_usd"])) > PRICE_TOLERANCE)
            raw_complete_attempts = sum(
                1
                for record in arm_rows
                for attempt_id in attempts.get((version, record["slot_id"]), {})
                if (version, attempt_id) in responses
            )
            group_cost_match_rows = sum(1 for record in arm_rows if record["cost_match"] is True)
            group_cost_mismatch_rows = sum(1 for record in arm_rows if record["cost_match"] is False)
            summary = {
                "source_version": version,
                "arm": arm,
                "rows": len(arm_rows),
                "denominator_tasks": N_TASKS,
                "totals": {
                    "input_tokens_total": total_input,
                    "input_tokens_without_cache_known": total_noncache_known,
                    "input_tokens_from_cache_known": total_cached_known,
                    "input_tokens_cache_field_covered": total_cache_covered_input,
                    "input_tokens_cache_unclassified": total_unclassified,
                    "output_tokens": total_output,
                    "reasoning_tokens_known": total_reasoning,
                    "reasoning_tokens_unknown_attempts": total_reasoning_unknown,
                    "cache_write_tokens_known": total_cache_write,
                    "cache_write_tokens_unknown_attempts": total_cache_write_unknown,
                    "attempts": total_attempts_in_rows,
                    "attempts_with_usage": usage_attempts,
                    "attempts_without_raw_response": attempts_without_raw,
                    "attempts_with_raw_response": response_attempts,
                    "attempts_with_cache_field": cache_attempts,
                    "attempts_with_usage_missing_token_fields": usage_attempts_missing_tokens,
                    "attempts_with_usage_missing_cost": usage_attempts_missing_cost,
                    "known_cost_usd": decimal_text(total_cost),
                    "result_cost_usd": decimal_text(expected_total),
                },
                "means_per_task": {
                    "input_tokens_total": mean_text(total_input) if usage_attempts_missing_tokens == 0 else None,
                    "input_tokens_without_cache": mean_text(total_noncache_known) if total_unclassified == 0 and usage_attempts_missing_tokens == 0 else None,
                    "input_tokens_from_cache": mean_text(total_cached_known) if total_unclassified == 0 and usage_attempts_missing_tokens == 0 else None,
                    "input_tokens_without_cache_known_subset_total_divided_by_2952": mean_text(total_noncache_known),
                    "input_tokens_from_cache_known_subset_total_divided_by_2952": mean_text(total_cached_known),
                    "input_tokens_cache_unclassified": mean_text(total_unclassified),
                    "output_tokens": mean_text(total_output) if usage_attempts_missing_tokens == 0 else None,
                    "reasoning_tokens_known": mean_text(total_reasoning) if total_reasoning_unknown == 0 else None,
                    "reasoning_tokens_known_subset_total_divided_by_2952": mean_text(total_reasoning),
                    "cache_write_tokens_known": mean_text(total_cache_write) if total_cache_write_unknown == 0 else None,
                    "cache_write_tokens_known_subset_total_divided_by_2952": mean_text(total_cache_write),
                    "attempts": mean_text(total_attempts_in_rows),
                },
                "coverage": {
                    "raw_response_attempts_of_usage_attempts": f"{usage_response_attempts}/{usage_attempts}",
                    "raw_response_attempt_coverage": ratio_text(usage_response_attempts, usage_attempts),
                    "cache_field_attempts_of_usage_attempts": f"{cache_attempts}/{usage_attempts}",
                    "cache_field_attempt_coverage": ratio_text(cache_attempts, usage_attempts),
                    "raw_prompt_tokens": raw_prompt_tokens,
                    "attempts_with_raw_prompt_tokens": raw_prompt_attempts,
                    "logged_input_tokens": total_input,
                    "raw_prompt_token_coverage": ratio_text(raw_prompt_tokens, total_input),
                    "raw_completion_tokens": raw_completion_tokens,
                    "attempts_with_raw_completion_tokens": raw_completion_attempts,
                    "logged_output_tokens": total_output,
                    "raw_completion_token_coverage": ratio_text(raw_completion_tokens, total_output),
                    "attempts_with_matching_prompt_and_completion_tokens": raw_token_match_attempts,
                    "cache_field_input_tokens": total_cache_covered_input,
                    "logged_input_tokens_cache_field_coverage": ratio_text(total_cache_covered_input, total_input),
                    "input_tokens_cache_unclassified": total_unclassified,
                },
                "cost_control": {
                    "rows_equal_exactly": group_cost_match_rows,
                    "rows_different": group_cost_mismatch_rows,
                    "cost_usd_per_1000_from_usage_logs": decimal_text(expected_cost_per_1000),
                    "cost_usd_per_1000_from_result_rows": decimal_text(result_cost_per_1000),
                    "expected_cost_usd_per_1000": decimal_text(EXPECTED_COST_PER_1000[arm]) if version != "alt" else None,
                    "expected_cost_control_matches": (
                        expected_cost_per_1000 == EXPECTED_COST_PER_1000[arm] if version != "alt" else None
                    ),
                },
                "price_control": {
                    "calculable_attempts": len(price_list),
                    "exact_matches": exact,
                    "nonexact_within_1e_9_usd": within_nonexact,
                    "outside_1e_9_usd": outside,
                    "largest_absolute_difference_usd": (
                        decimal_text(max((Decimal(item["absolute_difference_usd"]) for item in price_list), default=Decimal("0")))
                        if price_list
                        else None
                    ),
                },
            }
            arm_summaries.append(summary)

    arm_summaries.sort(key=lambda item: (0 if item["source_version"] == "haupt" else 1 if item["source_version"] == "alt" else 2, arm_key_order[item["arm"]]))
    output_rows.sort(
        key=lambda item: (
            item["panel"],
            int(str(item["block_id"]).rsplit(":", 1)[-1]),
            0 if item["source_version"] == "haupt" else 1 if item["source_version"] == "alt" else 2,
            arm_key_order.get(item["arm"], 99),
        )
    )

    # Row count and key checks are done against the inputs, not guessed from paths.
    row_counts_main = Counter(row.get("arm") for row in rows_main if row.get("panel") == PANEL)
    row_counts_sk = Counter(row.get("arm") for row in rows_sk if row.get("panel") == PANEL)
    row_key_duplicates_main = len(rows_main) - len(main_index)
    row_key_duplicates_sk = len(rows_sk) - len(sk_index_all)
    row_cost_matches = sum(1 for record in output_rows if record["cost_match"] is True)
    row_cost_differences = len(cost_mismatches)
    all_usage_attempts = sum(item["totals"]["attempts_with_usage"] for item in arm_summaries)
    all_attempts = sum(item["totals"]["attempts"] for item in arm_summaries)
    all_raw_attempts = sum(item["totals"]["attempts_with_raw_response"] for item in arm_summaries)
    all_raw_usage_attempts = sum(
        int(item["coverage"]["raw_response_attempts_of_usage_attempts"].split("/", 1)[0])
        for item in arm_summaries
    )
    all_cache_attempts = sum(item["totals"]["attempts_with_cache_field"] for item in arm_summaries)
    all_pricing = [item for values in price_records.values() for item in values]
    all_price_exact = sum(1 for item in all_pricing if Decimal(item["difference_usd"]) == 0)
    all_price_nonexact_within = sum(
        1
        for item in all_pricing
        if Decimal(item["difference_usd"]) != 0 and abs(Decimal(item["difference_usd"])) <= PRICE_TOLERANCE
    )
    all_price_outside = sum(1 for item in all_pricing if abs(Decimal(item["difference_usd"])) > PRICE_TOLERANCE)
    top_deviations = sorted(
        all_pricing,
        key=lambda item: (Decimal(item["absolute_difference_usd"]), item["arm"], item["block_id"], item["attempt_id"]),
        reverse=True,
    )[:20]
    for item in top_deviations:
        item.pop("absolute_difference_usd", None)

    input_meta = []
    for rel, rows in ((ROWS_MAIN_REL, rows_main), (ROWS_SK_REL, rows_sk)):
        input_meta.append(
            {
                "path": rel.as_posix(),
                "sha256": sha256_file(project_root / rel),
                "rows": len(rows),
            }
        )

    control_checks = {
        "result_row_counts": {
            "status": "bestanden" if all(row_counts_main[arm] == N_TASKS for arm in ARMS) and all(row_counts_sk[arm] == N_TASKS for arm in ARMS) else "nicht_bestanden",
            "z53_rows": len(rows_main),
            "z54_rows": len(rows_sk),
            "z53_by_arm": dict(sorted(row_counts_main.items())),
            "z54_by_arm": dict(sorted(row_counts_sk.items())),
            "duplicate_keys_z53": row_key_duplicates_main,
            "duplicate_keys_z54": row_key_duplicates_sk,
        },
        "z54_non_sk_rows_copied_exactly": {
            "status": "bestanden" if z54_non_sk_exact == z53_non_sk_exact and len(z54_non_sk) == 5 * N_TASKS else "nicht_bestanden",
            "z54_non_sk_rows": len(z54_non_sk),
            "z53_non_sk_rows": len(z53_non_sk),
            "exact_multiset_match": z54_non_sk_exact == z53_non_sk_exact,
            "new_sk_rows": len(new_sk_rows),
            "new_sk_rows_different_from_old": new_old_sk_differences,
        },
        "attempt_to_row_mapping": {
            "status": "bestanden" if (
                not missing_source_rows
                and not unmapped_source_rows
                and not attempt_row_mismatches
                and not any(key.startswith("journal_run_id_disagreements:") and value for key, value in source_counts.items())
            ) else "nicht_bestanden",
            "rows_without_attempt_records": len(missing_source_rows),
            "unmapped_source_result_records": len(unmapped_source_rows),
            "attempt_ids_assigned_to_multiple_rows": len(attempt_row_mismatches),
            "attempt_row_mapping_conflicts": attempt_row_mismatches,
            "journal_result_run_id_disagreements": sum(
                value for key, value in source_counts.items() if key.startswith("journal_run_id_disagreements:")
            ),
            "unique_attempts": all_attempts,
            "attempts_with_usage": all_usage_attempts,
            "attempts_without_usage": all_attempts - all_usage_attempts,
            "attempts_with_raw_response": all_raw_attempts,
            "attempts_without_raw_response": all_attempts - all_raw_attempts,
        },
        "row_cost_sums": {
            "status": "bestanden" if not cost_mismatches and not missing_usage_costs and not missing_result_costs else "nicht_bestanden",
            "rows_equal_exactly": row_cost_matches,
            "rows_different": row_cost_differences,
            "rows_missing_result_cost": len(missing_result_costs),
            "attempts_with_usage_but_missing_cost": len(missing_usage_costs),
            "deviations": cost_mismatches,
            "missing_result_cost_rows": missing_result_costs,
        },
        "raw_response_tokens_vs_logs": {
            "status": "bestanden" if not token_mismatches else "nicht_bestanden",
            "token_mismatches": len(token_mismatches),
            "mismatches": token_mismatches,
        },
        "provider_reported_cost_vs_usage_logs": {
            "status": "bestanden" if not provider_cost_mismatches else "nicht_bestanden",
            "mismatches": len(provider_cost_mismatches),
            "deviations": provider_cost_mismatches,
        },
        "attempt_id_double_count_check": {
            "status": "bestanden" if not conflicting_usage and not provider_conflicts and not attempt_row_mismatches else "nicht_bestanden",
            "duplicate_usage_records_ignored": dict(sorted(duplicate_usage_records.items())),
            "conflicting_usage_duplicates": conflicting_usage,
            "conflicting_provider_copies": provider_conflicts,
            "provider_conflicts_resolved_by_latest_provider_timestamp": dict(sorted(resolved_provider_conflicts.items())),
            "note": "Versuche werden je Quellstand und attempt_id einmal gezählt. Mehrere gebundene Rohantworten werden ohne Rückgriff auf Lauf-Tokens oder Laufkosten nach Anbieterzeitstempel, Antwortteilfolge und Feldvollständigkeit aufgelöst; gleichrangige widersprüchliche Antworten bleiben als Mehrdeutigkeit offen.",
        },
        "provider_response_coverage": {
            "status": "vollständig" if all_raw_usage_attempts == all_usage_attempts else "teilweise",
            "usage_attempts": all_usage_attempts,
            "attempts_with_raw_response": all_raw_usage_attempts,
            "attempts_with_any_raw_response": all_raw_attempts,
            "attempts_with_cache_field": all_cache_attempts,
            "raw_response_attempt_coverage": ratio_text(all_raw_usage_attempts, all_usage_attempts),
            "cache_field_attempt_coverage": ratio_text(all_cache_attempts, all_usage_attempts),
            "raw_provider_file_counts": dict(sorted(provider_counts.items())),
            "by_arm": [summary["coverage"] | {"source_version": summary["source_version"], "arm": summary["arm"]} for summary in arm_summaries],
        },
        "price_formula": {
            "status": "bestanden" if all_price_outside == 0 else "nicht_bestanden",
            "formula": "((prompt_tokens - cached_tokens) * 0.10 + cached_tokens * 0.01 + completion_tokens * 0.40) / 1,000,000 USD",
            "tolerance_usd": decimal_text(PRICE_TOLERANCE),
            "calculable_attempts": len(all_pricing),
            "exact_matches": all_price_exact,
            "nonexact_within_1e_9_usd": all_price_nonexact_within,
            "outside_1e_9_usd": all_price_outside,
            "not_calculable_missing_provider_cost_or_response_or_cache": all_usage_attempts - len(all_pricing),
            "largest_absolute_deviations": top_deviations,
        },
        "reasoning_tokens": {
            "status": "bestanden" if not any("reasoning_tokens_exceed_completion" in item for item in token_mismatches) else "nicht_bestanden",
            "interpretation": "reasoning_tokens werden als Detailmenge innerhalb completion_tokens behandelt und nicht zusätzlich zu den Ausgabetokens addiert.",
            "summed_separately": True,
            "usage_field": "completion_tokens_details.reasoning_tokens",
        },
        "cost_per_1000_tasks": {
            "status": "bestanden" if all(
                summary["cost_control"]["expected_cost_control_matches"] is True
                for summary in arm_summaries
                if summary["source_version"] in ("haupt", "neu")
            ) else "nicht_bestanden",
            "table_arms": {
                summary["arm"]: {
                    "calculated_usd_per_1000": summary["cost_control"]["cost_usd_per_1000_from_usage_logs"],
                    "result_rows_usd_per_1000": summary["cost_control"]["cost_usd_per_1000_from_result_rows"],
                    "expected_usd_per_1000": summary["cost_control"]["expected_cost_usd_per_1000"],
                    "matches": summary["cost_control"]["expected_cost_control_matches"],
                }
                for summary in arm_summaries
                if summary["source_version"] in ("haupt", "neu")
            },
        },
    }

    open_points = []
    for summary in arm_summaries:
        if summary["totals"]["input_tokens_cache_unclassified"]:
            open_points.append(
                f"{summary['source_version']} {summary['arm']}: Cache-Aufteilung für {summary['totals']['input_tokens_cache_unclassified']} Eingabetokens nicht belegt."
            )
        if summary["totals"]["attempts_with_usage_missing_token_fields"]:
            open_points.append(
                f"{summary['source_version']} {summary['arm']}: {summary['totals']['attempts_with_usage_missing_token_fields']} Versuche mit unvollständigen Tokenfeldern im Laufprotokoll."
            )
        if summary["totals"]["attempts_without_raw_response"]:
            open_points.append(
                f"{summary['source_version']} {summary['arm']}: {summary['totals']['attempts_without_raw_response']} Versuche ohne Rohantwort."
            )
        if summary["price_control"]["outside_1e_9_usd"]:
            open_points.append(
                f"{summary['source_version']} {summary['arm']}: {summary['price_control']['outside_1e_9_usd']} berechenbare Versuche außerhalb der Preistoleranz."
            )
    if missing_source_rows:
        open_points.append(f"{len(missing_source_rows)} Ergebniszeilen ohne Laufversuche.")
    if cost_mismatches:
        open_points.append(f"{len(cost_mismatches)} Zeilenkosten weichen von den Laufkosten ab.")
    if missing_result_costs:
        open_points.append(f"{len(missing_result_costs)} Ergebniszeilen ohne cost_usd.")
    if provider_cost_mismatches:
        open_points.append(f"{len(provider_cost_mismatches)} provider cost-Werte weichen von den Laufprotokollen ab.")
    if token_mismatches:
        open_points.append(f"{len(token_mismatches)} Tokenwerte zwischen Laufprotokoll und Rohantwort weichen ab.")
    if conflicting_usage or provider_conflicts:
        open_points.append("Mindestens eine doppelte usage-Angabe oder Rohantwortkopie ist widersprüchlich.")
    if not open_points:
        open_points.append("Keine offenen Punkte in den geprüften Daten.")

    summary = {
        "schema_version": 1,
        "purpose": "Tokens per task for the reference-comparison R panel; no answers, prompts, or external file paths stored.",
        "denominator_tasks_per_arm": N_TASKS,
        "input_result_files": input_meta,
        "source_roots": [
            {"label": label, "path": rel, "kind": kind}
            for label, rel, kind in source_roots
        ],
        "row_selection": {
            "z53": "All six arms from rows-R.json; S-k is the old arm and is reported separately.",
            "z54": "S-k only for the new arm. The other 14,760 rows are checked as exact copies of Z53 rows and excluded from aggregation.",
            "z54_s_k_same_ids": "Z54 reuses the old run_id/slot_id values; the new arm is distinguished by its Z54 source root.",
        },
        "source_inventory_counts": dict(sorted(source_counts.items())),
        "control_checks": control_checks,
        "arms": arm_summaries,
        "open_points": open_points,
    }

    report = render_report(summary)
    return summary, output_rows, report


def format_mean(value: str | None) -> str:
    if value is None:
        return "nicht vollständig belegt"
    return f"{Decimal(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def run_post_write_find(project_root: Path, output_dir: Path) -> dict[str, Any]:
    Auftrag = output_dir / "AUFTRAG.md"
    command = ["find", str(project_root), "-newer", str(Auftrag), "-type", "f"]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    candidates = [Path(line).resolve() for line in completed.stdout.splitlines() if line.strip()]
    output_resolved = output_dir.resolve()
    inside = []
    outside = []
    for path in candidates:
        try:
            relative = path.relative_to(project_root)
        except ValueError:
            outside.append(path)
            continue
        try:
            relative.relative_to(output_resolved.relative_to(project_root))
            inside.append(relative.as_posix())
        except ValueError:
            outside.append(path)
    return {
        "status": "ausgeführt",
        "command": "find <Projektwurzel> -newer AUFTRAG.md -type f",
        "files_newer_than_auftrag": len(candidates),
        "files_inside_output_dir": len(inside),
        "files_outside_output_dir": len(outside),
        "outside_output_paths_project_relative_sample": [
            path.relative_to(project_root).as_posix()
            for path in outside[:10]
            if path.is_relative_to(project_root)
        ],
        "outside_project_file_count": sum(not path.is_relative_to(project_root) for path in outside),
        "write_scope": output_dir.resolve().relative_to(project_root).as_posix(),
    }


def render_report(summary: dict[str, Any]) -> str:
    checks = summary["control_checks"]
    rows = []
    for item in summary["arms"]:
        version = item["source_version"]
        arm = item["arm"]
        label = arm
        if version == "alt":
            label = "S-k alt (gesondert)"
        elif version == "neu":
            label = "S-k neu"
        means = item["means_per_task"]
        cost = item["cost_control"]
        price = item["price_control"]
        rows.append(
            "| "
            + " | ".join(
                [
                    label,
                    format_mean(means["input_tokens_without_cache"]),
                    format_mean(means["input_tokens_from_cache"]),
                    format_mean(means["output_tokens"]),
                    format_mean(means["reasoning_tokens_known"]),
                    format_mean(means["cache_write_tokens_known"]),
                    format_mean(means["attempts"]),
                    f"{Decimal(cost['cost_usd_per_1000_from_usage_logs']):.2f}".replace(".", ",") + " USD",
                    f"{cost['rows_equal_exactly']}/{item['rows']} Zeilen",
                    f"Preis: {price['exact_matches']} exakt, {price['nonexact_within_1e_9_usd']} ≤1e-9, {price['outside_1e_9_usd']} darüber",
                    (f"{Decimal(price['largest_absolute_difference_usd']):f}".replace(".", ",") if price["largest_absolute_difference_usd"] is not None else "n/a") + " USD",
                ]
            )
            + " |"
        )
    check_lines = []
    for key, title in (
        ("result_row_counts", "Zeilenbestand"),
        ("z54_non_sk_rows_copied_exactly", "Z54-Nicht-S-k-Zeilen"),
        ("attempt_to_row_mapping", "Laufdatenzuordnung"),
        ("row_cost_sums", "Zeilenkosten"),
        ("raw_response_tokens_vs_logs", "Rohantwort-Tokenkontrolle"),
        ("provider_reported_cost_vs_usage_logs", "Providerkosten gegen Laufprotokolle"),
        ("attempt_id_double_count_check", "Doppelzählung"),
        ("provider_response_coverage", "Rohantwort-/Cacheabdeckung"),
        ("price_formula", "Preisformel"),
        ("reasoning_tokens", "Reasoning-Tokens"),
        ("cost_per_1000_tasks", "Kosten je 1.000 Aufgaben"),
    ):
        check = checks[key]
        status = check.get("status", "-")
        check_lines.append(f"- **{title}:** {status}.")

    inputs = "\n".join(
        f"- `{item['path']}` — {item['rows']:,} Zeilen; SHA-256 `{item['sha256']}`".replace(",", ".")
        for item in summary["input_result_files"]
    )
    sources = "\n".join(f"- `{item['path']}/blocks` ({item['label']})" for item in summary["source_roots"])
    open_points = "\n".join(f"- {item}" for item in summary["open_points"])
    coverage_lines = []
    for item in summary["arms"]:
        coverage = item["coverage"]
        coverage_lines.append(
            f"- {item['source_version']} / {item['arm']}: Rohantworten "
            f"{coverage['raw_response_attempts_of_usage_attempts']} Versuche "
            f"({coverage['raw_response_attempt_coverage'] or 'n/a'}); Cache-Angabe "
            f"{coverage['cache_field_attempts_of_usage_attempts']} Versuche "
            f"({coverage['cache_field_attempt_coverage'] or 'n/a'}); Prompt-Tokenabdeckung "
            f"{coverage['raw_prompt_token_coverage'] or 'n/a'}; Completion-Tokenabdeckung "
            f"{coverage['raw_completion_token_coverage'] or 'n/a'}; Cacheklassifizierung "
            f"{coverage['logged_input_tokens_cache_field_coverage'] or 'n/a'} der Eingabetokens; nicht cacheklassifizierte Eingabetokens "
            f"{item['totals']['input_tokens_cache_unclassified']:,}.".replace(",", ".")
        )
    return (
        "# Token-Referenzvergleich\n\n"
        "## Ergebnis je Arm\n\n"
        "Mittelwerte je Aufgabe; der Nenner beträgt 2.952. Reasoning ist als Teil der Ausgabetokens separat ausgewiesen. "
        "Kosten je 1.000 Aufgaben stammen aus den Laufprotokollen und wurden sowohl mit den Ergebniszeilen als auch mit dem gebundenen Sollwert geprüft.\n\n"
        "| Arm | Eingabe ohne Cache | Eingabe aus Cache | Ausgabe | davon Reasoning | Cache-Schreibtokens | Modellversuche | USD / 1.000 | Zeilenkosten exakt | Preisformel je Versuch | max. Preisabweichung |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|\n"
        + "\n".join(rows)
        + "\n\n## Quellen und Zuordnung\n\n"
        "Ergebniszeilen:\n\n"
        + inputs
        + "\n\nLaufdaten:\n\n"
        + sources
        + "\n\nDie 0–2.182-Blöcke stammen aus den aufeinanderfolgenden Z52-Live-Abschnitten; die 2.183–2.951-Blöcke aus Z53. "
        "Z54 liefert 2.952 neue S-k-Zeilen; die übrigen 14.760 Zeilen sind fünf andere Arme mit je 2.952 Zeilen und stimmen exakt mit Z53 überein. Überlappende Sicherungsstände werden anhand von `attempt_id` dedupliziert; bei S-k werden alter und neuer Laufstand getrennt gehalten. Mehrere gebundene Provider-Rohantworten werden ohne Rückgriff auf Lauf-Tokens oder Laufkosten nach Anbieterzeitstempel, Antwortteilfolge und Feldvollständigkeit aufgelöst; gleichrangige widersprüchliche Antworten bleiben als Mehrdeutigkeit ausgewiesen. Tokenwerte und Providerkosten werden danach separat mit den Laufprotokollen verglichen. Ein terminaler Überlauffehler ohne Abschlussereignis wird aus seinem gespeicherten Buchungsdatensatz ergänzt.\n\n"
        "## Kontrollen\n\n"
        + "\n".join(check_lines)
        + "\n\nPreisformel im Einzelversuch: "
        + f"{checks['price_formula']['exact_matches']} exakt, "
        + f"{checks['price_formula']['nonexact_within_1e_9_usd']} innerhalb 1e-9 USD, "
        + f"{checks['price_formula']['outside_1e_9_usd']} darüber; "
        + f"{checks['price_formula']['not_calculable_missing_provider_cost_or_response_or_cache']} nicht berechenbar."
        + "\n\nRohantwort- und Cacheabdeckung je Arm:\n\n"
        + "\n".join(coverage_lines)
        + "\n\nDie Preisformel nutzt `(prompt_tokens − cached_tokens) × 0,10 + cached_tokens × 0,01 + completion_tokens × 0,40` je Million Tokens. "
        "Reasoning wird nicht zusätzlich auf `completion_tokens` aufgeschlagen. Fehlende Cache-Angaben werden nicht geschätzt; die betroffenen Eingabetokens stehen als nicht klassifiziert.\n\n"
        "## Offene Punkte\n\n"
        + open_points
        + "\n\n"
        + render_scope_check(summary.get("post_write_find_check"))
    )


def render_scope_check(check: dict[str, Any] | None) -> str:
    if check is None:
        return "Die geforderte Nachlaufprüfung mit `find <Projektwurzel> -newer AUFTRAG.md -type f` ist noch nicht dokumentiert.\n"
    outside_count = check["files_outside_output_dir"]
    sentence = (
        f"Nach dem Schreiben wurde `{check['command']}` ausgeführt: "
        f"{check['files_newer_than_auftrag']} Dateien gefunden, "
        f"davon {check['files_inside_output_dir']} im Ausgabeordner und {outside_count} außerhalb. "
        f"Das Auswertungsskript schreibt ausschließlich nach `{check['write_scope']}`."
    )
    samples = check.get("outside_output_paths_project_relative_sample", [])
    if samples:
        sentence += " Außerhalb gefundene Pfadbeispiele: " + ", ".join(f"`{path}`" for path in samples) + "."
    if check.get("outside_project_file_count"):
        sentence += f" Zusätzlich meldet `find` {check['outside_project_file_count']} Dateien außerhalb der Projektwurzel."
    return sentence + "\n"


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path, help="Projektwurzel der gespeicherten Laufdaten")
    args = parser.parse_args(argv)
    project_root = args.project_root.resolve()
    output_dir = Path(__file__).resolve().parent
    for required in (project_root / ROWS_MAIN_REL, project_root / ROWS_SK_REL):
        if not required.is_file():
            parser.error(f"Eingabedatei fehlt: {required.relative_to(project_root)}")
    summary, per_row, report = build_reports(project_root, output_dir)
    write_json(output_dir / "TOKENS-REFERENZVERGLEICH.json", summary)
    write_json(output_dir / "tokens-je-lauf.json", per_row)
    (output_dir / "BERICHT.md").write_text(report, encoding="utf-8")
    summary["post_write_find_check"] = run_post_write_find(project_root, output_dir)
    report = render_report(summary)
    write_json(output_dir / "TOKENS-REFERENZVERGLEICH.json", summary)
    (output_dir / "BERICHT.md").write_text(report, encoding="utf-8")
    print(json.dumps({
        "summary": str((output_dir / "TOKENS-REFERENZVERGLEICH.json").name),
        "per_row": str((output_dir / "tokens-je-lauf.json").name),
        "report": str((output_dir / "BERICHT.md").name),
        "controls": {key: value.get("status") for key, value in summary["control_checks"].items()},
        "open_points": len(summary["open_points"]),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
