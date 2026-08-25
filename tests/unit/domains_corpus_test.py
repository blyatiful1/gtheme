"""Shared loading for the core-GNOME descriptor corpus under ``data/domains/``.

The three ``domains_*_test.py`` modules all need the same two things: the parsed
descriptor files, and the parsed coverage manifest. Parsing them here — through
the frozen pydantic models, never through a hand-rolled reader — means a
descriptor file that violates the contract fails collection of every domain test
rather than one of them.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from gtheme.panels.descriptor import DomainDescriptor, Row

REPO_ROOT = Path(__file__).resolve().parents[2]
DOMAINS_DIR = REPO_ROOT / "data" / "domains"
UNIVERSE = DOMAINS_DIR / "universe.txt"
COVERAGE = DOMAINS_DIR / "coverage.toml"

#: Descriptors whose ``(schema_id, key)`` is deliberately absent from the
#: coverage universe, because the setting belongs to an add-on rather than to
#: core GNOME. ``universe.txt`` is a sweep of core schemas only; an add-on's
#: settings are not on the default settings path at all.
#:
#: There is exactly one. The top bar's style is the single setting that a
#: person thinks of as "core desktop appearance" while the desktop keeps it in
#: an add-on, so it is authored here rather than left to the add-on panels.
FOREIGN_SCHEMA_ROWS = {"org.gnome.shell.extensions.user-theme:name"}


def domain_files() -> list[Path]:
    """Every authored domain descriptor file, in a stable order."""
    return sorted(p for p in DOMAINS_DIR.glob("*.toml") if p.name != "coverage.toml")


def load_domains() -> list[DomainDescriptor]:
    """Parse every domain file through the frozen model."""
    return [
        DomainDescriptor.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
        for path in domain_files()
    ]


def all_rows() -> list[Row]:
    return [row for domain in load_domains() for row in domain.rows]


def universe() -> list[tuple[str, str, str]]:
    """``(schema, key, type)`` for every key of the committed universe."""
    rows = []
    for line in UNIVERSE.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        schema, key, type_ = line.split("\t")
        rows.append((schema, key, type_))
    return rows


def coverage() -> dict:
    return tomllib.loads(COVERAGE.read_text(encoding="utf-8"))


def dispositions() -> dict[str, str]:
    return coverage()["dispositions"]


def test_the_corpus_exists():
    """A domains directory with only the universe in it is not a corpus."""
    assert domain_files(), "no domain descriptor files were authored"
    assert COVERAGE.is_file(), "coverage.toml is missing"


def test_every_domain_file_parses_against_the_frozen_model():
    """``extra='forbid'`` means a typo in a field name fails here, not at runtime."""
    domains = load_domains()
    assert len(domains) == len(domain_files())
    assert all(domain.rows for domain in domains), "a domain file with no rows is dead weight"


def test_domain_ids_are_unique_and_match_their_filenames():
    for path in domain_files():
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        assert parsed["id"] == path.stem, f"{path.name}: id is {parsed['id']!r}"


def test_no_setting_is_described_twice():
    """Two rows for one setting means two controls that fight each other."""
    seen: dict[str, str] = {}
    for domain in load_domains():
        for row in domain.rows:
            assert row.id not in seen, (
                f"{row.id} is described by both {seen[row.id]!r} and {domain.id!r}"
            )
            seen[row.id] = domain.id


def test_every_row_addresses_a_setting_that_exists():
    """A row for a key nobody has is a control that greys out forever."""
    known = {f"{schema}:{key}" for schema, key, _ in universe()}
    unknown = [row.id for row in all_rows() if row.id not in known]
    assert set(unknown) <= FOREIGN_SCHEMA_ROWS, (
        f"rows address settings that are in neither the universe nor the add-on "
        f"exception list: {sorted(set(unknown) - FOREIGN_SCHEMA_ROWS)}"
    )


def test_every_row_says_what_it_does():
    """The subtitle is mandatory in the model; this checks it is not a placeholder."""
    for row in all_rows():
        assert len(row.subtitle.split()) >= 3, f"{row.id}: subtitle is not a sentence"
        assert row.subtitle.strip().endswith("."), f"{row.id}: subtitle is not a sentence"
        assert row.title[:1].isupper(), f"{row.id}: title does not start with a capital"


def test_every_row_can_be_searched_for_in_someone_elses_words():
    """Synonyms are how a Windows switcher finds anything at all (competitor-ux P7)."""
    for row in all_rows():
        assert row.synonyms, f"{row.id}: no synonyms, so search only finds it by its own name"


def test_sliders_carry_the_bounds_the_system_does_not():
    """Several GNOME keys are unbounded in their own definition (gnome-domains §6)."""
    for row in all_rows():
        if row.kind.value != "slider":
            continue
        assert row.clamp_min is not None and row.clamp_max is not None
        assert row.clamp_min < row.clamp_max, f"{row.id}: bounds are the wrong way round"


def test_the_night_light_times_are_clamped_below_24():
    """The schedule keys take any number at all; a 24.5 o'clock start is nonsense."""
    rows = {row.id: row for row in all_rows()}
    for key in ("night-light-schedule-from", "night-light-schedule-to"):
        row = rows[f"org.gnome.settings-daemon.plugins.color:{key}"]
        assert row.clamp_min == 0.0
        assert row.clamp_max < 24.0, f"{key}: 24.0 is midnight tomorrow, not a time of day"


