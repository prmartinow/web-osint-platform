#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path


class StorageRootError(RuntimeError):
    pass


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def resolved_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def require_mnt_data_root(path: str | Path, *, allow_non_data_root: bool | None = None) -> Path:
    resolved = resolved_path(path)
    allow = allow_non_data_root
    if allow is None:
        allow = env("WEB_OSINT_ALLOW_NON_DATA_ROOT", "").lower() in {"1", "true", "yes", "on"}
    if allow:
        return resolved
    if str(resolved) in {"", "/", "/home", "/tmp"}:
        raise StorageRootError(f"unsafe durable data root: {resolved}")
    return resolved


def require_child_path(root: str | Path, child: str | Path) -> Path:
    resolved_root = require_mnt_data_root(root)
    resolved_child = resolved_path(child)
    try:
        resolved_child.relative_to(resolved_root)
    except ValueError as exc:
        raise StorageRootError(f"path {resolved_child} is outside data root {resolved_root}") from exc
    return resolved_child


def ensure_dir(path: str | Path, *, mode: int = 0o755) -> Path:
    resolved = resolved_path(path)
    resolved.mkdir(parents=True, exist_ok=True)
    try:
        resolved.chmod(mode)
    except PermissionError:
        pass
    return resolved


def evidence_data_root(default: str = "") -> Path:
    raw = env("OSINT_DATA_ROOT", env("WEB_OSINT_DATA_ROOT", default))
    if not raw:
        raise StorageRootError("OSINT_DATA_ROOT or WEB_OSINT_DATA_ROOT is required")
    return require_mnt_data_root(raw)
