"""The nothing-was-left-out check (DESIGN.md A7, F14).

``data/domains/universe.txt`` is every setting a GNOME 50 desktop actually has,
read off a live session. ``data/domains/coverage.toml`` says, for every one of
them, where it went. This module is what makes that a fact rather than a claim:

* a key with no disposition fails,
* an ``excluded`` disposition with a reason outside the closed set fails,
* a ``delegated`` disposition that is not on the committed allowlist, with a
  written justification, fails,
* a ``surfaced`` disposition naming a page that does not exist fails,
* a ``surfaced`` key with no hand-written row fails — otherwise "surfaced" would
  mean "somebody intends to write a control for this one day".

The escape valve is closed on purpose. Widening it means editing this file,
which is a thing a reviewer can see.
"""

from __future__ import annotations

import pytest
from domains_corpus_test import (
    FOREIGN_SCHEMA_ROWS,
    all_rows,
    coverage,
    dispositions,
    universe,
)

from gtheme.ui import registry

#: The only two reasons a setting may be hidden completely. Both come from
#: research/gnome-domains.md: §1.6 lists the keys that survive in the settings
#: definition but that nothing on a modern desktop reads, and §9.6 lists the
#: recipes that used to work and would now do harm.
LEGAL_EXCLUSION_REASONS = {"dead-key-§1.6", "obsolete-recipe-§9.6", "machine-state"}

#: Keyboard shortcuts are customisation, not input configuration, and may never
#: be handed to the desktop's own Settings app (F14). Anything in these schemas
#: has to be surfaced, floored or compounded here.
UNDELEGATABLE_SCHEMAS = (
    "org.gnome.desktop.wm.keybindings",
    "org.gnome.mutter.keybindings",
    "org.gnome.shell.keybindings",
    "org.gnome.settings-daemon.plugins.media-keys",
)


def _verb(disposition: str) -> str:
    return disposition.partition("(")[0].strip()


def _arg(disposition: str) -> str:
    _, _, rest = disposition.partition("(")
    return rest.rstrip(")").strip()


def test_every_setting_on_this_desktop_has_a_disposition():
    given = dispositions()
    missing = [f"{s}:{k}" for s, k, _ in universe() if f"{s}:{k}" not in given]
    assert missing == [], (
        f"{len(missing)} settings have nowhere to go, starting with {missing[:5]} — "
        "every key of universe.txt needs a disposition in coverage.toml"
    )


def test_no_disposition_is_invented_for_a_setting_that_does_not_exist():
    known = {f"{s}:{k}" for s, k, _ in universe()}
    stray = sorted(set(dispositions()) - known)
    assert stray == [], f"coverage.toml dispositions settings that are not in universe.txt: {stray}"


def test_every_disposition_uses_the_closed_vocabulary():
    for descriptor_id, disposition in dispositions().items():
        assert _verb(disposition) in {
            "surfaced", "compound", "floor", "excluded", "delegated",
        }, f"{descriptor_id}: {disposition!r} is not one of the five dispositions"


def test_the_manifest_and_the_coverage_agree_on_what_the_pages_are():
    """``resolve_surfaced`` raises on a page that is not in the manifest."""
    resolved = registry.resolve_surfaced(dispositions())
    assert set(resolved) == set(registry.page_ids())


def test_every_surfaced_setting_has_a_row_somebody_wrote():
    rows = {row.id for row in all_rows()}
    promised = [
        descriptor_id
        for descriptor_id, disposition in dispositions().items()
        if _verb(disposition) == "surfaced"
    ]
    undelivered = sorted(set(promised) - rows)
    assert undelivered == [], (
        f"{len(undelivered)} settings are marked as surfaced but no descriptor row exists "
        f"for them: {undelivered[:5]}"
    )


def test_every_row_is_surfaced_on_the_page_its_file_belongs_to():
    """A row nobody dispositioned would render nowhere."""
    given = dispositions()
    for row in all_rows():
        if row.id in FOREIGN_SCHEMA_ROWS:
            continue
        assert _verb(given[row.id]) == "surfaced", (
            f"{row.id}: a row was written for it but it is dispositioned {given[row.id]!r}"
        )


