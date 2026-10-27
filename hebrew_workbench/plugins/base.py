"""The shape of a plugin.

A plugin is a part of the program that the user can add, remove, or
leave out.  There are two kinds of plugin:

* an OCR engine - something that turns a local document into text;
* a module of proposals - the spelling, the grammar, or the scholarly
  style.

The application does not know the plugins in advance.  It reads the
manifests, it loads the entry points, and it asks the user which one of
them is the active one.  A plugin that is broken is reported and
skipped; it never stops the program.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "PluginManifest",
    "Plugin",
    "PluginError",
    "KIND_OCR",
    "KIND_SPELLING",
    "KIND_GRAMMAR",
    "KIND_STYLE",
    "KINDS",
    "KIND_NAMES",
]

#: The kinds of plugins the program knows.
KIND_OCR = "ocr"
KIND_SPELLING = "spelling"
KIND_GRAMMAR = "grammar"
KIND_STYLE = "style"

KINDS: tuple[str, ...] = (KIND_OCR, KIND_SPELLING, KIND_GRAMMAR, KIND_STYLE)

#: The names of the kinds, for the user.
KIND_NAMES: dict[str, str] = {
    KIND_OCR: "מנוע זיהוי כתב יד",
    KIND_SPELLING: "בדיקת איות",
    KIND_GRAMMAR: "בדיקת ניסוח",
    KIND_STYLE: "לשון הספר",
}


class PluginError(Exception):
    """Something is wrong with a plugin or with its manifest."""


@dataclass(frozen=True)
class PluginManifest:
    """What a plugin says about itself.

    Attributes:
        id: The identifier of the plugin.  It is used in the settings
            file, so it has to stay the same when the plugin is
            updated.
        name: The name of the plugin, for the user.
        version: The version of the plugin.
        kind: What the plugin does: ``ocr``, ``spelling``, ``grammar``
            or ``style``.
        entry: Where the code is: ``package.module:Name``.
        license: SPDX identifier of the licence of the plugin.
        license_url: Where the licence text can be read.
        description: One sentence for the user.
        builtin: Whether the plugin is part of the program.
        enabled_by_default: Whether the plugin is switched on when the
            program starts.
        options: The settings of the plugin.
    """

    id: str
    name: str
    version: str
    kind: str
    entry: str
    license: str = ""
    license_url: str = ""
    description: str = ""
    author: str = ""
    homepage: str = ""
    builtin: bool = False
    enabled_by_default: bool = True
    options: dict = field(default_factory=dict)

    # -- the file form -----------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "kind": self.kind,
            "entry": self.entry,
            "license": self.license,
            "license_url": self.license_url,
            "description": self.description,
            "author": self.author,
            "homepage": self.homepage,
            "builtin": self.builtin,
            "enabled_by_default": self.enabled_by_default,
            "options": dict(self.options),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PluginManifest":
        """Build a manifest from the contents of ``plugin.json``."""
        if not isinstance(data, dict):
            raise PluginError("the manifest has to be an object")
        missing = [
            key
            for key in ("id", "name", "version", "kind", "entry")
            if not str(data.get(key, "")).strip()
        ]
        if missing:
            raise PluginError(
                "the manifest is missing: " + ", ".join(sorted(missing))
            )
        options = data.get("options", {})
        if not isinstance(options, dict):
            raise PluginError("the options of the manifest have to be an object")
        manifest = cls(
            id=str(data["id"]).strip(),
            name=str(data["name"]).strip(),
            version=str(data["version"]).strip(),
            kind=str(data["kind"]).strip(),
            entry=str(data["entry"]).strip(),
            license=str(data.get("license", "")).strip(),
            license_url=str(data.get("license_url", "")).strip(),
            description=str(data.get("description", "")).strip(),
            author=str(data.get("author", "")).strip(),
            homepage=str(data.get("homepage", "")).strip(),
            builtin=bool(data.get("builtin", False)),
            enabled_by_default=bool(data.get("enabled_by_default", True)),
            options=dict(options),
        )
        manifest.validate()
        return manifest

    # -- the rules ---------------------------------------------------------
    def validate(self) -> None:
        """Check the manifest, and say what is wrong with it."""
        if not self.id or self.id in {".", ".."} or any(
            character not in "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
            for character in self.id
        ):
            raise PluginError(
                f"the identifier {self.id!r} may only hold letters, digits, "
                "a dash, an underscore and a dot"
            )
        if self.kind not in KINDS:
            raise PluginError(
                f"the kind {self.kind!r} is not known; it has to be one of: "
                + ", ".join(KINDS)
            )
        if ":" not in self.entry:
            raise PluginError(
                f"the entry {self.entry!r} has to look like 'package.module:Name'"
            )
        module_name, _, attribute = self.entry.partition(":")
        if not module_name or not attribute:
            raise PluginError(f"the entry {self.entry!r} is not complete")
        for part in (module_name, attribute):
            if not all(
                piece.isidentifier() for piece in part.split(".")
            ):
                raise PluginError(f"the entry {self.entry!r} is not a valid path")


@dataclass
class Plugin:
    """A plugin that was found, with the object it gave."""

    manifest: PluginManifest
    object: object | None = None
    error: str = ""

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def kind(self) -> str:
        return self.manifest.kind

    @property
    def version(self) -> str:
        return self.manifest.version

    @property
    def license(self) -> str:
        return self.manifest.license

    @property
    def description(self) -> str:
        return self.manifest.description

    @property
    def builtin(self) -> bool:
        return self.manifest.builtin

    def available(self) -> bool:
        """Can the plugin work right now?"""
        if self.error or self.object is None:
            return False
        checker = getattr(self.object, "available", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return False
        return True
