"""Theme manifest: load and validate ``theme.toml`` (+ optional ``palette.toml``).

A theme directory looks like::

    <name>/
      theme.toml      # [meta] [requires] [[files]] [[settings]] [[hooks]] [build]
      palette.toml    # optional; otherwise [palette] inside theme.toml is used
      files/          # sources referenced by [[files]].src
      assets/         # wallpapers, svgs, ascii, ...
      hooks/          # scripts referenced by [[hooks]]

Setting values are stored as **serialized GVariant text** so the same string
round-trips through both ``gsettings`` and ``dconf`` (e.g. a string is
``"'green'"``, a bool is ``"true"``, a list is ``"['a', 'b']"``).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Meta(_Model):
    name: str
    title: str = ""
    description: str = ""
    author: str = ""
    version: str = "0.1.0"
    based_on: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not v or not all(c.isalnum() or c in "-_" for c in v):
            raise ValueError(f"theme name must be a slug (got {v!r})")
        return v


class Requires(_Model):
    packages: list[str] = Field(default_factory=list)
    extensions: list[str] = Field(default_factory=list)
    fonts: list[str] = Field(default_factory=list)


class FileInstall(_Model):
    component: str
    src: str
    dest: str
    mode: Optional[str] = None  # octal string, e.g. "755" for bin scripts


class Setting(_Model):
    component: str
    backend: Literal["gsettings", "dconf"]
    key: str            # "SCHEMA KEY" for gsettings, "/path" for dconf
    value: str          # serialized GVariant text


class Hook(_Model):
    event: Literal["pre", "post"] = "post"
    component: str = "hook"
    sudo: bool = False
    optional: bool = False
    script: str
    restore: Optional[str] = None


class BuildConfig(_Model):
    # Components the render engine is allowed to (re)generate. Anything not
    # listed is treated as hand-authored and never overwritten by `build`.
    managed: list[str] = Field(default_factory=list)


class Theme(_Model):
    meta: Meta
    requires: Requires = Field(default_factory=Requires)
    palette: dict[str, str] = Field(default_factory=dict)
    files: list[FileInstall] = Field(default_factory=list)
    settings: list[Setting] = Field(default_factory=list)
    hooks: list[Hook] = Field(default_factory=list)
    build: BuildConfig = Field(default_factory=BuildConfig)

    # Filled in by the loader; not part of the TOML.
    path: Path = Field(exclude=True)

    def components(self) -> list[str]:
        seen: list[str] = []
        for item in (*self.files, *self.settings, *self.hooks):
            if item.component not in seen:
                seen.append(item.component)
        return seen


def _read_toml(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def load_theme(theme_dir: Path) -> Theme:
    """Load and validate the theme rooted at ``theme_dir``."""
    theme_dir = Path(theme_dir)
    manifest_path = theme_dir / "theme.toml"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"no theme.toml in {theme_dir}")

    data = _read_toml(manifest_path)

    # palette.toml, if present, is the palette source of truth.
    palette_path = theme_dir / "palette.toml"
    if palette_path.is_file():
        data["palette"] = _read_toml(palette_path)

    data["path"] = theme_dir
    return Theme.model_validate(data)
