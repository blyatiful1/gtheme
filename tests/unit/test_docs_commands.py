"""The commands the documentation tells a person to type have to exist.

Two real defects motivate this file, both found by an outside audit rather than
by anybody using the project:

* the bug-report form asked "Did ``gtheme restore`` recover your desktop?" and
  the theme form said ``gtheme publish <name>`` prints the submission steps.
  Neither command has ever existed — :data:`gtheme.cli._COMMANDS` has three
  entries — so both questions were asked of people at the exact moment they
  were already in trouble;
* the pull-request template asked contributors to run ``gtheme index``, which
  exits 2, and then CI failed them on the index freshness check they believed
  they had just done.

Prose is not tested by the rest of the suite and cannot be. A command in
backticks is not prose: it is an instruction, it is checkable, and this is the
check.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from gtheme.cli import _COMMANDS

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Documents that address a *reader* — the audit reports under ``.audit/`` and
#: the design notes deliberately quote commands that do not exist, because
#: naming them is the finding.
DOC_GLOBS = (
    "README.md",
    "GLOSSARY.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "docs/*.md",
    "themes/*/README.md",
    ".github/*.md",
    ".github/ISSUE_TEMPLATE/*.yml",
)

#: Ways the docs spell "run gtheme", longest first so the venv form is stripped
#: before the bare ``python -m`` one.
_LAUNCHERS = (
    "./.venv/bin/python -m ",
    "python3 -m ",
    "python -m ",
    "./bin/",
    "./",
)

_INLINE_CODE = re.compile(r"`([^`\n]*)`")
_FENCED = re.compile(r"```[a-z]*\n(.*?)```", re.DOTALL)
_SUBCOMMAND = re.compile(r"gtheme\s+([a-z][a-z0-9_-]*)")


def _documents() -> list[Path]:
    found: list[Path] = []
    for glob in DOC_GLOBS:
        found.extend(sorted(REPO_ROOT.glob(glob)))
    return found


def _code_snippets(text: str) -> list[str]:
    """Every inline-code span and every line of every fenced block."""
    snippets = list(_INLINE_CODE.findall(text))
    for block in _FENCED.findall(text):
        snippets.extend(block.splitlines())
    return snippets


def _invoked_subcommands(text: str) -> set[str]:
    """Subcommands the text tells a reader to run.

    Only snippets that *start* with an invocation count. That is what keeps
    prose inside a code comment — ``# gtheme does not interpret these`` in
    docs/preset-format.md — from being read as a command called ``does``.
    """
    found: set[str] = set()
    for snippet in _code_snippets(text):
        candidate = snippet.strip().removeprefix("$ ").strip()
        for launcher in _LAUNCHERS:
            if candidate.startswith(launcher):
                candidate = candidate[len(launcher) :]
                break
        match = _SUBCOMMAND.match(candidate)
        if match:
            found.add(match.group(1))
    return found


@pytest.mark.parametrize("document", _documents(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_documented_gtheme_commands_exist(document: Path) -> None:
    invoked = _invoked_subcommands(document.read_text(encoding="utf-8"))
    unknown = sorted(invoked - set(_COMMANDS))
    assert not unknown, (
        f"{document.relative_to(REPO_ROOT)} tells the reader to run "
        f"{', '.join('gtheme ' + name for name in unknown)}; gtheme has only "
        f"{', '.join(sorted(_COMMANDS))}"
    )


def test_the_documents_were_actually_read() -> None:
    """A glob that matches nothing would make the test above vacuously green."""
    documents = _documents()
    assert len(documents) >= 10
    assert REPO_ROOT / "README.md" in documents
    assert REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml" in documents
    # And the scanner has to find something, or the parse is broken rather than
    # the docs being clean.
    assert "rescue" in _invoked_subcommands((REPO_ROOT / "README.md").read_text(encoding="utf-8"))


# --- what the installer leaves behind --------------------------------------

_RM = re.compile(r'rm -f "([^"]+)"')

#: The shell variables install.sh writes its out-of-folder files through.
_SHELL_VARS = {
    "$TARGET": "~/.local/bin/gtheme",
    "$BIN_DIR": "~/.local/bin",
    "$DATA_HOME": "~/.local/share",
    "$APP_ID": "io.github.blyatiful1.Gtheme",
}


def _installer_removals() -> list[str]:
    """Everything ``install.sh --uninstall`` takes back outside its own folder.

    Read out of the script rather than written down here, so that adding a file
    to the installer and forgetting to tell the README fails this test instead
    of stranding it on somebody's computer.
    """
    text = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    paths = []
    for raw in _RM.findall(text):
        expanded = raw
        for name, value in _SHELL_VARS.items():
            expanded = expanded.replace(name, value)
        if expanded.startswith("~/.local"):
            paths.append(expanded)
    return paths


def test_readme_names_everything_the_installer_puts_outside_its_folder() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    removals = _installer_removals()
    assert len(removals) >= 5, f"expected the five out-of-folder files, parsed {removals}"
    missing = [
        path
        for path in removals
        if path not in readme and str(Path(path).parent) + "/" not in readme
    ]
    assert not missing, (
        "install.sh puts these outside the folder it was unpacked into and the "
        f"README's removal section never names them: {missing}"
    )


def test_readme_offers_the_uninstaller() -> None:
    """The one removal route that refuses to strand a changed desktop."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "./install.sh --uninstall" in readme
