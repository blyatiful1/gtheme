"""Home page: the reading and the wording, without a widget in sight."""

from __future__ import annotations

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the page modules")

from gtheme.core.settings_backend import BackendError, BackendErrorKind  # noqa: E402
from gtheme.ui import jargon  # noqa: E402
from gtheme.ui.pages import home  # noqa: E402


class FakeBackend:
    """Just enough of the backend contract to read a desktop back."""

    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def get(self, key: str) -> str:
        try:
            return self.values[key]
        except KeyError:
            raise BackendError(BackendErrorKind.NO_KEY, f"no {key}") from None


class FakeExtension:
    def __init__(self, running: bool) -> None:
        self.is_running = running


class FakeShell:
    def __init__(self, extensions: dict[str, FakeExtension] | None) -> None:
        self._extensions = extensions

    def load(self) -> dict[str, FakeExtension]:
        if self._extensions is None:
            raise RuntimeError("no desktop to ask")
        return self._extensions


def test_values_are_unquoted_before_they_are_shown():
    backend = FakeBackend({home.KEYS["icons"]: "'Papirus-Dark'"})
    assert home.read(backend, "icons") == "Papirus-Dark"


def test_an_unreadable_setting_is_none_not_a_guess():
    assert home.read(FakeBackend({}), "icons") is None


def test_light_or_dark_is_shown_in_words():
    assert home.describe_light_or_dark("prefer-dark") == "Dark"
    assert home.describe_light_or_dark("prefer-light") == "Light"
    # An unknown value is shown as it is rather than as a wrong translation.
    assert home.describe_light_or_dark("prefer-mauve") == "prefer-mauve"
    assert home.describe_light_or_dark(None) == home.COPY["unreadable"]


def test_every_accent_of_the_fixed_list_has_a_name_and_a_colour():
    """The setting is an enum of exactly nine; missing one shows a raw value."""
    expected = {"blue", "teal", "green", "yellow", "orange", "red", "pink", "purple", "slate"}
    assert set(home.ACCENT_NAMES) == expected
    assert set(home.ACCENT_COLOURS) == expected


def test_accent_is_described_in_words():
    assert home.describe_accent("slate") == "Grey"
    assert home.describe_accent(None) == home.COPY["unreadable"]


def test_wallpaper_uri_becomes_a_real_file(tmp_path):
    picture = tmp_path / "a picture.jpg"
    picture.write_bytes(b"not really a jpeg")
    backend = FakeBackend({home.KEYS["wallpaper"]: f"'file://{picture.as_posix().replace(' ', '%20')}'"})
    assert home.current_wallpaper(backend) == picture


def test_a_wallpaper_that_is_not_there_is_not_offered(tmp_path):
    backend = FakeBackend({home.KEYS["wallpaper"]: f"'file://{tmp_path}/gone.jpg'"})
    assert home.current_wallpaper(backend) is None


def test_addon_summary_counts_what_is_running():
    shell = FakeShell({"a": FakeExtension(True), "b": FakeExtension(False)})
    assert home.addon_summary(shell) == "1 of 2 switched on"


def test_addon_summary_is_honest_when_the_desktop_cannot_be_asked():
    assert home.addon_summary(FakeShell(None)) == home.COPY["addons-unavailable"]


def test_addon_summary_says_none_rather_than_zero_of_zero():
    assert home.addon_summary(FakeShell({})) == "None yet"


class CountingShell(FakeShell):
    """A connection that says whether it has listed, and counts the listings.

    The real ``ShellExtensions`` keeps its map live off ``ExtensionStateChanged``
    once it has listed, so asking it again is a ``ListExtensions`` round trip
    for something already in hand (review-report M26).
    """

    def __init__(self, extensions: dict[str, FakeExtension] | None) -> None:
        super().__init__(extensions)
        self.listings = 0
        self.loaded = False

    @property
    def all(self) -> dict[str, FakeExtension]:
        return dict(self._extensions or {})

    def load(self) -> dict[str, FakeExtension]:
        self.listings += 1
        answer = super().load()
        self.loaded = True
        return answer


def test_a_connection_that_has_already_listed_is_read_rather_than_asked_again():
    shell = CountingShell({"a": FakeExtension(True), "b": FakeExtension(False)})
    assert home.addon_summary(shell) == "1 of 2 switched on"
    assert home.addon_summary(shell) == "1 of 2 switched on"
    assert shell.listings == 1, "the second read must cost no round trip"


def test_the_accent_dot_is_a_filled_circle_of_the_right_colour():
    pixels = home.dot_pixels("#ff0000", size=16)
    assert len(pixels) == 16 * 16 * 4
    centre = ((8 * 16) + 8) * 4
    assert pixels[centre : centre + 4] == bytes((255, 0, 0, 255))
    assert pixels[0:4] == bytes(4)  # the corner is transparent, so it reads as a circle


def test_every_sentence_on_the_home_page_is_jargon_free():
    assert jargon.check_all(home.copy_strings()) == []
