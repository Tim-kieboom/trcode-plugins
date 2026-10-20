#!/usr/bin/env python3
"""Adds a plugin, or a new version of one, to index.json from its GitHub release.

    python3 scripts/add_plugin.py Tim-kieboom/trcode-plugin-git            # the latest release
    python3 scripts/add_plugin.py Tim-kieboom/trcode-plugin-git --tag v0.2.1
    python3 scripts/add_plugin.py you/trcode-plugin-hello --description "Says hello"

The release must have `manifest.toml` and the module the manifest names (`wasm`) as
assets, as the plugins' release workflows publish them; `description.md` is optional.
The entry's fields come from the manifest, the hash is of the module as it is
downloaded, and the result is checked like CI does (`check_index.py --download`).
A version that is listed already is refused: a published version must never change.
"""

import argparse
import hashlib
import json
import os
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

import check_index

ROOT = Path(__file__).resolve().parent.parent


def get(url, what, optional=False):
    """The bytes at `url`; None for a missing optional file."""
    request = urllib.request.Request(url)
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        request.add_header("Authorization", f"Bearer {token}")
    try:
        return urllib.request.urlopen(request, timeout=60).read()
    except urllib.error.HTTPError as error:
        if optional and error.code == 404:
            return None
        sys.exit(f"error: {what}: {url} answered {error.code}")
    except urllib.error.URLError as error:
        sys.exit(f"error: {what}: {url}: {error.reason}")


def latest_tag(repo):
    body = get(f"https://api.github.com/repos/{repo}/releases/latest", "the latest release")
    return json.loads(body)["tag_name"]


def build_entry(repo, tag, args, listed):
    base = f"https://github.com/{repo}/releases/download/{tag}"
    manifest_bytes = get(f"{base}/manifest.toml", "the manifest")
    manifest = tomllib.loads(manifest_bytes.decode("utf-8"))
    for key in ("id", "version", "abi", "wasm"):
        if key not in manifest:
            sys.exit(f"error: the manifest has no `{key}`")
    if tag.lstrip("v") != manifest["version"]:
        sys.exit(f"error: the tag is {tag} but the manifest says {manifest['version']}")

    module = get(f"{base}/{manifest['wasm']}", "the module")
    sha256 = hashlib.sha256(module).hexdigest()

    previous = [e for e in listed if e["id"] == manifest["id"]]
    description = args.description or (previous[-1]["description"] if previous else None)
    if not description:
        sys.exit("error: a new plugin needs --description \"what it is, in one line\"")

    entry = {
        "id": manifest["id"],
        "name": manifest.get("name", manifest["id"]),
        "description": description,
        "version": manifest["version"],
        "manifest": f"{base}/manifest.toml",
        "module": f"{base}/{manifest['wasm']}",
        "sha256": sha256,
        "abi": manifest["abi"],
    }
    if "requires" in manifest:
        entry["requires"] = manifest["requires"]

    # `d` shows description.md when the release has one; else a README, if there is one.
    has_description = get(f"{base}/description.md", "the description", optional=True)
    readme = args.readme
    if readme is None and has_description is None:
        raw = f"https://raw.githubusercontent.com/{repo}/{tag}/README.md"
        if get(raw, "the README", optional=True) is not None:
            readme = raw
    if readme:
        entry["readme"] = readme
    return entry, has_description is not None


def insert(plugins, entry):
    """After the last entry of the same plugin, else at the end."""
    same = [n for n, listed in enumerate(plugins) if listed["id"] == entry["id"]]
    plugins.insert(same[-1] + 1 if same else len(plugins), entry)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("repo", help="owner/name of the plugin's repository")
    parser.add_argument("--tag", help="the release (default: the latest)")
    parser.add_argument("--description", help="one line; the last listed one is kept for a new version")
    parser.add_argument("--readme", help="a link to a README, for a plugin without a description.md")
    parser.add_argument("--index", type=Path, default=ROOT / "index.json")
    parser.add_argument("--dry-run", action="store_true", help="show the entry, change nothing")
    parser.add_argument("--no-download-check", action="store_true", help="skip downloading the module again to check")
    args = parser.parse_args()

    index = json.loads(args.index.read_text(encoding="utf-8"))
    plugins = index.setdefault("plugins", [])
    tag = args.tag or latest_tag(args.repo)

    entry, has_description = build_entry(args.repo, tag, args, plugins)
    if any(e["id"] == entry["id"] and e["version"] == entry["version"] for e in plugins):
        sys.exit(f"error: {entry['id']} {entry['version']} is listed already; a published version never changes (release a new one)")

    verb = "update of" if any(e["id"] == entry["id"] for e in plugins) else "new plugin"
    print(f"{verb} {entry['name']} {entry['version']} (sha256 {entry['sha256'][:16]}…)")
    print(json.dumps(entry, indent=2))
    if not has_description and "readme" not in entry:
        print("note: no description.md and no README: `d` will say there is nothing to show")
    if args.dry_run:
        return

    insert(plugins, entry)
    problems = check_index.problems(index, download=not args.no_download_check)
    if problems:
        for line in problems:
            print(f"error: {line}")
        sys.exit("error: the index was not changed")
    args.index.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print(f"added to {args.index}; commit and push it")


if __name__ == "__main__":
    main()
