# trcode-plugins

A list of plugins for [TerminalCode](https://github.com/Tim-kieboom/TerminalCode), kept apart
from the editor: add it as a **plugin source** and its plugins show up in "Plugins: Manage"
beside the official ones, without a new version of the editor.

## Using it

In `settings.json`:

```jsonc
"plugin_sources": ["https://raw.githubusercontent.com/Tim-kieboom/trcode-plugins/main/index.json"]
```

Open "Plugins: Manage" (command palette). The plugins of this list are marked with
`Tim-kieboom/trcode-plugins`; installing one asks first and shows the source and the module's
hash. The first install pins that hash: if the same version ever comes with another module, the
editor refuses it. A plugin that came from here is updated only from here.

## Adding a plugin

A plugin is a WebAssembly module with a `manifest.toml`; see the
[Git plugin](https://github.com/Tim-kieboom/trcode-plugin-git) for one. Release it on GitHub
(the module and the manifest as release assets, or raw files of a tag), then add an entry to
`index.json` in a pull request:

```json
{
  "format": 1,
  "plugins": [
    {
      "id": "hello",
      "name": "Hello",
      "description": "Says hello",
      "version": "0.1.0",
      "manifest": "https://github.com/you/trcode-plugin-hello/releases/download/v0.1.0/manifest.toml",
      "module": "https://github.com/you/trcode-plugin-hello/releases/download/v0.1.0/hello.wasm",
      "sha256": "<sha256 of hello.wasm, lower case hex>",
      "abi": "1.4",
      "requires": "0.8.0"
    }
  ]
}
```

- `id` is the folder name and must equal the `id` in the manifest; `version` and `abi` must equal
  the manifest's too. `abi` is the plugin API the module needs; `requires` is the oldest editor
  (optional).
- List a new version as another entry; keep the old ones. A published version must never change:
  the editor pins its hash.
- URLs must be `https` addresses of `github.com` or `githubusercontent.com`.
- A name that an official plugin has cannot be used here (the official one wins).

`python3 scripts/check_index.py --download` runs the same check as CI: the index reads and every
module has the hash the entry promises.

## Trust

Installing from this list trusts whoever can merge here and whoever owns the plugin's repository.
Read what a plugin asks to be allowed to do (shown when you turn it on) before saying yes.

## License

MIT or Apache-2.0, at your option.
