"""What a Look may write, and what it may never write (C1, H4, H5).

The engine's promise — printed under every preview — is "Looks only change
settings. They can't run programs on your computer." Three findings said that
sentence was unenforced rather than untrue:

* **C1** — a Look's ``dest`` was checked only for being inside ``$HOME``, so
  ``~/.config/autostart/x.desktop`` was a legal target, and the preview
  collapsed it to "23 files".
* **H4** — a Look's settings ``key`` was an unvalidated string, so a custom
  shortcut's ``command``, or "which program opens a terminal", was a legal
  write.
* **H5** — ``confine_src`` implemented "a Look may only read from its own
  folder" and the apply path never called it, so a Look could ship a shortcut
  to a private key and have its contents copied out at a readable permission.

Everything here goes through the real route — ``compile_preset`` and then
``Transaction`` — rather than calling the policy directly, because that is
exactly the gap each finding was: a helper that existed and a path that did not
use it.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from gtheme.core.policy import Tier, file_verdict, setting_verdict
from gtheme.core.transaction import FileWrite, Transaction, TransactionError
from gtheme.preset.compile import compile_preset
from gtheme.preset.model import load_preset_dir

HEADER = """\
format = 2

[meta]
name = "demo"
title = "DEMO"
description = "A Look for a test."
author = "the suite"
version = "1.0.0"
"""


def _look(directory: Path, body: str, files: dict[str, str] | None = None) -> Path:
    """Write a Look folder and return it."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "theme.toml").write_text(HEADER + textwrap.dedent(body), encoding="utf-8")
    for name, contents in (files or {}).items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
    return directory


def _compiled(directory: Path, root: Path):
    preset = load_preset_dir(directory)
    return compile_preset(preset, directory, dest_root=str(root))


# -- C1: destinations ------------------------------------------------------


@pytest.mark.parametrize(
    "dest",
    [
        "~/.config/autostart/gtheme-look.desktop",
        "~/.config/systemd/user/look.service",
        "~/.config/environment.d/look.conf",
        "~/.local/bin/look",
        "~/bin/look",
        "~/.bashrc",
        "~/.zshrc",
        "~/.profile",
        "~/.config/fish/config.fish",
        "~/.config/fish/conf.d/look.fish",
        "~/.local/share/gnome-shell/extensions/look@demo/extension.js",
        "~/.local/share/applications/look.desktop",
    ],
)
def test_a_look_that_writes_a_program_is_refused_whole(engine, tmp_path, dest):
    """C1. Not "that entry is skipped" — the Look does not apply at all.

    A Look that needs to write a login script is not a decorative Look, and
    applying "the rest of it" would be applying something its author never
    designed. The innocent file in the same Look is the assertion that matters:
    it proves the refusal happened before the first byte, the way the
    confinement preflight does.
    """
    directory = _look(
        tmp_path / "demo",
        f"""
        [[files]]
        src = "innocent.css"
        dest = "~/.config/demo/innocent.css"

        [[files]]
        src = "payload"
        dest = "{dest}"
        """,
        {"innocent.css": "/* harmless */", "payload": "#!/bin/sh\nid > /tmp/pwned\n"},
    )
    compiled = _compiled(directory, engine.dest_root)

    assert compiled.refused, "the Look should be refused, and said to be"
    assert any(dest in line for line in compiled.refusals), compiled.refusals
    assert compiled.refusals[0] in compiled.warnings, "a caller reading warnings must see it"

    with pytest.raises(TransactionError):
        compiled.transaction.apply(restore_point=False)
    assert not (engine.dest_root / ".config" / "demo" / "innocent.css").exists()


def test_a_saved_moment_can_still_put_back_a_file_a_look_may_not_write(engine, tmp_path):
    """The refusal is about Looks, not about the machine's own history.

    A restore point describes this computer as it already was. If the policy
    applied to it, "Before gtheme" would refuse to put back a login entry the
    user had before gtheme ever ran — turning a safety feature into a way to
    lose things. A transaction with no ``look`` is not a Look being applied.
    """
    source = tmp_path / "theirs.desktop"
    source.write_text("[Desktop Entry]\n", encoding="utf-8")
    Transaction(
        [FileWrite(src=str(source), dest="~/.config/autostart/theirs.desktop")],
        dest_root=str(engine.dest_root),
        label="My desktop, 25 August",
    ).apply(restore_point=False)

    written = engine.dest_root / ".config" / "autostart" / "theirs.desktop"
    assert written.read_text(encoding="utf-8") == "[Desktop Entry]\n"


