#!/usr/bin/env python3
"""Record real e.g.o responses into tests/fixtures/ego/. Read-only GETs + the
documented read-only POST /update-info/ lookup. Run once."""

from __future__ import annotations

import datetime
import hashlib
import json
import urllib.request

OUT = str(__import__("pathlib").Path(__file__).resolve().parent)
BASE = "https://extensions.gnome.org"

GETS = {
    "query-downloads-p1.json": f"{BASE}/extension-query/?shell_version=50&sort=downloads&page=1&n_per_page=25",
    "query-search-blur.json": f"{BASE}/extension-query/?shell_version=50&search=blur&sort=relevance&page=1&n_per_page=5",
    "query-count-probe.json": f"{BASE}/extension-query/?shell_version=50&n_per_page=1&page=1",
    "query-past-end.json": f"{BASE}/extension-query/?shell_version=50&search=blur&page=999&n_per_page=25",
    "info-blur-my-shell.json": f"{BASE}/extension-info/?uuid=blur-my-shell@aunetx&shell_version=50",
    "info-blur-my-shell-noversion.json": f"{BASE}/extension-info/?uuid=blur-my-shell@aunetx",
    "info-adb-bp-incompatible.json": f"{BASE}/extension-info/?pk=4066&shell_version=50",
    "apiv1-blur-my-shell.json": f"{BASE}/api/v1/extensions/blur-my-shell@aunetx/",
    "apiv1-battery-indicator.json": f"{BASE}/api/v1/extensions/battery-indicator@tty.gr/",
    "comments-3193.json": f"{BASE}/comments/all/?pk=3193",
}

POSTS = {
    "update-info.json": (
        f"{BASE}/update-info/?shell_version=50.4&disable_version_validation=false",
        {
            "blur-my-shell@aunetx": {"version": 60},
            "adb_bp@gnome_extensions.github.com": {"version": 1},
            "nonexistent@gtheme.local": {"version": 1},
        },
    )
}

manifest = {}


def write(name, url, body, method):
    path = f"{OUT}/{name}"
    with open(path, "wb") as fh:
        fh.write(body)
    manifest[name] = {
        "url": url,
        "method": method,
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
    }
    print(f"{name}: {len(body)} bytes")


for name, url in GETS.items():
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    parsed = json.loads(raw)
    body = (json.dumps(parsed, indent=2, sort_keys=True) + "\n").encode()
    write(name, url, body, "GET")

for name, (url, payload) in POSTS.items():
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    parsed = json.loads(raw)
    body = (json.dumps(parsed, indent=2, sort_keys=True) + "\n").encode()
    manifest_extra = {"request_body": payload}
    write(name, url, body, "POST")
    manifest[name].update(manifest_extra)

lines = [
    "# Recorded extensions.gnome.org responses. Read-only captures; tests never",
    "# touch the network. Regenerate with tools/fetch_ego_fixtures.py.",
    f'fetched = "{datetime.date.today().isoformat()}"',
    "",
]
for name, meta in manifest.items():
    lines.append(f"[{name.replace('.json', '').replace('-', '_')}]")
    lines.append(f'file = "{name}"')
    lines.append(f'url = "{meta["url"]}"')
    lines.append(f'method = "{meta["method"]}"')
    if "request_body" in meta:
        lines.append("request_body_json = \"\"\"" + json.dumps(meta["request_body"]) + "\"\"\"")
    lines.append(f'sha256 = "{meta["sha256"]}"')
    lines.append(f"bytes = {meta['bytes']}")
    lines.append("")
with open(f"{OUT}/MANIFEST.toml", "w") as fh:
    fh.write("\n".join(lines))
print("manifest written")
