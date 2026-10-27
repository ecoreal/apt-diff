"""Tests for human and JSON rendering of diffs, log and show output."""

from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from apt_diff import render  # noqa: E402
from apt_diff.util import Palette  # noqa: E402


def ch(kind, severity="info", **kw):
    d = {"kind": kind, "severity": severity}
    d.update(kw)
    return d


def plain_palette():
    return Palette(enabled=False)


class DescribeTest(unittest.TestCase):
    def test_package_kinds(self):
        self.assertEqual(
            render.describe(ch("pkg-added", pkg="curl", to="8.0")),
            "curl  (new, 8.0)")
        self.assertEqual(
            render.describe(ch("pkg-removed", pkg="vim", from_="9.0") | {"from": "9.0"}),
            "vim  (was 9.0)")
        self.assertEqual(
            render.describe(ch("pkg-upgraded", pkg="bash", **{"from": "5.0", "to": "6.0"})),
            "bash  5.0 → 6.0")
        self.assertEqual(
            render.describe(ch("pkg-downgraded", pkg="bash", **{"from": "6.0", "to": "5.0"})),
            "bash  6.0 → 5.0")
        self.assertEqual(
            render.describe(ch("pkg-status", pkg="nginx", **{"from": "deinstall", "to": "install"})),
            "nginx  deinstall → install")

    def test_etc_kinds(self):
        self.assertEqual(
            render.describe(ch("etc-modified", path="ssh/sshd_config")),
            "/etc/ssh/sshd_config")
        self.assertEqual(
            render.describe(ch("etc-mode", path="passwd", detail="644 → 600")),
            "/etc/passwd  (644 → 600)")

    def test_unit_port_kernel_kinds(self):
        self.assertEqual(
            render.describe(ch("unit-added", unit="docker.service", to="enabled")),
            "docker.service  (enabled)")
        self.assertEqual(
            render.describe(ch("unit-removed", unit="old.service", **{"from": "disabled"})),
            "old.service  (was disabled)")
        self.assertEqual(
            render.describe(ch("unit-state", unit="cron.service", **{"from": "enabled", "to": "disabled"})),
            "cron.service  enabled → disabled")
        self.assertEqual(
            render.describe(ch("service-started", unit="nginx.service")),
            "nginx.service")
        self.assertEqual(
            render.describe(ch("port-opened", port="0.0.0.0:22")),
            "0.0.0.0:22")
        self.assertEqual(
            render.describe(ch("kernel-changed", **{"from": "6.1", "to": "6.2"})),
            "6.1 → 6.2")
        self.assertEqual(
            render.describe(ch("os-changed", **{"from": "Debian 12", "to": "Debian 13"})),
            "Debian 12 → Debian 13")

    def test_unknown_kind_falls_back_to_json(self):
        out = render.describe(ch("mystery", extra=1))
        self.assertIn("mystery", out)
        self.assertIn("extra", out)
        json.loads(out)  # must be valid JSON


class RenderChangesHumanTest(unittest.TestCase):
    def test_no_changes(self):
        out = render.render_changes_human([], plain_palette())
        self.assertIn("No changes", out)

    def test_groups_follow_known_order_with_severity_marks(self):
        changes = [
            ch("port-opened", port=":8080"),
            ch("pkg-added", pkg="curl", to="1.0"),
            ch("pkg-upgraded", severity="warn", pkg="bash", **{"from": "5", "to": "6"}),
            ch("etc-modified", severity="sec", path="shadow"),
        ]
        out = render.render_changes_human(changes, plain_palette(),
                                          meta={"from": "a", "to": "b"})
        i_upgraded = out.index("Packages upgraded")
        i_added = out.index("Packages installed")
        i_etc = out.index("/etc files modified")
        i_port = out.index("Ports opened")
        self.assertLess(i_upgraded, i_added)
        self.assertLess(i_added, i_etc)
        self.assertLess(i_etc, i_port)
        self.assertIn("Changes a → b", out)
        self.assertIn("!! /etc files modified [1]", out)   # sec mark
        self.assertIn(" ! Packages upgraded [1]", out)     # warn mark
        self.assertIn("Total: 4 changes", out)

    def test_truncates_large_groups(self):
        changes = [ch("pkg-added", pkg=f"p{i}", to="1.0") for i in range(5)]
        out = render.render_changes_human(changes, plain_palette(), max_per_group=3)
        self.assertEqual(out.count("(new, 1.0)"), 3)
        self.assertIn("… and 2 more", out)
        self.assertIn("Total: 5 changes", out)

    def test_unknown_kind_gets_question_mark_group(self):
        out = render.render_changes_human([ch("mystery", x=1)], plain_palette())
        self.assertIn("?? mystery [1]", out)


