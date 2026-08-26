"""Regression tests for the paranoid-review findings in ``gtheme.ego``.

Each test names the finding it pins in its own docstring. Every one of them
fails against the code as it stood before the fix in the same commit.
"""

from __future__ import annotations

import io
import json
import sys
import types
import zipfile

import pytest
from ego_install_test import build, info

from gtheme.ego.client import EgoError, EgoErrorKind, SoupTransport
from gtheme.ego.install import COPY, InstallOutcome, enable_transaction, safe_uuid
from gtheme.ego.models import Rating
from gtheme.ego.updates import stage_update

# -- install.py:217 --------------------------------------------------------


def test_switching_add_ons_on_is_never_dressed_up_as_a_look_switch():
    """Pins finding src/gtheme/ego/install.py:217.

    A transaction that only switches add-ons on used to be handed the Look's
    name as its label. The transaction layer treats a named transaction as a
    Look being applied and tidies away everything the previous Look owns that
    the new one does not list — and this transaction lists nothing but the
    enabled-add-ons setting, so the current Look's wallpaper, icons and fonts
    were stripped off the desktop as a side effect of enabling one add-on.
    Neither the Look name nor a label may reach it.
    """
    transaction = enable_transaction(["a@b"], label="NIGHTBLOOM")
    assert transaction.look is None
    assert transaction.label is None


def test_a_looks_enable_plan_carries_no_look_name_either():
    """Pins finding src/gtheme/ego/install.py:217 through the plan_for_look door."""
    installer, _proxy, _ = build({"a@b": info("a@b")})
    transaction, _missing = installer.plan_for_look(
        [("a@b", "ego", ())], label="NIGHTBLOOM"
    )
    assert transaction.look is None
    assert transaction.label is None


# -- install.py:525 / :526 -------------------------------------------------


def test_an_add_on_that_is_not_here_is_never_reported_as_added():
    """Pins findings src/gtheme/ego/install.py:525 and :526.

    plan_for_look tagged a missing-but-downloadable add-on with the sentence
    "Added. It starts working after you log out and back in." before anything
    had been downloaded. Both no-download paths in the caller show that report
    verbatim, so a person whose download never started was told the add-on had
    been added. The plan-stage sentence must not claim an add-on was added.
    """
    installer, _proxy, _ = build({})
    _transaction, missing = installer.plan_for_look([("ghost@nowhere", "ego", ())])

    assert len(missing) == 1
    report = missing[0]
    # The outcome stays NEEDS_RELOGIN: that is what the caller queues the
    # download on. Only the claim has to go.
    assert report.outcome is InstallOutcome.NEEDS_RELOGIN
    assert report.message != COPY[InstallOutcome.NEEDS_RELOGIN]
    assert "Added" not in report.message
    assert "could not add" in report.message


# -- updates.py:151 --------------------------------------------------------


def test_a_crafted_uuid_cannot_stage_an_update_outside_the_updates_folder(tmp_path):
    """Pins finding src/gtheme/ego/updates.py:151.

    ``destination = root / uuid`` used the uuid unsanitised, so a uuid of ".."
    made the destination the folder *above* the updates folder — which
    stage_update then rmtree'd and replaced. Reproduced before the fix: a file
    living outside the updates folder was destroyed.
    """
    updates = tmp_path / "extension-updates"
    updates.mkdir()
    bystander = tmp_path / "important.txt"
    bystander.write_text("do not delete me")

    # A package that is otherwise perfectly well formed, so the old code got
    # all the way to the rmtree/os.replace at the end rather than stopping at
    # "that is not a package".
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("metadata.json", json.dumps({"name": "evil"}))
        archive.writestr("extension.js", "// nothing")

    with pytest.raises(ValueError):
        stage_update("..", buffer.getvalue(), directory=updates)

    assert bystander.read_text() == "do not delete me"
    assert updates.is_dir()


