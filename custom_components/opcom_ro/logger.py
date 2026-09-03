"""Optional debug file logger for the OPCOM integration.

When enabled (via the integration options), key lifecycle events are written
to ``<config>/opcom_ro_debug.log`` so a user can grab a single file and share
it for troubleshooting. The file is size-capped with one rollover
(``opcom_ro_debug.log.1``) so it never grows without bound.

File I/O happens in the executor. The logger also forwards every line to the
standard Home Assistant logger, so the same events show up in the HA log too.
"""
from __future__ import annotations

import logging
import os

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DEBUG_LOG_FILENAME

_LOGGER = logging.getLogger(__name__)

_MAX_BYTES = 512 * 1024  # 512 KB per file before rolling over


class OpcomFileLogger:
    """Writes structured debug lines to a file in the HA config directory."""

    def __init__(self, hass: HomeAssistant, enabled: bool = False) -> None:
        self.hass = hass
        self._enabled = enabled
        self.path: str = hass.config.path(DEBUG_LOG_FILENAME)
        self._rollover_path: str = self.path + ".1"

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._enabled = True
        self.log("info", "OPCOM debug file logging enabled (path=%s)", self.path)

    def disable(self) -> None:
        self.log("info", "OPCOM debug file logging disabled")
        self._enabled = False

    def log(self, level: str, msg: str, *args: object) -> None:
        """Log to both the HA logger and, if enabled, the debug file."""
        getattr(_LOGGER, level, _LOGGER.debug)(msg, *args)
        if not self._enabled:
            return
        text = msg % args if args else msg
        line = f"{dt_util.now().isoformat()} [{level.upper()}] {text}\n"

        def _write() -> None:
            try:
                self._rollover()
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line)
            except OSError as exc:
                _LOGGER.error("Could not write OPCOM debug log: %s", exc)

        self.hass.async_add_executor_job(_write)

    def clear(self) -> None:
        """Delete the debug log files so the user can capture a clean run."""

        def _clear() -> None:
            for p in (self.path, self._rollover_path):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError as exc:
                    _LOGGER.warning("Could not remove %s: %s", p, exc)

        self.hass.async_add_executor_job(_clear)
        self.log("info", "OPCOM debug log cleared by user")

    def _rollover(self) -> None:
        """Move the current log to .1 once it exceeds the size cap."""
        try:
            if os.path.exists(self.path) and os.path.getsize(self.path) > _MAX_BYTES:
                if os.path.exists(self._rollover_path):
                    os.remove(self._rollover_path)
                os.rename(self.path, self._rollover_path)
        except OSError:
            pass