class RenderChangesJsonTest(unittest.TestCase):
    def test_document_shape(self):
        changes = [ch("pkg-added", pkg="curl", to="1.0")]
        doc = json.loads(render.render_changes_json(changes, meta={"from": "a", "to": "b"}))
        self.assertEqual(doc["total"], 1)
        self.assertEqual(doc["summary"], {"pkg-added": 1})
        self.assertEqual(doc["meta"], {"from": "a", "to": "b"})
        self.assertEqual(doc["changes"][0]["pkg"], "curl")

    def test_no_meta_omits_key(self):
        doc = json.loads(render.render_changes_json([]))
        self.assertNotIn("meta", doc)
        self.assertEqual(doc["total"], 0)


class RenderLogTest(unittest.TestCase):
    def test_empty_store(self):
        out = render.render_log("/store", [], [], plain_palette())
        self.assertIn("no snapshots yet", out)
        self.assertIn("/store", out)

    def test_lists_newest_first_with_baseline_mark_and_deltas(self):
        entries = [
            {"name": "s1", "ts": 1, "size": 900, "baseline": True, "counts": None},
            {"name": "s2", "ts": 2, "size": 1200, "counts": {"pkg-added": 2}},
            {"name": "s3", "ts": 3, "size": 1500, "counts": {}},
        ]
        out = render.render_log("/store", entries, entries, plain_palette())
        lines = [l for l in out.splitlines() if l.strip()]
        # header, then s3 s2 s1 (reversed)
        self.assertIn("s3", lines[1])
        self.assertIn("s2", lines[2])
        self.assertIn("s1", lines[4])
        self.assertIn("*baseline*", lines[4])
        self.assertIn("vs previous: 2 packages installed", lines[3])
        # s3 has empty counts → no delta line under it
        self.assertNotIn("↳", lines[1])


class RenderShowTest(unittest.TestCase):
    def test_snapshot_summary(self):
        snap = {
            "meta": {"taken_at": 1234, "root": "/"},
            "system": {"pretty_name": "Debian 13", "kernel": "6.12", "hostname": "box"},
            "packages": {"a": "1", "b": "2"},
            "etc": {"hosts": "x"},
            "units": {"ssh.service": "enabled"},
            "ports": ["127.0.0.1:22", "0.0.0.0:80"],
        }
        out = render.render_show(snap, plain_palette())
        self.assertIn("Snapshot 1234", out)
        self.assertIn("root        : /", out)
        self.assertIn("OS          : Debian 13", out)
        self.assertIn("packages    : 2", out)
        self.assertIn("/etc files  : 1", out)
        self.assertIn("units       : 1", out)
        self.assertIn("22, 80", out)   # host part stripped from ports

    def test_more_than_twelve_ports_elided(self):
        snap = {
            "meta": {}, "system": {}, "packages": {}, "etc": {}, "units": {},
            "ports": [f"127.0.0.1:{p}" for p in range(20)],
        }
        out = render.render_show(snap, plain_palette())
        self.assertIn("…", out)
        self.assertNotIn("127.0.0.1:19", out.split("ports")[1].split("\n")[0])


if __name__ == "__main__":
    unittest.main()
