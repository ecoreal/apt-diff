"""System state collectors.

Every collector takes a ``root`` parameter (default ``/``) so tests can run
against a fixture tree instead of the live system.  Nothing here shells out
except the systemd unit collector, which falls back to scanning
``/etc/systemd/system`` when ``systemctl`` is unavailable or a different
root is being inspected.
"""

from __future__ import annotations

import ipaddress
import os
import stat as stat_mod
import subprocess
import time

from .util import sha256_file

LISTEN_STATE = "0A"  # /proc/net/tcp st column value for TCP_LISTEN


# ------------------------------------------------------------- packages ---


def collect_packages(root: str = "/") -> dict:
    """Parse the dpkg status database: {name: {version, arch, status}}."""
    status_file = os.path.join(root, "var", "lib", "dpkg", "status")
    packages: dict = {}
    try:
        with open(status_file, "r", encoding="utf-8", errors="replace") as fh:
            current: dict = {}
            for line in fh:
                line = line.rstrip("\n")
                if not line:
                    if current.get("Package"):
                        _store_package(packages, current)
                    current = {}
                    continue
                if line[0] in " \t" or line.startswith(". "):
                    continue  # continuation / description lines
                key, _, value = line.partition(":")
                current[key.strip()] = value.strip()
            if current.get("Package"):
                _store_package(packages, current)
    except OSError:
        pass  # no dpkg database (e.g. fixture root) → empty inventory
    return packages


def _store_package(packages: dict, fields: dict) -> None:
    name = fields.get("Package")
    if not name:
        return
    packages[name] = {
        "version": fields.get("Version", ""),
        "arch": fields.get("Architecture", ""),
        "status": fields.get("Status", ""),
    }


# ------------------------------------------------------------------ etc ---


def collect_etc(root: str = "/", max_file_size: int = 2 * 1024 * 1024) -> dict:
    """Hash every regular file under /etc; record symlink targets and modes.

    Returns {path: {"sha": hex|None, "mode": "0644", "size": int, "target": str|None}}
    Paths are relative to the /etc directory (e.g. "hostname").
    """
    base = os.path.join(root, "etc")
    result: dict = {}
    if not os.path.isdir(base):
        return result
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames.sort()
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, base)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if stat_mod.S_ISLNK(st.st_mode):
                try:
                    target = os.readlink(full)
                except OSError:
                    target = None
                result[rel] = {"sha": None, "mode": "", "size": 0, "target": target}
                continue
            if not stat_mod.S_ISREG(st.st_mode):
                continue
            digest = sha256_file(full, max_bytes=max_file_size)
            result[rel] = {
                "sha": digest,
                "mode": format(st.st_mode & 0o7777, "04o"),
                "size": st.st_size,
                "target": None,
            }
    return result


# ---------------------------------------------------------------- units ---


def collect_units(root: str = "/") -> dict:
    """Enabled/running systemd units: {unit: {"state": str, "running": bool}}.

    Uses systemctl when inspecting the live system; otherwise approximates
    "enabled" from /etc/systemd/system/*.wants/ symlinks.
    """
    if root == "/" and os.path.exists("/run/systemd/system"):
        return _collect_units_systemctl()
    return _collect_units_files(root)


def _collect_units_systemctl() -> dict:
    units: dict = {}
    try:
        out = subprocess.run(
            ["systemctl", "list-unit-files", "--no-legend", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                units[parts[0]] = {"state": parts[1], "running": False}
    except (OSError, subprocess.SubprocessError):
        return _collect_units_files("/")
    try:
        out = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--state=running",
             "--no-legend", "--no-pager"],
            capture_output=True, text=True, timeout=30,
        ).stdout
        for line in out.splitlines():
            parts = line.split()
            if parts:
                name = parts[0]
                if name.endswith(".scope"):
                    continue
                entry = units.setdefault(name, {"state": "static", "running": False})
                entry["running"] = True
    except (OSError, subprocess.SubprocessError):
        pass
    return units


def _collect_units_files(root: str = "/") -> dict:
    units: dict = {}
    base = os.path.join(root, "etc", "systemd", "system")
    if not os.path.isdir(base):
        return units
    for entry in sorted(os.listdir(base)):
        wants = os.path.join(base, entry)
        if entry.endswith(".wants") and os.path.isdir(wants):
            for name in sorted(os.listdir(wants)):
                units.setdefault(name, {"state": "enabled", "running": False})
        elif not entry.endswith(".wants"):
            units.setdefault(entry, {"state": "present", "running": False})
    return units


# ---------------------------------------------------------------- ports ---


def collect_ports(root: str = "/") -> list:
    """Listening TCP ports from /proc/net/tcp{,6}: ["tcp:0.0.0.0:22", ...]."""
    ports: set = set()
    for table, family in (("proc/net/tcp", 4), ("proc/net/tcp6", 6)):
        path = os.path.join(root, table)
        try:
            with open(path, "r", encoding="ascii") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        for line in lines[1:]:
            fields = line.split()
            if len(fields) < 4 or fields[3].upper() != LISTEN_STATE:
                continue
            addr = _decode_proc_address(fields[1], family)
            if addr:
                ports.add(f"{family}:{addr}")
    return sorted(ports)


def _decode_proc_address(hex_addr: str, family: int) -> str | None:
    """Decode /proc/net/tcp "HHHHHHHH:PPPP" fields into "ip:port".

    The kernel prints IPv4 addresses byte-reversed and IPv6 addresses as
    four little-endian 32-bit words, e.g. ::1 appears as "01000000".
    """
    try:
        ip_hex, port_hex = hex_addr.split(":")
        port = int(port_hex, 16)
        raw = bytes.fromhex(ip_hex)
        if family == 4:
            ip = ".".join(str(b) for b in raw[::-1])
        else:
            in6 = b"".join(raw[i:i + 4][::-1] for i in range(0, 16, 4))
            ip = str(ipaddress.IPv6Address(in6))
        return f"{ip}:{port}"
    except (ValueError, IndexError):
        return None


# --------------------------------------------------------------- system ---


def collect_system(root: str = "/") -> dict:
    def _read(rel: str) -> str:
        try:
            with open(os.path.join(root, rel), "r", encoding="utf-8", errors="replace") as fh:
                return fh.read().strip()
        except OSError:
            return ""

    info: dict = {
        "kernel": _read("proc/sys/kernel/osrelease"),
        "hostname": _read("etc/hostname"),
        "debian_version": _read("etc/debian_version"),
        "pretty_name": "",
    }
    os_release = _read("etc/os-release")
    for line in os_release.splitlines():
        if line.startswith("PRETTY_NAME="):
            info["pretty_name"] = line.split("=", 1)[1].strip().strip('"')
            break
    return info


# ------------------------------------------------------------------ all ---


def collect_all(root: str = "/", etc_max_file_size: int = 2 * 1024 * 1024) -> dict:
    """Collect every subsystem into one snapshot dictionary."""
    return {
        "meta": {
            "tool": "apt-diff",
            "schema": 1,
            "taken_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "root": root,
        },
        "packages": collect_packages(root),
        "etc": collect_etc(root, max_file_size=etc_max_file_size),
        "units": collect_units(root),
        "ports": collect_ports(root),
        "system": collect_system(root),
    }
