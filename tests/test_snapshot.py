"""Tests for snapshot storage: roundtrip, ordering, pruning, baseline."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from apt_diff import snapshot as snapmod  # noqa: E402


class StoreMixin:
    def store(self) -> str:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return td.name


class SnapshotTest(unittest.TestCase, StoreMixin):
    def make(self, n=1, payload=None):
        store = self.store()
        paths = []
        base = time.time() - 100
        for i in range(n):
            data = payload or {"seq": i}
            paths.append(snapmod.save_snapshot(store, data, ts=base + i * 10))
        return store, paths

    def test_roundtrip_preserves_data(self):
        store, (path,) = self.make(payload={"packages": {"bash": {"version": "1"}}})
        data = snapmod.load_snapshot(path)
        self.assertEqual(data["packages"]["bash"]["version"], "1")

    def test_names_are_ordered(self):
        store, paths = self.make(n=3)
        listed = snapmod.list_snapshots(store)
        self.assertEqual(listed, paths)
        self.assertTrue(all(os.path.basename(p).startswith("snapshot-") for p in paths))

    def test_same_second_snapshots_do_not_collide(self):
        store = self.store()
        ts = time.time()
        p1 = snapmod.save_snapshot(store, {"a": 1}, ts=ts)
        p2 = snapmod.save_snapshot(store, {"a": 2}, ts=ts)
        self.assertNotEqual(p1, p2)
        self.assertEqual(len(snapmod.list_snapshots(store)), 2)

    def test_newest_before(self):
        store, paths = self.make(n=3)
        self.assertEqual(snapmod.newest_before(store), paths[-1])
        self.assertEqual(snapmod.newest_before(store, paths[-1]), paths[-2])
        self.assertEqual(snapmod.newest_before(store, paths[0]), None)

    def test_newest_before_with_relative_store(self):
        # a relative --store makes list_snapshots return relative paths;
        # newest_before must still match them (abspath on both sides)
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        workdir = tempfile.mkdtemp(dir=td.name)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(workdir)
        store = "snaps"
        p1 = snapmod.save_snapshot(store, {"seq": 0}, ts=time.time() - 20)
        p2 = snapmod.save_snapshot(store, {"seq": 1}, ts=time.time())
        self.assertEqual(snapmod.newest_before(store, p2), p1)

    def test_prune_keeps_newest(self):
        store, paths = self.make(n=5)
        removed = snapmod.prune(store, keep=2)
        self.assertEqual(removed, 3)
        self.assertEqual(snapmod.list_snapshots(store), paths[-2:])

    def test_no_temp_files_left_behind(self):
        store, _ = self.make(n=2)
        leftovers = [f for f in os.listdir(store) if f.startswith(".tmp-")]
        self.assertEqual(leftovers, [])

    def test_baseline_roundtrip(self):
        store, paths = self.make(n=2)
        self.assertIsNone(snapmod.get_baseline(store))
        snapmod.set_baseline(store, paths[0])
        self.assertEqual(snapmod.get_baseline(store), paths[0])
        snapmod.set_baseline(store, paths[1])
        self.assertEqual(snapmod.get_baseline(store), paths[1])

    def test_baseline_ignores_deleted_snapshot(self):
        store, paths = self.make(n=1)
        snapmod.set_baseline(store, paths[0])
        os.unlink(paths[0])
        self.assertIsNone(snapmod.get_baseline(store))


if __name__ == "__main__":
    unittest.main()
