#!/usr/bin/env python3
"""Makes a syntax plugin (a language and no code) from a tree-sitter grammar.

    python3 scripts/make_syntax_plugin.py syntax/go.toml                 # build the plugin folder
    python3 scripts/make_syntax_plugin.py syntax/go.toml --check sample.go --editor ../TerminalCode
    python3 scripts/make_syntax_plugin.py syntax/go.toml --publish       # repo, release, index.json

A spec (see syntax/README.md) names the grammar's repository and tag, the language's name,
extensions, comment marker, description and tags, and what to change in the highlight query.
The script

  1. clones the grammar at its tag (the latest release tag when the spec gives none),
  2. runs `tree-sitter generate` when the repository has no generated parser, applies the spec's
     patch to the grammar, and builds the module with `tree-sitter build --wasm`,
  3. turns the grammar's highlight query into the form TerminalCode wants: the patterns in the
     opposite order (the editor takes the first of two patterns on the same text, the grammars'
     files are written for the last), `#lua-match?` as `#match?`, old capture names as the ones
     the themes have colors for, patterns that need `locals` dropped; and warns about what is
     left that no theme colors,
  4. writes the plugin folder next to this repository (manifest.toml, the module, description.md,
     README.md, the licenses) and commits it,
  5. with --check, loads the plugin the way the editor does and shows which captures color what
     in a sample file, and with --publish creates the GitHub repository, releases the version
     and runs add_plugin.py.

It needs the `tree-sitter` command (and `node` for a grammar that must be generated), `git`
and, to publish, `gh`. The first `tree-sitter build --wasm` downloads the WASI SDK it uses.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import check_index

ROOT = Path(__file__).resolve().parent.parent

# The capture names the default themes have a color for (the `syntax.*` slots of
# TerminalCode's default theme). A capture is styled by its longest prefix that is a slot.
SLOTS = [
    "keyword", "keyword.control", "variable", "namespace", "function", "function.macro", "type",
    "constructor", "string", "escape", "constant", "comment", "operator", "punctuation",
    "property", "attribute", "label", "variable.parameter", "variable.builtin", "number", "float",
    "boolean", "character", "string.escape", "string.special.key", "text.title", "text.literal",
    "text.uri", "text.reference", "text.strong", "text.emphasis",
]

# Capture names from older Neovim query files, as the names the themes know.
LEGACY_NAMES = {
    "conditional": "keyword.control",
    "repeat": "keyword.control",
    "exception": "keyword.control",
    "include": "keyword",
    "storageclass": "keyword",
    "parameter": "variable.parameter",
    "field": "property",
    "keyword.return": "keyword.control",
    "keyword.function": "keyword",
}

# A pattern with one of these cannot work in the editor (it has no `locals` pass), so it goes.
DROP_ALWAYS = ["#is-not? local", "#is? local"]

# Predicates the editor evaluates; any other is ignored, so its pattern matches too much.
KNOWN_PREDICATES = {"match?", "not-match?", "eq?", "not-eq?", "any-of?", "not-any-of?", "set!", "is?", "is-not?"}


def run(cmd, cwd=None, env=None, quiet=False):
    result = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        sys.exit(f"error: `{' '.join(map(str, cmd))}` failed ({result.returncode})")
    if not quiet and result.stdout.strip():
        print(result.stdout.rstrip())
    return result.stdout.strip()


def need(program, hint):
    if shutil.which(program) is None:
        sys.exit(f"error: `{program}` is not on the PATH ({hint})")


# --- the query -------------------------------------------------------------------------------


def split_patterns(text):
    """The top-level patterns of a query, each with the comments written before it."""
    i, n = 0, len(text)
    patterns, start = [], 0
    capture = re.compile(r"[ \t]*[?*+]?[ \t]*@[\w.\-]+")
    quantifier = re.compile(r"[ \t]*[?*+](?![\w])")
    while i < n:
        while i < n and (text[i].isspace() or text[i] == ";"):
            if text[i] == ";":
                while i < n and text[i] != "\n":
                    i += 1
            else:
                i += 1
        if i >= n:
            break
        c = text[i]
        if c in "([":
            depth = 0
            while i < n:
                ch = text[i]
                if ch == '"':
                    i += 1
                    while i < n and text[i] != '"':
                        i += 2 if text[i] == "\\" else 1
                elif ch == ";":
                    while i < n and text[i] != "\n":
                        i += 1
                    continue
                elif ch in "([":
                    depth += 1
                elif ch in ")]":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
        elif c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            i += 1
        elif c == "@" or c.isalpha() or c in "_.":
            while i < n and text[i] != "\n":
                i += 1
        else:
            i += 1
            continue
        while True:
            m = capture.match(text, i) or quantifier.match(text, i)
            if not m:
                break
            i = m.end()
        patterns.append(text[start:i].strip("\n"))
        start = i
    return patterns


def node_vocabulary(folder):
    """The named nodes, anonymous tokens and fields a grammar has (its src/node-types.json)."""
    path = folder / "src" / "node-types.json"
    if not path.exists():
        return None
    named, anonymous, fields = set(), set(), set()

    def visit(node):
        (named if node.get("named") else anonymous).add(node["type"])
        fields.update(node.get("fields", {}))
        for child in [*node.get("subtypes", []), *node.get("children", {}).get("types", [])]:
            (named if child.get("named") else anonymous).add(child["type"])
        for field in node.get("fields", {}).values():
            for child in field.get("types", []):
                (named if child.get("named") else anonymous).add(child["type"])

    import json
    for node in json.loads(path.read_text()):
        visit(node)
    return named, anonymous, fields


STRING = re.compile(r'"(?:[^"\\\n]|\\.)*"')


def strip_predicates(pattern):
    """The pattern without its `(#eq? ...)` groups and comments, to read the nodes it names."""
    out, i, n = [], 0, len(pattern)
    while i < n:
        if pattern[i] == ";":
            while i < n and pattern[i] != "\n":
                i += 1
        elif pattern.startswith("(#", i):
            depth = 0
            while i < n:
                if pattern[i] == '"':
                    m = STRING.match(pattern, i)
                    i = m.end() if m else i + 1
                    continue
                depth += pattern[i] == "("
                depth -= pattern[i] == ")"
                i += 1
                if depth == 0:
                    break
        else:
            out.append(pattern[i])
            i += 1
    return "".join(out)


ESCAPES = {"n": "\n", "t": "\t", "r": "\r"}


def token_text(quoted):
    """The text of a quoted query token, as the grammar's node-types.json has it."""
    return re.sub(r"\\(.)", lambda m: ESCAPES.get(m.group(1), m.group(1)), quoted[1:-1])


