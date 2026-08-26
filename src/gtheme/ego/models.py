"""What extensions.gnome.org sends back, as types instead of dictionaries.

Every field here was read off a real response recorded into
``tests/fixtures/ego/`` (see the MANIFEST there for the exact URLs and the day
they were fetched). The parsers are deliberately forgiving about *extra* keys
and strict about the handful gtheme depends on, because the site adds fields
without notice and has done so twice in the fixtures' lifetime.

Three facts drive the shapes below, all of them from ``research/ego-api.md``:

* the legacy endpoints return **site-relative** image paths and ``/api/v1/``
  returns absolute ones, so one normaliser runs over both;
* an extension with no icon is ``/static/images/plugin.png`` on the legacy
  endpoints and ``null`` on ``/api/v1/`` — both mean "no icon";
* ``shell_version_map`` is the **only** trustworthy compatibility source. The
  detail endpoint happily hands out a GNOME 3.36 build for a GNOME 50 request,
  so :meth:`ExtensionRecord.supports` is what decides, never an HTTP status.

Nothing in this module talks to the network or to the desktop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "BASE_URL",
    "NO_ICON_PATH",
    "Comment",
    "ExtensionRecord",
    "QueryPage",
    "Rating",
    "absolute_url",
    "shell_major",
]

#: Where all of this comes from. One constant, so a mirror is a one-line change.
BASE_URL = "https://extensions.gnome.org"

#: The placeholder the legacy endpoints return instead of a null icon.
NO_ICON_PATH = "/static/images/plugin.png"


def absolute_url(url: str | None) -> str | None:
    """Make a site-relative path absolute; leave an absolute URL alone.

    Returns None for the icon placeholder as well as for a missing value, so
    callers have exactly one "there is no picture" case to handle instead of
    three.
    """
    if not url or url == NO_ICON_PATH:
        return None
    if url.startswith(("http://", "https://")):
        return url
    return BASE_URL + url


def shell_major(version: str) -> str:
    """``"50.4"`` -> ``"50"``. The key that ``shell_version_map`` is keyed on."""
    return version.split(".")[0]


def _as_int(value: Any, default: int = 0) -> int:
    """D-Bus and JSON both hand back floats where an int is meant."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any) -> float | None:
    """A number the site says is a rating, or None when it is not a number.

    The site has been seen to send ``null``, ``""`` and ``"n/a"`` in this slot.
    A bare ``float()`` turns any of those into an exception three frames inside
    a main-loop callback, where nobody catches it and the whole request goes
    silent. A missing rating is not an error; it is simply no rating.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class ExtensionRecord:
    """One add-on as the legacy endpoints describe it.

    ``version``, ``version_tag`` and ``download_path`` appear only when the
    request carried a ``shell_version`` — they are absent from every
    ``/extension-query/`` result, which is why they are optional here rather
    than required.
    """

    uuid: str
    name: str
    creator: str
    pk: int
    description: str = ""
    link: str = ""
    icon: str | None = None
    screenshot: str | None = None
    shell_version_map: dict[str, dict[str, int]] = field(default_factory=dict)
    downloads: int = 0
    url: str | None = None
    donation_urls: tuple[str, ...] = ()
    version: int | None = None
    version_tag: int | None = None
    download_path: str | None = None

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> ExtensionRecord:
        """Parse one object out of ``/extension-query/`` or ``/extension-info/``.

        Raises:
            ValueError: the object has no ``uuid``. Anything else missing is
                defaulted; a nameless add-on is a display problem, an
                identity-less one is not something gtheme can act on at all.
        """
        uuid = raw.get("uuid")
        if not uuid:
            raise ValueError("an extension record with no uuid is not usable")
        version_map: dict[str, dict[str, int]] = {}
        for key, entry in (raw.get("shell_version_map") or {}).items():
            if isinstance(entry, dict):
                version_map[str(key)] = {
                    "pk": _as_int(entry.get("pk")),
                    "version": _as_int(entry.get("version")),
                }
        return cls(
            uuid=str(uuid),
            name=str(raw.get("name") or uuid),
            creator=str(raw.get("creator") or ""),
            pk=_as_int(raw.get("pk")),
            description=str(raw.get("description") or ""),
            link=str(raw.get("link") or ""),
            icon=absolute_url(raw.get("icon")),
            screenshot=absolute_url(raw.get("screenshot")),
            shell_version_map=version_map,
            downloads=_as_int(raw.get("downloads")),
            url=raw.get("url") or None,
            donation_urls=tuple(raw.get("donation_urls") or ()),
            version=_as_int(raw["version"]) if raw.get("version") is not None else None,
            version_tag=(
                _as_int(raw["version_tag"]) if raw.get("version_tag") is not None else None
            ),
            download_path=raw.get("download_url") or None,
        )

    # -- compatibility ----------------------------------------------------

    def supports(self, shell_version: str) -> bool:
        """Whether this add-on has a build for that desktop version.

        Answered from ``shell_version_map`` alone. The detail endpoint returns
        200 with a download link for versions it has no build for — trusting it
        is how an app hands somebody a five-year-old add-on and calls it
        compatible.
        """
        return shell_major(shell_version) in self.shell_version_map

    def release_for(self, shell_version: str) -> dict[str, int] | None:
        """``{"pk": version_tag, "version": n}`` for that desktop, or None."""
        return self.shell_version_map.get(shell_major(shell_version))

    def version_tag_for(self, shell_version: str) -> int | None:
        """The exact release id to download for that desktop version.

        Downloading by version tag pins the build that was shown to the user;
        downloading by desktop version lets the server re-decide in between.
        """
        release = self.release_for(shell_version)
        return release["pk"] if release else None

    def version_for(self, shell_version: str) -> int | None:
        """The add-on's own version number for that desktop version."""
        release = self.release_for(shell_version)
        return release["version"] if release else None

    @property
    def page_url(self) -> str | None:
        """The human-readable page, for a "learn more" link."""
        return absolute_url(self.link)


