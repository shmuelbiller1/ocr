"""The manifest of a plugin: the file ``plugin.json``.

Every plugin - the ones that come with the program and the ones that
the user adds - is described by one JSON file:

```json
{
  "id": "my-hebrew-engine",
  "name": "מנוע עברי שלי",
  "version": "1.0.0",
  "kind": "ocr",
  "entry": "my_engine:MyEngine",
  "license": "Apache-2.0",
  "license_url": "https://www.apache.org/licenses/LICENSE-2.0",
  "description": "מנוע לזיהוי כתב יד עברי",
  "options": {"model": "my-model.safetensors"}
}
```
"""

from __future__ import annotations

from .base import PluginManifest

__all__ = ["MANIFEST_NAME", "PluginManifest"]

#: The name of the file that holds the manifest.
MANIFEST_NAME = "plugin.json"
