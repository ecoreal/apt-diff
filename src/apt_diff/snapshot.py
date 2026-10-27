"""Snapshot storage: gzip-JSON files, ordering, retention, baseline marker."""

from __future__ import annotations

import gzip
import json
import os
import re
import tempfile
import time

SNAPSHOT_RE = re.compile(r"^snapshot-(\d{8}T\d{6})(?:\.(\d+))?\.json\.gz$")
BASELINE_FILE = "baseline"
RETAIN_DEFAULT = 30


def default_store() -> str:
    """System store when running as root, user store otherwise."""
    if os.geteuid() == 0:
        return "/var/lib/apt-diff"
    xdg = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(xdg, "apt-diff")


def snapshot_name(ts: float | None = None) -> str:
    return time.strftime("snapshot-%Y%m%dT%H%M%S.json.gz", time.localtime(ts))


def new_snapshot_path(store: str, ts: float | None = None) -> str:
    name = snapshot_name(ts)
    # disambiguate same-second snapshots
    candidate = os.path.join(store, name)
    n = 0
    while os.path.exists(candidate):
        n += 1
        stem = name[: -len(".json.gz")]
        candidate = os.path.join(store, f"{stem}.{n}.json.gz")
    return candidate


def save_snapshot(store: str, data: dict, ts: float | None = None) -> str:
    """Write a snapshot atomically and return its path."""
    os.makedirs(store, exist_ok=True)
    path = new_snapshot_path(store, ts)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-apt-diff-", dir=store)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(gzip.compress(json.dumps(data, sort_keys=True).encode("utf-8")))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


def load_snapshot(path: str) -> dict:
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:  # type: ignore[operator]
        return json.load(fh)


def list_snapshots(store: str) -> list:
    """All snapshot paths, oldest first (same-second suffixes ordered too)."""
    if not os.path.isdir(store):
        return []
    found = []
    for name in os.listdir(store):
        m = SNAPSHOT_RE.match(name)
        if m:
            found.append((m.group(1), int(m.group(2) or 0), os.path.join(store, name)))
    found.sort(key=lambda t: (t[0], t[1]))
    return [p for _, _, p in found]


def newest_before(store: str, path: str | None = None) -> str | None:
    """Newest snapshot strictly older than ``path`` (or the newest overall)."""
    snaps = list_snapshots(store)
    if not snaps:
        return None
    if path is None:
        return snaps[-1]
    try:
        i = snaps.index(os.path.abspath(path))
    except ValueError:
        return snaps[-1]
    return snaps[i - 1] if i > 0 else None


def prune(store: str, keep: int = RETAIN_DEFAULT) -> int:
    """Delete all but the newest ``keep`` snapshots. Returns removed count."""
    snaps = list_snapshots(store)
    removed = 0
    for path in snaps[:-keep] if keep > 0 else snaps:
        try:
            os.unlink(path)
            removed += 1
        except OSError:
            pass
    return removed


def set_baseline(store: str, path: str) -> None:
    os.makedirs(store, exist_ok=True)
    tmp = os.path.join(store, f".baseline.{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(os.path.basename(path))
    os.replace(tmp, os.path.join(store, BASELINE_FILE))


def get_baseline(store: str) -> str | None:
    """Path of the baseline snapshot, or None."""
    try:
        with open(os.path.join(store, BASELINE_FILE), "r", encoding="utf-8") as fh:
            name = fh.read().strip()
    except OSError:
        return None
    path = os.path.join(store, name)
    return path if os.path.exists(path) else None