def test_a_real_add_on_uuid_still_passes_the_gate():
    """Pins finding src/gtheme/ego/updates.py:151 — the gate must not be too tight.

    Every real uuid holds an '@', which ``core.confine.safe_name`` rejects, so
    the ego side needs its own gate rather than borrowing that one.
    """
    assert safe_uuid("blur-my-shell@aunetx") == "blur-my-shell@aunetx"
    for bad in ("", ".", "..", "../evil", "a/b@c", "näme@x"):
        with pytest.raises(ValueError):
            safe_uuid(bad)


# -- models.py:239 ---------------------------------------------------------


def test_a_rating_that_is_not_a_number_is_simply_no_rating():
    """Pins finding src/gtheme/ego/models.py:239.

    ``float(rating)`` was unguarded, so a body with "rating": "n/a" raised
    ValueError out of a main-loop callback with no handler anywhere in the
    chain — the request went silent instead of producing a MALFORMED EgoError.
    A missing rating is not an error; it is no rating.
    """
    assert Rating.from_json({"uuid": "a@b", "id": 1, "rating": "n/a"}).rating is None
    assert Rating.from_json({"uuid": "a@b", "id": 1, "rating": ""}).rating is None
    assert Rating.from_json({"uuid": "a@b", "id": 1, "rating": None}).rating is None
    assert Rating.from_json({"uuid": "a@b", "id": 1, "rating": "4.5"}).rating == 4.5
    assert Rating.from_json({"uuid": "a@b", "id": 1, "rating": "n/a"}).stars is None


# -- client.py:142 ---------------------------------------------------------


def _fake_gi(monkeypatch, *, raises: Exception | None = None):
    """Put a stand-in ``gi`` in place, recording the versions asked for."""
    asked: list[tuple[str, str]] = []

    def require_version(namespace: str, version: str) -> None:
        asked.append((namespace, version))
        if raises is not None:
            raise raises

    gi = types.ModuleType("gi")
    gi.require_version = require_version  # type: ignore[attr-defined]
    repository = types.ModuleType("gi.repository")
    repository.GLib = object()  # type: ignore[attr-defined]
    repository.Soup = object()  # type: ignore[attr-defined]
    gi.repository = repository  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gi", gi)
    monkeypatch.setitem(sys.modules, "gi.repository", repository)
    return asked


def test_the_soup_version_is_pinned_before_the_typelib_is_imported(monkeypatch):
    """Pins finding src/gtheme/ego/client.py:142.

    Without ``gi.require_version`` the loader takes whichever libsoup typelib
    it finds first, and 2.4 ships beside 3.0 nearly everywhere. Under 2.4 the
    Session keyword and send_and_read_async do not exist, and the failure shows
    up as an attribute error inside a callback rather than as a clear answer.
    """
    asked = _fake_gi(monkeypatch)
    SoupTransport()._soup()
    assert ("Soup", "3.0") in asked


@pytest.mark.parametrize(
    "boom", [ValueError("no typelib 3.0"), ImportError("no module named gi")]
)
def test_a_machine_without_libsoup_three_is_told_so_instead_of_crashing(monkeypatch, boom):
    """Pins finding src/gtheme/ego/client.py:142.

    There was no graceful-absence path at all: the bare import raised straight
    out of ``get``/``post_json`` — from a main-loop handler in the real app —
    so the callback was never called and the request hung silently.
    """
    _fake_gi(monkeypatch, raises=boom)
    transport = SoupTransport()

    seen: list[tuple[bytes | None, EgoError | None]] = []
    transport.get("https://example.invalid/x", lambda body, error: seen.append((body, error)))
    transport.post_json(
        "https://example.invalid/y", {}, lambda body, error: seen.append((body, error))
    )

    assert len(seen) == 2
    for body, error in seen:
        assert body is None
        assert isinstance(error, EgoError)
        assert error.kind is EgoErrorKind.NETWORK
        assert "libsoup 3" in str(error)
