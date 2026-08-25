"""The client, against recorded answers. No socket is opened in this file.

The transport is injected, and it refuses any URL nobody recorded — so a change
that quietly reaches for the network fails here instead of passing on a machine
that happens to be online.
"""

from __future__ import annotations

import json

import pytest
from ego_fakes import RecordedTransport, collect, fixture_bytes, network_error

from gtheme.ego.client import (
    MAX_N_PER_PAGE,
    DiskCache,
    EgoClient,
    EgoError,
    EgoErrorKind,
    cache_dir,
    download_url,
)
from gtheme.ego.models import Comment, QueryPage, Rating


def client(routes, **kwargs) -> tuple[EgoClient, RecordedTransport]:
    transport = RecordedTransport(routes)
    return EgoClient(transport, kwargs.pop("shell_version", "50.4"), **kwargs), transport


# -- url building ----------------------------------------------------------


def test_only_the_major_desktop_version_is_ever_sent():
    api, _ = client({})
    assert "shell_version=50&" in api.query_url() or api.query_url().endswith(
        "shell_version=50"
    )
    assert "50.4" not in api.query_url()


def test_the_page_size_is_capped_where_the_server_caps_it():
    """Asking for 200 gets 25 and a page count computed as if you asked for 25."""
    api, _ = client({})
    assert f"n_per_page={MAX_N_PER_PAGE}" in api.query_url(n_per_page=200)
    assert "n_per_page=1" in api.query_url(n_per_page=1)
    assert "n_per_page=1" in api.query_url(n_per_page=0)


def test_an_unknown_sort_is_refused_here_because_the_site_will_not_refuse_it():
    api, _ = client({})
    with pytest.raises(ValueError):
        api.query_url(sort="downlods")


def test_a_search_term_reaches_the_query_string():
    api, _ = client({})
    assert "search=blur" in api.query_url(search="blur", sort="relevance")


def test_download_is_addressed_by_release_not_by_desktop_version():
    url = download_url("blur-my-shell@aunetx", 69740)
    assert url.endswith("blur-my-shell@aunetx.shell-extension.zip?version_tag=69740")
    assert "shell_version" not in url


# -- listing ---------------------------------------------------------------


def test_query_returns_a_parsed_page():
    api, transport = client({"/extension-query/": "query-downloads-p1.json"})
    box: list = []
    api.query(collect(box), page=1)
    page, error = box[0]
    assert error is None
    assert isinstance(page, QueryPage)
    assert len(page.extensions) == 25
    assert page.page == 1
    assert transport.requests[0].startswith("https://extensions.gnome.org/extension-query/")


def test_paging_is_driven_by_numpages_not_by_a_short_page():
    api, _ = client({"/extension-query/": "query-search-blur.json"})
    box: list = []
    api.query(collect(box), search="blur", sort="relevance", page=1, n_per_page=5)
    page, _ = box[0]
    assert (page.numpages, page.has_next) == (3, True)

    box.clear()
    api.query(collect(box), search="blur", sort="relevance", page=3, n_per_page=5)
    last, _ = box[0]
    assert last.has_next is False


def test_the_exact_result_count_comes_from_a_one_item_probe():
    """numpages at n_per_page=1 is the only exact count the site will give."""
    api, _ = client({"/extension-query/": "query-count-probe.json"})
    box: list = []
    api.query(collect(box), n_per_page=1)
    page, _ = box[0]
    assert page.numpages == 1087
    assert page.estimated_count == 1087


def test_a_page_past_the_end_is_not_an_error():
    api, _ = client({"/extension-query/": "query-past-end.json"})
    box: list = []
    api.query(collect(box), search="blur", page=999)
    page, error = box[0]
    assert error is None
    assert page.extensions == ()


def test_a_body_that_is_not_an_object_is_a_typed_failure():
    api, _ = client({"/extension-query/": b"[1, 2, 3]"})
    box: list = []
    api.query(collect(box))
    page, error = box[0]
    assert page is None
    assert error.kind is EgoErrorKind.MALFORMED


def test_a_body_that_is_not_json_is_a_typed_failure():
    api, _ = client({"/extension-query/": b"<html>404</html>"})
    box: list = []
    api.query(collect(box))
    page, error = box[0]
    assert page is None
    assert error.kind is EgoErrorKind.MALFORMED


