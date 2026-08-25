"""Setting descriptors — the app's controls are data, not code.

THE CONTRACT IS FROZEN. These models define every ``.toml`` under
``data/panels/`` (one per curated add-on) and ``data/domains/`` (one per area
of core GNOME). A page renders rows by looking descriptors up; nobody writes a
row by hand. That is what lets one agent author the 24 add-on panels while
another builds the pages, and it is what makes "nothing was left out" a thing a
test can check rather than a thing someone remembers.

Two rules that come from the research and are not negotiable:

* **Address settings by ``(schema_id, key)``, never by key alone.**
  blur-my-shell, night-theme-switcher, space-bar and gsconnect each split their
  settings across child schemas, and the same key name means different things
  in different children.
* **Never trust ``metadata.json``'s ``settings-schema``, and never trust
  filenames.** Four of the curated add-ons omit the field entirely and
  clipboard-history ships its schema in a file named after a *different*
  extension. Schema ids come from parsing ``schemas/*.gschema.xml``.

Every row carries a plain-language ``subtitle``: it is mandatory, and the
jargon lint runs over every title and subtitle in this corpus.
"""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "Choice",
    "DomainDescriptor",
    "PanelDescriptor",
    "PanelTarget",
    "RequireFirst",
    "Row",
    "WidgetKind",
    "descriptor_id",
]


def descriptor_id(schema_id: str, key: str) -> str:
    """The stable id of one setting, used everywhere a row is referenced.

    ``coverage.toml`` dispositions are keyed by this, the row index deep-links
    by this, and search results resolve through this. Format: ``schema:key``.
    """
    return f"{schema_id}:{key}"


class WidgetKind(enum.StrEnum):
    """How a row is drawn. Closed set — an unknown kind is a data error."""

    #: On/off. Backed by a boolean key.
    TOGGLE = "toggle"
    #: A number with a range. ``clamp_min``/``clamp_max`` are MANDATORY here:
    #: several GNOME keys (the night-light times, the colour temperature) have
    #: no bounds in their own schema and will happily take nonsense.
    SLIDER = "slider"
    #: One of a fixed list. ``choices`` are MANDATORY.
    CHOICE = "choice"
    #: Free text. The app validates it itself — GSettings validates enums and
    #: ranges but NOT strings, and will accept a garbage window-button layout
    #: or a wallpaper path that does not exist.
    TEXT = "text"
    #: A colour. Stored either as a hex string or as a ``(dddd)`` tuple
    #: depending on the schema; the widget hides the difference.
    COLOR = "color"
    #: A scan-the-system picker: themes, icon sets, cursors, wallpapers,
    #: sound themes. The row shows what is installed, never a text box.
    PICKER = "picker"
    #: A number that lives inside an ``a{sv}`` dictionary value. Exactly one
    #: add-on needs this (rounded-window-corners' corner radius) and it is
    #: worth its own kind rather than a generic variant editor.
    DICT_SLIDER = "dict_slider"
    #: A key combination, captured from a real key press.
    SHORTCUT = "shortcut"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Choice(_Strict):
    """One option of a :attr:`WidgetKind.CHOICE` row."""

    #: GVariant text of the stored value, e.g. ``"'prefer-dark'"`` or ``"2"``.
    value: str
    #: What the user sees. Plain language; the jargon lint checks it.
    label: str
    subtitle: str | None = None


class RequireFirst(_Strict):
    """A key that must be written first for this row to have any effect.

    GNOME has several settings that are silently inert until a *different* key
    is set. Writing the visible one alone produces a control that appears to
    work and does nothing, which is the worst failure mode a novice app can
    have. The known cases:

    * font hinting and antialiasing do nothing while
      ``interface font-rendering`` is ``'automatic'``,
    * the titlebar font does nothing while
      ``wm.preferences titlebar-uses-system-font`` is true,
    * a fixed workspace count does nothing while ``mutter dynamic-workspaces``
      is true.
    """

    schema_id: str
    key: str
    #: GVariant text to write into that key first.
    value: str
    #: One sentence, shown when the app has to make this change: "To do this,
    #: gtheme also needs to stop letting the system pick the title font."
    explain: str