def test_a_file_that_can_start_programs_is_named_in_the_preview_not_counted(engine, tmp_path):
    """C1's other half: allowed, never anonymous.

    Three of the four Looks in this repository write ``starship.toml``, whose
    format holds ``command = "…"`` lines that run on every prompt. Refusing it
    would refuse the shipped product; hiding it inside "4 files" is what let
    the safety sentence sit under it. So it is written, and it is named.
    """
    directory = _look(
        tmp_path / "demo",
        """
        [[files]]
        src = "starship.toml"
        dest = "~/.config/starship.toml"

        [[files]]
        src = "wall.png"
        dest = "~/.local/share/backgrounds/demo/wall.png"

        [[files]]
        src = "gtk.css"
        dest = "~/.config/gtk-4.0/gtk.css"
        """,
        {"starship.toml": "format = '$all'\n", "wall.png": "not really a png", "gtk.css": "* {}"},
    )
    compiled = _compiled(directory, engine.dest_root)
    assert not compiled.refused

    lines = compiled.transaction.plan().to_novice_lines()
    assert any("starship.toml" in line for line in lines), lines
    assert "2 files" in lines, "the ordinary two are still counted together"
    assert not any(line == "3 files" for line in lines), lines

    compiled.transaction.apply(restore_point=False)
    assert (engine.dest_root / ".config" / "starship.toml").is_file()


def test_a_desktop_saved_as_a_look_never_carries_something_it_may_not_write(
    engine, tmp_path
):
    """The policy has to hold for gtheme's own output, not only for downloads.

    "Save my desktop as a Look" captures every setting the app can describe —
    and the app describes "which program opens a command window", which is one
    of the settings a Look may not carry. Captured and then applied, that Look
    would be refused whole: the user's own desktop, saved by the app, unable to
    go back on. So the capture leaves it out and says so, which is also what
    makes the sentence written into every saved Look ("it changes settings
    only; it cannot run programs") true rather than decorative.
    """
    from gtheme.preset.capture import capture_share

    keys = [
        "gsettings:org.gnome.desktop.interface icon-theme",
        "gsettings:org.gnome.desktop.default-applications.terminal exec",
    ]
    engine.backend.set(keys[0], "'Papirus'")

    result = capture_share(
        keys,
        engine.backend,
        out_dir=tmp_path / "saved",
        name="saved",
        title="My desktop, 25 August",
    )

    saved = [entry.key for entry in result.preset.settings]
    assert keys[0] in saved
    assert keys[1] not in saved, "a saved desktop must stay applicable"
    assert any("not allowed" in reason for _key, reason in result.skipped), result.skipped

    compiled = compile_preset(
        result.preset, result.path, dest_root=str(engine.dest_root)
    )
    assert not compiled.refused, compiled.refusals


def test_every_shipped_look_stays_applicable(repo_root, tmp_dest_root, memory_settings):
    """The policy is judged against the product it has to keep working.

    All four bundled Looks write a terminal prompt file and a terminal's own
    settings file. If a tier ever grows an entry that refuses one of them, this
    is the test that says so before a person finds out by pressing "Use this
    look".
    """
    del memory_settings  # requested for the isolation seam
    for name in ("magma", "netrunner", "hyperclass", "nightbloom"):
        directory = repo_root / "themes" / name
        compiled = compile_preset(
            load_preset_dir(directory), directory, dest_root=str(tmp_dest_root)
        )
        assert not compiled.refused, f"{name} would no longer apply: {compiled.refusals}"


# -- H4: settings ----------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        (
            "gsettings-path:org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
            ":/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ command"
        ),
        (
            "gsettings-path:org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
            ":/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ binding"
        ),
        "gsettings:org.gnome.desktop.default-applications.terminal exec",
        "gsettings:org.gnome.desktop.session session-name",
        "dconf:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/command",
        "dconf:/org/gnome/desktop/interface/icon-theme",
        "keyfile:/home/someone/.config/autostart/x.desktop:org.a.b:/x/ key",
    ],
)
def test_a_look_that_changes_what_the_desktop_runs_is_refused(engine, tmp_path, key):
    """H4. The op set is closed; what op #2 could address was not.

    The last two are the quieter cases. A raw settings location has no
    description attached, so nothing can check what is being written there —
    which is why a Look may only use that form inside the add-on trees a
    decorative Look legitimately reaches into, and why naming a file to write
    settings straight into is not a Look's business at all.
    """
    directory = _look(
        tmp_path / "demo",
        f"""
        [[files]]
        src = "innocent.css"
        dest = "~/.config/demo/innocent.css"

        [[settings]]
        key = "{key}"
        value = "'anything'"
        """,
        {"innocent.css": "/* harmless */"},
    )
    compiled = _compiled(directory, engine.dest_root)

    assert compiled.refused, compiled.warnings
    with pytest.raises(TransactionError):
        compiled.transaction.apply(restore_point=False)
    assert not (engine.dest_root / ".config" / "demo" / "innocent.css").exists()


def test_the_add_on_locations_the_shipped_looks_use_are_still_allowed(engine, tmp_path):
    """The refusal is a boundary, not a wall: add-on tuning still applies."""
    directory = _look(
        tmp_path / "demo",
        """
        [[settings]]
        key = "dconf:/org/gnome/shell/extensions/blur-my-shell/panel/blur"
        value = "true"
        component = "addons"
        """,
    )
    compiled = _compiled(directory, engine.dest_root)
    assert not compiled.refused, compiled.refusals


