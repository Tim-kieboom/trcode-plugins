# trcode-plugins

The official list of plugins for [TerminalCode](https://github.com/Tim-kieboom/TerminalCode),
kept apart from the editor: a plugin is added or updated here, without a new version of the editor.

## Using it

Nothing to set up: the editor reads this list when you open "Plugins: Manage" (command palette)
and keeps the last copy it got. The first install of a version pins the module's hash: if the
same version ever comes with another module, the editor refuses it.

| Plugin | What it is |
| --- | --- |
| [Git](https://github.com/Tim-kieboom/trcode-plugin-git) | The changed files of the repository: stage, commit, fetch, pull and push, with buttons and a right-click menu (0.3.0 needs plugin API 1.10, TerminalCode 0.9.5) |
| [Markdown Preview](https://github.com/Tim-kieboom/trcode-plugin-markdown) | A preview of the markdown file you edit, in a pane beside the editor (needs plugin API 1.5) |
| [Tests](https://github.com/Tim-kieboom/trcode-plugin-test) | The tests of a project as folders, with Run buttons; a click opens a test's code, and what a failed test wrote is shown under the tests (needs plugin API 1.9, TerminalCode 0.9.4, and the Rust Test Adapter) |
| [Fake Test Adapter](https://github.com/Tim-kieboom/trcode-plugin-test) | Made-up tests and a clock you turn, for the Tests pane (needs plugin API 1.8) |
| [Rust Test Adapter](https://github.com/Tim-kieboom/trcode-plugin-test) | Lists and runs the tests of a Rust project with `cargo nextest` (must be installed) and finds the code of a test with `grep` (Linux and macOS), for the Tests pane (needs plugin API 1.8; runs commands in a folder you trust) |
| Syntax highlighting: [Go](https://github.com/Tim-kieboom/trcode-plugin-go-syntax), [Java](https://github.com/Tim-kieboom/trcode-plugin-java-syntax), [C#](https://github.com/Tim-kieboom/trcode-plugin-csharp-syntax), [YAML](https://github.com/Tim-kieboom/trcode-plugin-yaml-syntax), [SQL](https://github.com/Tim-kieboom/trcode-plugin-sql-syntax), [PHP](https://github.com/Tim-kieboom/trcode-plugin-php-syntax), [Ruby](https://github.com/Tim-kieboom/trcode-plugin-ruby-syntax), [Kotlin](https://github.com/Tim-kieboom/trcode-plugin-kotlin-syntax), [Swift](https://github.com/Tim-kieboom/trcode-plugin-swift-syntax), [Zig](https://github.com/Tim-kieboom/trcode-plugin-zig-syntax), [PowerShell](https://github.com/Tim-kieboom/trcode-plugin-powershell-syntax), [Dockerfile](https://github.com/Tim-kieboom/trcode-plugin-dockerfile-syntax), [XML](https://github.com/Tim-kieboom/trcode-plugin-xml-syntax) | Each colors the files of one language with its tree-sitter grammar and query, a language and no code (needs plugin API 1.12, TerminalCode 0.11.0; Dockerfile colors `*.dockerfile`, not a file named just `Dockerfile`) |

Your own list works the same way: put an `index.json` like this one in a repository and add its
address to `plugin_sources` in `settings.json`. Its plugins are marked with where they come from,
and installing one asks first.

## Adding a plugin

The quick way, once the plugin is released on GitHub (its release has `manifest.toml` and the module):

```sh
python3 scripts/add_plugin.py you/trcode-plugin-hello --description "Says hello"   # a new plugin
python3 scripts/add_plugin.py you/trcode-plugin-hello                              # its next version
```

It also works for a plugin that is only a language (a `[language]` table in its manifest and a tree-sitter grammar as its module). It reads the manifest of the latest release (`--tag vX.Y.Z` for another), downloads the module
for its hash, picks the `description.md` or README link, keeps the last description for a new
version, refuses a version that is listed already, checks the result like CI does and writes
`index.json`; commit and push it. `--dry-run` only shows the entry.

A plugin that is only a language (a tree-sitter grammar and its highlight query) can be made from a short
spec in `syntax/`: `python3 scripts/make_syntax_plugin.py syntax/go.toml` builds the grammar, converts the query for
the editor, writes and commits the plugin folder, and with `--publish` creates the repository and release and runs
`add_plugin.py`. See `syntax/README.md`.

By hand, a plugin is a WebAssembly module with a `manifest.toml`; see the
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
      "requires": "0.8.0",
      "tags": ["syntax", "python"],
      "readme": "https://github.com/you/trcode-plugin-hello/raw/v0.1.0/README.md"
    }
  ]
}
```

- `id` is the folder name and must equal the `id` in the manifest; `version` and `abi` must equal
  the manifest's too. `abi` is the plugin API the module needs; `requires` is the oldest editor
  (optional).
- `tags` (optional) is what the manager's search finds the plugin by (`/` and `tag:syntax`): a list from the set the editor knows, what the plugin is (`syntax`, `git`, `test`, `language-server`) and the language it is for (`python`, `c++`, ...). The manifest has the same `tags` and is the source of truth: `scripts/add_plugin.py` copies them into the entry, and `scripts/check_index.py` refuses a name the editor does not know (the editor would leave it out). A new tag needs an editor release first.
- `d` in the manager shows what the plugin says about itself: the `description.md` that a plugin publishes next to its `manifest.toml` (a release asset with the same address, apart from the file name; it is installed with the plugin). Plugins that have none can set `readme`, a link to a README (plain text or Markdown) that is shown instead; point it at the tag of that version. Both are optional.
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
