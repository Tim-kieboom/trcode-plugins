#!/usr/bin/env python3
"""Checks index.json the way TerminalCode reads it: the format, every entry's fields,
the hosts the URLs point at and, with --download, that each module has the SHA-256
the entry promises."""

import hashlib
import json
import re
import sys
import urllib.request

FORMAT = 1
ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
VERSION = re.compile(r"^\d+(\.\d+){0,2}$")
HASH = re.compile(r"^[0-9a-f]{64}$")
HOSTS = {
    "github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
REQUIRED = ["id", "name", "version", "manifest", "module", "sha256", "abi"]


def problems(index, download):
    found = []
    if index.get("format") != FORMAT:
        found.append(f"format must be {FORMAT}")
    seen = set()
    for n, entry in enumerate(index.get("plugins", [])):
        name = entry.get("id", f"#{n}")
        for key in REQUIRED:
            if not isinstance(entry.get(key), str) or not entry[key]:
                found.append(f"{name}: `{key}` is missing")
        if found and any(f.startswith(f"{name}:") for f in found):
            continue
        if not ID.match(entry["id"]):
            found.append(f"{name}: the id is not lower case letters, digits, - and _")
        for key in ("version", "abi"):
            if not VERSION.match(entry[key]):
                found.append(f"{name}: `{key}` is not a version such as 1.4")
        if "requires" in entry and not VERSION.match(entry["requires"]):
            found.append(f"{name}: `requires` is not a version such as 0.8.0")
        if not HASH.match(entry["sha256"]):
            found.append(f"{name}: sha256 is not 64 lower case hex digits")
        if "source" in entry:
            found.append(f"{name}: `source` is set by the editor, leave it out")
        for key in ("manifest", "module"):
            url = entry[key]
            host = url.split("/")[2] if url.startswith("https://") else None
            if host not in HOSTS:
                found.append(f"{name}: `{key}` must be an https address of GitHub: {url}")
        pair = (entry["id"], entry["version"])
        if pair in seen:
            found.append(f"{name}: {entry['version']} is listed twice")
        seen.add(pair)
        if download and not found:
            body = urllib.request.urlopen(entry["module"], timeout=60).read()
            actual = hashlib.sha256(body).hexdigest()
            if actual != entry["sha256"]:
                found.append(f"{name} {entry['version']}: the module has sha256 {actual}")
    return found


def main():
    download = "--download" in sys.argv[1:]
    with open("index.json", encoding="utf-8") as file:
        index = json.load(file)
    found = problems(index, download)
    for line in found:
        print(f"error: {line}")
    print(f"{len(index.get('plugins', []))} plugins, {len(found)} problems")
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
