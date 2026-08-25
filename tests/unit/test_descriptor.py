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
