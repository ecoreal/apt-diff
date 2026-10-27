# apt-diff

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Deps](https://img.shields.io/badge/dependencies-zero-brightgreen)

**Know what changed on your Debian / Raspberry Pi system — down to the file.**

`apt-diff` photographs your system's state and diffs the photos over time.
It answers the question every sysadmin eventually asks: *"it worked yesterday —
what changed?"*

One snapshot records:

| Subsystem | Detail |
| --- | --- |
| 📦 **dpkg packages** | name, version, arch, install status — catches installs, removals, upgrades, downgrades and half-configured regressions |
| ⚙️ **/etc** | SHA-256 of every regular file, symlink targets, permission bits |
| 🔧 **systemd units** | enablement state changes, services started/stopped |
| 🌐 **listening ports** | parsed straight from `/proc/net/tcp{,6}` (IPv4 + IPv6) |
| 🐧 **system** | kernel release, OS pretty name, hostname |

Zero dependencies. Pure Python 3.9+ stdlib. No root required to snapshot.

```console
$ sudo apt-diff init
Snapshot: /var/lib/apt-diff/snapshot-20261028T030000.json.gz
  packages 2306, /etc files 2012, units 354, listening 11
Baseline set to snapshot-20261028T030000.json.gz

$ ... a few days later ...

$ apt-diff diff
Changes 20261028T030000 → 20261031T030000

 ! /etc files modified [1]
      /etc/apt/sources.list.d/debian.sources

   Packages upgraded [3]
      bash  5.2.15-2+b7 → 5.2.15-2+b8
      ...

!! Ports opened [1]
      4:0.0.0.0:5432        ← postgres started listening? you decide.

Total: 7 changes — ...
```

## Why not etckeeper / apt-listchanges / git?

Different jobs: `etckeeper` tracks /etc only, `apt-listchanges` shows
changelogs of *pending* upgrades. `apt-diff` is the post-hoc timeline of the
**whole machine** — packages + config + services + network surface — in one
command, with no repository to maintain and nothing to configure. If you want
deep per-file history, use etckeeper *too*; they get along.

## Quick start

```bash
git clone <repo> && cd apt-diff
make test          # 59 unit tests, no root needed
sudo ./install.sh  # installs CLI + man page + bash completion + nightly timer
sudo apt-diff init # baseline
```

Without installing (great for Raspberry Pis over ssh):

```bash
make zipapp        # single-file executable: dist/apt-diff
scp dist/apt-diff pi@raspberrypi:
ssh pi@raspberrypi './apt-diff init && ./apt-diff check'
```

## Commands

| Command | What it does |
| --- | --- |
| `init` | First snapshot + baseline (what `check` compares against) |
| `snapshot` | New snapshot; prunes old ones (default keep 30) |
| `diff [old] [new]` | Compare any two snapshots (default: baseline → latest) |
| `check` | Exit 1 if system drifted from baseline — built for cron |
| `log` | Snapshot history with per-interval change counts |
| `show [name]` | One-page summary of a snapshot |
| `prune --keep N` | Retention control |

Names resolve flexibly: `latest`, `baseline`, `20261028T030000`, a file name,
or a full path.

### Cron / systemd

`install.sh` enables a nightly 03:00 snapshot timer. For cron instead:

```
0 3 * * * root apt-diff snapshot
30 3 * * * root apt-diff check -q
```

`check` exits 1 on drift, so you can pipe it anywhere
(mail, ntfy, healthchecks.io, a wall-mounted LED...).

### Machine-readable output

Every inspection command takes `--json`:

```console
$ apt-diff check --json | jq '.summary'
{ "pkg-upgraded": 3, "etc-modified": 1, "port-opened": 1 }
```

## Design notes

- **Snapshots are gzip-JSON** (~100 KB on a desktop, less on a Pi) in
  `/var/lib/apt-diff` (root) or `~/.local/share/apt-diff` (user), written
  atomically. Nothing is a black box.
- **Ports come from `/proc/net/tcp[6]`** — no `ss`/`netstat` dependency, and
  the IPv6 little-endian word format the kernel prints is decoded properly.
- **Version comparison** implements dpkg's practical rules: epochs dominate,
  numeric runs compare numerically (`1.10 > 1.9`), and `~` sorts before
  release (`1.0~rc1 < 1.0`).
- **`--root`** makes every collector inspect a chroot or fixture tree instead
  of `/` — that's how the test suite tests a "system" without a system.
- The systemd collector uses `systemctl` on the live system and falls back to
  scanning `/etc/systemd/system/*.wants/` elsewhere.

## Testing

```bash
make test          # unit + end-to-end CLI tests on a fake root
make integration   # snapshot + diff the real machine you're on
```

## License

[MIT](LICENSE)
