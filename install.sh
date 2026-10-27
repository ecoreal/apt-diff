#!/bin/sh
# Install apt-diff system-wide from this repository.
# Usage: sudo ./install.sh [--bin DIR] [--no-systemd]
set -eu

PREFIX=${1:-}
BIN_DIR=/usr/local/bin
MAN_DIR=/usr/local/share/man/man1
COMP_DIR=/etc/bash_completion.d
NO_SYSTEMD=0

while [ $# -gt 0 ]; do
    case "$1" in
        --bin) BIN_DIR="$2"; shift 2 ;;
        --no-systemd) NO_SYSTEMD=1; shift ;;
        *) echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then
    echo "apt-diff: install.sh needs root (or use 'make zipapp' for a single-file copy)" >&2
    exit 1
fi

echo "==> building zipapp"
make zipapp >/dev/null

echo "==> installing to $BIN_DIR/apt-diff"
install -m 0755 dist/apt-diff "$BIN_DIR/apt-diff"

if [ -d "$MAN_DIR" ]; then
    echo "==> installing man page"
    install -m 0644 man/apt-diff.1 "$MAN_DIR/apt-diff.1"
fi

if [ -d "$COMP_DIR" ]; then
    echo "==> installing bash completion"
    install -m 0644 completion/apt-diff.bash "$COMP_DIR/apt-diff"
fi

if [ "$NO_SYSTEMD" -eq 0 ] && [ -d /etc/systemd/system ]; then
    echo "==> installing systemd timer (nightly 03:00 snapshot)"
    install -m 0644 systemd/apt-diff-snapshot.service /etc/systemd/system/
    install -m 0644 systemd/apt-diff-snapshot.timer /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable --now apt-diff-snapshot.timer
    echo "    timer: $(systemctl is-enabled apt-diff-snapshot.timer)"
fi

echo "==> done. Now run: sudo apt-diff init"
