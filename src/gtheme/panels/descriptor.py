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
    #: One of N booleans, exactly one of which may be true. burn-my-windows is
    #: the reason: it has 26 separate on/off settings, one per animation, and
    #: the add-on plays whichever is on. Six on/off rows in the app meant six
    #: switches that fight each other and a person left wondering why turning
    #: one on turned another off. One picker sets the chosen effect and clears
    #: the rest in a single action.
    #:
    #: ``choices`` are MANDATORY, and unlike every other kind their ``value``
    #: is the NAME of the sibling key, not a stored value: ``fire-enable-effect``,
    #: not ``true``.
    EFFECT_PICKER = "effect-picker"
    #: A number belonging to whichever of those effects is currently chosen.
    #: burn-my-windows has one duration setting per effect; twenty-six sliders
    #: of which twenty-five do nothing is not a control panel. This row reads
    #: and writes ``<chosen effect>-animation-time``, following the picker.
    #: Needs ``clamp_min`` and ``clamp_max`` like any other number.
    EFFECT_SPEED = "effect-speed"
    #: Not a setting at all: a way through to somewhere else. Some add-ons keep
    #: a whole world behind their own preferences window — dash-to-panel's
    #: per-monitor layout, GSConnect's per-phone pages, rounded-window-corners'
    #: per-app list. Rebuilding those here would mean shipping a worse copy of
    #: a window that already exists, and pretending they are not there would
    #: mean quietly hiding half the add-on. A link row says where the rest is
    #: and takes you there. It has a ``link_target`` and no key.
    LINK = "link"


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

    #: The settings group this row reads and writes. ``None`` only for
    #: :attr:`WidgetKind.LINK` rows, which read and write nothing.
    schema_id: str | None = None
    #: The key inside that group. ``None`` only for link rows.
    key: str | None = None
    title: str
    #: MANDATORY. Says what the setting does, in the words of someone who has
    #: never used Linux. "Blurs the bar at the top of the screen", not
    #: "toggles panel blur".
    subtitle: str
    #: Other words a person might search for. "taskbar" finds the dock,
    #: "start menu" finds the overview.
    synonyms: list[str] = Field(default_factory=list)
    kind: WidgetKind
    #: Instance path for a relocatable schema, or — with :attr:`keyfile` — the
    #: root the settings file is mounted at. Starts and ends with "/".
    path: str | None = None
    #: Absolute location of the settings FILE this row's value really lives
    #: in, for the add-ons that keep their own rather than using the desktop's
    #: settings store. burn-my-windows is the one case.
    #:
    #: Never written in a ``.toml`` — a committed descriptor cannot know which
    #: profile file is in use, and a test asserts none tries. It is filled in
    #: at runtime by :func:`gtheme.panels.schema_probe.resolve_row`.
    keyfile: str | None = None

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
    #: Where a :attr:`WidgetKind.LINK` row goes. Two forms:
    #: ``extension-prefs:<uuid>`` opens that add-on's own preferences window,
    #: and ``page:<page-id>`` moves to another page of this app.
    link_target: str | None = None

    @property
    def id(self) -> str:
        """This row's :func:`descriptor_id`.

        A link row has no setting behind it, so its id is its destination.
        The prefix keeps it out of the ``schema:key`` namespace that
        ``coverage.toml`` and the row index are keyed by.
        """
        if self.kind is WidgetKind.LINK:
            return f"link:{self.link_target}"
        assert self.schema_id is not None and self.key is not None  # enforced below
        return descriptor_id(self.schema_id, self.key)

    @model_validator(mode="after")
    def _kind_requirements(self) -> Row:
        if self.kind is WidgetKind.LINK:
            if not self.link_target:
                raise ValueError(f"{self.title!r}: a 'link' row needs link_target")
            if not self.link_target.startswith(("extension-prefs:", "page:")):
                raise ValueError(
                    f"{self.title!r}: link_target must be 'extension-prefs:<uuid>' "
                    f"or 'page:<page-id>', not {self.link_target!r}"
                )
            if self.schema_id is not None or self.key is not None:
                raise ValueError(
                    f"{self.title!r}: a 'link' row goes somewhere, it does not read a "
                    "setting — drop schema_id and key"
                )
            return self
        if self.link_target is not None:
            raise ValueError(f"{self.title!r}: link_target only makes sense on a 'link' row")
        if self.schema_id is None or self.key is None:
            raise ValueError(
                f"{self.title!r}: a {self.kind.value!r} row needs schema_id and key"
            )
        if self.kind is WidgetKind.CHOICE and not self.choices:
            raise ValueError(f"{self.id}: a 'choice' row needs choices")
        if self.kind is WidgetKind.EFFECT_PICKER and len(self.choices) < 2:
            raise ValueError(
                f"{self.id}: an 'effect-picker' row needs at least two effects to pick between"
            )
        if self.kind is WidgetKind.EFFECT_SPEED and (
            self.clamp_min is None or self.clamp_max is None
        ):
            raise ValueError(f"{self.id}: an 'effect-speed' row needs clamp_min and clamp_max")
        if self.kind is WidgetKind.SLIDER and (self.clamp_min is None or self.clamp_max is None):
            raise ValueError(
                f"{self.id}: a 'slider' row needs clamp_min and clamp_max — several GNOME "
                "keys are unbounded in their own schema and the app is what bounds them"
            )
        if self.kind is WidgetKind.DICT_SLIDER and not self.dict_key:
            raise ValueError(f"{self.id}: a 'dict_slider' row needs dict_key")
        if self.choices and self.kind not in (WidgetKind.CHOICE, WidgetKind.EFFECT_PICKER):
            raise ValueError(f"{self.id}: choices only make sense on a 'choice' row")
        if self.path is not None and not (self.path.startswith("/") and self.path.endswith("/")):
            raise ValueError(f"{self.id}: a relocatable path must start and end with '/'")
        if self.keyfile is not None:
            if not self.keyfile.startswith("/"):
                raise ValueError(f"{self.id}: a settings file must be a full location")
            if self.path is None:
                raise ValueError(
                    f"{self.id}: a settings file also needs the root it is mounted at"
                )
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
    #: For a panel shared by add-ons that do the same job under DIFFERENT
    #: schema ids: ``{uuid: schema_id}``. Desktop Icons is the case — DING and
    #: Gtk4-DING have the same keys under
    #: ``org.gnome.shell.extensions.ding`` and
    #: ``org.gnome.shell.extensions.gtk4-ding``, and a row written against one
    #: addresses nothing on a machine running the other.
    #:
    #: This used to be smuggled through ``child_schemas``, which says something
    #: different and untrue: a child schema is a *sub-group of the same
    #: add-on's* settings, and listing a rival add-on's schema there told the
    #: corpus checks that rows may reach into it — the opposite of the truth.
    #: Declared honestly, the engine can rewrite each row for whichever of the
    #: two is actually installed.
    schema_by_uuid: dict[str, str] = Field(default_factory=dict)
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

    @property
    def declared_schemas(self) -> set[str]:
        """Every settings group this panel says the add-on family owns."""
        return {self.schema_id, *self.child_schemas, *self.schema_by_uuid.values()}

    def schema_for(self, uuid: str) -> str:
        """The main schema id to use when ``uuid`` is the installed add-on."""
        return self.schema_by_uuid.get(uuid, self.schema_id)

    @model_validator(mode="after")
    def _schema_by_uuid_is_about_this_panel(self) -> PanelTarget:
        strangers = sorted(set(self.schema_by_uuid) - set(self.uuids))
        if strangers:
            raise ValueError(
                f"schema_by_uuid names {strangers}, which this panel is not for — "
                "the keys have to be uuids from this panel's own list"
            )
        return self


class PanelDescriptor(_Strict):
    """One curated add-on panel: ``data/panels/<id>.toml``."""

    id: str
    target: PanelTarget
    rows: list[Row] = Field(default_factory=list)

    @property
    def descriptor_ids(self) -> list[str]:
        return [row.id for row in self.rows]

    def rows_for(self, uuid: str) -> list[Row]:
        """This panel's rows, addressed at whichever add-on is installed.

        For every panel but one this is just :attr:`rows`. For Desktop Icons it
        is what makes the panel work at all: the rows are written once, against
        DING's schema, and rewritten here against Gtk4-DING's when that is the
        one on the machine.
        """
        schema = self.target.schema_for(uuid)
        if schema == self.target.schema_id:
            return list(self.rows)
        return [
            row.model_copy(update={"schema_id": schema})
            if row.schema_id == self.target.schema_id
            else row
            for row in self.rows
        ]


class DomainDescriptor(_Strict):
    """One area of core GNOME: ``data/domains/<id>.toml``."""

    id: str
    title: str
    rows: list[Row] = Field(default_factory=list)

    @property
    def descriptor_ids(self) -> list[str]:
        return [row.id for row in self.rows]
