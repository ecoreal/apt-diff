"""Human and JSON rendering of diffs and snapshot listings."""

from __future__ import annotations

import json

from .diff import summarize
from .util import Palette, human_size

LABELS = {
    "pkg-added": "Packages installed",
    "pkg-removed": "Packages removed",
    "pkg-upgraded": "Packages upgraded",
    "pkg-downgraded": "Packages downgraded",
    "pkg-status": "Package state changes",
    "etc-added": "/etc files added",
    "etc-removed": "/etc files removed",
    "etc-modified": "/etc files modified",
    "etc-mode": "/etc permission changes",
    "unit-added": "Units appeared",
    "unit-removed": "Units disappeared",
    "unit-state": "Unit state changes",
    "service-started": "Services started",
    "service-stopped": "Services stopped",
    "port-opened": "Ports opened",
    "port-closed": "Ports closed",
    "kernel-changed": "Kernel",
    "os-changed": "OS release",
}

ORDER = [
    "pkg-upgraded", "pkg-downgraded", "pkg-added", "pkg-removed", "pkg-status",
    "etc-modified", "etc-added", "etc-removed", "etc-mode",
    "unit-added", "unit-removed", "unit-state", "service-started", "service-stopped",
    "port-opened", "port-closed", "kernel-changed", "os-changed",
]

SEV_MARK = {"sec": "!!", "warn": " !", "info": "  "}


def describe(change: dict) -> str:
    """One-line human description of a change record."""
    k = change["kind"]
    if k == "pkg-added":
        return f"{change['pkg']}  (new, {change['to']})"
    if k == "pkg-removed":
        return f"{change['pkg']}  (was {change['from']})"
    if k in ("pkg-upgraded", "pkg-downgraded"):
        return f"{change['pkg']}  {change['from']} → {change['to']}"
    if k == "pkg-status":
        return f"{change['pkg']}  {change['from']} → {change['to']}"
    if k in ("etc-added", "etc-removed", "etc-modified", "etc-mode"):
        extra = f"  ({change['detail']})" if change.get("detail") else ""
        return f"/etc/{change['path']}{extra}"
    if k in ("unit-added",):
        return f"{change['unit']}  ({change['to']})"
    if k in ("unit-removed",):
        return f"{change['unit']}  (was {change['from']})"
    if k == "unit-state":
        return f"{change['unit']}  {change['from']} → {change['to']}"
    if k in ("service-started", "service-stopped"):
        return change["unit"]
    if k in ("port-opened", "port-closed"):
        return change["port"]
    if k == "kernel-changed":
        return f"{change['from']} → {change['to']}"
    if k == "os-changed":
        return f"{change['from']} → {change['to']}"
    return json.dumps(change, ensure_ascii=False)


def render_changes_human(changes: list, palette: Palette, meta: dict | None = None,
                         max_per_group: int = 200) -> str:
    lines = []
    if meta:
        old_name, new_name = meta.get("from", "?"), meta.get("to", "?")
        lines.append(palette.bold(f"Changes {old_name} → {new_name}"))
        lines.append("")
    if not changes:
        lines.append(palette.green("No changes. System state is identical."))
        return "\n".join(lines)

    groups: dict = {}
    for ch in changes:
        groups.setdefault(ch["kind"], []).append(ch)

    total = 0
    for kind in ORDER:
        items = groups.pop(kind, None)
        if not items:
            continue
        total += len(items)
        sev = items[0]["severity"]
        mark = SEV_MARK.get(sev, "  ")
        color = palette.red if sev == "sec" else (palette.yellow if sev == "warn" else palette.cyan)
        lines.append(color(f"{mark} {LABELS.get(kind, kind)} [{len(items)}]"))
        for ch in items[:max_per_group]:
            lines.append(f"      {describe(ch)}")
        if len(items) > max_per_group:
            lines.append(palette.dim(f"      … and {len(items) - max_per_group} more"))
        lines.append("")

    for kind, items in groups.items():  # anything not in the known order
        total += len(items)
        lines.append(palette.yellow(f"?? {LABELS.get(kind, kind)} [{len(items)}]"))
        for ch in items[:max_per_group]:
            lines.append(f"      {describe(ch)}")
        lines.append("")

    counts = summarize(changes)
    bits = [f"{n} {LABELS.get(k, k).lower()}" for k, n in counts.items()]
    lines.append(palette.bold(f"Total: {total} changes — " + ", ".join(bits)))
    return "\n".join(lines)


def render_changes_json(changes: list, meta: dict | None = None) -> str:
    doc = {
        "summary": summarize(changes),
        "total": len(changes),
        "changes": changes,
    }
    if meta:
        doc["meta"] = meta
    return json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=False)


def render_log(store: str, snaps: list, entries: list, palette: Palette) -> str:
    """Render `log` output. entries: [{name, size, counts or None}]"""
    lines = [palette.bold(f"Snapshots in {store}"), ""]
    if not entries:
        lines.append("  (no snapshots yet — run `apt-diff init`)")
        return "\n".join(lines)
    prev = None
    for e in reversed(entries):
        baseline_mark = "  *baseline*" if e.get("baseline") else ""
        lines.append(
            f"  {e['name']}  {human_size(e['size'])}{baseline_mark}"
        )
        if prev is not None and e.get("counts"):
            bits = [f"{n} {LABELS.get(k, k).lower()}" for k, n in e["counts"].items()]
            if bits:
                lines.append(palette.dim(f"      ↳ vs previous: " + ", ".join(bits)))
        prev = e
    return "\n".join(lines)


def render_show(snapshot: dict, palette: Palette) -> str:
    meta = snapshot.get("meta", {})
    sysinfo = snapshot.get("system", {})
    pkgs = snapshot.get("packages", {})
    lines = [
        palette.bold(f"Snapshot {meta.get('taken_at', '?')}"),
        f"  root        : {meta.get('root', '?')}",
        f"  OS          : {sysinfo.get('pretty_name', '?')}",
        f"  kernel      : {sysinfo.get('kernel', '?')}",
        f"  hostname    : {sysinfo.get('hostname', '?')}",
        f"  packages    : {len(pkgs)}",
        f"  /etc files  : {len(snapshot.get('etc', {}))}",
        f"  units       : {len(snapshot.get('units', {}))}",
        f"  listening   : {len(snapshot.get('ports', []))} tcp ports",
    ]
    ports = snapshot.get("ports", [])
    shown = [p.split(":", 1)[1] if ":" in p else p for p in ports[:12]]
    if shown:
        lines.append("  ports       : " + ", ".join(shown) + (", …" if len(ports) > 12 else ""))
    return "\n".join(lines)
