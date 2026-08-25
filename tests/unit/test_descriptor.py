"""Setting descriptors: the shape every panel and domain file must fit."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gtheme.panels.descriptor import (
    DomainDescriptor,
    PanelDescriptor,
    Row,
    WidgetKind,
    descriptor_id,
)


def _row(**overrides):
    base = {
        "schema_id": "org.gnome.desktop.interface",
        "key": "color-scheme",
        "title": "Dark mode",
        "subtitle": "Use dark colours everywhere",
        "kind": "toggle",
    }
    return Row.model_validate({**base, **overrides})


def test_descriptor_id_is_schema_colon_key():
    assert descriptor_id("org.gnome.desktop.interface", "color-scheme") == (
        "org.gnome.desktop.interface:color-scheme"
    )
    assert _row().id == "org.gnome.desktop.interface:color-scheme"


def test_a_subtitle_is_mandatory():
    """Every control explains itself. That is the whole product."""
    with pytest.raises(ValidationError, match="subtitle"):
        Row.model_validate(
            {
                "schema_id": "org.a.b",
                "key": "k",
                "title": "T",
                "kind": "toggle",
            }
        )


def test_a_typo_in_a_descriptor_is_an_error():
    with pytest.raises(ValidationError, match="sybtitle"):
        _row(sybtitle="oops")


def test_a_slider_must_be_clamped():
    """GNOME's night-light keys are unbounded; the app is what bounds them."""
    with pytest.raises(ValidationError, match="clamp_min and clamp_max"):
        _row(kind="slider")


def test_a_clamped_slider_is_fine():
    row = _row(kind="slider", clamp_min=1700, clamp_max=4700, step=100)
    assert row.kind is WidgetKind.SLIDER
    assert row.clamp_max == 4700


def test_a_choice_needs_choices():
    with pytest.raises(ValidationError, match="needs choices"):
        _row(kind="choice")


def test_choices_only_belong_on_a_choice_row():
    with pytest.raises(ValidationError, match="only make sense"):
        _row(kind="toggle", choices=[{"value": "1", "label": "One"}])


def test_a_dict_slider_needs_the_key_inside_the_dictionary():
    with pytest.raises(ValidationError, match="dict_key"):
        _row(kind="dict_slider")
    assert _row(kind="dict_slider", dict_key="radius").dict_key == "radius"


def test_a_relocatable_path_must_be_bracketed_by_slashes():
    with pytest.raises(ValidationError, match="start and end with"):
        _row(path="/no/trailing/slash")
    assert _row(path="/org/a/b/1/").path == "/org/a/b/1/"


def test_an_unknown_widget_kind_is_rejected():
    with pytest.raises(ValidationError):
        _row(kind="hologram")


def test_requires_first_carries_an_explanation():
    row = _row(
        requires_first=[
            {
                "schema_id": "org.gnome.desktop.interface",
                "key": "font-rendering",
                "value": "'manual'",
                "explain": "To change this, gtheme also stops the system choosing for itself.",
            }
        ]
    )
    assert row.requires_first[0].value == "'manual'"


def test_reset_defaults_on_and_advanced_defaults_off():
    row = _row()
    assert row.reset is True
    assert row.advanced is False


# -- panels ----------------------------------------------------------------


def _panel(**overrides):
    base = {
        "id": "blur-my-shell",
        "target": {
            "uuids": ["blur-my-shell@aunetx"],
            "ego_pk": 3193,
            "schema_id": "org.gnome.shell.extensions.blur-my-shell",
            "child_schemas": ["org.gnome.shell.extensions.blur-my-shell.panel"],
            "category": "looks",
            "summary": "Makes the bar at the top and the app view look frosted.",
        },
        "rows": [],
    }
    return PanelDescriptor.model_validate({**base, **overrides})


def test_a_panel_needs_at_least_one_uuid():
    with pytest.raises(ValidationError):
        _panel(
            target={
                "uuids": [],
                "schema_id": "org.a",
                "category": "looks",
                "summary": "x",
            }
        )


def test_a_panel_lists_its_descriptor_ids():
    panel = _panel(
        rows=[
            {
                "schema_id": "org.gnome.shell.extensions.blur-my-shell.panel",
                "key": "blur",
                "title": "Frost the top bar",
                "subtitle": "Makes the bar across the top see-through and blurry.",
                "kind": "toggle",
            }
        ]
    )
    assert panel.descriptor_ids == ["org.gnome.shell.extensions.blur-my-shell.panel:blur"]


def test_a_panel_can_declare_conflicts_and_a_warning():
    panel = _panel(
        target={
            "uuids": ["dash-to-dock@micxgx.gmail.com"],
            "schema_id": "org.gnome.shell.extensions.dash-to-dock",
            "conflicts": ["dash-to-panel@jderose9.github.com"],
            "category": "layout",
            "summary": "Keeps your app icons in a bar you can always see.",
            "warn": "This replaces the taskbar-style add-on if you have it.",
        }
    )
    assert panel.target.conflicts == ["dash-to-panel@jderose9.github.com"]
    assert panel.target.warn


def test_a_panel_can_bind_several_uuids_to_one_definition():
    """ding and gtk4-ding are the same panel with two identities."""
    panel = _panel(
        target={
            "uuids": ["gtk4-ding@smedius.gitlab.com", "ding@rastersoft.com"],
            "alternates": ["ding@rastersoft.com"],
            "schema_id": "org.gnome.shell.extensions.gtk4-ding",
            "category": "layout",
            "summary": "Puts your files and a bin back on the desktop.",
        }
    )
    assert len(panel.target.uuids) == 2


# -- domains ---------------------------------------------------------------


