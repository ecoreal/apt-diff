"""Command line interface: apt-diff init | snapshot | diff | check | log | show | prune."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__, collect, diff as diffmod, render, snapshot as snapmod
from .util import make_palette


def build_parser() -> argparse.ArgumentParser:
    # Common options live on a parent parser so they work both before and
    # after the subcommand. SUPPRESS in the sub copies prevents sub-parsing
    # from overwriting values given before the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--store", metavar="DIR", default=argparse.SUPPRESS,
                        help="snapshot store (default: /var/lib/apt-diff or ~/.local/share/apt-diff)")
    common.add_argument("--root", metavar="DIR", default=argparse.SUPPRESS,
                        help="system root to inspect (for testing/chroots; default /)")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="machine-readable output")
    common.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS,
                        help="disable ANSI colors")
    common.add_argument("-q", "--quiet", action="store_true", default=argparse.SUPPRESS,
                        help="only print what matters")

    p = argparse.ArgumentParser(
        prog="apt-diff",
        parents=[common],
        description="Snapshot dpkg packages, /etc, systemd units and listening "
                    "ports; diff the system against any past snapshot.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="COMMAND", required=True)

    s = sub.add_parser("init", parents=[common],
                       help="take the first snapshot and mark it as baseline")
    s.add_argument("--etc-max", type=int, default=2 * 1024 * 1024, metavar="BYTES",
                   help="skip /etc files larger than this (default 2 MiB)")

    s = sub.add_parser("snapshot", parents=[common], help="take a new snapshot")
    s.add_argument("--keep", type=int, default=snapmod.RETAIN_DEFAULT, metavar="N",
                   help="retain the newest N snapshots (default 30)")

    s = sub.add_parser("diff", parents=[common], help="compare two snapshots")
    s.add_argument("old", nargs="?", default=None,
                   help="older snapshot name/path (default: baseline or previous)")
    s.add_argument("new", nargs="?", default=None,
                   help="newer snapshot name/path (default: latest)")

    s = sub.add_parser("check", parents=[common],
                       help="diff against baseline; exit 1 when changed")
    s.add_argument("--against", default=None, help="snapshot name to compare against")

    s = sub.add_parser("log", parents=[common],
                       help="list snapshots and the changes between them")
    s.add_argument("-n", type=int, default=20, metavar="N", help="how many to show")

    s = sub.add_parser("show", parents=[common], help="summarize one snapshot")
    s.add_argument("name", nargs="?", default="latest", help="snapshot name/path")

    s = sub.add_parser("prune", parents=[common], help="delete old snapshots")
    s.add_argument("--keep", type=int, default=snapmod.RETAIN_DEFAULT, metavar="N")
    return p


def resolve_store(args) -> str:
    return getattr(args, "store", None) or snapmod.default_store()


def resolve_snapshot(store: str, name: str | None) -> str | None:
    """A CLI name ("latest", "baseline", file name or path) → snapshot path."""
    if name is None or name == "latest":
        snaps = snapmod.list_snapshots(store)
        return snaps[-1] if snaps else None
    if name == "baseline":
        return snapmod.get_baseline(store)
    if os.path.isabs(name) or os.sep in name:
        return name if os.path.exists(name) else None
    for candidate in (
        os.path.join(store, name),
        os.path.join(store, name + ".json.gz"),
        os.path.join(store, "snapshot-" + name + ".json.gz"),
    ):
        if os.path.exists(candidate):
            return candidate
    return None


def short_name(path: str | None) -> str:
    if not path:
        return "?"
    return os.path.basename(path).replace("snapshot-", "").replace(".json.gz", "")


# ------------------------------------------------------------- commands ---


def cmd_init(args, store: str) -> int:
    data = collect.collect_all(args.root, etc_max_file_size=args.etc_max)
    path = snapmod.save_snapshot(store, data)
    snapmod.set_baseline(store, path)
    _print_counts(args, data, path)
    if not args.quiet:
        print(f"Baseline set to {os.path.basename(path)}")
    return 0


def cmd_snapshot(args, store: str) -> int:
    data = collect.collect_all(args.root)
    path = snapmod.save_snapshot(store, data)
    removed = snapmod.prune(store, keep=args.keep)
    _print_counts(args, data, path)
    if removed and not args.quiet:
        print(f"Pruned {removed} old snapshot(s)")
    return 0


def _print_counts(args, data: dict, path: str) -> None:
    if args.json:
        print(json.dumps({"snapshot": os.path.basename(path),
                          "packages": len(data.get("packages", {})),
                          "etc_files": len(data.get("etc", {})),
                          "units": len(data.get("units", {})),
                          "ports": len(data.get("ports", []))}))
        return
    if args.quiet:
        print(path)
        return
    print(f"Snapshot: {path}")
    print(f"  packages {len(data.get('packages', {}))}, "
          f"/etc files {len(data.get('etc', {}))}, "
          f"units {len(data.get('units', {}))}, "
          f"listening {len(data.get('ports', []))}")


def cmd_diff(args, store: str) -> int:
    new = resolve_snapshot(store, args.new)
    if new is None:
        print("apt-diff: no snapshots found — run `apt-diff init` first", file=sys.stderr)
        return 2
    if args.old:
        old = resolve_snapshot(store, args.old)
        if old is None:
            print(f"apt-diff: unknown snapshot '{args.old}'", file=sys.stderr)
            return 2
    else:
        old = snapmod.get_baseline(store) or snapmod.newest_before(store, new)
        if old is None:
            old = new  # only one snapshot exists → compare with itself
    a, b = snapmod.load_snapshot(old), snapmod.load_snapshot(new)
    changes = diffmod.diff_snapshots(a, b)
    meta = {"from": short_name(old), "to": short_name(new)}
    if args.json:
        print(render.render_changes_json(changes, meta))
    else:
        palette = make_palette(args.no_color)
        print(render.render_changes_human(changes, palette, meta=meta))
    return 0


def cmd_check(args, store: str) -> int:
    new = resolve_snapshot(store, "latest")
    if new is None:
        print("apt-diff: no snapshots found — run `apt-diff init` first", file=sys.stderr)
        return 2
    if args.against:
        old = resolve_snapshot(store, args.against)
        if old is None:
            print(f"apt-diff: unknown snapshot '{args.against}'", file=sys.stderr)
            return 2
    else:
        old = snapmod.get_baseline(store)
        if old is None:
            print("apt-diff: no baseline — run `apt-diff init`", file=sys.stderr)
            return 2
    a, b = snapmod.load_snapshot(old), snapmod.load_snapshot(new)
    changes = diffmod.diff_snapshots(a, b)
    meta = {"from": short_name(old), "to": short_name(new)}
    if args.json:
        print(render.render_changes_json(changes, meta))
    elif changes:
        palette = make_palette(args.no_color)
        print(render.render_changes_human(changes, palette, meta=meta))
    else:
        if not args.quiet:
            print("OK: no changes")
        return 0
    counts = diffmod.summarize(changes)
    total = len(changes)
    print(f"apt-diff: {total} change(s) since {meta['from']}: "
          + ", ".join(f"{n} {render.LABELS.get(k, k)}" for k, n in counts.items()),
          file=sys.stderr)
    return 1


def cmd_log(args, store: str) -> int:
    snaps = snapmod.list_snapshots(store)
    baseline = snapmod.get_baseline(store)
    entries = []
    prev_data = None
    for path in snaps:
        data = snapmod.load_snapshot(path)
        counts = None
        if prev_data is not None:
            counts = diffmod.summarize(diffmod.diff_snapshots(prev_data, data))
        entries.append({
            "name": os.path.basename(path),
            "size": os.path.getsize(path),
            "counts": counts,
            "baseline": baseline == path,
        })
        prev_data = data
    if args.json:
        print(json.dumps({"store": store, "snapshots": entries}, indent=2))
        return 0
    entries = entries[-args.n:]
    palette = make_palette(args.no_color)
    print(render.render_log(store, snaps, entries, palette))
    return 0


def cmd_show(args, store: str) -> int:
    path = resolve_snapshot(store, args.name)
    if path is None:
        print(f"apt-diff: no such snapshot '{args.name}'", file=sys.stderr)
        return 2
    data = snapmod.load_snapshot(path)
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
        return 0
    print(render.render_show(data, make_palette(args.no_color)))
    return 0


def cmd_prune(args, store: str) -> int:
    removed = snapmod.prune(store, keep=args.keep)
    print(f"Removed {removed} snapshot(s); kept {args.keep} newest")
    return 0


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)
    # SUPPRESS'd common options are absent when not given — backfill defaults
    # (root/store also honour env vars).
    if not hasattr(args, "root"):
        args.root = os.environ.get("APTDIFF_ROOT", "/")
    if not hasattr(args, "store"):
        args.store = os.environ.get("APTDIFF_STORE")
    for flag in ("json", "no_color", "quiet"):
        if not hasattr(args, flag):
            setattr(args, flag, False)
    store = resolve_store(args)
    handlers = {
        "init": cmd_init,
        "snapshot": cmd_snapshot,
        "diff": cmd_diff,
        "check": cmd_check,
        "log": cmd_log,
        "show": cmd_show,
        "prune": cmd_prune,
    }
    try:
        return handlers[args.cmd](args, store)
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