def test_a_transport_failure_reaches_the_caller_intact():
    api, _ = client({"/extension-query/": network_error()})
    box: list = []
    api.query(collect(box))
    page, error = box[0]
    assert page is None
    assert error.kind is EgoErrorKind.NETWORK
    assert "internet" in error.user_text()


# -- one add-on ------------------------------------------------------------


def test_info_carries_the_release_and_the_compatibility_map():
    api, transport = client({"/extension-info/": "info-blur-my-shell.json"})
    box: list = []
    api.info("blur-my-shell@aunetx", collect(box))
    record, error = box[0]
    assert error is None
    assert (record.version, record.version_tag) == (72, 69740)
    assert "shell_version=50" in transport.requests[0]


def test_an_incompatible_add_on_is_caught_by_the_map_not_by_the_status():
    api, _ = client({"/extension-info/": "info-adb-bp-incompatible.json"})
    box: list = []
    api.info("adb_bp@gnome_extensions.github.com", collect(box))
    record, error = box[0]
    assert error is None, "the site answers 200 — the client must not read that as compatible"
    assert record.supports("50.4") is False


def test_a_missing_add_on_is_reported_as_not_found():
    api, _ = client({"/extension-info/": EgoError(EgoErrorKind.NOT_FOUND, "404", status=404)})
    box: list = []
    api.info("nope@nowhere", collect(box))
    record, error = box[0]
    assert record is None
    assert error.kind is EgoErrorKind.NOT_FOUND


def test_rating_uses_the_other_endpoint():
    api, transport = client({"/api/v1/extensions/": "apiv1-blur-my-shell.json"})
    box: list = []
    api.rating("blur-my-shell@aunetx", collect(box))
    rating, error = box[0]
    assert error is None
    assert isinstance(rating, Rating)
    assert rating.rated > 0
    assert transport.requests[0].endswith("/api/v1/extensions/blur-my-shell%40aunetx/")


def test_comments_are_keyed_by_the_number_and_come_back_as_a_bare_list():
    api, transport = client({"/comments/all/": "comments-3193.json"})
    box: list = []
    api.comments(3193, collect(box))
    comments, error = box[0]
    assert error is None
    assert comments and isinstance(comments[0], Comment)
    assert "pk=3193" in transport.requests[0]
    assert "all=true" not in transport.requests[0]


def test_asking_for_every_comment_is_opt_in():
    api, transport = client({"/comments/all/": "comments-3193.json"})
    api.comments(3193, collect([]), all_of_them=True)
    assert "all=true" in transport.requests[0]


# -- downloads -------------------------------------------------------------


def test_a_download_that_is_not_a_package_is_refused_before_it_is_unpacked():
    api, _ = client({"/download-extension/": b"<html>sorry</html>"})
    box: list = []
    api.download("blur-my-shell@aunetx", 69740, collect(box))
    body, error = box[0]
    assert body is None
    assert error.kind is EgoErrorKind.MALFORMED


def test_a_real_package_passes_the_check():
    api, _ = client({"/download-extension/": b"PK\x03\x04rest-of-the-zip"})
    box: list = []
    api.download("x@y", 1, collect(box))
    body, error = box[0]
    assert error is None
    assert body.startswith(b"PK\x03\x04")


# -- the update lookup -----------------------------------------------------


def test_the_desktop_version_goes_in_the_query_and_the_versions_go_in_the_body():
    """Swapping the two is a 400, and the usual reason this is called broken."""
    api, transport = client({"/update-info/": "update-info.json"})
    box: list = []
    api.update_info({"blur-my-shell@aunetx": 60, "adb_bp@gnome_extensions.github.com": 1}, collect(box))
    url, payload = transport.posts[0]
    assert "shell_version=50.4" in url
    assert "disable_version_validation=false" in url
    assert payload == {
        "blur-my-shell@aunetx": {"version": 60},
        "adb_bp@gnome_extensions.github.com": {"version": 1},
    }
    verdicts, error = box[0]
    assert error is None
    assert verdicts["blur-my-shell@aunetx"] == "upgrade"
    assert verdicts["adb_bp@gnome_extensions.github.com"] == "blacklist"


