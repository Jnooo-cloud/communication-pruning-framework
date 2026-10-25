"""Z56 V3 network lock: every connection or name lookup is counted and refused (target 0)."""
import json
import socket

COUNT = {"socket.connect": 0, "socket.connect_ex": 0, "create_connection": 0, "getaddrinfo": 0}
_PATCHES = {}


def _blocked(name):
    def refuse(*_args, **_kwargs):
        COUNT[name] += 1
        raise OSError(f"Z56-V3 network lock: {name} refused")
    refuse.z56_guard = name
    return refuse


def install():
    """Install (or re-install after foreign patches, e.g. Z37 generate.py) the counting lock."""
    if not _PATCHES:
        _PATCHES.update({name: _blocked(name) for name in COUNT})
    socket.socket.connect = _PATCHES["socket.connect"]
    socket.socket.connect_ex = _PATCHES["socket.connect_ex"]
    socket.create_connection = _PATCHES["create_connection"]
    socket.getaddrinfo = _PATCHES["getaddrinfo"]


def installed():
    return (getattr(socket.socket.connect, "z56_guard", None) == "socket.connect"
            and getattr(socket.socket.connect_ex, "z56_guard", None) == "socket.connect_ex"
            and getattr(socket.create_connection, "z56_guard", None) == "create_connection"
            and getattr(socket.getaddrinfo, "z56_guard", None) == "getaddrinfo")


def report():
    return {"attempts": dict(COUNT), "total": sum(COUNT.values()), "lock_installed_at_end": installed()}


def selftest():
    """Prove the lock counts: one refused lookup, then reset the counter."""
    before = dict(COUNT)
    try:
        socket.getaddrinfo("example.invalid", 443)
    except OSError:
        pass
    ok = COUNT["getaddrinfo"] == before["getaddrinfo"] + 1
    COUNT.update(before)
    return ok


def dump(path):
    with open(path, "x") as out:
        json.dump(report(), out, indent=1)
        out.write("\n")