def test_a_setting_whose_location_makes_no_sense_is_refused_before_the_apply(engine, tmp_path):
    """H1's first trigger, closed from the front.

    A key with no prefix survived loading, and the failure landed as an
    untyped raise in the middle of an apply — past the rollback. A Look that
    cannot be read is refused before anything happens instead.
    """
    directory = _look(
        tmp_path / "demo",
        """
        [[settings]]
        key = "org.gnome.desktop.interface icon-theme"
        value = "'Papirus'"
        """,
    )
    compiled = _compiled(directory, engine.dest_root)
    assert compiled.refused, compiled.warnings
    with pytest.raises(TransactionError):
        compiled.transaction.apply(restore_point=False)


# -- H5: sources -----------------------------------------------------------


def test_a_look_cannot_siphon_a_file_from_outside_its_own_folder(engine, tmp_path):
    """H5. The exfiltration case, through the apply path this time.

    ``tests/regression/test_confinement_escapes.py`` proves ``confine_src``
    refuses this. It had one production caller, and it was not the apply path,
    so the rule was true of a function nobody called: the Look's own private
    key was copied to a Look-chosen destination at the Look's chosen
    permission, its 0600 discarded.
    """
    secret = tmp_path / "id_ed25519"
    secret.write_text("PRIVATE KEY MATERIAL", encoding="utf-8")
    secret.chmod(0o600)

    directory = _look(
        tmp_path / "demo",
        """
        [[files]]
        src = "files/wallpaper.png"
        dest = "~/.local/share/backgrounds/demo/wallpaper.png"
        mode = "0644"
        """,
    )
    (directory / "files").mkdir()
    (directory / "files" / "wallpaper.png").symlink_to(secret)

    compiled = _compiled(directory, engine.dest_root)
    assert compiled.ops == (), "nothing should have been compiled from that entry"
    assert any("outside this Look's own folder" in line for line in compiled.warnings)

    stolen = engine.dest_root / ".local" / "share" / "backgrounds" / "demo" / "wallpaper.png"
    assert not stolen.exists()


def test_an_absolute_source_does_not_escape_the_look_folder(engine, tmp_path):
    """``Path(base) / "/etc/hostname"`` is ``/etc/hostname``. It always was."""
    directory = _look(
        tmp_path / "demo",
        """
        [[files]]
        src = "/etc/hostname"
        dest = "~/.config/demo/hostname"
        """,
    )
    compiled = _compiled(directory, engine.dest_root)
    assert compiled.ops == ()
    assert any("outside this Look's own folder" in line for line in compiled.warnings)


def test_the_engine_refuses_a_source_that_became_a_shortcut(engine, tmp_path):
    """The re-check, for an op that did not come from the compiler.

    Compiling resolves every source and stores the real location, so a
    transaction's source is a real file inside the Look's folder. Anything else
    is either a hand-built op or a file that changed under the plan, and
    following it would read whatever it now points at.
    """
    secret = tmp_path / "secret"
    secret.write_text("PRIVATE KEY MATERIAL", encoding="utf-8")
    link = tmp_path / "look" / "wallpaper.png"
    link.parent.mkdir()
    link.symlink_to(secret)

    with pytest.raises(TransactionError, match="shortcut"):
        Transaction(
            [FileWrite(src=str(link), dest="~/.config/demo/wallpaper.png")],
            dest_root=str(engine.dest_root),
            label="DEMO",
            look="demo",
        ).apply(restore_point=False)
    assert not (engine.dest_root / ".config" / "demo" / "wallpaper.png").exists()


# -- the tiers themselves --------------------------------------------------


def test_the_tiers_say_what_they_are_for(tmp_dest_root):
    """A verdict carries the words the dialog shows, not just a flag."""
    refused = file_verdict("~/.config/autostart/x.desktop", root=tmp_dest_root)
    assert refused.tier is Tier.REFUSED
    assert refused.reason and refused.what

    named = file_verdict("~/.config/starship.toml", root=tmp_dest_root)
    assert named.tier is Tier.CONSEQUENTIAL
    assert named.named and named.what == "starship.toml"

    ordinary = file_verdict("~/.config/gtk-4.0/gtk.css", root=tmp_dest_root)
    assert ordinary.tier is Tier.ALLOWED
    assert not ordinary.refused and not ordinary.named

    assert setting_verdict("gsettings:org.gnome.desktop.interface icon-theme").tier is Tier.ALLOWED
    # A token that is not filled in yet is nobody's verdict: the apply asks
    # again with the real value, and refuses to write a half-resolved one.
    unresolved = "dconf:/org/gnome/Ptyxis/Profiles/{{ ptyxis_default_profile }}/palette"
    assert setting_verdict(unresolved).tier is Tier.ALLOWED