def fit_to_grammar(pattern, vocabulary):
    """The pattern, trimmed to what the grammar has; None when it cannot work."""
    named, anonymous, fields = vocabulary
    named = named | {"ERROR", "MISSING"}
    body = strip_predicates(pattern)
    tokens = STRING.findall(body)
    if re.match(r"\s*\[\s*(?:" + STRING.pattern + r"\s*)+\]", body):
        # a list of tokens: keep the ones the grammar has
        keep = [t for t in tokens if token_text(t) in anonymous]
        if not keep:
            return None
        for t in tokens:
            if t not in keep:
                pattern = pattern.replace(t, "", 1)
        return pattern
    if any(token_text(t) not in anonymous for t in tokens):
        return None
    code = STRING.sub('""', body)
    if any(name not in named for name in re.findall(r"\(\s*([A-Za-z]\w*)", code)):
        return None
    if any(field not in fields for field in re.findall(r"(?<![\w@.#])!?([a-z_]\w*)\s*:", code)):
        return None
    return pattern


def convert_query(texts, spec_query, vocabulary):
    """The manifest's `highlights` text, and the notes about what was changed or is not colored.

    `texts` are in the order a Neovim query reads them (the last pattern wins); the result is in
    the order the editor reads (the first wins)."""
    rename = {**LEGACY_NAMES, **spec_query.get("rename", {})}
    drop = DROP_ALWAYS + spec_query.get("drop", [])
    patterns = []
    for text in texts:
        patterns += [p.strip() for p in split_patterns(text) if p.strip()]
    patterns = [p for p in patterns if not any(d in p for d in drop)]
    notes, unusable, trimmed = [], [], 0
    converted = []
    for pattern in reversed(patterns):
        pattern = pattern.replace("#lua-match?", "#match?").replace("#vim-match?", "#match?")
        for old, new in rename.items():
            pattern = re.sub(r"@" + re.escape(old) + r"(?![\w.\-])", "@" + new, pattern)
        if vocabulary:
            fitted = fit_to_grammar(pattern, vocabulary)
            if fitted is None:
                unusable.append(pattern)
                continue
            trimmed += fitted != pattern
            pattern = fitted
        converted.append(pattern)
    if unusable:
        first = "; ".join(" ".join(p.split())[:60] for p in unusable[:4])
        notes.append(f"{len(unusable)} patterns name nodes the grammar does not have and were left out (for example {first})")
    if trimmed:
        notes.append(f"{trimmed} token lists had tokens the grammar does not have; those were removed")
    body = "\n\n".join(p for p in [spec_query.get("before", "").strip(), *converted, spec_query.get("after", "").strip()] if p)
    if "'''" in body:
        sys.exit("error: the query has ''' in it, which a TOML literal string cannot hold")
    return body, notes + query_warnings(body)


