"""The exact strings. This is the file that makes undo work.

gtheme does not know the type of ``org.gnome.desktop.interface font-name``. It
reads the string GLib prints, keeps it, and writes that string back later. The
round-trip is the entire safety model, and it is exact-string or nothing:

* ``@as []`` is an empty array of strings. ``[]`` on its own has no type and
  ``gsettings set`` refuses it outright. A backend that "helpfully" normalised
  the first into the second would make every Look that clears a list
  unrestorable.
* ``@ms nothing`` is a maybe-type holding nothing. Printed without its type
  annotation it becomes ``nothing``, which is not a value.
* Pango writes font axes into the family string — ``'Cantarell 11 @wght=460'``.
  A parser that split on ``@`` would lose the weight and the desktop would come
  back at the wrong one.
* Values are UTF-8 and stay UTF-8. A theme called ``'café — ü'`` round-trips.

These are checked against GLib itself, so if a future GLib changes how it
prints something, this fails here rather than silently in somebody's restore.
"""

from __future__ import annotations

import pytest

from gtheme.core.gvariant import (
    EMPTY_STRING_LIST,
    bare_number,
    canonical,
    format_string_list,
    merge_string_lists,
    parse_string_list,
    values_equal,
)

GLib = pytest.importorskip("gi.repository.GLib", reason="PyGObject is needed for GVariant text")

#: Every one of these is a real value some real key on this machine holds, or a
#: shape one of them can hold. The string on the right is what GLib prints.
GOLDEN = [
    ("@as []", "as"),
    ("['dash-to-dock@micxgx.gmail.com']", "as"),
    ("['a@b', 'c@d']", "as"),
    ("'Adwaita'", "s"),
    ("'adw-gtk3-dark'", "s"),
    ("'Cantarell 11 @wght=460'", "s"),
    ("'café — ü'", "s"),
    ("''", "s"),
    ("true", "b"),
    ("false", "b"),
    ("uint32 42", "u"),
    ("-1.0", "d"),
    ("@ms nothing", "ms"),
    ("@ms 'something'", "ms"),
    ("(1, 2)", "(ii)"),
    ("{'a': <1>}", "a{sv}"),
    ("@a{sv} {}", "a{sv}"),
]


@pytest.mark.parametrize(("text", "type_string"), GOLDEN)
def test_a_value_survives_a_round_trip_through_glib(text, type_string):
    """Parse, print, parse again: the text must be a fixed point.

    This is exactly what a snapshot and a restore do, one after the other.
    """
    variant = GLib.Variant.parse(None, text, None, None)
    assert variant.get_type_string() == type_string
    printed = variant.print_(True)
    assert printed == text
    again = GLib.Variant.parse(None, printed, None, None)
    assert again.print_(True) == text


def test_an_empty_string_list_keeps_its_type_annotation():
    """The one that would break undo the most quietly.

    ``[]`` cannot be written back. A Look that empties ``enabled-extensions``
    and an undo that cannot put the old list back would leave every add-on off
    with no way to say which ones were on.
    """
    assert EMPTY_STRING_LIST == "@as []"
    assert format_string_list([]) == "@as []"
    assert GLib.Variant.parse(None, EMPTY_STRING_LIST, None, None).print_(True) == "@as []"


def test_the_list_formatter_agrees_with_glib():
    for items in ([], ["a@b"], ["a@b", "c@d"], ["one", "two", "three"]):
        assert format_string_list(items) == GLib.Variant("as", items).print_(True)


def test_the_list_parser_reads_both_forms():
    assert parse_string_list("@as []") == []
    assert parse_string_list("[]") == []
    assert parse_string_list("['a', 'b']") == ["a", "b"]
    assert parse_string_list('["a", "b"]') == ["a", "b"]


def test_the_list_parser_refuses_to_guess():
    """Anything that is not plainly a list of strings comes back as None.

    A guess here becomes a wrong write to shared global state.
    """
    for text in ("'a string'", "true", "42", "[1, 2]", "['a', 2]", "{'a': <1>}", "nonsense("):
        assert parse_string_list(text) is None


def test_comparison_ignores_how_a_value_was_spelled_but_not_what_it_is():
    """A preview must not report a change that is only a change of quoting."""
    assert values_equal('"zoom"', "'zoom'")
    assert values_equal("  'zoom'  ", "'zoom'")
    assert values_equal("@as []", "[]")
    assert not values_equal("'zoom'", "'wallpaper'")
    assert not values_equal(None, "'zoom'")


def test_canonicalisation_never_loses_a_font_axis():
    assert "@wght=460" in canonical("'Cantarell 11 @wght=460'")


def test_unparseable_text_compares_strictly_rather_than_loosely():
    """The fallback can only make the comparison stricter.

    Reporting an unreadable value as changed costs a redundant write. Reporting
    it as unchanged would skip a write the user asked for.
    """
    assert canonical("not a variant at all") == "not a variant at all"
    assert not values_equal("not a variant", "also not a variant")


def test_merging_shared_lists_keeps_both_sides_exactly():
    """The union that stops a Look deleting somebody's add-ons."""
    merged = merge_string_lists("['mine@user']", "['theirs@look']")
    assert merged == "['mine@user', 'theirs@look']"
    assert parse_string_list(merged) == ["mine@user", "theirs@look"]
    assert GLib.Variant.parse(None, merged, None, None).get_type_string() == "as"


def test_a_merge_result_is_always_writable_text():
    for current, wanted in [
        ("@as []", "@as []"),
        ("@as []", "['a@b']"),
        ("['a@b']", "@as []"),
        (None, "['a@b']"),
    ]:
        merged = merge_string_lists(current, wanted)
        assert merged is not None
        GLib.Variant.parse(None, merged, None, None)


# ---------------------------------------------------------------------------
# the type word GVariant prints in front of a number
# ---------------------------------------------------------------------------


def test_glib_really_does_print_the_type_in_front_of_a_uint32():
    """The premise. If GLib ever stops doing this, this fails here first."""
    assert GLib.Variant("u", 300).print_(True) == "uint32 300"
    assert GLib.Variant("i", 300).print_(True) == "300"


def test_every_annotated_numeric_type_is_bared():
    for text, expected in [
        ("uint32 300", "300"),
        ("int64 -5", "-5"),
        ("uint64 18446744073709551615", "18446744073709551615"),
        ("byte 0x0c", "12"),
        ("int16 7", "7"),
        ("uint16 7", "7"),
        ("int32 7", "7"),
        ("handle 3", "3"),
        ("double 1.5", "1.5"),
    ]:
        assert bare_number(text) == expected, text


def test_a_bare_number_and_a_non_number_are_returned_untouched():
    """Baring must be a no-op on everything that is not one of these."""
    for text in ["300", "-5", "1.5", "true", "'Papirus-Dark'", "@as []", "", "uint32"]:
        assert bare_number(text) == text, text


def test_a_string_that_merely_starts_with_a_type_word_is_not_a_number():
    """``'uint32 300'`` quoted is a *string*, and its quotes must survive."""
    assert bare_number("'uint32 300'") == "'uint32 300'"


def test_a_bared_number_is_still_accepted_for_the_key_it_came_from():
    """Why nothing needs baring on the way out: GLib parses against the type."""
    printed = GLib.Variant("u", 300).print_(True)
    assert GLib.Variant.parse(GLib.VariantType("u"), bare_number(printed), None, None).unpack() == 300