@dataclass(frozen=True)
class QueryPage:
    """One page of search results.

    ``total`` is the number of items **on this page**, not the size of the
    result set — the name is the site's, the trap is real, and
    :attr:`estimated_count` is what to show a person instead.
    """

    extensions: tuple[ExtensionRecord, ...]
    numpages: int
    page: int
    n_per_page: int
    total: int = 0

    @classmethod
    def from_json(
        cls, raw: dict[str, Any], *, page: int, n_per_page: int
    ) -> QueryPage:
        records = []
        for entry in raw.get("extensions") or ():
            try:
                records.append(ExtensionRecord.from_json(entry))
            except ValueError:
                continue
        return cls(
            extensions=tuple(records),
            numpages=_as_int(raw.get("numpages")),
            page=page,
            n_per_page=n_per_page,
            total=_as_int(raw.get("total")),
        )

    @property
    def has_next(self) -> bool:
        return self.page < self.numpages

    @property
    def estimated_count(self) -> int:
        """About how many results there are, from the page count.

        The last page is usually short, so this over-counts by up to
        ``n_per_page - 1``. Show it as "about 1,100", never as an exact figure.
        """
        return self.numpages * self.n_per_page


@dataclass(frozen=True)
class Rating:
    """Stars and dates, which only ``/api/v1/`` knows."""

    uuid: str
    pk: int
    rating: float | None = None
    rated: int = 0
    created: str | None = None
    updated: str | None = None
    icon: str | None = None
    screenshot: str | None = None

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Rating:
        return cls(
            uuid=str(raw.get("uuid") or ""),
            pk=_as_int(raw.get("id")),
            rating=_as_float(raw.get("rating")),
            rated=_as_int(raw.get("rated")),
            created=raw.get("created") or None,
            updated=raw.get("updated") or None,
            icon=absolute_url(raw.get("icon")),
            screenshot=absolute_url(raw.get("screenshot")),
        )

    @property
    def stars(self) -> float | None:
        """The rating rounded to a half star, which is how it is drawn."""
        if self.rating is None:
            return None
        return round(self.rating * 2) / 2


@dataclass(frozen=True)
class Comment:
    """One review. ``body_html`` is pre-rendered HTML and is not trusted.

    The site returns markup it generated from user input. gtheme never feeds it
    to a label with markup enabled; :attr:`plain_text` is what the UI shows.
    """

    author: str
    body_html: str
    date: str = ""
    rating: int = 0
    is_author: bool = False
    avatar: str | None = None

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Comment:
        author = (raw.get("author") or {}).get("username") or ""
        date = (raw.get("date") or {}).get("standard") or ""
        return cls(
            author=str(author),
            body_html=str(raw.get("comment") or ""),
            date=str(date),
            rating=_as_int(raw.get("rating")),
            is_author=bool(raw.get("is_extension_creator")),
            avatar=raw.get("gravatar") or None,
        )

    @property
    def plain_text(self) -> str:
        """The comment with its markup taken off and its entities resolved."""
        import html
        import re

        without_tags = re.sub(r"<[^>]+>", " ", self.body_html)
        collapsed = re.sub(r"\s+", " ", html.unescape(without_tags))
        return collapsed.strip()