def test_surfaced_rows_reach_the_page_they_were_promised_to():
    resolved = registry.resolve_surfaced(dispositions())
    for descriptor_id, disposition in dispositions().items():
        if _verb(disposition) != "surfaced":
            continue
        assert descriptor_id in resolved[_arg(disposition)]


def test_the_floor_catches_everything_nobody_designed_a_home_for():
    """Floor keys must land on More Settings and must have a type to draw."""
    resolved = registry.resolve_surfaced(dispositions())
    floor_page = resolved[registry.FLOOR_PAGE_ID]
    types = {f"{s}:{k}": t for s, k, t in universe()}
    floored = [d for d, disp in dispositions().items() if _verb(disp) == "floor"]
    assert floored, "a floor page with nothing on it means the long tail went missing"
    for descriptor_id in floored:
        assert descriptor_id in floor_page, f"{descriptor_id}: floored but not on More Settings"
        assert types[descriptor_id], f"{descriptor_id}: no type, so no row can be drawn for it"


def test_hiding_a_setting_needs_one_of_three_argued_reasons():
    for descriptor_id, disposition in dispositions().items():
        if _verb(disposition) != "excluded":
            continue
        assert _arg(disposition) in LEGAL_EXCLUSION_REASONS, (
            f"{descriptor_id}: excluded({_arg(disposition)}) — the only legal reasons are "
            f"{sorted(LEGAL_EXCLUSION_REASONS)}"
        )


def test_machine_state_is_what_the_desktop_writes_to_itself():
    """The third exclusion reason, pinned to the keys it was argued for.

    ``machine-state`` is the reason with the most room to be abused — almost
    any key could be called bookkeeping if nobody checked. So the list is
    written down: these keys and no others, and the neighbouring keys that
    look similar and are NOT machine state are pinned beside them.
    """
    given = dispositions()
    expected = {
        "org.gnome.shell:command-history",
        "org.gnome.shell:looking-glass-history",
        "org.gnome.shell:app-picker-layout",
        "org.gnome.shell:welcome-dialog-last-shown-version",
        "org.gnome.shell:last-selected-power-profile",
        "org.gnome.settings-daemon.plugins.color:night-light-last-coordinates",
        "org.gnome.mutter:output-luminance",
        "org.gnome.desktop.peripherals.keyboard:numlock-state",
        "org.gnome.desktop.session:session-name",
        "org.gnome.desktop.app-folders:folder-children",
        "org.gnome.shell.world-clocks:locations",
    }
    actual = {d for d, disp in given.items() if disp == "excluded(machine-state)"}
    assert actual == expected

    # People do name their desktops, so this one is a setting, not bookkeeping.
    assert given["org.gnome.desktop.wm.preferences:workspace-names"] == "floor"
    # And the switch that decides whether Num Lock is remembered is a real row,
    # even though the remembered value itself is not.
    assert (
        given["org.gnome.desktop.peripherals.keyboard:remember-numlock-state"]
        == "surfaced(more)"
    )


def test_the_dead_keys_are_the_ones_the_research_named():
    """A spot check that ``excluded`` was used on the list, not as a dumping ground."""
    given = dispositions()
    for key in ("gtk-key-theme", "menus-have-tearoff", "toolbar-style", "gtk-color-palette"):
        assert given[f"org.gnome.desktop.interface:{key}"] == "excluded(dead-key-§1.6)"
    assert given["org.gnome.mutter:experimental-features"] == "excluded(obsolete-recipe-§9.6)"
    assert given["org.gnome.desktop.wm.preferences:theme"] == "excluded(obsolete-recipe-§9.6)"
    # Still live for older apps, so it is NOT a dead key.
    assert given["org.gnome.desktop.interface:gtk-enable-primary-paste"] == "floor"


def test_handing_a_setting_to_the_desktops_own_app_needs_a_written_reason():
    allowlist = coverage()["delegated"]
    given = dispositions()
    delegated = {d for d, disp in given.items() if _verb(disp) == "delegated"}

    unlisted = sorted(delegated - set(allowlist))
    assert unlisted == [], (
        f"delegated without an entry in [delegated]: {unlisted} — the allowlist is committed "
        "on purpose so it cannot grow quietly"
    )
    stale = sorted(set(allowlist) - delegated)
    assert stale == [], f"[delegated] lists settings that are not delegated: {stale}"
    for descriptor_id, justification in allowlist.items():
        assert len(justification) > 60, f"{descriptor_id}: the justification is not an argument"


