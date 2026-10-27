"""Pure snapshot-diffing: two snapshot dicts → list of change records."""

from __future__ import annotations

# severities: info (expected churn), warn (worth eyeballing), sec (ports)
SEV_INFO = "info"
SEV_WARN = "warn"
SEV_SEC = "sec"


def diff_snapshots(old: dict, new: dict) -> list:
    """Compare two snapshots and return change records, grouped by section."""
    changes: list = []
    changes.extend(_diff_packages(old.get("packages", {}), new.get("packages", {})))
    changes.extend(_diff_etc(old.get("etc", {}), new.get("etc", {})))
    changes.extend(_diff_units(old.get("units", {}), new.get("units", {})))
    changes.extend(_diff_ports(old.get("ports", []), new.get("ports", [])))
    changes.extend(_diff_system(old.get("system", {}), new.get("system", {})))
    return changes


def summarize(changes: list) -> dict:
    counts: dict = {}
    for ch in changes:
        counts[ch["kind"]] = counts.get(ch["kind"], 0) + 1
    return counts


def _diff_packages(old: dict, new: dict) -> list:
    out = []
    for name in sorted(set(old) | set(new)):
        o, n = old.get(name), new.get(name)
        if o is None:
            out.append({"kind": "pkg-added", "severity": SEV_INFO,
                        "pkg": name, "to": n["version"]})
        elif n is None:
            out.append({"kind": "pkg-removed", "severity": SEV_INFO,
                        "pkg": name, "from": o["version"]})
        elif o["version"] != n["version"]:
            kind = "pkg-upgraded"
            if _version_lt(n["version"], o["version"]):
                kind = "pkg-downgraded"
            out.append({"kind": kind, "severity": SEV_INFO,
                        "pkg": name, "from": o["version"], "to": n["version"]})
        elif o["status"] != n["status"]:
            healthy = "install ok installed"
            if o["status"] == healthy and n["status"] != healthy:
                sev = SEV_WARN
            else:
                sev = SEV_INFO
            out.append({"kind": "pkg-status", "severity": sev, "pkg": name,
                        "from": o["status"], "to": n["status"]})
    return out


def _version_lt(a: str, b: str) -> bool:
    """Rough version comparison (epoch:upstream-revision, numeric-aware).

    Not a full dpkg implementation, but enough to tell upgrades from
    downgrades in practice.
    """
    return _version_key(a) < _version_key(b)


def _version_key(v: str):
    """Sort key approximating dpkg version ordering.

    Digit runs compare numerically, letter runs lexically, '~' sorts before
    end-of-string (so 1.0~rc1 < 1.0 < 1.0.1), epoch dominates ("1:x" > "0.5").
    """
    import re

    key = []
    for tok in re.findall(r"\d+|[A-Za-z]+|~|[^A-Za-z0-9~]", v):
        if tok == "~":
            key.append((0, 0, "~"))
        elif tok.isdigit():
            key.append((1, int(tok), ""))
        elif tok.isalpha():
            key.append((2, 0, tok))
        else:
            key.append((3, 0, tok))
    key.append((0, 1, ""))  # end-of-string sentinel: after '~', before all else
    return key


def _diff_etc(old: dict, new: dict) -> list:
    out = []
    for path in sorted(set(old) | set(new)):
        o, n = old.get(path), new.get(path)
        if o is None:
            out.append({"kind": "etc-added", "severity": SEV_WARN, "path": path})
        elif n is None:
            out.append({"kind": "etc-removed", "severity": SEV_WARN, "path": path})
        elif o["target"] != n["target"]:
            out.append({"kind": "etc-modified", "severity": SEV_WARN, "path": path,
                        "detail": f"symlink {o['target']} → {n['target']}"})
        elif o["sha"] != n["sha"] and (o["sha"] is not None or n["sha"] is not None):
            out.append({"kind": "etc-modified", "severity": SEV_WARN, "path": path})
        elif o["mode"] != n["mode"]:
            out.append({"kind": "etc-mode", "severity": SEV_WARN, "path": path,
                        "detail": f"{o['mode']} → {n['mode']}"})
    return out


def _diff_units(old: dict, new: dict) -> list:
    out = []
    for unit in sorted(set(old) | set(new)):
        o, n = old.get(unit), new.get(unit)
        if o is None:
            out.append({"kind": "unit-added", "severity": SEV_WARN,
                        "unit": unit, "to": n["state"]})
        elif n is None:
            out.append({"kind": "unit-removed", "severity": SEV_WARN,
                        "unit": unit, "from": o["state"]})
        elif o["state"] != n["state"]:
            out.append({"kind": "unit-state", "severity": SEV_WARN, "unit": unit,
                        "from": o["state"], "to": n["state"]})
        elif o["running"] != n["running"]:
            kind = "service-started" if n["running"] else "service-stopped"
            out.append({"kind": kind, "severity": SEV_INFO, "unit": unit})
    return out


def _diff_ports(old: list, new: list) -> list:
    out = []
    for p in sorted(set(old) - set(new)):
        out.append({"kind": "port-closed", "severity": SEV_INFO, "port": p})
    for p in sorted(set(new) - set(old)):
        out.append({"kind": "port-opened", "severity": SEV_SEC, "port": p})
    return out


def _diff_system(old: dict, new: dict) -> list:
    out = []
    if old.get("kernel") != new.get("kernel") and new.get("kernel"):
        out.append({"kind": "kernel-changed", "severity": SEV_INFO,
                    "from": old.get("kernel", ""), "to": new.get("kernel", "")})
    if old.get("pretty_name") != new.get("pretty_name") and new.get("pretty_name"):
        out.append({"kind": "os-changed", "severity": SEV_INFO,
                    "from": old.get("pretty_name", ""), "to": new.get("pretty_name", "")})
    return out
