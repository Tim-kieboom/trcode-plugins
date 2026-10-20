# trcode-plugins

The official list of plugins for [TerminalCode](https://github.com/Tim-kieboom/TerminalCode),
kept apart from the editor: a plugin is added or updated here, without a new version of the editor.

## Using it

Nothing to set up: the editor reads this list when you open "Plugins: Manage" (command palette)
and keeps the last copy it got. The first install of a version pins the module's hash: if the
same version ever comes with another module, the editor refuses it.

| Plugin | What it is |
| --- | --- |
| [Git](https://github.com/Tim-kieboom/trcode-plugin-git) | The changed files of the repository: stage, commit, fetch, pull and push, with buttons |

Your own list works the same way: put an `index.json` like this one in a repository and add its
address to `plugin_sources` in `settings.json`. Its plugins are marked with where they come from,
and installing one asks first.

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
- A name that is listed here cannot be used by anyone else's source (the official list wins).

`python3 scripts/check_index.py --download` runs the same check as CI: the index reads and every
module has the hash the entry promises.

## Trust

Installing from this list trusts whoever can merge here (the editor does not ask first for this list, which is the official one) and whoever owns the plugin's repository.
Read what a plugin asks to be allowed to do (shown when you turn it on) before saying yes.

## License

MIT or Apache-2.0, at your option.
