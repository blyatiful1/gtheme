"""What the Look preview has to say before anything is downloaded or applied.

Three findings, one dialog. Each of them is a promise the app made somewhere in
writing and then did not keep in the one place it mattered — the box that opens
when somebody clicks a Look.

* **H6** — "This Look uses 3 add-ons you don't have." and a button that
  downloads three pieces of somebody else's code. A count is not something
  anybody can accept or refuse; which three they are is the whole question, and
  on this path the desktop shows no confirmation box of its own, so this dialog
  is the only place it can be asked.
* **U6 (values)** — all four Looks gtheme shipped first set the icon set to
  ``Papirus-Dark`` and none of them ships an icon set. The write succeeds
  because the *setting* exists; the desktop falls back, and nobody is told.
  ``scan_font_families`` had no caller anywhere in the application.
* **U6 (either/or and accessibility)** — the Add-ons page offers to switch one
  of a colliding pair off; the Look path never consulted the table, so a Look
  bringing a dock left an Ubuntu desktop with two. And a Look that writes over
  high contrast, larger text or reduced movement said nothing at all.

Marked ``gtk``: the page module imports libadwaita. Nothing is presented — the
dialog bodies are read off the objects — and every setting read goes to an
in-memory store.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the Looks page")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.core.backends import use_backend  # noqa: E402
from gtheme.core.settings_backend import MemoryBackend  # noqa: E402
from gtheme.preset.compile import Available, value_warnings  # noqa: E402
from gtheme.preset.loader import load  # noqa: E402
from gtheme.ui.pages import looks  # noqa: E402

pytestmark = pytest.mark.gtk


@pytest.fixture(autouse=True, scope="module")
def _adw():
    if not Gtk.init_check():
        pytest.skip("no display is available for GTK — run under gtk4-broadwayd")
    Adw.init()


@pytest.fixture
def backend():
    with use_backend(MemoryBackend()) as memory:
        yield memory


THEME = """
format = 2

[meta]
name = "{name}"
title = "{title}"
description = "A Look written by a test."
author = "tests"
version = "1.0.0"

[palette]
bg = "#101010"
accent = "#52E0A4"

{body}
"""


def write_look(directory: Path, *, name="testlook", title="Test Look", body="") -> Path:
    folder = directory / name
    folder.mkdir(parents=True)
    (folder / "theme.toml").write_text(
        THEME.format(name=name, title=title, body=body), encoding="utf-8"
    )
    return folder


def a_tile(directory: Path, **kwargs) -> looks.LookTile:
    return looks.tiles_from_results([load(write_look(directory, **kwargs))])[0]


# ── H6: the add-ons are named, not counted ────────────────────────────────

WANTS_ADDONS = """
[extensions]
enable = ["blur-my-shell@aunetx", "dash-to-dock@micxgx.gmail.com"]
"""


def test_the_preview_names_every_add_on_it_would_download(tmp_path, backend):
    """Fails on the old code: the body held the count and nothing else."""
    tile = a_tile(tmp_path, body=WANTS_ADDONS)

    plan = looks.plan_apply(tile, installed=[], enabled=[])

    assert plan.missing_addons == 2
    assert len(plan.addon_lines) == 2
    body = plan.body()
    for line in plan.addon_lines:
        assert line in body, "a name that is not in the body is not a name anybody read"
    assert "Blur my shell" in body
    assert "Dash to dock" in body


def test_the_names_are_readable_and_say_where_they_come_from(tmp_path, backend):
    """No identifiers on screen, and the address is part of the offer."""
    tile = a_tile(tmp_path, body=WANTS_ADDONS)

    plan = looks.plan_apply(tile, installed=[], enabled=[])

    assert "extensions.gnome.org" in plan.body()
    assert "@aunetx" not in plan.body(), "an add-on's internal name is not for the screen"


def test_naming_them_needs_nothing_from_the_network(tmp_path, backend, monkeypatch):
    """The dialog opens the same with the connection pulled out.

    ``plan_apply`` is a pure function over what is on this computer; anything
    that reached the add-on library from inside it would make the preview of a
    Look fail, or hang, when the machine is offline.
    """
    import gtheme.ego.client as client_module

    def refuse(*_args, **_kwargs):
        raise AssertionError("the preview asked the network for something")

    monkeypatch.setattr(client_module, "SoupTransport", refuse)
    tile = a_tile(tmp_path, body=WANTS_ADDONS)

    plan = looks.plan_apply(tile, installed=[], enabled=[])

    assert plan.addon_lines


# ── U6: the values a Look asks for are checked against this computer ───────

WANTS_PAPIRUS = """
[[settings]]
key = "gsettings:org.gnome.desktop.interface icon-theme"
value = "'Papirus-Dark'"
component = "icons"

