"""Tests for the collectors using fixture trees instead of the live system."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from apt_diff import collect  # noqa: E402


DPKG_STATUS = """\
Package: bash
Status: install ok installed
Version: 5.2.15-2+b7
Architecture: amd64
Essential: yes
Description-lines-follow
 GNU Bourne Again SHell
 .
 second continuation

Package: nginx
Status: install ok half-configured
Version: 1.22.1-9
Architecture: arm64

Package: vim
Status: deinstall ok config-files
Version: 2:9.0.1378-2
Architecture: all

"""


def write(path: str, content: str = "", mode: int | None = None) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)
    if mode is not None:
        os.chmod(path, mode)


class TempRootMixin:
    def tmp_root(self) -> str:
        import tempfile

        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return td.name


class PackagesTest(unittest.TestCase, TempRootMixin):
    def setUp(self):
        self.root = self.tmp_root()
        write(os.path.join(self.root, "var/lib/dpkg/status"), DPKG_STATUS)

    def test_parses_packages(self):
        pkgs = collect.collect_packages(self.root)
        self.assertIn("bash", pkgs)
        self.assertEqual(pkgs["bash"]["version"], "5.2.15-2+b7")
        self.assertEqual(pkgs["bash"]["arch"], "amd64")
        self.assertEqual(pkgs["bash"]["status"], "install ok installed")

    def test_continuation_lines_do_not_pollute_fields(self):
        pkgs = collect.collect_packages(self.root)
        self.assertNotIn("Description-lines-follow", pkgs["bash"])
        self.assertEqual(pkgs["bash"]["status"], "install ok installed")

    def test_unhealthy_statuses_preserved(self):
        pkgs = collect.collect_packages(self.root)
        self.assertEqual(pkgs["nginx"]["status"], "install ok half-configured")
        self.assertEqual(pkgs["vim"]["status"], "deinstall ok config-files")

    def test_missing_database_is_empty(self):
        root = self.tmp_root()
        self.assertEqual(collect.collect_packages(root), {})


class PortsTest(unittest.TestCase, TempRootMixin):
    TCP_V4 = (
        "  sl local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        "   0: 0100007F:0019 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12345 1\n"
        "   1: 00000000:001B 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12346 1\n"
        "   2: 0100007F:9D3C 0100007F:1F90 01 00000000:00000000 00:00000000 00000000  1000        0 12347 1\n"
    )
    TCP_V6 = (
        "  sl local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        "   0: 00000000000000000000000000000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 999 1\n"
        "   1: 00000000000000000000000001000000:0050 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 998 1\n"
    )

    def setUp(self):
        self.root = self.tmp_root()
        write(os.path.join(self.root, "proc/net/tcp"), self.TCP_V4)
        write(os.path.join(self.root, "proc/net/tcp6"), self.TCP_V6)

    def test_listening_v4_ports(self):
        ports = collect.collect_ports(self.root)
        self.assertIn("4:127.0.0.1:25", ports)      # 0019 = 25 (smtp)
        self.assertIn("4:0.0.0.0:27", ports)        # 001B = 27
        self.assertNotIn("4:127.0.0.1:40284", ports)  # established (st=01) ignored

    def test_listening_v6_ports(self):
        ports = collect.collect_ports(self.root)
        self.assertIn("6::::22", ports)              # 0016 = 22
        self.assertIn("6:::1:80", ports)             # 0050 = 80 on ::1

    def test_sorted_and_deduplicated(self):
        ports = collect.collect_ports(self.root)
        self.assertEqual(ports, sorted(set(ports)))

    def test_decode_address(self):
        self.assertEqual(collect._decode_proc_address("0100007F:1F90", 4), "127.0.0.1:8080")
        self.assertIsNone(collect._decode_proc_address("zz:1F90", 4))


class EtcTest(unittest.TestCase, TempRootMixin):
    def setUp(self):
        self.root = self.tmp_root()
        etc = os.path.join(self.root, "etc")
        write(os.path.join(etc, "hostname"), "debian\n", mode=0o644)
        write(os.path.join(etc, "nginx/nginx.conf"), "user www-data;\n", mode=0o640)
        wants_dir = os.path.join(etc, "systemd/system/multi-user.target.wants")
        os.makedirs(wants_dir, exist_ok=True)
        os.symlink("/lib/systemd/system/sshd.service",
                   os.path.join(wants_dir, "sshd.service"))

    def test_hashes_and_modes(self):
        etc = collect.collect_etc(self.root)
        self.assertIn("hostname", etc)
        self.assertEqual(etc["hostname"]["mode"], "0644")
        self.assertTrue(etc["hostname"]["sha"])
        self.assertEqual(etc["nginx/nginx.conf"]["mode"], "0640")

    def test_symlinks_recorded_with_target(self):
        etc = collect.collect_etc(self.root)
        rel = "systemd/system/multi-user.target.wants/sshd.service"
        self.assertIn(rel, etc)
        self.assertEqual(etc[rel]["target"], "/lib/systemd/system/sshd.service")
        self.assertIsNone(etc[rel]["sha"])

    def test_directory_symlinks_recorded_with_target(self):
        # a directory replaced by / pointing through a symlink is an auditable
        # fact; os.walk keeps it in dirnames, so it must be handled explicitly
        os.symlink("nginx", os.path.join(self.root, "etc", "linkdir"))
        etc = collect.collect_etc(self.root)
        self.assertEqual(etc["linkdir"],
                         {"sha": None, "mode": "", "size": 0, "target": "nginx"})

    def test_directory_symlinks_are_not_walked(self):
        os.symlink("nginx", os.path.join(self.root, "etc", "linkdir"))
        etc = collect.collect_etc(self.root)
        self.assertNotIn("linkdir/nginx.conf", etc)
        self.assertIn("nginx/nginx.conf", etc)

    def test_max_file_size_skips_large_files(self):
        root = self.tmp_root()
        write(os.path.join(root, "etc/small.conf"), "x=1\n")
        write(os.path.join(root, "etc/big.conf"), "y" * 8)
        etc = collect.collect_etc(root, max_file_size=4)
        self.assertIsNone(etc["big.conf"]["sha"])
        self.assertTrue(etc["small.conf"]["sha"])
        self.assertEqual(etc["big.conf"]["size"], 8)

    def test_modification_changes_hash(self):
        before = collect.collect_etc(self.root)
        write(os.path.join(self.root, "etc/hostname"), "pi\n", mode=0o644)
        after = collect.collect_etc(self.root)
        self.assertNotEqual(before["hostname"]["sha"], after["hostname"]["sha"])

    def test_mode_change_detected(self):
        before = collect.collect_etc(self.root)
        os.chmod(os.path.join(self.root, "etc/hostname"), 0o600)
        after = collect.collect_etc(self.root)
        self.assertNotEqual(before["hostname"]["mode"], after["hostname"]["mode"])


class UnitsTest(unittest.TestCase, TempRootMixin):
    def test_fallback_scanner_reads_wants_dirs(self):
        root = self.tmp_root()
        base = os.path.join(root, "etc/systemd/system")
        write(os.path.join(base, "multi-user.target.wants/sshd.service"), "")
        write(os.path.join(base, "custom.timer"), "")
        units = collect.collect_units(root)
        self.assertEqual(units["sshd.service"], {"state": "enabled", "running": False})
        self.assertEqual(units["custom.timer"], {"state": "present", "running": False})

    def test_missing_systemd_tree(self):
        root = self.tmp_root()
        self.assertEqual(collect.collect_units(root), {})


class SystemTest(unittest.TestCase, TempRootMixin):
    def test_reads_kernel_and_os_release(self):
        root = self.tmp_root()
        write(os.path.join(root, "proc/sys/kernel/osrelease"), "6.12.113+v8\n")
        write(os.path.join(root, "etc/os-release"),
              'NAME="Debian GNU/Linux"\nPRETTY_NAME="Debian GNU/Linux 13 (trixie)"\n')
        info = collect.collect_system(root)
        self.assertEqual(info["kernel"], "6.12.113+v8")
        self.assertEqual(info["pretty_name"], "Debian GNU/Linux 13 (trixie)")


class CollectAllTest(unittest.TestCase, TempRootMixin):
    def test_assembles_every_section(self):
        root = self.tmp_root()
        write(os.path.join(root, "var/lib/dpkg/status"), DPKG_STATUS)
        write(os.path.join(root, "etc/hostname"), "box\n")
        data = collect.collect_all(root)
        for key in ("meta", "packages", "etc", "units", "ports", "system"):
            self.assertIn(key, data)
        self.assertEqual(data["meta"]["schema"], 1)
        self.assertIn("bash", data["packages"])


if __name__ == "__main__":
    unittest.main()
