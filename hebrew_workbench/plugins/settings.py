"""The choices of the user: which plugin is active, and which are on.

The settings are kept in one small JSON file, so that the user can
look at them, and so that the program works with no plugins at all.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["PluginSettings"]


@dataclass
class PluginSettings:
    """What the user has chosen.

    Attributes:
        active: The identifier of the active plugin of every kind.
        disabled: The identifiers of the plugins that are switched off.
        options: The settings of every plugin, by its identifier.
    """

    active: dict[str, str] = field(default_factory=dict)
    enabled: set[str] = field(default_factory=set)
    disabled: set[str] = field(default_factory=set)
    options: dict[str, dict] = field(default_factory=dict)

    # -- the file ----------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path) -> "PluginSettings":
        """Read the settings.  A missing file means the default settings."""
        file_path = Path(path)
        if not file_path.is_file():
            return cls()
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A broken settings file must not stop the program; the
            # defaults are used instead.
            return cls()
        if not isinstance(data, dict):
            return cls()
        active = data.get("active", {})
        enabled = data.get("enabled", [])
        disabled = data.get("disabled", [])
        options = data.get("options", {})
        return cls(
            active={str(k): str(v) for k, v in active.items()}
            if isinstance(active, dict)
            else {},
            enabled={str(item) for item in enabled}
            if isinstance(enabled, list)
            else set(),
            disabled={str(item) for item in disabled}
            if isinstance(disabled, list)
            else set(),
            options={
                str(k): dict(v)
                for k, v in options.items()
                if isinstance(v, dict)
            }
            if isinstance(options, dict)
            else {},
        )

    def save(self, path: str | Path) -> None:
        """Write the settings, so that a power cut cannot empty them."""
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "active": dict(self.active),
            "enabled": sorted(self.enabled),
            "disabled": sorted(self.disabled),
            "options": {key: dict(value) for key, value in self.options.items()},
        }
        handle, temporary = tempfile.mkstemp(
            dir=str(file_path.parent), prefix=".settings-", suffix=".json"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, file_path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    # -- the choices -------------------------------------------------------
    def is_disabled(self, plugin_id: str) -> bool:
        return plugin_id in self.disabled

    def is_enabled(self, plugin_id: str) -> bool:
        """Did the user switch this plugin on explicitly?"""
        return plugin_id in self.enabled

    def set_disabled(self, plugin_id: str, disabled: bool) -> None:
        if disabled:
            self.disabled.add(plugin_id)
            self.enabled.discard(plugin_id)
        else:
            self.disabled.discard(plugin_id)

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        """Record the choice of the user for a plugin."""
        if enabled:
            self.enabled.add(plugin_id)
            self.disabled.discard(plugin_id)
        else:
            self.disabled.add(plugin_id)
            self.enabled.discard(plugin_id)

    def option(self, plugin_id: str, key: str, default=None):
        return self.options.get(plugin_id, {}).get(key, default)

    def set_option(self, plugin_id: str, key: str, value) -> None:
        self.options.setdefault(plugin_id, {})[key] = value