def test_add_ons_with_nothing_to_report_are_simply_absent():
    api, _ = client({"/update-info/": "update-info.json"})
    box: list = []
    api.update_info({"blur-my-shell@aunetx": 60, "nonexistent@gtheme.local": 1}, collect(box))
    verdicts, _ = box[0]
    assert "nonexistent@gtheme.local" not in verdicts


def test_asking_about_nothing_makes_no_request_at_all():
    api, transport = client({})
    box: list = []
    api.update_info({}, collect(box))
    assert box[0] == ({}, None)
    assert transport.requests == []


# -- the cache -------------------------------------------------------------


def test_the_cache_directory_honours_the_override(tmp_path, monkeypatch):
    monkeypatch.setenv("GTHEME_CACHE_DIR", str(tmp_path / "somewhere"))
    assert cache_dir() == tmp_path / "somewhere"
    monkeypatch.delenv("GTHEME_CACHE_DIR")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert cache_dir() == tmp_path / "xdg" / "gtheme" / "ego"


def test_a_second_identical_request_is_served_without_asking_again(tmp_path):
    cache = DiskCache(tmp_path, ttl=3600)
    api, transport = client({"/extension-query/": "query-downloads-p1.json"}, cache=cache)
    box: list = []
    api.query(collect(box), page=1)
    api.query(collect(box), page=1)
    assert len(transport.requests) == 1
    first, second = box[0][0], box[1][0]
    assert [e.uuid for e in first.extensions] == [e.uuid for e in second.extensions]


def test_a_different_page_is_a_different_cache_entry(tmp_path):
    cache = DiskCache(tmp_path, ttl=3600)
    api, transport = client({"/extension-query/": "query-downloads-p1.json"}, cache=cache)
    api.query(collect([]), page=1)
    api.query(collect([]), page=2)
    api.query(collect([]), search="blur", page=1)
    api.query(collect([]), sort="recent", page=1)
    assert len(transport.requests) == 4


def test_a_stale_entry_is_fetched_again(tmp_path):
    cache = DiskCache(tmp_path, ttl=0)
    api, transport = client({"/extension-query/": "query-downloads-p1.json"}, cache=cache)
    api.query(collect([]), page=1)
    api.query(collect([]), page=1)
    assert len(transport.requests) == 2


def test_an_unreadable_cache_is_a_miss_and_never_a_failure(tmp_path):
    cache = DiskCache(tmp_path / "does" / "not" / "exist", ttl=3600)
    key = DiskCache.key_for("https://example.org/x")
    assert cache.get(key) is None
    cache.put(key, b"body")  # the directory is created
    assert cache.get(key) == b"body"


def test_a_corrupt_cache_entry_does_not_poison_a_later_request(tmp_path):
    cache = DiskCache(tmp_path, ttl=3600)
    api, transport = client({"/extension-query/": "query-downloads-p1.json"}, cache=cache)
    url = api.query_url(page=1)
    (tmp_path / f"{DiskCache.key_for(url)}.body").write_bytes(b"not json")
    box: list = []
    api.query(collect(box), page=1)
    page, error = box[0]
    assert page is None and error.kind is EgoErrorKind.MALFORMED
    cache.clear()
    box.clear()
    api.query(collect(box), page=1)
    assert box[0][1] is None
    assert len(transport.requests) == 1


def test_downloads_are_never_cached(tmp_path):
    cache = DiskCache(tmp_path, ttl=3600)
    api, transport = client({"/download-extension/": b"PK\x03\x04zip"}, cache=cache)
    api.download("x@y", 1, collect([]))
    api.download("x@y", 1, collect([]))
    assert len(transport.requests) == 2


def test_the_cache_stores_exactly_what_arrived(tmp_path):
    cache = DiskCache(tmp_path, ttl=3600)
    api, _ = client({"/extension-query/": "query-search-blur.json"}, cache=cache)
    api.query(collect([]), search="blur", sort="relevance", n_per_page=5)
    stored = cache.get(DiskCache.key_for(api.query_url(search="blur", sort="relevance", n_per_page=5)))
    assert stored is not None
    assert json.loads(stored) == json.loads(fixture_bytes("query-search-blur.json"))
