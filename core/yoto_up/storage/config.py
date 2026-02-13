"""Application settings and configuration constants.

``AppSettings`` provides a simple key-value store backed by a JSON file.
``CLIENT_ID`` is the OAuth client identifier used for the Yoto API.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import SETTINGS_FILE, ensure_parents

# ---------------------------------------------------------------------------
# OAuth client ID for the Yoto device-code flow
# ---------------------------------------------------------------------------

CLIENT_ID = "RslORm04nKbhf04qb91r2Pxwjsn3Hnd5"

# ---------------------------------------------------------------------------
# Default settings
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, Any] = {
    "debug": False,
    "cache_enabled": False,
    "cache_max_age": 0,
    "audio_target_lufs": -16.0,
}


# ---------------------------------------------------------------------------
# AppSettings
# ---------------------------------------------------------------------------


class AppSettings:
    """JSON-backed application settings store."""

    @staticmethod
    def load() -> dict[str, Any]:
        """Load settings from disk, returning defaults for missing keys."""
        settings = dict(_DEFAULTS)
        try:
            if SETTINGS_FILE.exists():
                data = json.loads(SETTINGS_FILE.read_text())
                if isinstance(data, dict):
                    settings.update(data)
        except Exception:
            pass
        return settings

    @staticmethod
    def save(settings: dict[str, Any]) -> None:
        """Persist *settings* to disk."""
        ensure_parents(SETTINGS_FILE)
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2))

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """Return a single setting value."""
        return cls.load().get(key, default)

    @classmethod
    def set(cls, key: str, value: Any) -> None:
        """Update a single setting value and save."""
        settings = cls.load()
        settings[key] = value
        cls.save(settings)