def test_a_domain_descriptor_holds_rows_too():
    domain = DomainDescriptor.model_validate(
        {
            "id": "wallpaper",
            "title": "Wallpaper",
            "rows": [
                {
                    "schema_id": "org.gnome.desktop.background",
                    "key": "picture-uri",
                    "title": "Background picture",
                    "subtitle": "The picture behind your windows.",
                    "kind": "picker",
                }
            ],
        }
    )
    assert domain.descriptor_ids == ["org.gnome.desktop.background:picture-uri"]


# -- one panel, two add-ons, two schema ids --------------------------------


def _two_addon_panel(**target_overrides) -> PanelDescriptor:
    target = {
        "uuids": ["ding@rastersoft.com", "gtk4-ding@smedius.gitlab.com"],
        "schema_id": "org.gnome.shell.extensions.ding",
        "schema_by_uuid": {
            "ding@rastersoft.com": "org.gnome.shell.extensions.ding",
            "gtk4-ding@smedius.gitlab.com": "org.gnome.shell.extensions.gtk4-ding",
        },
        "category": "layout",
        "summary": "Puts your files back onto the desktop background.",
        **target_overrides,
    }
    return PanelDescriptor.model_validate(
        {
            "id": "desktop-icons",
            "target": target,
            "rows": [
                {
                    "schema_id": "org.gnome.shell.extensions.ding",
                    "key": "show-home",
                    "title": "Home folder",
                    "subtitle": "Shows your own folder on the desktop background.",
                    "kind": "toggle",
                }
            ],
        }
    )


def test_rows_are_addressed_at_whichever_add_on_is_installed():
    panel = _two_addon_panel()
    ding = panel.rows_for("ding@rastersoft.com")
    gtk4 = panel.rows_for("gtk4-ding@smedius.gitlab.com")
    assert ding[0].schema_id == "org.gnome.shell.extensions.ding"
    assert gtk4[0].schema_id == "org.gnome.shell.extensions.gtk4-ding"
    assert gtk4[0].key == ding[0].key
    assert gtk4[0].id == "org.gnome.shell.extensions.gtk4-ding:show-home"


def test_an_unlisted_uuid_falls_back_to_the_panels_own_schema():
    panel = _two_addon_panel()
    assert panel.target.schema_for("something@else") == "org.gnome.shell.extensions.ding"


def test_both_schemas_count_as_declared():
    """Which is what lets the corpus check pass without lying in child_schemas."""
    assert _two_addon_panel().target.declared_schemas == {
        "org.gnome.shell.extensions.ding",
        "org.gnome.shell.extensions.gtk4-ding",
    }


def test_schema_by_uuid_may_only_name_this_panels_own_add_ons():
    with pytest.raises(ValidationError, match="this panel is not for"):
        _two_addon_panel(
            schema_by_uuid={"someone@else": "org.gnome.shell.extensions.elsewhere"}
        )


def test_the_committed_desktop_icons_panel_declares_both_honestly(repo_root):
    from gtheme.panels.loader import load_panels

    panels, problems = load_panels(repo_root / "data" / "panels")
    assert problems == []
    panel = next(p for p in panels if p.id == "desktop-icons")
    assert panel.target.child_schemas == [], (
        "a rival add-on's schema is not a child schema of this one"
    )
    assert set(panel.target.schema_by_uuid) == set(panel.target.uuids)
    for uuid in panel.target.uuids:
        prefix = panel.target.schema_for(uuid)
        assert all(row.schema_id == prefix for row in panel.rows_for(uuid))


# -- link rows -------------------------------------------------------------


def _link(**overrides):
    base = {
        "title": "Open the add-on's own settings",
        "subtitle": "The rest of this add-on's settings open in its own window.",
        "kind": "link",
        "link_target": "extension-prefs:dash-to-panel@jderose9.github.com",
    }
    return Row.model_validate({**base, **overrides})


def test_a_link_row_needs_no_setting_behind_it():
    row = _link()
    assert row.schema_id is None and row.key is None
    assert row.id == "link:extension-prefs:dash-to-panel@jderose9.github.com"


def test_a_link_row_must_say_where_it_goes():
    with pytest.raises(ValidationError, match="needs link_target"):
        _link(link_target=None)


def test_a_link_row_may_only_go_somewhere_the_app_knows():
    with pytest.raises(ValidationError, match="extension-prefs"):
        _link(link_target="https://example.invalid/settings")


def test_a_link_row_may_not_also_claim_a_setting():
    with pytest.raises(ValidationError, match="it does not read a setting"):
        _link(schema_id="org.gnome.shell", key="favorite-apps")


def test_only_a_link_row_may_carry_a_link_target():
    with pytest.raises(ValidationError, match="only makes sense on a 'link' row"):
        _row(link_target="page:addons")


def test_every_other_kind_still_needs_a_setting():
    with pytest.raises(ValidationError, match="needs schema_id and key"):
        Row.model_validate(
            {"title": "Nowhere", "subtitle": "Reads nothing at all.", "kind": "toggle"}
        )


def test_the_committed_deep_links_point_at_their_own_add_ons(repo_root):
    """A link row that names a uuid the panel is not for goes nowhere."""
    from gtheme.panels.loader import load_panels

    panels, problems = load_panels(repo_root / "data" / "panels")
    assert problems == []
    links = {
        panel.id: [row for row in panel.rows if row.kind is WidgetKind.LINK] for panel in panels
    }
    assert sorted(name for name, rows in links.items() if rows) == [
        "dash-to-panel",
        "gsconnect",
        "rounded-window-corners",
    ]
    by_id = {panel.id: panel for panel in panels}
    for name, rows in links.items():
        for row in rows:
            assert row.link_target is not None
            uuid = row.link_target.split(":", 1)[1]
            assert uuid in by_id[name].target.uuids, (
                f"{name}: link row points at {uuid}, which is not this panel's add-on"
            )
