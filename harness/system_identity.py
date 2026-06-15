"""System identity helpers for session recovery across reboots.

A PID alone is not enough to decide whether a job recorded earlier is
still the same running process: after a reboot the OS reuses PID numbers,
so a stored PID may now point at an unrelated process. We therefore stamp
every persisted job/session with the current *boot id*. On recovery we
compare boot ids: if they differ the machine has rebooted and the old
process is definitely gone — regardless of whether that PID happens to be
alive now.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_BOOT_ID_CACHE: str | None = None


def boot_id() -> str:
    """A stable identifier for the current OS boot. Changes on reboot.

    Order: Linux random boot_id, then /proc/stat btime, then macOS
    kern.boottime, then a clearly-degraded fallback.
    """
    global _BOOT_ID_CACHE
    if _BOOT_ID_CACHE is not None:
        return _BOOT_ID_CACHE

    val = _linux_boot_id() or _proc_btime() or _macos_boottime()
    _BOOT_ID_CACHE = val or "unknown-boot"
    return _BOOT_ID_CACHE


def _linux_boot_id() -> str | None:
    try:
        text = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        return f"linux:{text}" if text else None
    except Exception:
        return None


def _proc_btime() -> str | None:
    try:
        for line in Path("/proc/stat").read_text().splitlines():
            if line.startswith("btime"):
                return f"btime:{line.split()[1]}"
    except Exception:
        pass
    return None


def _macos_boottime() -> str | None:
    try:
        out = subprocess.run(["sysctl", "-n", "kern.boottime"],
                             capture_output=True, text=True, timeout=5)
        text = out.stdout.strip()
        if text:
            # e.g. "{ sec = 1700000000, usec = 0 } ..."
            for tok in text.replace(",", " ").split():
                if tok.isdigit() and len(tok) >= 9:
                    return f"boottime:{tok}"
            return f"boottime:{text[:40]}"
    except Exception:
        pass
    return None


def rebooted_since(stored_boot_id: str | None) -> bool:
    """True if the machine has rebooted since `stored_boot_id` was taken
    (treat unknown/missing as "cannot confirm same boot" → rebooted)."""
    if not stored_boot_id or stored_boot_id == "unknown-boot":
        return True
    return stored_boot_id != boot_id()


def human_gap(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}m"
    if seconds < 172800:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"