class Row(_Strict):
    """One control. The unit both ``data/panels/`` and ``data/domains/`` use."""

    schema_id: str
    key: str
    title: str
    #: MANDATORY. Says what the setting does, in the words of someone who has
    #: never used Linux. "Blurs the bar at the top of the screen", not
    #: "toggles panel blur".
    subtitle: str
    #: Other words a person might search for. "taskbar" finds the dock,
    #: "start menu" finds the overview.
    synonyms: list[str] = Field(default_factory=list)
    kind: WidgetKind
    #: Instance path for a relocatable schema. Starts and ends with "/".
    path: str | None = None

    clamp_min: float | None = None
    clamp_max: float | None = None
    step: float | None = None

    choices: list[Choice] = Field(default_factory=list)
    requires_first: list[RequireFirst] = Field(default_factory=list)

    #: Hide behind an expander. For settings that are real but that nobody
    #: should have to see to get a good desktop.
    advanced: bool = False
    #: A consequence, phrased as one: "This can stop screen recording from
    #: working on some machines." Rendered as a banner, not a scary dialog.
    warn: str | None = None
    #: Offer a per-row "put this back" button.
    reset: bool = True
    #: The key inside the ``a{sv}`` dictionary, for DICT_SLIDER rows.
    dict_key: str | None = None

    @property
    def id(self) -> str:
        """This row's :func:`descriptor_id`."""
        return descriptor_id(self.schema_id, self.key)

    @model_validator(mode="after")
    def _kind_requirements(self) -> Row:
        if self.kind is WidgetKind.CHOICE and not self.choices:
            raise ValueError(f"{self.id}: a 'choice' row needs choices")
        if self.kind is WidgetKind.SLIDER and (self.clamp_min is None or self.clamp_max is None):
            raise ValueError(
                f"{self.id}: a 'slider' row needs clamp_min and clamp_max — several GNOME "
                "keys are unbounded in their own schema and the app is what bounds them"
            )
        if self.kind is WidgetKind.DICT_SLIDER and not self.dict_key:
            raise ValueError(f"{self.id}: a 'dict_slider' row needs dict_key")
        if self.choices and self.kind is not WidgetKind.CHOICE:
            raise ValueError(f"{self.id}: choices only make sense on a 'choice' row")
        if self.path is not None and not (self.path.startswith("/") and self.path.endswith("/")):
            raise ValueError(f"{self.id}: a relocatable path must start and end with '/'")
        return self


class PanelTarget(_Strict):
    """Which add-on a panel is for, and what the app needs to know about it."""

    #: Every uuid this panel applies to. More than one when an add-on was
    #: forked or superseded (ding and gtk4-ding share a panel).
    uuids: list[str] = Field(min_length=1)
    #: Preference order among uuids when several are installed.
    alternates: list[str] = Field(default_factory=list)
    ego_pk: int | None = None
    #: The add-on's main schema id, parsed from its own gschema XML.
    #: Named ``schema_id`` rather than ``schema`` because pydantic's BaseModel
    #: already has a ``schema`` attribute and shadowing it warns at import.
    schema_id: str
    child_schemas: list[str] = Field(default_factory=list)
    #: For add-ons whose settings live in relocatable per-instance schemas,
    #: a path template such as
    #: ``/org/gnome/shell/extensions/burn-my-windows/profiles/{profile}/``.
    relocatable_path_template: str | None = None
    #: uuids this add-on must not be enabled alongside. Presented as either/or
    #: ("this replaces X — turn X off?"), never as a silent failure.
    conflicts: list[str] = Field(default_factory=list)
    category: str
    #: One sentence saying what the add-on does, for someone who has never
    #: heard of it. This is the text on the add-on's card.
    summary: str
    #: A machine- or combination-specific hazard, phrased as a consequence.
    warn: str | None = None


class PanelDescriptor(_Strict):
    """One curated add-on panel: ``data/panels/<id>.toml``."""

    id: str
    target: PanelTarget
    rows: list[Row] = Field(default_factory=list)

    @property
    def descriptor_ids(self) -> list[str]:
        return [row.id for row in self.rows]


class DomainDescriptor(_Strict):
    """One area of core GNOME: ``data/domains/<id>.toml``."""

    id: str
    title: str
    rows: list[Row] = Field(default_factory=list)

    @property
    def descriptor_ids(self) -> list[str]:
        return [row.id for row in self.rows]
