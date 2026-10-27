"""apt-diff — snapshot and audit what changed on a Debian system.

Pure-stdlib tool that captures dpkg package state, /etc contents, systemd
unit states and listening ports into compressible snapshots, then diffs
them over time.  Works on Debian and Raspberry Pi OS.

Copyright 2026  MIT license.
"""

__version__ = "1.0.1"
TOOL = "apt-diff"
