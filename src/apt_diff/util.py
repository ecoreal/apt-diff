"""Small shared helpers: output colors, human sizes, hashing."""

from __future__ import annotations

import hashlib
import os
import sys

# ---------------------------------------------------------------- colors ---


class Palette:
    """ANSI colors; disabled when not a TTY, NO_COLOR set, or asked off."""

    def __init__(self, enabled: bool = True) -> None:
        on = enabled and sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        self.on = on

    def _c(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.on else text

    def red(self, t: str) -> str:
        return self._c("31", t)

    def green(self, t: str) -> str:
        return self._c("32", t)

    def yellow(self, t: str) -> str:
        return self._c("33", t)

    def blue(self, t: str) -> str:
        return self._c("34", t)

    def cyan(self, t: str) -> str:
        return self._c("36", t)

    def bold(self, t: str) -> str:
        return self._c("1", t)

    def dim(self, t: str) -> str:
        return self._c("2", t)


def make_palette(no_color: bool = False) -> Palette:
    return Palette(enabled=not no_color)


# ----------------------------------------------------------------- sizes ---


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# --------------------------------------------------------------- hashing ---


def sha256_file(path: str, max_bytes: int = 0) -> str | None:
    """SHA-256 of a file; returns None if unreadable.

    max_bytes > 0 skips files larger than the limit (returns None).
    """
    try:
        st = os.stat(path)
        if max_bytes and st.st_size > max_bytes:
            return None
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None
