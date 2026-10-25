"""Explicit, local handoffs; no integration, cleanup, or archive authorization.

Read-only copies plus a checked manifest detect subsequent tampering. They are not
WORM storage against an owner who can change permissions. Manifests bind bytes,
not a reviewer's identity or scientific approval. Failed attempts remain in place.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess


class WorkspaceError(ValueError):
    pass


def _name(value):
    if (not isinstance(value, str) or not value or "\\" in value or "\x00" in value
            or value != PurePosixPath(value).as_posix()
            or PurePosixPath(value).is_absolute()
            or any(part in {".", "..", ".git"} for part in value.split("/"))):
        raise WorkspaceError("Expected a plain relative file path")
    return value


def _names(paths):
    if isinstance(paths, (str, bytes)):
        raise WorkspaceError("Paths must be a collection")
    result = [_name(p) for p in paths]
    if not result or len(set(result)) != len(result):
        raise WorkspaceError("Paths must be nonempty and unique")
    return sorted(result)


def _root(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_dir():
        raise WorkspaceError("Root must be a real directory")
    return path.resolve()


def _read(root, name):
    """Open each component relative to a descriptor, refusing symlinks and FIFOs."""
    name = _name(name)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = name.split("/")
        for component in parts[:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise WorkspaceError("Only regular files are allowed: " + name)
            body = stream.read()
            after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise WorkspaceError("File changed during capture: " + name)
            return ("100755" if before.st_mode & 0o111 else "100644", body)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise WorkspaceError("Unsafe or unreadable file: " + name) from exc
    finally:
        os.close(directory)


def _entry(captured):
    if captured is None:
        return {"deleted": True}
    mode, body = captured
    return {"sha256": hashlib.sha256(body).hexdigest(), "mode": mode}


def reviewed_manifest(candidate_root, paths):
    """Return exact subjects, including explicit deletions; caller stores the review."""
    root = _root(candidate_root)
    return {name: _entry(_read(root, name)) for name in _names(paths)}


def validate_review_manifest(manifest, captured, changed_paths):
    """Validate the very same byte/mode tuples which will be committed."""
    if not isinstance(manifest, dict) or set(manifest) != set(changed_paths):
        raise WorkspaceError("Review subjects differ from the changed files")
    for name, expected in manifest.items():
        _name(name)
        actual = _entry(captured.get(name))
        if not isinstance(expected, dict):
            raise WorkspaceError("Invalid review entry: " + name)
        if actual == {"deleted": True}:
            valid = set(expected) == {"deleted"} and expected["deleted"] is True
        else:
            valid = (set(expected) == {"sha256", "mode"}
                     and expected.get("sha256") == actual["sha256"]
                     and expected.get("mode") == actual["mode"])
        if not valid:
            raise WorkspaceError("Review differs from captured content: " + name)


def _encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def _revision(root, ref):
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", ref],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.decode().strip() if result.returncode == 0 else None


def _write(root, name, body, mode):
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = name.split("/")
        for component in parts[:-1]:
            try:
                os.mkdir(component, mode=0o700, dir_fd=directory)
            except FileExistsError:
                pass
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), mode)
    finally:
        os.close(directory)


def seal_handoff(source_root, paths, destination):
    """Copy only explicit subjects into a new sibling/independent destination.

    No source files are changed. Existing destinations are never overwritten.
    Missing subjects (deletions) remain explicit in the manifest. Any failed
    destination is retained for investigation; archival remains a separate step.
    """
    root, names = _root(source_root), _names(paths)
    target = Path(destination).absolute()
    if target.exists() or target.is_symlink():
        raise WorkspaceError("Handoff destination already exists")
    parent = _root(target.parent)
    target = parent / target.name
    if target == root or root in target.parents or target in root.parents:
        raise WorkspaceError("Source and handoff roots must be independent")
    captured = {name: _read(root, name) for name in names}
    entries = {name: _entry(value) for name, value in captured.items()}
    manifest = {"schema": 1, "source_root": str(root),
                "base_revision": _revision(root, "HEAD"),
                "history_revision": _revision(root, "refs/heads/codex/forschungsverlauf"),
                "files": entries, "archive_status": "pending"}
    manifest["source_id"] = hashlib.sha256(_encoded(manifest)).hexdigest()
    target.mkdir(mode=0o700)
    (target / "files").mkdir(mode=0o700)
    for name, value in captured.items():
        if value is not None:
            mode, body = value
            _write(target / "files", name, body, 0o555 if mode == "100755" else 0o444)
    if captured != {name: _read(root, name) for name in names}:
        raise WorkspaceError("Source changed while sealing; failed destination retained")
    _write(target, "manifest.json", _encoded(manifest), 0o444)
    verify_handoff(target)
    for folder, directories, files in os.walk(target, topdown=False, followlinks=False):
        for child in directories:
            if (Path(folder) / child).is_symlink():
                raise WorkspaceError("Unexpected symlink in handoff")
        os.chmod(folder, 0o555)
    return manifest


def verify_handoff(destination):
    """Check identity, exact inventory, content and executable modes, read-only."""
    root = _root(destination)
    raw = _read(root, "manifest.json")
    if raw is None:
        raise WorkspaceError("Incomplete handoff: no manifest")
    try:
        manifest = json.loads(raw[1])
        identity = dict(manifest)
        source_id = identity.pop("source_id")
        if manifest.get("schema") != 1 or source_id != hashlib.sha256(_encoded(identity)).hexdigest():
            raise WorkspaceError("Invalid handoff identity")
        names = _names(manifest["files"])
        file_root = _root(root / "files")
        captured = {name: _read(file_root, name) for name in names}
        validate_review_manifest(manifest["files"], captured, names)
        expected = {"manifest.json"} | {"files/" + name for name, value in captured.items()
                                      if value is not None}
        actual = set()
        for folder, dirs, files in os.walk(root, followlinks=False):
            for name in dirs + files:
                path = Path(folder) / name
                if path.is_symlink():
                    raise WorkspaceError("Unexpected symlink in handoff")
            actual.update((Path(folder) / name).relative_to(root).as_posix() for name in files)
        if actual != expected:
            raise WorkspaceError("Handoff inventory differs from manifest")
        return manifest
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise WorkspaceError("Invalid handoff manifest") from exc
