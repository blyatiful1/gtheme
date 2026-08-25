#!/usr/bin/env python3
"""Build the committed schema-fixture corpus (DESIGN.md F5).

Every descriptor gtheme ships names a ``(schema_id, key)`` pair, and a test
asserts each one resolves against a *real* schema. Hand-written fixtures would
defeat that test: the point is to catch the case where an add-on renamed a key
and gtheme's descriptor still names the old one. So the fixtures are the real
schema files, downloaded from extensions.gnome.org and committed.

For each curated add-on this fetches the version that extensions.gnome.org
serves for GNOME Shell 50, unpacks ``schemas/*.gschema.xml`` and
``metadata.json`` into ``tests/fixtures/schemas/<uuid>/``, compiles the
schemas, and records provenance in ``MANIFEST.toml``. Add-ons that are also
installed on this machine get a second copy under
``tests/fixtures/schemas-local/<uuid>/`` — the version actually in use here,
which is not always the version the website serves.

Copies from the local extensions directory are strictly read-only.

    ./.venv/bin/python tools/fetch_schema_fixtures.py
    ./.venv/bin/python tools/fetch_schema_fixtures.py --only impatience@gfxmonk.net

A target that cannot be fetched is RECORDED AS A SKIP and does not fail the
run — one flaky download must not cost the other twenty-three.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "schemas"
LOCAL_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "schemas-local"
LOCAL_EXTENSIONS = Path.home() / ".local" / "share" / "gnome-shell" / "extensions"

EGO = "https://extensions.gnome.org"
SHELL_VERSION = "50"
USER_AGENT = "gtheme-fixture-fetcher/2.0 (+https://github.com/blyatiful1/gtheme)"

#: The curated set (DESIGN.md A9), uuid -> extensions.gnome.org pk. Eighteen
#: first-class panels, five second-tier, and compiz-windows-effect promoted in.
#: forge and quick-settings-tweaks are deliberately absent: neither supports
#: GNOME Shell 50, and extensions.gnome.org will happily serve an incompatible
#: zip if asked, so "the download worked" is not evidence of support.
#: gtk4-ding rides along because it shares the ding panel through alt uuids.
TARGETS: dict[str, int] = {
    # -- tier 1
    "blur-my-shell@aunetx": 3193,
    "dash-to-dock@micxgx.gmail.com": 307,
    "just-perfection-desktop@just-perfection": 3843,
    "user-theme@gnome-shell-extensions.gcampax.github.com": 19,
    "caffeine@patapon.info": 517,
    "Vitals@CoreCoding.com": 1460,
    "clipboard-indicator@tudmotu.com": 779,
    "gsconnect@andyholmes.github.io": 1319,
    "appindicatorsupport@rgcjonas.gmail.com": 615,
    "tilingshell@ferrarodomenico.com": 7065,
    "burn-my-windows@schneegans.github.com": 4679,
    "compiz-alike-magic-lamp-effect@hermes83.github.com": 3740,
    "ding@rastersoft.com": 2087,
    "rounded-window-corners@fxgn": 7048,
    "nightthemeswitcher@romainvigier.fr": 2236,
    "space-bar@luchrioh": 5090,
    "tophat@fflewddur.github.io": 5219,
    "logomenu@aryan_k": 4451,
    # -- tier 2
    "dash-to-panel@jderose9.github.com": 1160,
    "arcmenu@arcmenu.com": 3628,
    "hidetopbar@mathieu.bidon.ca": 545,
    "clipboard-history@alexsaveau.dev": 4839,
    "impatience@gfxmonk.net": 277,
    # -- promoted (installed here, 1.02M downloads, a five-control panel)
    "compiz-windows-effect@hermes83.github.com": 3210,
    # -- shares the ding panel through alt uuids
    "gtk4-ding@smedius.gitlab.com": 5263,
}


def _get(url: str, timeout: int = 45) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


def extension_info(uuid: str) -> dict:
    query = urllib.parse.urlencode({"uuid": uuid, "shell_version": SHELL_VERSION})
    return json.loads(_get(f"{EGO}/extension-info/?{query}"))


def extract(archive: zipfile.ZipFile, dest: Path) -> list[str]:
    """Unpack the schema XML and metadata. Returns what was written."""
    written = []
    for name in archive.namelist():
        base = Path(name).name
        if name.endswith("/"):
            continue
        if name == "metadata.json":
            target = dest / "metadata.json"
        elif "schemas/" in name and base.endswith(".gschema.xml"):
            target = dest / "schemas" / base
        else:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(name))
        written.append(str(target.relative_to(dest)))
    return sorted(written)


def compile_schemas(directory: Path) -> str | None:
    """Compile a fixture's ``schemas/`` dir. Returns an error string or None."""
    schemas = directory / "schemas"
    if not schemas.is_dir() or not any(schemas.glob("*.gschema.xml")):
        return "no .gschema.xml in the archive"
    if shutil.which("glib-compile-schemas") is None:
        return "glib-compile-schemas is not installed"
    result = subprocess.run(
        ["glib-compile-schemas", str(schemas)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return f"glib-compile-schemas failed: {result.stderr.strip()}"
    return None


def schema_ids(directory: Path) -> list[str]:
    """Schema ids parsed out of the XML — never from metadata.json.

    Four of the curated add-ons omit ``settings-schema`` entirely and one ships
    its schema in a file named after a different extension, so the XML is the
    only trustworthy source.
    """
    import xml.etree.ElementTree as ET

    ids: set[str] = set()
    for path in sorted((directory / "schemas").glob("*.gschema.xml")):
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        for element in root.iter("schema"):
            schema_id = element.get("id")
            if schema_id:
                ids.add(schema_id)
    return sorted(ids)


def fetch_one(uuid: str, pk: int) -> dict:
    """Fetch one add-on. Returns a manifest record; never raises for network."""
    record: dict = {"uuid": uuid, "pk": pk, "provenance": "ego"}
    try:
        info = extension_info(uuid)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        record["skipped"] = f"extension-info failed: {exc}"
        return record

    version_map = info.get("shell_version_map") or {}
    if SHELL_VERSION not in version_map:
        # e.g.o serves a zip for an unsupported shell without complaining, so
        # the map is the only honest check.
        record["skipped"] = (
            f"no GNOME Shell {SHELL_VERSION} release "
            f"(supports: {', '.join(sorted(version_map)) or 'nothing'})"
        )
        return record

    version_tag = version_map[SHELL_VERSION]["pk"]
    record["version_tag"] = version_tag
    record["version"] = version_map[SHELL_VERSION]["version"]
    record["name"] = info.get("name", "")

    url = f"{EGO}/download-extension/{urllib.parse.quote(uuid)}.shell-extension.zip?version_tag={version_tag}"
    try:
        blob = _get(url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        record["skipped"] = f"download failed: {exc}"
        return record

    record["sha256"] = hashlib.sha256(blob).hexdigest()

    dest = FIXTURES / uuid
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            record["files"] = extract(archive, dest)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(dest, ignore_errors=True)
        record["skipped"] = f"not a zip file: {exc}"
        return record

    error = compile_schemas(dest)
    if error:
        record["compile_error"] = error
    record["schema_ids"] = schema_ids(dest)
    if not record["schema_ids"]:
        record["note"] = "this add-on ships no settings schema"
    return record


def copy_local(uuid: str) -> dict | None:
    """Copy this machine's installed copy, read-only. None if not installed."""
    source = LOCAL_EXTENSIONS / uuid
    if not source.is_dir():
        return None
    dest = LOCAL_FIXTURES / uuid
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    record: dict = {"uuid": uuid, "provenance": "local", "files": []}

    metadata = source / "metadata.json"
    if metadata.is_file():
        shutil.copy2(metadata, dest / "metadata.json")
        record["files"].append("metadata.json")
        try:
            record["version"] = json.loads(metadata.read_text(encoding="utf-8")).get("version")
        except (OSError, json.JSONDecodeError):
            pass

    for xml in sorted((source / "schemas").glob("*.gschema.xml")):
        (dest / "schemas").mkdir(exist_ok=True)
        shutil.copy2(xml, dest / "schemas" / xml.name)
        record["files"].append(f"schemas/{xml.name}")

    if not record["files"]:
        shutil.rmtree(dest, ignore_errors=True)
        return None

    error = compile_schemas(dest)
    if error and "no .gschema.xml" not in error:
        record["compile_error"] = error
    record["schema_ids"] = schema_ids(dest) if (dest / "schemas").is_dir() else []
    record["files"] = sorted(record["files"])
    return record


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def write_manifest(records: list[dict], local_records: list[dict]) -> Path:
    lines = [
        "# GENERATED by tools/fetch_schema_fixtures.py — do not edit by hand.",
        "#",
        "# Provenance for the committed schema corpus. Every descriptor gtheme",
        "# ships is checked against these files, so they are real downloads and",
        "# real local copies, never hand-written approximations.",
        "",
        f'generated = "{dt.datetime.now(dt.UTC).date().isoformat()}"',
        f'shell_version = "{SHELL_VERSION}"',
        f"targets = {len(TARGETS)}",
        f"fetched = {len([r for r in records if 'skipped' not in r])}",
        f"skipped = {len([r for r in records if 'skipped' in r])}",
        f"local_copies = {len(local_records)}",
        "",
    ]
    for record in sorted(records, key=lambda r: r["uuid"].lower()):
        lines.append("[[extension]]")
        for key in (
            "uuid",
            "pk",
            "name",
            "provenance",
            "version",
            "version_tag",
            "sha256",
            "schema_ids",
            "files",
            "note",
            "compile_error",
            "skipped",
        ):
            if key in record:
                lines.append(f"{key} = {_toml_value(record[key])}")
        lines.append("")
    for record in sorted(local_records, key=lambda r: r["uuid"].lower()):
        lines.append("[[local]]")
        for key in ("uuid", "provenance", "version", "schema_ids", "files", "compile_error"):
            if key in record:
                lines.append(f"{key} = {_toml_value(record[key])}")
        lines.append("")

    path = FIXTURES / "MANIFEST.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", help="fetch just this uuid (repeatable)")
    parser.add_argument("--no-local", action="store_true", help="skip the local copies")
    args = parser.parse_args(argv)

    targets = {u: pk for u, pk in TARGETS.items() if not args.only or u in args.only}
    if not targets:
        print("nothing to do", file=sys.stderr)
        return 1

    FIXTURES.mkdir(parents=True, exist_ok=True)
    records, local_records = [], []

    for index, (uuid, pk) in enumerate(targets.items(), 1):
        record = fetch_one(uuid, pk)
        records.append(record)
        if "skipped" in record:
            print(f"[{index}/{len(targets)}] SKIP {uuid}: {record['skipped']}")
        else:
            note = f" ({record['note']})" if "note" in record else ""
            print(
                f"[{index}/{len(targets)}] ok   {uuid} "
                f"v{record.get('version')} tag={record.get('version_tag')} "
                f"schemas={len(record.get('schema_ids', []))}{note}"
            )

        if not args.no_local:
            local = copy_local(uuid)
            if local is not None:
                local_records.append(local)
                print(f"                local copy: {uuid} v{local.get('version')}")

    path = write_manifest(records, local_records)
    fetched = len([r for r in records if "skipped" not in r])
    print(
        f"\n{fetched}/{len(targets)} fetched, {len(targets) - fetched} skipped, "
        f"{len(local_records)} local copies -> {path.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