def test_the_delegated_allowlist_is_only_input_configuration():
    """F14 allows delegation for keyboard-layout-style input configuration only."""
    for descriptor_id in coverage()["delegated"]:
        assert descriptor_id.startswith("org.gnome.desktop.input-sources:"), (
            f"{descriptor_id}: delegation is allowed for input configuration only"
        )


@pytest.mark.parametrize("schema", UNDELEGATABLE_SCHEMAS)
def test_keyboard_shortcuts_are_never_handed_off(schema):
    for descriptor_id, disposition in dispositions().items():
        if descriptor_id.startswith(f"{schema}:"):
            assert _verb(disposition) != "delegated", f"{descriptor_id}: shortcuts stay in gtheme"


def test_the_shortcut_editor_really_covers_the_shortcuts():
    """F14: shortcuts get a real editor on Windows & Desktops, not a hand-wave."""
    rows = {row.id: row for row in all_rows()}
    resolved = registry.resolve_surfaced(dispositions())
    for descriptor_id in resolved["windows"]:
        row = rows.get(descriptor_id)
        if row is None or not descriptor_id.split(":")[0].endswith("keybindings"):
            continue
        assert row.kind.value == "shortcut", f"{descriptor_id}: a shortcut needs a key-capture row"
    for key in ("close", "switch-windows", "toggle-maximized"):
        assert f"org.gnome.desktop.wm.keybindings:{key}" in rows


def test_the_headline_settings_land_where_the_plan_says():
    """A spot check of DESIGN.md A6 against the data."""
    given = dispositions()
    expected = {
        "org.gnome.desktop.interface:accent-color": "surfaced(colors)",
        "org.gnome.desktop.interface:gtk-theme": "surfaced(colors)",
        "org.gnome.desktop.a11y.interface:high-contrast": "surfaced(colors)",
        "org.gnome.desktop.a11y.interface:reduced-motion": "surfaced(colors)",
        "org.gnome.desktop.interface:icon-theme": "surfaced(icons)",
        "org.gnome.desktop.interface:cursor-theme": "surfaced(icons)",
        "org.gnome.desktop.interface:font-name": "surfaced(fonts)",
        "org.gnome.desktop.background:picture-uri": "surfaced(wallpaper)",
        "org.gnome.desktop.background:picture-uri-dark": "surfaced(wallpaper)",
        "org.gnome.desktop.interface:clock-format": "surfaced(topbar)",
        "org.gnome.desktop.wm.preferences:button-layout": "surfaced(windows)",
        "org.gnome.settings-daemon.plugins.color:night-light-enabled": "surfaced(nightlight)",
        "org.gnome.desktop.sound:theme-name": "surfaced(sound)",
        "org.gnome.desktop.session:idle-delay": "surfaced(power)",
        "org.gnome.desktop.privacy:disable-camera": "surfaced(more)",
        "org.gnome.desktop.lockdown:disable-printing": "surfaced(more)",
        "org.gnome.shell:disable-user-extensions": "surfaced(addons)",
        # The one dark-mode control writes two keys; neither is a row of its own.
        "org.gnome.desktop.interface:color-scheme": "compound(dark-mode)",
        "org.gnome.shell:enabled-extensions": "compound(add-on-enable)",
    }
    for descriptor_id, disposition in expected.items():
        assert given[descriptor_id] == disposition, f"{descriptor_id} went to {given[descriptor_id]}"


def test_the_surface_is_actually_broad():
    """A corpus that surfaced twenty settings and floored five hundred would pass
    every check above while being the thing this whole design exists to prevent."""
    counts: dict[str, int] = {}
    for disposition in dispositions().values():
        counts[_verb(disposition)] = counts.get(_verb(disposition), 0) + 1
    assert counts["surfaced"] > 250, f"only {counts.get('surfaced', 0)} settings were given a real control"
    assert counts["excluded"] < 40, "too much of the desktop is being hidden"
    assert counts["delegated"] < 20, "delegation is an exception, not a strategy"
