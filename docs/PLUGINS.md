# The plugins: adding another engine, or another word list

The program is not tied to one recognition engine.  The engine is a
*plugin*, and so are the modules that propose corrections (the
spelling, the grammar, the scholarly style).  A better Hebrew
recognizer can therefore be added later without changing the code of
the program: it is installed, it is chosen in the settings screen, and
that is all.

## What the program comes with

| Plugin | Kind | State |
| --- | --- | --- |
| `kraken` - kraken + PP-OCRv6 | engine | works, needs the model file |
| `kraken-worker` - the same engine in a separate process | engine | works, needs the model file and the worker |
| `spelling-hebrew` | spelling | works, needs a word list of the user |
| `grammar-hebrew` | grammar | works, a few rules |
| `style-leshon-ha-sefer` | style | a frame only; it is switched off and says why |

A plugin that comes with the program cannot be removed, but it can be
switched off, and then the program works without it.

## The settings screen

**הגדרות > תוספים ומנועים...** shows every plugin: its name, its
kind, its version, its licence, whether it is switched on, and whether
it came with the program or was installed by the user.

From that screen the user can

* install a plugin from a folder or from a ZIP file,
* remove a plugin that was installed,
* switch a plugin on and off,
* choose which plugin of each kind is the active one.

The choice is kept in `plugins/settings.json` in the data directory of
the user (`%LOCALAPPDATA%\HebrewNotesWorkbench` on Windows).

## The shape of a plugin

A plugin is a folder with a file `plugin.json` in it:

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

| Field | Meaning |
| --- | --- |
| `id` | Letters, digits, a dash, an underscore and a dot. It is used in the settings file, so it should not change. |
| `kind` | `ocr`, `spelling`, `grammar` or `style`. |
| `entry` | `package.module:Name` - where the code is. |
| `license`, `license_url` | The licence of the plugin. The program shows it to the user. |
| `enabled_by_default` | Whether the plugin starts switched on (`true` by default). |
| `options` | The settings of the plugin. They are given to the plugin when it starts. |

The folder of the plugin is added to the end of the search path of
Python, and the module of the plugin is read from that folder under a
name of its own.  A file of a plugin therefore cannot take the place of
a module of the program, and two plugins cannot take each other's place.

### The trust of the user

Installing a plugin means **running its code inside the program**.  The
program does not check signatures, and it does not run a plugin in a
sandbox.  A plugin can do whatever its code does.

Therefore a plugin may only be installed from a source the user trusts,
and the licence of the plugin is shown in the settings screen before it
is used.  The program itself never downloads a plugin.

### An engine plugin

The object of an engine plugin has to implement the contract of
`hebrew_workbench.engine.base`:

* `available() -> bool` - whether the engine can work right now;
* `recognize(path, progress=None, cancel=None) -> OCRResult` - the
  recognition of a document;
* `manifest() -> EngineManifest` (optional) - what the user needs to
  know: the name, the version, the script, the licence, the model and
  its digests.  An engine without it is allowed.

`progress` and `cancel` are optional: an engine that does not take them
keeps working.

### A plugin of proposals

The object has to implement the contract of
`hebrew_workbench.suggestions.base`:

* `available() -> bool` and `unavailable_reason() -> str`;
* `check(text) -> list[Suggestion]` - the proposals for a text;
* `configure(options)` - the settings of the plugin (optional).

A module of proposals **never changes the text**.  It returns
proposals, and the user accepts or refuses every one of them.

## What the program does with a plugin that does not work

* A manifest that is not valid is refused, with the reason.
* A plugin whose code cannot be imported is listed with the error, and
  the program carries on without it.
* A plugin that raises an exception while it checks a text does not stop
  the other modules.
* A ZIP file that holds a file outside of itself is refused.

## The licence of a plugin

The program does not check the licence of a plugin, and it does not
download plugins.  The user brings the plugin, and the licence of the
plugin is shown in the settings screen, so that the user can see what
it is before using it.

The licences of the parts that come with the program are in
`LICENCES/` in the folder of the program, and in `docs/THIRD_PARTY.md`
in the sources.
