"""Parsing what the add-on library actually sent, on a recorded day.

Every assertion here runs against bytes captured from extensions.gnome.org (see
``tests/fixtures/ego/MANIFEST.toml``). Nothing in this file touches the network.
"""

from __future__ import annotations

import json

from ego_fakes import fixture_json

from gtheme.ego.models import (
    NO_ICON_PATH,
    Comment,
    ExtensionRecord,
    QueryPage,
    Rating,
    absolute_url,
    shell_major,
)


def test_shell_major_takes_the_part_the_version_map_is_keyed_on():
    assert shell_major("50.4") == "50"
    assert shell_major("50") == "50"


def test_relative_paths_become_absolute_and_placeholders_become_nothing():
    assert absolute_url("/extension-data/icons/i.png") == (
        "https://extensions.gnome.org/extension-data/icons/i.png"
    )
    assert absolute_url("https://example.org/i.png") == "https://example.org/i.png"
    # Both ways the site says "no picture" collapse to one.
    assert absolute_url(NO_ICON_PATH) is None
    assert absolute_url(None) is None
    assert absolute_url("") is None


def test_query_page_parses_a_real_listing():
    page = QueryPage.from_json(fixture_json("query-downloads-p1.json"), page=1, n_per_page=25)
    assert len(page.extensions) == 25
    assert page.extensions[0].uuid == "dash-to-dock@micxgx.gmail.com"
    assert page.extensions[0].downloads > 1_000_000


def test_total_is_the_page_size_and_never_the_result_count():
    """The site's ``total`` counts what is in your hand. numpages counts results."""
    raw = fixture_json("query-downloads-p1.json")
    page = QueryPage.from_json(raw, page=1, n_per_page=25)
    assert page.total == len(page.extensions) == 25
    assert page.numpages > 1
    assert page.estimated_count == page.numpages * 25
    assert page.estimated_count > page.total


def test_a_page_past_the_end_is_an_empty_answer_not_an_error():
    page = QueryPage.from_json(fixture_json("query-past-end.json"), page=999, n_per_page=25)
    assert page.extensions == ()
    assert page.numpages == 0
    assert page.has_next is False


def test_has_next_follows_numpages():
    raw = fixture_json("query-search-blur.json")
    first = QueryPage.from_json(raw, page=1, n_per_page=5)
    assert first.numpages == 3
    assert first.has_next is True
    assert QueryPage.from_json(raw, page=3, n_per_page=5).has_next is False


def test_a_record_without_an_identity_is_skipped_not_crashed_on():
    page = QueryPage.from_json(
        {"extensions": [{"name": "nameless"}, {"uuid": "a@b", "name": "A"}], "numpages": 1},
        page=1,
        n_per_page=25,
    )
    assert [e.uuid for e in page.extensions] == ["a@b"]


def test_detail_response_carries_the_exact_release_to_download():
    record = ExtensionRecord.from_json(fixture_json("info-blur-my-shell.json"))
    assert record.uuid == "blur-my-shell@aunetx"
    assert record.version == 72
    assert record.version_tag == 69740
    assert record.version_tag_for("50.4") == 69740
    assert record.version_for("50.4") == 72
    # The tag in the version map and the tag in the response are the same thing.
    assert record.shell_version_map["50"]["pk"] == record.version_tag


def test_a_listing_result_has_no_release_because_no_version_was_asked_for():
    record = ExtensionRecord.from_json(fixture_json("info-blur-my-shell-noversion.json"))
    assert record.version is None
    assert record.version_tag is None
    assert record.download_path is None
    # …and the version map is still there, which is what compatibility uses.
    assert record.supports("50.4")


def test_compatibility_is_decided_from_the_map_not_from_a_successful_answer():
    """The site answered 200 with a download link for a desktop it has no build for."""
    raw = fixture_json("info-adb-bp-incompatible.json")
    assert raw["download_url"], "the fixture must contain the misleading download link"
    record = ExtensionRecord.from_json(raw)
    assert list(record.shell_version_map) == ["3.36"]
    assert record.supports("50.4") is False
    assert record.version_tag_for("50.4") is None
    assert record.release_for("50.4") is None


def test_page_url_is_built_from_the_relative_link():
    record = ExtensionRecord.from_json(fixture_json("info-blur-my-shell.json"))
    assert record.page_url == "https://extensions.gnome.org/extension/3193/blur-my-shell/"


def test_a_listing_screenshot_may_simply_be_missing():
    page = QueryPage.from_json(fixture_json("query-downloads-p1.json"), page=1, n_per_page=25)
    without = [e for e in page.extensions if e.screenshot is None]
    assert without, "the recorded page contains add-ons with no screenshot"


def test_rating_comes_from_the_other_endpoint():
    rating = Rating.from_json(fixture_json("apiv1-blur-my-shell.json"))
    assert rating.uuid == "blur-my-shell@aunetx"
    assert rating.pk == 3193
    assert rating.rated > 100
    assert 0 <= (rating.rating or 0) <= 5
    assert rating.stars == round((rating.rating or 0) * 2) / 2
    assert rating.created and rating.updated


def test_the_other_endpoint_says_no_icon_with_null_and_gives_absolute_urls():
    raw = fixture_json("apiv1-battery-indicator.json")
    assert raw["icon"] is None
    assert raw["screenshot"].startswith("https://")
    rating = Rating.from_json(raw)
    assert rating.icon is None
    assert rating.screenshot is not None
    assert rating.screenshot.startswith("https://extensions.gnome.org/")
    assert "https://https" not in rating.screenshot


def test_comments_parse_and_their_markup_is_never_passed_on():
    raw = fixture_json("comments-3193.json")
    assert isinstance(raw, list), "the comments endpoint answers with a bare list"
    comments = [Comment.from_json(entry) for entry in raw]
    assert comments and all(c.author for c in comments)
    with_markup = next(c for c in comments if "<p>" in c.body_html)
    assert "<" not in with_markup.plain_text
    assert "&#x27;" not in with_markup.plain_text


def test_a_comment_without_stars_is_zero_not_missing():
    comment = Comment.from_json(
        json.loads('{"comment": "<p>hi</p>", "author": {"username": "x"}, "rating": 0}')
    )
    assert comment.rating == 0
    assert comment.plain_text == "hi"