def test_the_night_light_temperature_is_clamped_to_the_usable_band():
    row = {r.id: r for r in all_rows()}["org.gnome.settings-daemon.plugins.color:night-light-temperature"]
    assert (row.clamp_min, row.clamp_max) == (1700, 4700)


def test_the_window_button_layout_is_a_closed_set_of_layouts():
    """GSettings accepts ``"garbage:::"`` here without complaint (gnome-domains §5.1)."""
    row = {r.id: r for r in all_rows()}["org.gnome.desktop.wm.preferences:button-layout"]
    assert row.kind.value == "choice"
    valid = {"menu", "appmenu", "minimize", "maximize", "close", "spacer"}
    for choice in row.choices:
        text = choice.value.strip("'")
        assert text.count(":") == 1, f"{choice.value}: a layout has exactly one ':'"
        tokens = [t for half in text.split(":") for t in half.split(",") if t]
        assert set(tokens) <= valid, f"{choice.value}: unknown button name"
        assert len(tokens) == len(set(tokens)), f"{choice.value}: duplicate button"


def test_the_settings_that_are_inert_alone_say_what_else_must_change():
    """The three known two-key atoms of gnome-domains §9.1."""
    rows = {row.id: row for row in all_rows()}
    expected = {
        "org.gnome.desktop.interface:font-hinting": ("org.gnome.desktop.interface", "font-rendering"),
        "org.gnome.desktop.interface:font-antialiasing": ("org.gnome.desktop.interface", "font-rendering"),
        "org.gnome.desktop.wm.preferences:titlebar-font": (
            "org.gnome.desktop.wm.preferences", "titlebar-uses-system-font",
        ),
        "org.gnome.desktop.wm.preferences:num-workspaces": ("org.gnome.mutter", "dynamic-workspaces"),
    }
    for descriptor_id, (schema, key) in expected.items():
        row = rows[descriptor_id]
        pairs = {(r.schema_id, r.key) for r in row.requires_first}
        assert (schema, key) in pairs, f"{descriptor_id}: does not first write {schema} {key}"
        for req in row.requires_first:
            assert req.explain.strip().endswith("."), f"{descriptor_id}: explanation is not a sentence"


def test_nothing_promises_a_separate_lock_screen_picture():
    """``org.gnome.desktop.screensaver`` has no dark picture key, and on GNOME 50
    the lock screen is drawn from the desktop background anyway (gnome-domains §3.3).
    Surfacing a lock-screen picture row would be a promise the desktop cannot keep."""
    ids = {row.id for row in all_rows()}
    assert "org.gnome.desktop.screensaver:picture-uri" not in ids
    assert "org.gnome.desktop.screensaver:picture-uri-dark" not in ids
    assert dispositions()["org.gnome.desktop.screensaver:picture-uri"].startswith("compound(")
