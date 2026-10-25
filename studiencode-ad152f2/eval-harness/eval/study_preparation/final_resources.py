"""Local observations for Z50; no model cost or incremental arm-memory estimate.

The elapsed and CPU intervals begin when ProcessObservation is constructed and
end on its first finish call. CPU covers this process's threads, not children.
RUSAGE_SELF.ru_maxrss is the process high-water mark since process start: its
start/end readings are retained separately and are deliberately not subtracted.
Linux reports KiB; macOS reports bytes. Other platforms remain explicitly
unavailable rather than receiving a guessed conversion or a zero value.
"""
from copy import deepcopy
import math
import os
import sys
import time

try:
    import resource
except ImportError:  # Keep failure records possible on unsupported platforms.
    resource = None


SCHEMA = "z50-process-observation/v1"
SCOPE = {
    "wall": "elapsed_monotonic_time_between_observation_start_and_finish",
    "process_cpu": "current_process_user_and_system_cpu_all_threads_children_excluded",
    "peak_rss": "current_process_peak_since_process_start_not_incremental_arm_memory",
}
SOURCES = {
    "wall": "time.perf_counter_ns",
    "process_cpu": "time.process_time_ns",
    "utc": "time.time_ns",
    "peak_rss": "resource.getrusage(resource.RUSAGE_SELF).ru_maxrss",
}
UNITS = {"wall": "ns", "process_cpu": "ns", "utc": "unix_ns", "peak_rss": "bytes"}
_READ_FIELDS = (
    "process_id", "finished_process_id", "started_at_utc_ns", "finished_at_utc_ns",
    "wall_start_ns", "wall_end_ns", "process_cpu_start_ns", "process_cpu_end_ns",
    "ru_maxrss_start_raw", "ru_maxrss_end_raw",
)
_DERIVED_FIELDS = ("wall_ns", "process_cpu_ns", "peak_rss_start_bytes", "peak_rss_end_bytes")
_FIELDS = set(_READ_FIELDS + _DERIVED_FIELDS) | {
    "schema", "observation_status", "platform", "ru_maxrss_native_unit",
    "scope", "sources", "units", "errors",
}


def _native_unit(platform):
    return {"darwin": "bytes", "linux": "KiB"}.get(platform)


def _read(field, reader, errors):
    try:
        value = reader()
    except Exception:
        errors[field] = "read_failed"
        return None
    # ru_maxrss may be exposed as an integral float by a platform binding.
    if field.startswith("ru_maxrss_") and type(value) is float:
        value = int(value) if math.isfinite(value) and value.is_integer() else None
    positive = field not in ("wall_start_ns", "wall_end_ns", "process_cpu_start_ns", "process_cpu_end_ns")
    if type(value) is not int or value < (1 if positive else 0):
        errors[field] = "invalid_value"
        return None
    return value


def _maxrss():
    if resource is None:
        raise RuntimeError("resource module unavailable")
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def _duration(start, end, field, errors):
    if start is None or end is None:
        errors[field] = "missing_input"
        return None
    if end < start:
        errors[field] = "nonmonotonic_counter"
        return None
    return end - start


def _rss_bytes(raw, unit, field, errors):
    if raw is None:
        errors[field] = "missing_input"
        return None
    if unit is None:
        errors[field] = "unsupported_platform"
        return None
    return raw * (1024 if unit == "KiB" else 1)


