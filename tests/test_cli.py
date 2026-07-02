"""Tests for the CLI layer: parser polish, typo hints, consent gates, output shaping.

Everything runs hermetically: no network (remote calls are monkeypatched), no
real HOME writes (commands under test either die before touching disk or have
their engine calls stubbed).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from gtheme import cli
from gtheme.engine.apply import Diff
from gtheme.errors import GthemeError


def _ns(**kw) -> argparse.Namespace:
    base = dict(
        name=None, only=None, dry_run=False, no_sudo=False, no_hooks=False,
        yes=False, wipe=False, summary=False, force=False, insecure=False,
        allow_unsafe=False, source=None, query=None, title=None, output=None,
        verbose=False, remote=False,
    )
    base.update(kw)
    base.setdefault("all", False)
    return argparse.Namespace(**base)


# --- parser polish (cli-ux-1 / cli-ux-7 / cli-ux-8) --------------------------


def test_usage_has_no_brace_blob():
    usage = cli.build_parser().format_usage()
    assert "<command>" in usage
    assert "{menu" not in usage


def test_help_has_examples_epilog():
    assert "examples:" in cli.build_parser().format_help()


def test_switch_is_alias_of_apply():
    p = cli.build_parser()
    args = p.parse_args(["switch", "x"])
    assert args.func is cli.cmd_apply
    assert args.no_hooks is False  # full apply flag set, not a drifted copy


def test_apply_flags_have_help_text():
    p = cli.build_parser()
    sub = next(a for a in p._actions if isinstance(a, argparse._SubParsersAction))
    help_text = sub.choices["apply"].format_help()
    assert "show what would change without writing anything" in help_text
    assert "theme to apply" in help_text


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["-v", "apply", "x"], True),
        (["apply", "x", "-v"], True),
        (["-v", "apply", "x", "-v"], True),
        (["apply", "x"], False),
    ],
)
def test_verbose_accepted_before_and_after_subcommand(argv, expected):
    assert cli.build_parser().parse_args(argv).verbose is expected


# --- did-you-mean (cli-ux-2) --------------------------------------------------


def test_mistyped_command_suggests(capsys):
    assert cli.main(["aply", "nsx"]) == 2
    err = capsys.readouterr().err
    assert "did you mean 'apply'" in err


def test_mistyped_theme_suggests(monkeypatch, capsys):
    monkeypatch.setattr(cli, "find", lambda n: None)
    monkeypatch.setattr(cli, "discover", lambda: {"nsx": Path("/x")})
    with pytest.raises(SystemExit) as exc:
        cli._load_named("nsxx")
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "did you mean: nsx?" in err
    assert "available: nsx" in err


# --- bare invocation runs the menu even off-TTY (live-probe-7) -----------------


def test_bare_invocation_runs_menu(monkeypatch):
    import gtheme.menu as menu

    monkeypatch.setattr(menu, "run", lambda: 42)
    assert cli.main([]) == 42


def test_plain_flag_sets_env(monkeypatch):
    import gtheme.menu as menu

    monkeypatch.setattr(menu, "run", lambda: 0)
    monkeypatch.delenv("GTHEME_PLAIN", raising=False)
    cli.main(["--plain"])
    assert os.environ.get("GTHEME_PLAIN") == "1"


def test_bare_invocation_menu_errors_print_one_clean_line(monkeypatch, capsys):
    # Engine errors escaping the menu (e.g. the process lock) must hit the same
    # handler as subcommands: one ✗ line + exit 1, never a raw traceback.
    import gtheme.menu as menu

    def boom():
        raise GthemeError("another gtheme is already applying/restoring — wait for it to finish")

    monkeypatch.setattr(menu, "run", boom)
    assert cli.main([]) == 1
    err = capsys.readouterr().err
    assert "another gtheme is already applying/restoring" in err
    assert "Traceback" not in err


# --- restore: empty baseline & hooks footer (cli-ux-4 / live-probe-10) ---------


class _StubBaseline:
    def __init__(self, empty=True, hooks=()):
        self.is_empty = empty
        self.hooks = list(hooks)
        self.warnings = []

    def load(self):
        return self


def test_restore_empty_baseline_single_friendly_line(monkeypatch, capsys):
    import gtheme.backup as backup

    monkeypatch.setattr(backup, "Baseline", lambda: _StubBaseline(empty=True))
    rc = cli.cmd_restore(_ns())
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip() == "nothing to restore — no theme has been applied yet"


def _restore_with_warnings(monkeypatch, warnings):
    import gtheme.backup as backup

    monkeypatch.setattr(backup, "Baseline", lambda: _StubBaseline(empty=False))
    monkeypatch.setattr(cli.engine, "restore", lambda **kw: (["reverted x"], warnings, False))


def test_restore_footer_not_shown_for_non_hook_warning(monkeypatch, capsys):
    _restore_with_warnings(monkeypatch, ["something unrelated went sideways"])
    assert cli.cmd_restore(_ns()) == 0
    assert "hooks were skipped" not in capsys.readouterr().out


def test_restore_footer_shown_for_actual_hook_skip(monkeypatch, capsys):
    _restore_with_warnings(monkeypatch, ["skipped sudo restore hook x.sh (--no-sudo)"])
    assert cli.cmd_restore(_ns()) == 0
    assert "hooks were skipped" in capsys.readouterr().out


# --- update: named-target errors (cli-ux-3) ------------------------------------


def test_update_unknown_name_dies_with_candidates(tmp_path, monkeypatch, capsys):
    import gtheme.paths as paths

    monkeypatch.setattr(paths, "INSTALLED_THEMES_DIR", tmp_path / "installed")
    monkeypatch.setattr(cli, "find", lambda n: None)
    monkeypatch.setattr(cli, "discover", lambda: {"nsx": Path("/x")})
    with pytest.raises(SystemExit) as exc:
        cli.cmd_update(_ns(name="bogus"))
    assert exc.value.code == 1
    assert "theme not found: bogus" in capsys.readouterr().err


def test_update_bundled_only_name_explains(tmp_path, monkeypatch, capsys):
    import gtheme.paths as paths

    monkeypatch.setattr(paths, "INSTALLED_THEMES_DIR", tmp_path / "installed")
    monkeypatch.setattr(cli, "find", lambda n: Path("/somewhere/nsx"))
    with pytest.raises(SystemExit):
        cli.cmd_update(_ns(name="nsx"))
    assert "bundled theme" in capsys.readouterr().err


def test_update_no_origin_explains(tmp_path, monkeypatch, capsys):
    import gtheme.paths as paths

    d = tmp_path / "installed" / "foo"
    d.mkdir(parents=True)
    (d / "theme.toml").write_text('[meta]\nname = "foo"\n')
    monkeypatch.setattr(paths, "INSTALLED_THEMES_DIR", tmp_path / "installed")
    with pytest.raises(SystemExit):
        cli.cmd_update(_ns(name="foo"))
    assert "no recorded origin" in capsys.readouterr().err


# --- non-GNOME guard (onboarding-3) --------------------------------------------


def _kde(monkeypatch):
    monkeypatch.delenv("GTHEME_ASSUME_GNOME", raising=False)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setenv("DESKTOP_SESSION", "plasma")


def _dummy_theme():
    return SimpleNamespace(
        meta=SimpleNamespace(name="x", title="X"), components=lambda: ["gtk"]
    )


def test_apply_refuses_non_gnome_non_interactive(monkeypatch, capsys):
    _kde(monkeypatch)
    monkeypatch.setattr(cli, "_load_named", lambda n: _dummy_theme())
    with pytest.raises(SystemExit) as exc:
        cli.cmd_apply(_ns(name="x"))
    assert exc.value.code == 1
    assert "refusing to apply outside GNOME" in capsys.readouterr().err


def test_apply_non_gnome_passes_with_yes(monkeypatch):
    _kde(monkeypatch)
    monkeypatch.setattr(cli, "_load_named", lambda n: _dummy_theme())
    res = SimpleNamespace(hooks_run=[], warnings=[], notes=[], failed=False,
                          applied_files=0, applied_settings=0)
    monkeypatch.setattr(cli.engine, "apply", lambda *a, **kw: res)
    assert cli.cmd_apply(_ns(name="x", yes=True)) == 0


def test_apply_non_gnome_guard_skipped_for_dry_run(monkeypatch):
    _kde(monkeypatch)
    monkeypatch.setattr(cli, "_load_named", lambda n: _dummy_theme())
    monkeypatch.setattr(cli.engine, "compute_diffs", lambda *a, **kw: [])
    res = SimpleNamespace(hooks_run=[], warnings=[], notes=[], failed=False,
                          applied_files=0, applied_settings=0)
    monkeypatch.setattr(cli.engine, "apply", lambda *a, **kw: res)
    assert cli.cmd_apply(_ns(name="x", dry_run=True)) == 0


def test_gtheme_assume_gnome_env_override(monkeypatch):
    _kde(monkeypatch)
    monkeypatch.setenv("GTHEME_ASSUME_GNOME", "1")
    assert cli._desktop_is_gnome() is True


# --- search --remote & suggestion (critic-6) -------------------------------------


def test_search_local_miss_suggests_remote(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_all", lambda: ([], []))
    assert cli.cmd_search(_ns(query="zzz")) == 1
    assert "search --remote" in capsys.readouterr().out


def test_search_remote_lists_index_matches(monkeypatch, capsys):
    from gtheme.engine import remote

    monkeypatch.setattr(
        remote, "fetch_index",
        lambda: [{"name": "nsx", "title": "NSX", "description": "red"},
                 {"name": "other", "title": "", "description": ""}],
    )
    assert cli.cmd_search(_ns(query="nsx", remote=True)) == 0
    out = capsys.readouterr().out
    assert "nsx" in out and "install with" in out and "other" not in out


def test_search_remote_offline_friendly_error(monkeypatch, capsys):
    from gtheme.engine import remote

    def boom():
        raise GthemeError("could not fetch the community theme index — are you online?")

    monkeypatch.setattr(remote, "fetch_index", boom)
    with pytest.raises(SystemExit) as exc:
        cli.cmd_search(_ns(query="nsx", remote=True))
    assert exc.value.code == 1
    assert "are you online" in capsys.readouterr().err


# --- install: community-collection fallback (critic-6) ---------------------------


def _fallback_env(monkeypatch, index, install_result):
    from gtheme.engine import remote

    def fake_install(source, **kw):
        if source == remote.DEFAULT_REMOTE:
            return install_result
        raise FileNotFoundError(f"no such theme {source!r}")

    monkeypatch.setattr(remote, "fetch_index", lambda: index)
    monkeypatch.setattr(remote, "install", fake_install)


def test_install_bare_name_falls_back_to_community_with_yes(monkeypatch, capsys):
    _fallback_env(monkeypatch, [{"name": "communal", "title": "Communal"}], ["communal"])
    assert cli.cmd_install(_ns(source="communal", yes=True)) == 0
    assert "installed communal" in capsys.readouterr().out


def test_install_fallback_requires_yes_non_interactive(monkeypatch, capsys):
    _fallback_env(monkeypatch, [{"name": "communal"}], ["communal"])
    with pytest.raises(SystemExit):
        cli.cmd_install(_ns(source="communal"))
    assert "--yes" in capsys.readouterr().err


def test_install_fallback_skipped_when_offline(monkeypatch, capsys):
    from gtheme.engine import remote

    def offline():
        raise GthemeError("no network")

    def fake_install(source, **kw):
        raise FileNotFoundError(f"no such theme {source!r}")

    monkeypatch.setattr(remote, "fetch_index", offline)
    monkeypatch.setattr(remote, "install", fake_install)
    with pytest.raises(SystemExit):
        cli.cmd_install(_ns(source="communal", yes=True))
    # falls back to the plain local error, not a network crash
    assert "no such theme" in capsys.readouterr().err


def test_install_fallback_rejects_non_ascii_names(monkeypatch):
    # Same ASCII-only rule as safe_theme_name: homograph names must not even
    # reach the index lookup / network path.
    from gtheme.engine import remote

    def netcall():
        raise AssertionError("network must not be touched for a non-ASCII name")

    monkeypatch.setattr(remote, "fetch_index", netcall)
    assert cli._install_from_community(_ns(source="ｎｓｘ", yes=True)) is None


# --- diff output shaping (live-probe-5) ------------------------------------------


def _flood_diffs():
    home = str(Path.home())
    diffs = [
        Diff("file", f"{home}/.local/share/x/ascii/f{i}.txt", "ascii", "new")
        for i in range(7)
    ]
    diffs.append(Diff("file", f"{home}/.config/starship.toml", "prompt", "changed", "a -> b"))
    diffs.append(Diff("setting", "org.gnome.x y", "desktop", "new", "None -> 1"))
    return diffs


def test_print_diffs_groups_new_file_floods(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_VERBOSE", False)
    cli._print_diffs(_flood_diffs(), show_detail=False)
    out = capsys.readouterr().out
    assert "7 files under ~/.local/share/x/ascii/" in out
    assert "f3.txt" not in out                      # individual lines collapsed
    assert "~/.config/starship.toml" in out         # CHANGE kept, tilde-shortened
    assert "org.gnome.x y" in out                   # settings kept verbatim


def test_print_diffs_verbose_lists_everything(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_VERBOSE", True)
    cli._print_diffs(_flood_diffs(), show_detail=False)
    out = capsys.readouterr().out
    assert "files under" not in out
    assert "f3.txt" in out


# --- misc hints (cli-ux-9 / live-probe-6) -----------------------------------------


def test_capture_hint_names_theme(monkeypatch, capsys):
    import gtheme.engine.capture as capture

    monkeypatch.setattr(capture, "capture", lambda name, title=None: (Path("/x"), []))
    assert cli.cmd_capture(_ns(name="livecap")) == 0
    assert "gtheme apply livecap --dry-run" in capsys.readouterr().out


def test_export_hint_uses_zip_name(tmp_path, monkeypatch, capsys):
    import gtheme.engine.export as export

    out = tmp_path / "mytheme.zip"
    out.write_bytes(b"x")
    monkeypatch.setattr(export, "export_theme", lambda name, out=None: (Path(out), 1))
    assert cli.cmd_export(_ns(name="mytheme", output=str(out))) == 0
    assert "gtheme install mytheme.zip" in capsys.readouterr().out