def styled(capture):
    while capture:
        if capture in SLOTS:
            return True
        capture = capture.rpartition(".")[0]
    return False


def query_warnings(body):
    code = re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', re.sub(r";[^\n]*", "", body))
    warnings = []
    unstyled = sorted({c for c in re.findall(r"@([\w.\-]+)", code) if not styled(c) and not c.startswith(("_", "injection", "local"))})
    if unstyled:
        warnings.append("captures no theme colors (left out by the editor): " + ", ".join("@" + c for c in unstyled))
    unknown = sorted({p for p in re.findall(r"\(#([\w\-]+[?!])", code) if p not in KNOWN_PREDICATES})
    if unknown:
        warnings.append("predicates the editor ignores (their patterns match too much): " + ", ".join("#" + p for p in unknown))
    return warnings


# --- the grammar -----------------------------------------------------------------------------


def latest_tag(url):
    out = run(["git", "ls-remote", "--tags", "--refs", url], quiet=True)
    tags = []
    for line in out.splitlines():
        name = line.split("refs/tags/", 1)[1]
        m = re.fullmatch(r"v?(\d+)\.(\d+)(?:\.(\d+))?", name)
        if m:
            tags.append((tuple(int(g or 0) for g in m.groups()), name))
    if not tags:
        sys.exit(f"error: {url} has no release tags like v1.2.3; set `tag` in the spec")
    return max(tags)[1]


def fetch_grammar(grammar, dest):
    repo = grammar["repo"]
    url = repo if "://" in repo else f"https://github.com/{repo}"
    tag = grammar.get("tag", "latest")
    if tag == "latest":
        tag = latest_tag(url)
    run(["git", "clone", "-q", "--depth", "1", "--branch", tag, url, str(dest)], quiet=True)
    commit = run(["git", "-C", str(dest), "rev-parse", "--short", "HEAD"], quiet=True)
    return dest, url, tag, commit


def build_module(root, grammar, spec_dir, module):
    need("tree-sitter", "install the tree-sitter CLI, for example `nix shell nixpkgs#tree-sitter` or `cargo install tree-sitter-cli`")
    folder = root / grammar.get("dir", ".")
    generated = bool(grammar.get("generate")) or not (folder / "src" / "parser.c").exists()
    if generated:
        need("node", "this grammar has no generated parser, and `tree-sitter generate` needs node")
        print("tree-sitter generate")
        run(["tree-sitter", "generate"], cwd=folder, quiet=True)
    if "patch" in grammar:
        patch = (spec_dir / grammar["patch"]).resolve()
        print(f"patch {patch.name}")
        run(["patch", "-p1", "--no-backup-if-mismatch", "-i", str(patch)], cwd=folder, quiet=True)
    print("tree-sitter build --wasm")
    run(["tree-sitter", "build", "--wasm", "-o", str(module)], cwd=folder, quiet=True)
    return generated, folder


# --- the plugin folder -----------------------------------------------------------------------


def grammar_entry(folder):
    """The `<name>` of `tree_sitter_<name>` in the generated parser (the manifest's `grammar_name`)."""
    parser = folder / "src" / "parser.c"
    found = re.findall(r"TSLanguage \*tree_sitter_(\w+)\(void\)", parser.read_text(errors="replace")) if parser.exists() else []
    return found[-1] if found else None


def license_name(text):
    if "Apache License" in text:
        return "Apache-2.0"
    if "MIT License" in text or "Permission is hereby granted" in text:
        return "MIT"
    return "see `LICENSE-GRAMMAR`"


