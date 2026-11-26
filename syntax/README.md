# Syntax plugin specs

One file per language, read by `scripts/make_syntax_plugin.py`, which builds the plugin (a tree-sitter
grammar and its highlight query, no code) as a folder `trcode-plugin-<id>` next to this repository.

```sh
nix shell nixpkgs#tree-sitter nixpkgs#nodejs      # or have `tree-sitter` (and `node`) on the PATH
python3 scripts/make_syntax_plugin.py syntax/go.toml                       # build and commit the folder
python3 scripts/make_syntax_plugin.py syntax/go.toml --check sample.go     # and color a sample through the editor's loader
python3 scripts/make_syntax_plugin.py syntax/go.toml --publish             # create the repository, release, add to index.json
```

`--check` needs the TerminalCode repository (`--editor`, default `../TerminalCode`) and `cargo`: it writes
a temporary test into the editor's syntax crate, runs it and removes it, and prints which captures color which
words, so a query that colors too little or too much shows at once. `TRCODE_CHECK_TARGET` is a cargo target
folder to use for it.

## The spec

```toml
id = "go-syntax"                  # default: the file name + "-syntax"
name = "Go"                       # what the manager and the status bar show
description = "Syntax highlighting for Go"   # the line of the index entry
tags = ["syntax", "go"]           # from the set the editor knows (scripts/check_index.py has it); an
                                  # unknown one is kept in the manifest but the script says so
extensions = ["go"]               # without the dot; the editor picks a language by extension only
comment = "//"                    # for ctrl+/, leave out when the language has no line comment
version = "0.0.1"                 # default 0.0.1, or --version
readme_notes = "..."              # extra paragraphs for the plugin's README (a limit, a size)

[grammar]
repo = "tree-sitter/tree-sitter-go"   # owner/name on GitHub, or a full URL
tag = "latest"                        # the newest v1.2.3 tag, or a tag or branch
dir = "."                             # the folder with the grammar, when it is not the root (php, xml)
generate = false                      # run `tree-sitter generate`; done anyway when src/parser.c is missing
patch = "patches/xml-scanner.patch"   # applied with `patch -p1` in `dir` before building; kept in the README

[query]
files = ["queries/highlights.scm"]    # in the grammar's repository
rename = { "tag" = "type" }           # capture names to change, on top of the old Neovim names the script
                                      # maps itself (conditional, repeat, parameter, ...)
drop = ["\"$\" @operator"]            # patterns that contain this text are left out
before = "..."                        # patterns that go first and so win a tie
after = "..."                         # patterns that go last and only fill in what is left uncolored

[[query.inherit]]                     # queries this grammar builds on, in the order Neovim reads them
repo = "tree-sitter/tree-sitter-javascript"   # (QML builds on JavaScript's and TypeScript's)
files = ["queries/highlights.scm"]
```

## What the script changes in a query

- The patterns are put in the opposite order: the editor takes the first of two patterns on the same text, and the
  grammars' files are written for the last (Neovim, Zed).
- `#lua-match?` and `#vim-match?` become `#match?`; the editor ignores any other predicate it does not know, so its
  pattern would match too much (the script warns). Patterns that need `locals` (`#is-not? local`) are dropped.
- Old capture names become the ones the themes color (`@conditional` is `@keyword.control`, `@parameter` is
  `@variable.parameter`). The script warns about the captures that are still not colored.
- A pattern that names a node, token or field the grammar does not have is dropped (the editor would refuse the whole
  plugin for it), and a list of tokens loses the tokens that are missing. The script says how many.

## What it cannot do

A grammar whose external scanner does something a WebAssembly module cannot (`fprintf`, `exit`) or has a bug needs a
patch written by hand: see `patches/`. Whether the colors look right is for `--check` and your eyes. Two builds of the
same grammar are not byte for byte the same module, so a published version is never rebuilt: a change is a new version.
