"""Tests for the pure diff logic."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from apt_diff import diff as diffmod  # noqa: E402


def snap(packages=None, etc=None, units=None, ports=None, system=None):
    return {
        "packages": packages or {},
        "etc": etc or {},
        "units": units or {},
        "ports": ports or [],
        "system": system or {},
    }


def kinds(changes):
    return [c["kind"] for c in changes]


class PackageDiffTest(unittest.TestCase):
    def test_added_removed_upgraded(self):
        old = snap(packages={
            "gone": {"version": "1.0", "arch": "all", "status": "install ok installed"},
            "app": {"version": "1.2", "arch": "amd64", "status": "install ok installed"},
        })
        new = snap(packages={
            "app": {"version": "1.3", "arch": "amd64", "status": "install ok installed"},
            "new": {"version": "0.1", "arch": "all", "status": "install ok installed"},
        })
        changes = diffmod.diff_snapshots(old, new)
        by_kind = {}
        for c in changes:
            by_kind.setdefault(c["kind"], []).append(c["pkg"])
        self.assertEqual(by_kind["pkg-added"], ["new"])
        self.assertEqual(by_kind["pkg-removed"], ["gone"])
        self.assertEqual(by_kind["pkg-upgraded"], ["app"])

    def test_downgrade_detected_via_version_compare(self):
        old = snap(packages={"app": {"version": "2.10", "arch": "all", "status": "install ok installed"}})
        new = snap(packages={"app": {"version": "2.9", "arch": "all", "status": "install ok installed"}})
        self.assertIn("pkg-downgraded", kinds(diffmod.diff_snapshots(old, new)))

    def test_version_compare_numeric(self):
        self.assertFalse(diffmod._version_lt("1.10", "1.9"))
        self.assertTrue(diffmod._version_lt("1.9", "1.10"))
        self.assertFalse(diffmod._version_lt("1:0.1", "0.5"))  # epoch dominates
        self.assertTrue(diffmod._version_lt("0.5", "1:0.1"))
        self.assertTrue(diffmod._version_lt("1.0~rc1", "1.0"))
        self.assertFalse(diffmod._version_lt("2a", "1z"))

    def test_status_regression_is_warning(self):
        old = snap(packages={"nginx": {"version": "1.0", "arch": "all", "status": "install ok installed"}})
        new = snap(packages={"nginx": {"version": "1.0", "arch": "all", "status": "install ok half-configured"}})
        (ch,) = diffmod.diff_snapshots(old, new)
        self.assertEqual(ch["kind"], "pkg-status")
        self.assertEqual(ch["severity"], "warn")


class EtcDiffTest(unittest.TestCase):
    def file(self, sha="a" * 64, mode="0644", size=10, target=None):
        return {"sha": sha, "mode": mode, "size": size, "target": target}

    def test_add_remove_modify(self):
        old = snap(etc={"keep.conf": self.file(), "drop.conf": self.file(), "mod.conf": self.file(sha="b" * 64)})
        new = snap(etc={"keep.conf": self.file(), "mod.conf": self.file(sha="c" * 64), "new.conf": self.file()})
        by_kind = {}
        for c in diffmod.diff_snapshots(old, new):
            by_kind.setdefault(c["kind"], []).append(c["path"])
        self.assertEqual(by_kind["etc-added"], ["new.conf"])
        self.assertEqual(by_kind["etc-removed"], ["drop.conf"])
        self.assertEqual(by_kind["etc-modified"], ["mod.conf"])
        self.assertNotIn("keep.conf", [c.get("path") for c in diffmod.diff_snapshots(old, new)])

    def test_mode_change_is_distinct(self):
        old = snap(etc={"f.conf": self.file(mode="0644")})
        new = snap(etc={"f.conf": self.file(mode="0600")})
        (ch,) = diffmod.diff_snapshots(old, new)
        self.assertEqual(ch["kind"], "etc-mode")
        self.assertIn("0644", ch["detail"])

    def test_symlink_target_change(self):
        old = snap(etc={"link": self.file(target="/a")})
        new = snap(etc={"link": self.file(target="/b")})
        (ch,) = diffmod.diff_snapshots(old, new)
        self.assertEqual(ch["kind"], "etc-modified")
        self.assertIn("symlink", ch["detail"])

    def test_unreadable_to_readed_is_modified(self):
        old = snap(etc={"f": self.file(sha=None)})
        new = snap(etc={"f": self.file(sha="d" * 64)})
        self.assertIn("etc-modified", kinds(diffmod.diff_snapshots(old, new)))


class UnitDiffTest(unittest.TestCase):
    def test_enable_disable_and_running(self):
        old = snap(units={
            "a.service": {"state": "enabled", "running": True},
            "b.service": {"state": "disabled", "running": False},
            "c.service": {"state": "enabled", "running": False},
        })
        new = snap(units={
            "a.service": {"state": "disabled", "running": True},
            "b.service": {"state": "enabled", "running": False},
            "c.service": {"state": "enabled", "running": True},
        })
        by_kind = {}
        for c in diffmod.diff_snapshots(old, new):
            by_kind.setdefault(c["kind"], []).append(c["unit"])
        self.assertEqual(by_kind["unit-state"], ["a.service", "b.service"])
        self.assertEqual(by_kind["service-started"], ["c.service"])


class PortDiffTest(unittest.TestCase):
    def test_opened_is_security_severity(self):
        old = snap(ports=["4:0.0.0.0:22"])
        new = snap(ports=["4:0.0.0.0:22", "4:0.0.0.0:8080"])
        changes = diffmod.diff_snapshots(old, new)
        self.assertEqual(changes[0]["kind"], "port-opened")
        self.assertEqual(changes[0]["severity"], "sec")

    def test_closed_is_info(self):
        old = snap(ports=["4:0.0.0.0:80"])
        new = snap(ports=[])
        (ch,) = diffmod.diff_snapshots(old, new)
        self.assertEqual(ch["kind"], "port-closed")
        self.assertEqual(ch["severity"], "info")


class SystemDiffTest(unittest.TestCase):
    def test_kernel_change(self):
        old = snap(system={"kernel": "6.1.0", "pretty_name": "Debian 12"})
        new = snap(system={"kernel": "6.12", "pretty_name": "Debian 12"})
        (ch,) = diffmod.diff_snapshots(old, new)
        self.assertEqual(ch["kind"], "kernel-changed")
        self.assertEqual(ch["from"], "6.1.0")

    def test_no_change_no_noise(self):
        s = snap(system={"kernel": "6.1.0", "pretty_name": "Debian 12"})
        self.assertEqual(diffmod.diff_snapshots(s, s), [])


class SummarizeTest(unittest.TestCase):
    def test_counts_by_kind(self):
        changes = [{"kind": "pkg-added"}, {"kind": "pkg-added"}, {"kind": "etc-modified"}]
        self.assertEqual(diffmod.summarize(changes), {"pkg-added": 2, "etc-modified": 1})


if __name__ == "__main__":
    unittest.main()