def toml_string(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_plugin(dest, spec, generated, repo_root, module, url, tag, commit, body, version, sources):
    dest.mkdir(parents=True, exist_ok=True)
    key = spec["id"].removesuffix("-syntax")
    module_file = spec.get("module", f"{key}.wasm")
    shutil.copy(module, dest / module_file)
    os.chmod(dest / module_file, 0o755)
    for name in ("LICENSE-APACHE", "LICENSE-MIT"):
        shutil.copy(ROOT / name, dest / name)
    license_file = next((repo_root / n for n in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING") if (repo_root / n).exists()), None)
    if license_file is None:
        sys.exit("error: the grammar's repository has no LICENSE file; the plugin must carry its license")
    shutil.copy(license_file, dest / "LICENSE-GRAMMAR")
    licence = license_name(license_file.read_text(errors="replace"))
    (dest / ".gitignore").write_text("target\n")

    name = spec["name"]
    exts = ", ".join(toml_string(e) for e in spec["extensions"])
    comment = spec.get("comment")
    head = f"""id = {toml_string(spec['id'])}
name = {toml_string(name)}
version = {toml_string(version)}
abi = "1.12"
"""
    if spec.get("tags"):
        head += "tags = [" + ", ".join(toml_string(t) for t in spec["tags"]) + "]\n"
    head += f"""# A language and nothing else: no module of its own and no pane. The grammar is the file the
# installer downloads and checks.

[language]
name = {toml_string(name)}
grammar = {toml_string(module_file)}
extensions = [{exts}]
"""
    if comment:
        head += f"comment = {toml_string(comment)}\n"
    if spec.get("entry"):
        head += f"grammar_name = {toml_string(spec['entry'])}\n"
    query_files = spec.get("query", {}).get("files", ["queries/highlights.scm"])
    owner_repo = url.removeprefix("https://github.com/")
    own = f"{', '.join(query_files)} of {url}, {tag} ({commit})"
    if sources:
        head += f"# The query is the grammar's own ({own}), with what it builds on: " + "; ".join(sources) + ".\n"
        head += "# Patterns that name nodes this grammar does not have were left out.\n"
    else:
        head += f"# The query is the grammar's own ({own}).\n"
    head += f"""\
# The patterns are in the opposite order of the grammar's file: TerminalCode takes the first of two
# patterns on the same text, and that file is written for the last (as Neovim and Zed take it).
highlights = '''
{body}
'''
"""
    (dest / "manifest.toml").write_text(head)

    shown = ", ".join(f"`.{e}`" for e in spec["extensions"])
    (dest / "description.md").write_text(f"""# {name}

Syntax highlighting for {name} files ({shown}), in the colors of your theme. It is the tree-sitter grammar of {name} and its query, with no code.

Needs a TerminalCode that has plugin API 1.12 (0.11.0 or later).
""")

    grammar = spec["grammar"]
    steps = [f"git clone {url} && cd {url.rstrip('/').split('/')[-1]}", f"git checkout {tag}"]
    if grammar.get("dir", ".") != ".":
        steps.append(f"cd {grammar['dir']}")
    if generated:
        steps.append("tree-sitter generate")
    if "patch" in grammar:
        steps.append("patch -p1 < the-patch-below.patch")
    steps.append(f"tree-sitter build --wasm -o {module_file}")
    notes = spec.get("readme_notes", "").strip()
    if sources:
        listed = "\n".join(f"- {source}" for source in sources)
        notes = (notes + "\n\n" if notes else "") + f"The grammar's own query only covers what it adds, so the highlight query also holds these (MIT), which it builds on:\n\n{listed}\n\nPatterns of them that name nodes this grammar does not have were left out."
    if "patch" in grammar:
        patch_text = (Path(spec["_dir"]) / grammar["patch"]).read_text()
        notes = (notes + "\n\n" if notes else "") + (
            "The grammar is changed before it is built, with this patch to its sources:\n\n```diff\n" + patch_text.rstrip() + "\n```"
        )
    (dest / "README.md").write_text(f"""# {name} syntax for TerminalCode

Syntax highlighting for {name} ({shown}) as a [TerminalCode](https://github.com/Tim-kieboom/TerminalCode) plugin.

It is a language and nothing else: there is no code in it and no pane. The plugin is

- `{module_file}`, the tree-sitter grammar built for WebAssembly,
- `manifest.toml`, which says which files are {name} (`[language]`: `extensions`, `comment`) and has the
  highlight query as text.

TerminalCode loads the grammar in its sandbox (plugin API 1.12, TerminalCode 0.11.0 or later) and colors the
files with the query, using the colors of your theme (`syntax.keyword`, `syntax.string`, ... in the theme file).

## Use

"Plugins: Manage", install **{name}**, and turn it on. {name} files are colored when they are opened{', and `ctrl+/` comments a line with `' + comment + '`' if comment else ''}.

## Where the grammar comes from

The grammar and the query are those of [{owner_repo}]({url}) at {tag} ({commit})
({licence}, `LICENSE-GRAMMAR`). The module was built from that revision with the tree-sitter CLI:

```sh
{chr(10).join(steps)}
```

{notes + chr(10) + chr(10) if notes else ''}A new version of the grammar needs a new `version` in `manifest.toml` and a release (the module is the file the
installer checks). The query is copied into the manifest with its patterns in the opposite order (TerminalCode takes the first of two patterns on the same text; the grammar's file is written for the last).
This plugin is made by `scripts/make_syntax_plugin.py` of [trcode-plugins](https://github.com/Tim-kieboom/trcode-plugins) from `syntax/{key}.toml`.

## Licence

The plugin is MIT or Apache-2.0, as the other plugins; the grammar is {licence} (`LICENSE-GRAMMAR`).
""")


def commit_plugin(dest, spec, version):
    if not (dest / ".git").exists():
        run(["git", "init", "-q", "-b", "main"], cwd=dest, quiet=True)
    run(["git", "add", "-A"], cwd=dest, quiet=True)
    if not run(["git", "status", "--porcelain"], cwd=dest, quiet=True):
        print("nothing changed, nothing to commit")
        return
    has_commits = subprocess.run(["git", "rev-parse", "-q", "--verify", "HEAD"], cwd=dest, capture_output=True).returncode == 0
    what = f"{spec['id']} {version}: the tree-sitter grammar and query" if has_commits else f"{spec['id']}: the tree-sitter grammar and query as a plugin"
    run(["git", "commit", "-q", "-m", what], cwd=dest, quiet=True)
    print(f"committed: {what}")


# --- the check, through the editor's own loader ----------------------------------------------

HARNESS = r'''//! Written by make_syntax_plugin.py --check, and removed again.
use ropey::Rope;
use super::TestTheme;
use crate::{Highlighter, Language, LanguageSpec, register_language};

const SLOTS: &[&str] = &[%SLOTS%];

#[test]
#[ignore]
fn zz_check_plugin() {
    let dir = std::path::PathBuf::from(std::env::var("CHK_DIR").unwrap());
    let sample = std::fs::read_to_string(std::env::var("CHK_SAMPLE").unwrap()).unwrap();
    let manifest: toml::Table = std::fs::read_to_string(dir.join("manifest.toml")).unwrap().parse().unwrap();
    let lang = manifest["language"].as_table().unwrap();
    let name = lang["name"].as_str().unwrap().to_owned();
    let entry = lang.get("grammar_name").and_then(|v| v.as_str()).map(str::to_owned).unwrap_or(name.to_lowercase());
    let exts: Vec<String> = lang["extensions"].as_array().unwrap().iter().map(|v| v.as_str().unwrap().to_owned()).collect();
    let spec = LanguageSpec {
        name: name.clone(),
        extensions: exts.clone(),
        comment: lang.get("comment").and_then(|v| v.as_str()).map(str::to_owned),
        entry,
        grammar: std::fs::read(dir.join(lang["grammar"].as_str().unwrap())).unwrap(),
        highlights: lang["highlights"].as_str().unwrap().to_owned(),
        injections: lang.get("injections").and_then(|v| v.as_str()).unwrap_or("").to_owned(),
    };
    let started = std::time::Instant::now();
    register_language("chk", spec).unwrap();
    println!("registered in {:?}", started.elapsed());
    let language = Language::from_path(std::path::Path::new(&format!("a.{}", exts[0]))).unwrap();
    let mut theme = String::new();
    for (i, slot) in SLOTS.iter().enumerate() {
        theme.push_str(&format!("[\"syntax.{slot}\"]\ntext = \"#{:02x}0000\"\n", i + 1));
    }
    let started = std::time::Instant::now();
    let mut highlighter = Highlighter::new(language, &TestTheme::from_toml(&theme)).unwrap();
    println!("highlighter made in {:?}", started.elapsed());
    let text = Rope::from_str(&sample);
    highlighter.parse(&text).expect("the sample parses");
    let spans = highlighter.spans(&text, 0..sample.len());
    println!("{} spans", spans.len());
    let mut seen = std::collections::BTreeMap::new();
    for span in spans.iter() {
        let slot = match span.style.fg {
            Some(ratatui::style::Color::Rgb(r, _, _)) => SLOTS[r as usize - 1].to_string(),
            other => format!("{other:?}"),
        };
        seen.entry(slot).or_insert_with(Vec::new).push(sample[span.range.clone()].to_owned());
    }
    for (slot, words) in seen {
        let words: Vec<_> = words.into_iter().take(14).collect();
        println!("{slot}: {words:?}");
    }
}
'''


def check_plugin(dest, sample, editor):
    """Loads the plugin through the syntax crate of the editor at `editor`, as the editor does."""
    crate = editor / "crates" / "syntax"
    tests = crate / "src" / "tests"
    mod = tests / "mod.rs"
    if not mod.exists():
        sys.exit(f"error: {editor} has no crates/syntax/src/tests/mod.rs; --editor is the TerminalCode repository")
    original = mod.read_text()
    harness = tests / "zz_check.rs"
    harness.write_text(HARNESS.replace("%SLOTS%", ", ".join(f'"{s}"' for s in SLOTS)))
    mod.write_text(original.rstrip("\n") + "\nmod zz_check;\n")
    env = dict(os.environ, CHK_DIR=str(dest), CHK_SAMPLE=str(Path(sample).resolve()))
    if os.environ.get("TRCODE_CHECK_TARGET"):
        env["CARGO_TARGET_DIR"] = os.environ["TRCODE_CHECK_TARGET"]
    try:
        result = subprocess.run(
            ["cargo", "test", "-p", "trcode-syntax", "--release", "zz_check_plugin", "--", "--ignored", "--nocapture"],
            cwd=editor, env=env, text=True, capture_output=True,
        )
    finally:
        mod.write_text(original)
        harness.unlink(missing_ok=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout[-3000:] + result.stderr[-3000:])
        sys.exit("error: the editor could not load the plugin or parse the sample (above)")
    for line in result.stdout.splitlines():
        if not line.startswith(("running", "test ", "test result")) and line.strip():
            print(line[:240])


# --- publishing ------------------------------------------------------------------------------


def publish(dest, spec, version):
    need("gh", "https://cli.github.com")
    repo = f"Tim-kieboom/trcode-plugin-{spec['id']}"
    manifest = tomllib.loads((dest / "manifest.toml").read_text())
    module = manifest["language"]["grammar"]
    shown = ", ".join("." + e for e in spec["extensions"])
    exists = subprocess.run(["gh", "repo", "view", repo], capture_output=True).returncode == 0
    if not exists:
        run(["gh", "repo", "create", repo, "--public", "--description",
             f"{spec['name']} syntax highlighting for TerminalCode: the tree-sitter grammar and query, as a plugin",
             "--source", str(dest), "--remote", "origin", "--push"])
    else:
        if subprocess.run(["git", "remote", "get-url", "origin"], cwd=dest, capture_output=True).returncode != 0:
            run(["git", "remote", "add", "origin", f"https://github.com/{repo}.git"], cwd=dest)
        run(["git", "push", "-u", "origin", "main"], cwd=dest)
    tag = f"v{version}"
    run(["git", "tag", tag], cwd=dest, quiet=True)
    run(["git", "push", "origin", tag], cwd=dest, quiet=True)
    run(["gh", "release", "create", tag, "manifest.toml", module, "description.md", "-R", repo, "--title", tag,
         "--notes", f"{spec['name']} ({shown}) syntax highlighting: the tree-sitter grammar and query. Needs plugin API 1.12 (TerminalCode 0.11.0)."],
        cwd=dest)
    description = spec.get("description") or f"Syntax highlighting for {spec['name']}"
    run([sys.executable, str(ROOT / "scripts" / "add_plugin.py"), repo, "--tag", tag,
         "--description", f"{description} ({shown}): the tree-sitter grammar and query; a language and no code"])
    print(f"index.json changed: commit and push it in {ROOT}")


# --- main ------------------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("spec", type=Path, help="the spec, a TOML file such as syntax/go.toml")
    parser.add_argument("--out", type=Path, help="where the plugin folder goes (default: trcode-plugin-<id> next to this repository)")
    parser.add_argument("--version", help="the plugin's version (default: the spec's, else 0.0.1)")
    parser.add_argument("--no-commit", action="store_true", help="write the folder, commit nothing")
    parser.add_argument("--check", metavar="SAMPLE", help="a source file to highlight through the editor's loader")
    parser.add_argument("--editor", type=Path, default=ROOT.parent / "TerminalCode", help="the TerminalCode repository, for --check")
    parser.add_argument("--publish-only", action="store_true", help="publish the folder as it is committed: no build, no changes")
    parser.add_argument("--publish", action="store_true", help="create the GitHub repository, release the version, add it to index.json")
    args = parser.parse_args()

    spec = tomllib.loads(args.spec.read_text(encoding="utf-8"))
    spec["_dir"] = str(args.spec.resolve().parent)
    for key in ("name", "extensions", "grammar"):
        if key not in spec:
            sys.exit(f"error: the spec has no `{key}`")
    if "repo" not in spec["grammar"]:
        sys.exit("error: the spec's [grammar] has no `repo`")
    spec.setdefault("id", args.spec.stem + "-syntax")
    version = args.version or spec.get("version", "0.0.1")
    unknown = [t for t in spec.get("tags", []) if t not in check_index.TAGS]
    if unknown:
        print(f"note: the editor does not know the tags {', '.join(unknown)} yet and leaves them out of its search; "
              f"a new tag needs an editor release (src/plugins/tags.rs) and an entry in scripts/check_index.py")
    dest = (args.out or ROOT.parent / f"trcode-plugin-{spec['id']}").resolve()

    if args.publish_only:
        if not (dest / "manifest.toml").exists():
            sys.exit(f"error: {dest} has no plugin to publish; build it first")
        if run(["git", "status", "--porcelain"], cwd=dest, quiet=True):
            sys.exit(f"error: {dest} has changes that are not committed")
        publish(dest, spec, tomllib.loads((dest / "manifest.toml").read_text())["version"])
        return

    with tempfile.TemporaryDirectory(prefix="make-syntax-") as tmp:
        work = Path(tmp)
        repo_root, url, tag, commit = fetch_grammar(spec["grammar"], work / "grammar")
        print(f"{url} {tag} ({commit})")
        module = work / "module.wasm"
        generated, folder = build_module(repo_root, spec["grammar"], args.spec.resolve().parent, module)
        entry = grammar_entry(folder)
        if entry and entry != spec["name"].lower() and "entry" not in spec:
            spec["entry"] = entry
            print(f"the grammar's entry is tree_sitter_{entry}")
        spec_query = spec.get("query", {})
        files = spec_query.get("files", ["queries/highlights.scm"])
        texts, sources = [], []
        for number, inherited in enumerate(spec_query.get("inherit", [])):
            other, other_url, other_tag, other_commit = fetch_grammar(inherited, work / f"inherit{number}")
            for name in inherited.get("files", ["queries/highlights.scm"]):
                texts.append((other / name).read_text(encoding="utf-8"))
                sources.append(f"{name} of {other_url}, {other_tag} ({other_commit})")
            print(f"inherits {other_url} {other_tag} ({other_commit})")
        for name in files:
            path = repo_root / name
            if not path.exists():
                sys.exit(f"error: the grammar has no {name}; set [query] files in the spec")
            texts.append(path.read_text(encoding="utf-8"))
        body, warnings = convert_query(texts, spec_query, node_vocabulary(folder))
        for warning in warnings:
            print(f"warning: {warning}")
        write_plugin(dest, spec, generated, repo_root, module, url, tag, commit, body, version, sources)
    print(f"wrote {dest}")

    if args.check:
        check_plugin(dest, args.check, args.editor.resolve())
    if not args.no_commit:
        commit_plugin(dest, spec, version)
    if args.publish:
        if args.no_commit:
            sys.exit("error: --publish needs the commit")
        publish(dest, spec, version)


if __name__ == "__main__":
    main()
