# Changelog

## Unreleased

- Added: symlinks to directories under /etc are now recorded in snapshots
  (same record shape as file symlinks: target kept, no hash). Previously a
  directory replaced by — or newly appearing as — a symlink was completely
  invisible to the audit. Diffs against snapshots taken before this change
  will report existing directory symlinks once as "etc-added".

## 1.0.1 — 2026-10-28

- Fixed: `make zipapp` failed on a fresh checkout because the `dist/`
  directory did not exist yet; it is now created on demand.
- Fixed: with a relative `--store`, `apt-diff diff` without arguments could
  compare the newest snapshot with itself and always report "no changes",
  because the previous-snapshot lookup matched raw vs absolute paths.
- Added: dedicated unit tests for the render module (+15, 60 total).

## 1.0.0 — 2026-10-28

Initial release.

- Snapshot collectors: dpkg status, /etc hashes (files, symlinks, modes),
  systemd unit states (systemctl + file fallback), listening TCP ports
  (/proc/net/tcp[6] with proper IPv6 decoding), kernel/OS/hostname.
- Snapshot store: gzip-JSON, atomic writes, same-second collision handling,
  retention pruning, baseline marker.
- Diffs: package add/remove/upgrade/downgrade/status-regression, /etc
  add/remove/modify/permission/symlink changes, unit enable/disable and
  service start/stop, port opened (security-marked) / closed, kernel and OS
  release changes.
- CLI: init, snapshot, diff, check (cron-friendly exit codes), log, show,
  prune; --json, --root, --store, --no-color, -q.
- Packaging: zipapp single-file build, install.sh, man page, bash
  completion, systemd service + nightly timer.
- 45 unit/end-to-end tests on fixture roots; verified on Debian 13 (2306
  packages, port count matches ss(1)).