[[settings]]
key = "gsettings:org.gnome.desktop.interface font-name"
value = "'Rajdhani Medium 11'"
component = "fonts"
"""


def test_a_look_asking_for_an_icon_set_that_is_not_here_says_so(tmp_path, backend):
    """Fails on the old code: nothing ever validated a value."""
    tile = a_tile(tmp_path, body=WANTS_PAPIRUS)
    here = Available(icon_themes=frozenset({"Adwaita"}), fonts=frozenset({"Rajdhani"}))

    plan = looks.plan_apply(tile, installed=[], enabled=[], available=here)

    said = "\n".join(plan.warnings)
    assert "Papirus-Dark" in said
    assert "papirus-icon-theme" in said, "name the package, or the sentence is a shrug"
    assert "Rajdhani" not in said, "an installed family must not be reported missing"
    assert said in plan.body() or "Papirus-Dark" in plan.body()


def test_nothing_is_claimed_about_values_that_were_never_measured(tmp_path, backend):
    """"Not measured" and "not installed" are different answers."""
    tile = a_tile(tmp_path, body=WANTS_PAPIRUS)

    plan = looks.plan_apply(tile, installed=[], enabled=[], available=None)

    assert not [line for line in plan.warnings if "Papirus" in line]


def test_a_font_is_matched_on_its_family_and_not_on_its_size():
    """"Adwaita Sans 11" is the family "Adwaita Sans" with a size after it."""
    preset = load(
        write_look(
            Path(_a_tmp()),
            body=(
                '[[settings]]\nkey = "gsettings:org.gnome.desktop.interface font-name"\n'
                "value = \"'Adwaita Sans 11'\"\ncomponent = \"fonts\"\n"
            ),
        )
    ).preset
    assert value_warnings(preset, Available(fonts=frozenset({"Adwaita Sans"}))) == []
    assert value_warnings(preset, Available(fonts=frozenset({"Cantarell"})))


def _a_tmp() -> str:
    import tempfile

    return tempfile.mkdtemp(prefix="gtheme-fonts-")


# ── U6: two add-ons doing the same job, and the settings you see with ──────

BRINGS_A_SECOND_DOCK = """
[extensions]
enable = ["dash-to-dock@micxgx.gmail.com"]
"""


def test_a_look_that_brings_a_second_dock_says_so_before_it_is_applied(tmp_path, backend):
    """The Add-ons page has always asked this question; the Look path never did."""
    tile = a_tile(tmp_path, body=BRINGS_A_SECOND_DOCK)

    plan = looks.plan_apply(
        tile,
        installed=["dash-to-dock@micxgx.gmail.com"],
        enabled=["ubuntu-dock@ubuntu.com"],
    )

    assert plan.conflicts, "both are on afterwards, and both do the same job"
    said = "\n".join(plan.conflicts)
    assert "two of them" in said
    assert "@ubuntu.com" not in said, "a pair is never described by identifier"
    assert said in plan.body() or plan.conflicts[0] in plan.body()


def test_no_pair_is_reported_when_only_one_of_them_would_be_on(tmp_path, backend):
    tile = a_tile(tmp_path, body=BRINGS_A_SECOND_DOCK)

    plan = looks.plan_apply(
        tile, installed=["dash-to-dock@micxgx.gmail.com"], enabled=["Vitals@CoreCoding.com"]
    )

    assert plan.conflicts == []


WRITES_OVER_ACCESSIBILITY = """
[[settings]]
key = "gsettings:org.gnome.desktop.a11y.interface high-contrast"
value = "false"
component = "colors"

[[settings]]
key = "gsettings:org.gnome.desktop.interface enable-animations"
value = "true"
component = "animations"
"""


def test_a_look_that_undoes_high_contrast_says_it_out_loud(tmp_path, backend):
    """Fails on the old code: this was written silently, like any other setting."""
    backend.set("gsettings:org.gnome.desktop.a11y.interface high-contrast", "true")
    backend.set("gsettings:org.gnome.desktop.interface enable-animations", "false")
    tile = a_tile(tmp_path, body=WRITES_OVER_ACCESSIBILITY)

    plan = looks.plan_apply(tile, installed=[], enabled=[])

    assert looks.COPY["a11y-contrast"] in plan.accessibility
    assert looks.COPY["a11y-motion"] in plan.accessibility
    body = plan.body()
    assert looks.COPY["a11y-heading"] in body
    assert looks.COPY["a11y-contrast"] in body


def test_nothing_is_said_when_those_settings_are_not_switched_on(tmp_path, backend):
    """A person who is not using high contrast does not need a line about it."""
    backend.set("gsettings:org.gnome.desktop.a11y.interface high-contrast", "false")
    backend.set("gsettings:org.gnome.desktop.interface enable-animations", "true")
    tile = a_tile(tmp_path, body=WRITES_OVER_ACCESSIBILITY)

    plan = looks.plan_apply(tile, installed=[], enabled=[])

    assert plan.accessibility == []
    assert looks.COPY["a11y-heading"] not in plan.body()


def test_larger_text_counts_as_something_you_see_the_screen_with(tmp_path, backend):
    backend.set("gsettings:org.gnome.desktop.interface text-scaling-factor", "1.25")
    tile = a_tile(
        tmp_path,
        body=(
            '[[settings]]\nkey = "gsettings:org.gnome.desktop.interface '
            'text-scaling-factor"\nvalue = "1.0"\ncomponent = "fonts"\n'
        ),
    )

    plan = looks.plan_apply(tile, installed=[], enabled=[])

    assert looks.COPY["a11y-text"] in plan.accessibility
