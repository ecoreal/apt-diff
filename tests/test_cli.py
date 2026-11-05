"""End-to-end CLI tests against a fake system root and a temp store."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, SRC)

from apt_diff.cli import build_parser  # noqa: E402

DPKG_V1 = """\
Package: bash
Status: install ok installed
Version: 5.2-1
Architecture: amd64

Package: coreutils
Status: install ok installed
Version: 9.1-1
Architecture: amd64

"""
DPKG_V2 = DPKG_V1.replace("5.2-1", "5.2-2").replace(
    "Package: coreutils\nStatus: install ok installed\nVersion: 9.1-1",
    "Package: coreutils\nStatus: install ok installed\nVersion: 9.1-1",
) + "Package: htop\nStatus: install ok installed\nVersion: 3.3.0-1\nArchitecture: all\n\n"


class FakeSystem:
    """A fake root tree we can mutate between snapshots."""

    def __init__(self, root: str):
        self.root = root
        self._seq = 0

    def path(self, rel: str) -> str:
        return os.path.join(self.root, rel)

    def setup_v1(self):
        os.makedirs(self.path("var/lib/dpkg"), exist_ok=True)
        self.write("var/lib/dpkg/status", DPKG_V1)
        self.write("etc/hostname", "old-host\n")
        self.write("etc/nginx/nginx.conf", "worker_processes 1;\n")
        os.makedirs(self.path("etc/systemd/system/multi-user.target.wants"), exist_ok=True)
        self.write("etc/systemd/system/multi-user.target.wants/ssh.service", "")
        self.write("proc/net/tcp",
                   "  sl local_address rem_address   st\n"
                   "   0: 00000000:0016 00000000:0000 0A\n")

    def setup_v2(self):
        self.write("var/lib/dpkg/status", DPKG_V2)
        self.write("etc/hostname", "new-host\n")
        self.write("etc/nginx/nginx.conf", "worker_processes 4;\n")
        self.write("etc/newconf/app.conf", "x=1\n")
        os.unlink(self.path("etc/systemd/system/multi-user.target.wants/ssh.service"))
        self.write("proc/net/tcp",
                   "  sl local_address rem_address   st\n"
                   "   0: 00000000:0016 00000000:0000 0A\n"
                   "   1: 00000000:0050 00000000:0000 0A\n")

    def write(self, rel: str, content: str):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(content)


class CliTest(unittest.TestCase):
    def setUp(self):
        td_root = tempfile.TemporaryDirectory()
        td_store = tempfile.TemporaryDirectory()
        self.addCleanup(td_root.cleanup)
        self.addCleanup(td_store.cleanup)
        self.root = td_root.name
        self.store = td_store.name
        self.sys = FakeSystem(self.root)
        self.sys.setup_v1()

    def run_cli(self, *args):
        env = dict(os.environ)
        env["PYTHONPATH"] = SRC
        env.pop("APTDIFF_STORE", None)
        env.pop("APTDIFF_ROOT", None)
        return subprocess.run(
            [sys.executable, "-m", "apt_diff.cli",
             "--root", self.root, "--store", self.store, *args],
            capture_output=True, text=True, env=env, timeout=120,
        )

    # -- lifecycle ------------------------------------------------------

    def test_full_lifecycle(self):
        r = self.run_cli("init")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Baseline set", r.stdout)

        # clean check right after init
        r = self.run_cli("check")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("OK", r.stdout)

        # mutate the system
        time.sleep(1.1)  # snapshot names have 1s resolution
        self.sys.setup_v2()
        r = self.run_cli("snapshot")
        self.assertEqual(r.returncode, 0, r.stderr)

        # check must now fail with a summary
        r = self.run_cli("check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("apt-diff:", r.stderr)
        self.assertIn("change", r.stderr)

        # diff against baseline shows every category we mutated
        r = self.run_cli("diff")
        self.assertEqual(r.returncode, 0, r.stderr)
        for expected in ("Packages upgraded", "Packages installed", "/etc files modified",
                         "Ports opened", "Units disappeared"):
            self.assertIn(expected, r.stdout)
        self.assertIn("bash  5.2-1 → 5.2-2", r.stdout)
        self.assertIn("/etc/newconf/app.conf", r.stdout)
        self.assertIn("4:0.0.0.0:80", r.stdout)

    def test_diff_clean_between_consecutive_snapshots(self):
        self.run_cli("init")
        time.sleep(1.1)
        self.run_cli("snapshot")
        r = self.run_cli("diff")
        self.assertEqual(r.returncode, 0)
        self.assertIn("No changes", r.stdout)

    def test_explicit_snapshot_names(self):
        self.run_cli("init")
        time.sleep(1.1)
        self.sys.setup_v2()
        self.run_cli("snapshot")
        snaps = sorted(n for n in os.listdir(self.store) if n.startswith("snapshot-"))
        first = snaps[0].replace("snapshot-", "").replace(".json.gz", "")
        r = self.run_cli("diff", first)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(first[:8], r.stdout)

    def test_json_outputs_parse(self):
        self.run_cli("init")
        time.sleep(1.1)
        self.sys.setup_v2()
        self.run_cli("snapshot")
        r = self.run_cli("diff", "--json")
        doc = json.loads(r.stdout)
        self.assertGreater(doc["total"], 0)
        self.assertIn("pkg-upgraded", doc["summary"])
        self.assertTrue(all("kind" in c for c in doc["changes"]))

        r = self.run_cli("check", "--json")
        doc = json.loads(r.stdout)
        self.assertEqual(doc["total"], len(doc["changes"]))

    def test_check_exit_codes(self):
        self.run_cli("init")
        self.assertEqual(self.run_cli("check").returncode, 0)
        time.sleep(1.1)
        self.sys.setup_v2()
        self.run_cli("snapshot")
        self.assertEqual(self.run_cli("check").returncode, 1)
        self.assertEqual(self.run_cli("check", "-q").returncode, 1)
        self.assertEqual(self.run_cli("check", "-q").stderr.count("\n"), 1)

    def test_log_and_show_and_prune(self):
        self.run_cli("init")
        time.sleep(1.1)
        self.run_cli("snapshot")
        time.sleep(1.1)
        self.run_cli("snapshot")
        r = self.run_cli("log")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.count("snapshot-"), 3)
        self.assertIn("*baseline*", r.stdout)

        r = self.run_cli("show", "latest")
        self.assertIn("packages    : 2", r.stdout)
        self.assertIn("listening   : 1 tcp ports", r.stdout)

        r = self.run_cli("prune", "--keep", "1")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(os.listdir(self.store)) - 1, 1)  # -1 for baseline file

    def test_snapshot_honours_etc_max(self):
        # Regression: --etc-max used to exist only on init, so nightly
        # snapshots silently fell back to the 2 MiB default and every diff
        # reported a phantom /etc modification for big unchanged files.
        big = self.sys.path("etc/big.conf")
        with open(big, "wb") as fh:  # 3 MiB: below the 4 MiB cap, above default
            fh.write(b"x" * (3 * 1024 * 1024))
        r = self.run_cli("init", "--etc-max", str(4 * 1024 * 1024))
        self.assertEqual(r.returncode, 0, r.stderr)
        time.sleep(1.1)  # snapshot names have 1s resolution
        r = self.run_cli("snapshot", "--etc-max", str(4 * 1024 * 1024))
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_cli("diff")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("No changes", r.stdout)

    def test_etc_max_defaults_match_between_init_and_snapshot(self):
        p = build_parser()
        self.assertEqual(p.parse_args(["init"]).etc_max,
                         p.parse_args(["snapshot"]).etc_max)

    def test_errors_reported(self):
        self.assertEqual(self.run_cli("diff").returncode, 2)
        self.assertEqual(self.run_cli("check").returncode, 2)
        r = self.run_cli("diff", "nonexistent")
        self.assertEqual(r.returncode, 2)
        r = self.run_cli("show", "nonexistent")
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
