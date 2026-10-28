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
| `options` | The settings of the plugin. They are given to the plugin when it starts, and the choices of the user in the settings screen are put on top of them. |

The folder of the plugin is added at the end of the search path of
Python, and the module of the plugin is read from that folder under a
package of its own, whose name is built from a digest of the
identifier of the plugin.  The entry point of the plugin therefore
cannot take the place of a module of the program, and two plugins
cannot take each other's place.

What is **not** isolated is the folder of the plugin itself: it is on
the search path of Python, so a plugin that imports a helper by a plain
name (`import helper`) may get the helper of another plugin.  A plugin
that wants to be sure of its own files should import them as part of
its package (`from . import helper`).

### The trust of the user

Installing a plugin means **running its code inside the program**.  The
program does not check signatures, and it does not run a plugin in a
sandbox.  A plugin can do whatever its code does.

Therefore a plugin may only be installed from a source the user trusts,
and the licence of the plugin is shown in the settings screen.  The
licence is read from the manifest of the plugin and is shown as
information; it is not a promise that the code was examined, because
the code of the plugin runs as soon as the plugin is loaded.  The
program itself never downloads a plugin.

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

### How the settings reach the plugin

The settings of the plugin are the `options` of the manifest, with the
choices of the user in the settings screen put on top of them.  They
are given to the plugin **twice**, in the two ways a plugin can read
them:

* the constructor of the object, when it takes an `options` argument:
  `MyEngine(options=...)`;
* the method `configure(options)`, when the object has one.

A plugin that reads its settings in its constructor therefore gets them
when it starts and after every change, and a plugin that has a
`configure` method gets them in the same way.  A plugin that refuses a
setting - by raising an exception in `configure` - does not keep it: the
old setting stays, and the program tells the user that the new one was
refused.

The program knows the models of the plugins that come with it (the
option `model_id`), and offers to download them.  The model of a plugin
of another maker is the business of its own maker, and the program does
not offer it the model of another engine.

### A plugin of proposals

The object has to implement the contract of
`hebrew_workbench.suggestions.base`:

* `available() -> bool` and `unavailable_reason() -> str`;
* `check(text) -> list[Suggestion]` - the proposals for a text;
* `configure(options)` - the settings of the plugin (optional).

The kind of the module - `spelling`, `grammar` or `style` - is the kind
of the plugin in the manifest.  A module that does not choose one of
its own is taken to have the kind of its manifest.

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