class ProcessObservation:
    """Begin immediately; finish once, retaining explicit partial measurements."""

    def __init__(self):
        self._finished = None
        self._errors = {}
        self._record = {
            "schema": SCHEMA, "platform": sys.platform,
            "scope": deepcopy(SCOPE), "sources": deepcopy(SOURCES), "units": deepcopy(UNITS),
        }
        r, errors = self._record, self._errors
        r["process_id"] = _read("process_id", os.getpid, errors)
        r["started_at_utc_ns"] = _read("started_at_utc_ns", time.time_ns, errors)
        r["wall_start_ns"] = _read("wall_start_ns", time.perf_counter_ns, errors)
        r["process_cpu_start_ns"] = _read("process_cpu_start_ns", time.process_time_ns, errors)
        r["ru_maxrss_start_raw"] = _read("ru_maxrss_start_raw", _maxrss, errors)
        r["ru_maxrss_native_unit"] = _native_unit(r["platform"])
        if r["ru_maxrss_native_unit"] is None:
            errors["ru_maxrss_native_unit"] = "unsupported_platform"

    def finish(self):
        """Return the same interval on later calls, always as a separate dict."""
        if self._finished is not None:
            return deepcopy(self._finished)
        r, errors = self._record, self._errors
        r["ru_maxrss_end_raw"] = _read("ru_maxrss_end_raw", _maxrss, errors)
        r["process_cpu_end_ns"] = _read("process_cpu_end_ns", time.process_time_ns, errors)
        r["wall_end_ns"] = _read("wall_end_ns", time.perf_counter_ns, errors)
        r["finished_at_utc_ns"] = _read("finished_at_utc_ns", time.time_ns, errors)
        r["finished_process_id"] = _read("finished_process_id", os.getpid, errors)
        for kind in ("wall", "process_cpu"):
            r[kind + "_ns"] = _duration(r[kind + "_start_ns"], r[kind + "_end_ns"], kind + "_ns", errors)
        for endpoint in ("start", "end"):
            field = "peak_rss_" + endpoint + "_bytes"
            r[field] = _rss_bytes(r["ru_maxrss_" + endpoint + "_raw"], r["ru_maxrss_native_unit"], field, errors)
        if (r["peak_rss_start_bytes"] is not None and r["peak_rss_end_bytes"] is not None
                and r["peak_rss_end_bytes"] < r["peak_rss_start_bytes"]):
            r["peak_rss_end_bytes"] = None
            errors["peak_rss_end_bytes"] = "decreasing_process_peak"
        if (r["process_id"] is not None and r["finished_process_id"] is not None
                and r["process_id"] != r["finished_process_id"]):
            errors["process_identity"] = "process_changed"
        r["errors"] = dict(errors)
        r["observation_status"] = "incomplete" if errors else "complete"
        validate_observation(r, require_complete=False)
        self._finished = deepcopy(r)
        return deepcopy(self._finished)


def validate_observation(record, *, require_complete=True):
    """Reject missing, invented or inconsistent measurements; never impute zero.

    Explicit incomplete records are valid evidence of a measurement failure only
    when require_complete=False. They cannot certify the dependent study step.
    UTC references may move backwards after clock correction; elapsed durations
    come only from the monotone/process clocks, never subtraction of UTC values.
    """
    if not isinstance(record, dict) or set(record) != _FIELDS:
        raise ValueError("incomplete or changed process observation schema")
    if (record["schema"] != SCHEMA or record["scope"] != SCOPE
            or record["sources"] != SOURCES or record["units"] != UNITS
            or not isinstance(record["platform"], str) or not record["platform"]):
        raise ValueError("changed process observation semantics")
    errors = record["errors"]
    if not isinstance(errors, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in errors.items()):
        raise ValueError("invalid measurement errors")
    expected_errors = {}
    for field in _READ_FIELDS:
        value = record[field]
        positive = field not in ("wall_start_ns", "wall_end_ns", "process_cpu_start_ns", "process_cpu_end_ns")
        if value is None:
            if errors.get(field) not in ("read_failed", "invalid_value"):
                raise ValueError("missing observation without measurement failure")
            expected_errors[field] = errors[field]
        elif type(value) is not int or value < (1 if positive else 0):
            raise ValueError("invalid observation value")
    unit = _native_unit(record["platform"])
    if record["ru_maxrss_native_unit"] != unit:
        raise ValueError("incorrect platform ru_maxrss unit")
    if unit is None:
        expected_errors["ru_maxrss_native_unit"] = "unsupported_platform"
    for kind in ("wall", "process_cpu"):
        field = kind + "_ns"
        expected = _duration(record[kind + "_start_ns"], record[kind + "_end_ns"], field, expected_errors)
        if record[field] != expected or (expected is not None and type(record[field]) is not int):
            raise ValueError("inconsistent measured duration")
    rss = {}
    for endpoint in ("start", "end"):
        field = "peak_rss_" + endpoint + "_bytes"
        rss[endpoint] = _rss_bytes(record["ru_maxrss_" + endpoint + "_raw"], unit, field, expected_errors)
    if rss["start"] is not None and rss["end"] is not None and rss["end"] < rss["start"]:
        rss["end"] = None
        expected_errors["peak_rss_end_bytes"] = "decreasing_process_peak"
    for endpoint, expected in rss.items():
        value = record["peak_rss_" + endpoint + "_bytes"]
        if value != expected or (expected is not None and type(value) is not int):
            raise ValueError("incorrect process peak conversion")
    if (record["process_id"] is not None and record["finished_process_id"] is not None
            and record["process_id"] != record["finished_process_id"]):
        expected_errors["process_identity"] = "process_changed"
    if errors != expected_errors:
        raise ValueError("measurement error state does not match values")
    expected_status = "incomplete" if errors else "complete"
    if record["observation_status"] != expected_status:
        raise ValueError("measurement status does not match values")
    if require_complete and errors:
        raise ValueError("process observation is incomplete")
