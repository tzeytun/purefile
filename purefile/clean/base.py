"""Types shared by all cleaners."""

from __future__ import annotations

from dataclasses import dataclass, field


class CleanError(RuntimeError):
    """The file could not be cleaned (corrupt input or verification failed)."""


@dataclass
class Changes:
    """What a cleaner removed from, and deliberately kept in, a file."""

    removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)

    def remove(self, what: str) -> None:
        if what not in self.removed:
            self.removed.append(what)

    def keep(self, what: str) -> None:
        if what not in self.kept:
            self.kept.append(what)


# Codes for data that is kept on purpose (localized by the UI).
KEPT_ICC = "icc_profile"
KEPT_ORIENTATION = "orientation"
