"""Lifecycle tests for the baseline/restore/switch-cleanup/ledger state machine.

Everything runs hermetically: paths.* are monkeypatched to tmp_path and the
gsettings/dconf backends are replaced with an in-memory store, so no test ever
touches the real $HOME or runs a real gsettings/dconf write.

Covers the audit regressions: BL0 failed-revert blob safety, BL1 restore
consumes the baseline, BL2 --only is not a switch, BL3 AS4 rollback keeps
prior epoch state, BL4 missing blobs never wedge restore, plus the lock,
special-file, '//'-dconf, schema-skip and extension-merge fixes.
"""

from __future__ import annotations

import fcntl
import os
from types import SimpleNamespace

import pytest

from gtheme import backup, paths, settings
from gtheme.engine import apply as apply_mod
from gtheme.errors import GthemeError
from gtheme.manifest import Theme


# ------------------------------------------------------------------ fixtures ---
@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Reroot every gtheme path to tmp_path and fake the settings backends."""
    home = tmp_path / "home"
    home.mkdir()
    state = tmp_path / "state" / "gtheme"
    data = tmp_path / "data" / "gtheme"
    monkeypatch.setattr(paths, "DEST_ROOT", home)
    monkeypatch.setattr(paths, "XDG_DATA_HOME", tmp_path / "data")
    monkeypatch.setattr(paths, "DATA_DIR", data)
    monkeypatch.setattr(paths, "STATE_DIR", state)
    monkeypatch.setattr(paths, "INSTALLED_THEMES_DIR", data / "themes")
    monkeypatch.setattr(paths, "BACKUP_DIR", state / "backups")
    monkeypatch.setattr(paths, "BASELINE_DIR", state / "backups" / "baseline")
    monkeypatch.setattr(paths, "CURRENT_FILE", state / "current")
    monkeypatch.setattr(backup, "_LEDGER_FILE", state / "ownership.json")

    # In-memory gsettings/dconf. Keys: "g:<schema> <key>" / "d:<path>".
    store: dict[str, str] = {}

    def g_get(schema, key):
        return store.get(f"g:{schema} {key}")

    def g_set(schema, key, val):
        store[f"g:{schema} {key}"] = val
        return True, ""

    def g_reset(schema, key):
        store.pop(f"g:{schema} {key}", None)
        return True, ""

    def d_read(path):
        return store.get(f"d:{path}")

    def d_write(path, val):
        store[f"d:{path}"] = val
        return True, ""

    def d_reset(path):
        store.pop(f"d:{path}", None)
        return True, ""

    monkeypatch.setattr(settings, "gsettings_get", g_get)
    monkeypatch.setattr(settings, "gsettings_set", g_set)
    monkeypatch.setattr(settings, "gsettings_reset", g_reset)
    monkeypatch.setattr(settings, "dconf_read", d_read)
    monkeypatch.setattr(settings, "dconf_write", d_write)
    monkeypatch.setattr(settings, "dconf_reset", d_reset)
    monkeypatch.setattr(apply_mod, "backend_available", lambda b: True)
    monkeypatch.setattr(apply_mod, "_has_session_bus", lambda: True)
    settings.runtime_context.cache_clear()
    yield SimpleNamespace(home=home, state=state, store=store, tmp=tmp_path)
    settings.runtime_context.cache_clear()  # drop ctx built against the fake


def make_theme(root, name, files=(), settings_=(), requires=None) -> Theme:
    """Build a loaded Theme; files = (component, relsrc, dest, content)."""
    tdir = root / "themes" / name
    entries = []
    for comp, relsrc, dest, content in files:
        src = tdir / "files" / relsrc
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(content)
        entries.append({"component": comp, "src": f"files/{relsrc}", "dest": dest})
    tdir.mkdir(parents=True, exist_ok=True)
    data = {"meta": {"name": name}, "files": entries,
            "settings": [dict(s) for s in settings_], "path": tdir}
    if requires:
        data["requires"] = requires
    return Theme.model_validate(data)


def _blobs(sandbox):
    d = paths.BASELINE_DIR / "files"
    return sorted(p.name for p in d.glob("*")) if d.is_dir() else []


# ------------------------------------------------------- apply/restore roundtrip ---
def test_roundtrip_existing_file(sandbox):
    dest = sandbox.home / ".config" / "app.conf"
    dest.parent.mkdir(parents=True)
    dest.write_text("PRISTINE")
    theme = make_theme(sandbox.tmp, "alpha", files=[("c", "app.conf", "~/.config/app.conf", "THEMED")])

    res = apply_mod.apply(theme)
    assert not res.failed and dest.read_text() == "THEMED"
    assert backup.read_current() == "alpha"

    log, warns, hard = apply_mod.restore()
    assert not hard and dest.read_text() == "PRISTINE"
    # BL1: a successful full restore consumes records + blobs and clears state.
    b = backup.Baseline().load()
    assert not b.files and not b.settings
    assert _blobs(sandbox) == []
    assert backup.read_current() is None
    assert backup.read_ledger() == {}


def test_roundtrip_new_file_prunes_dir_skeleton(sandbox):
    keep = sandbox.home / ".local" / "share" / "keep.txt"
    keep.parent.mkdir(parents=True)
    keep.write_text("mine")
    theme = make_theme(sandbox.tmp, "alpha",
                       files=[("c", "gtk.css", "~/.local/share/themes/X/gtk-4.0/gtk.css", "css")])
    apply_mod.apply(theme)
    dest = sandbox.home / ".local/share/themes/X/gtk-4.0/gtk.css"
    assert dest.read_text() == "css"

    _, _, hard = apply_mod.restore()
    assert not hard and not dest.exists()
    # The mkdir-ed skeleton is gone; pre-existing dirs (still in use) survive.
    assert not (sandbox.home / ".local/share/themes").exists()
    assert keep.read_text() == "mine"


def test_roundtrip_symlink_dest(sandbox):
    target = sandbox.home / "real.conf"
    target.write_text("TARGET")
    dest = sandbox.home / "link.conf"
    dest.symlink_to(target)
    theme = make_theme(sandbox.tmp, "alpha", files=[("c", "l.conf", "~/link.conf", "THEMED")])

    apply_mod.apply(theme)
    assert not dest.is_symlink() and dest.read_text() == "THEMED"

    _, _, hard = apply_mod.restore()
    assert not hard
    assert dest.is_symlink() and os.readlink(dest) == str(target)
    assert target.read_text() == "TARGET"


def test_roundtrip_settings(sandbox):
    sandbox.store["g:org.x key"] = "'old'"
    theme = make_theme(sandbox.tmp, "alpha", settings_=[
        {"component": "c", "backend": "gsettings", "key": "org.x key", "value": "'new'"},
        {"component": "c", "backend": "dconf", "key": "/a/b", "value": "'fresh'"},
    ])
    res = apply_mod.apply(theme)
    assert res.applied_settings == 2
    assert sandbox.store["g:org.x key"] == "'new'" and sandbox.store["d:/a/b"] == "'fresh'"

    _, _, hard = apply_mod.restore()
    assert not hard
    assert sandbox.store["g:org.x key"] == "'old'"
    assert "d:/a/b" not in sandbox.store  # no prior value -> reset


# ------------------------------------------------------------- switch cleanup ---
def test_switch_cleanup_reverts_orphans(sandbox):
    wall = sandbox.home / "wall.txt"
    wall.write_text("PRISTINE-WALL")
    a = make_theme(sandbox.tmp, "aaa", files=[
        ("gtk", "g.css", "~/.g/gtk.css", "A-GTK"),
        ("wall", "w.txt", "~/wall.txt", "A-WALL"),
    ])
    b = make_theme(sandbox.tmp, "bbb", files=[("gtk", "g.css", "~/.g/gtk.css", "B-GTK")])

    apply_mod.apply(a)
    apply_mod.apply(b)
    # A's wall.txt is an orphan: reverted to pristine and forgotten.
    assert wall.read_text() == "PRISTINE-WALL"
    assert (sandbox.home / ".g/gtk.css").read_text() == "B-GTK"
    assert list(backup.read_ledger()) == ["bbb"]
    bl = backup.Baseline().load()
    assert str(wall) not in bl.files  # forgotten (it reverted)
    assert str(sandbox.home / ".g/gtk.css") in bl.files  # shared dest kept


def test_switch_cleanup_failed_revert_keeps_record_and_blob(sandbox):
    # BL0: a transient revert failure must NOT forget the record or delete the
    # only pristine copy — `gtheme restore` must still recover it later.
    prot = sandbox.home / "protected"
    prot.mkdir()
    dest = prot / "a.conf"
    dest.write_text("PRISTINE")
    a = make_theme(sandbox.tmp, "aaa", files=[("c", "a.conf", "~/protected/a.conf", "A")])
    b = make_theme(sandbox.tmp, "bbb", files=[("c", "b.conf", "~/b.conf", "B")])

    apply_mod.apply(a)
    key = str(dest)
    blob = backup.Baseline().load().files[key]["backup"]
    prot.chmod(0o555)  # make the revert fail (unlink denied)
    try:
        res = apply_mod.apply(b)
    finally:
        prot.chmod(0o755)
    assert any("could not be reverted" in w for w in res.warnings)
    bl = backup.Baseline().load()
    assert key in bl.files  # record kept
    assert (paths.BASELINE_DIR / "files" / blob).is_file()  # blob kept
    assert dest.read_text() == "A"  # still themed, as warned

    _, _, hard = apply_mod.restore()  # the safety net still works
    assert not hard and dest.read_text() == "PRISTINE"


def test_switch_cleanup_missing_blob_keeps_record(sandbox):
    # BL0 nuance: a dead record stays through switch-cleanup so the eventual
    # full restore warns loudly instead of silently claiming success.
    dest = sandbox.home / "a.conf"
    dest.write_text("PRISTINE")
    a = make_theme(sandbox.tmp, "aaa", files=[("c", "a.conf", "~/a.conf", "A")])
    b = make_theme(sandbox.tmp, "bbb", files=[("c", "b.conf", "~/b.conf", "B")])

    apply_mod.apply(a)
    blob = backup.Baseline().load().files[str(dest)]["backup"]
    (paths.BASELINE_DIR / "files" / blob).unlink()
    res = apply_mod.apply(b)
    assert any("backup blob missing" in w for w in res.warnings)
    assert str(dest) in backup.Baseline().load().files

    # BL4: the dead record is warned about, dropped, and never wedges restore.
    _, warns, hard = apply_mod.restore()
    assert not hard
    assert any(str(dest) in w and "blob missing" in w for w in warns)
    assert backup.read_current() is None
    assert not backup.Baseline().load().files


# ------------------------------------------------------------------ --only ---
def test_only_apply_is_not_a_switch(sandbox):
    # BL2: `apply B --only gtk` must not strip the rest of theme A.
    wall = sandbox.home / "wall.txt"
    wall.write_text("PRISTINE-WALL")
    a = make_theme(sandbox.tmp, "aaa", files=[
        ("gtk", "g.css", "~/.g/gtk.css", "A-GTK"),
        ("wall", "w.txt", "~/wall.txt", "A-WALL"),
    ])
    b = make_theme(sandbox.tmp, "bbb", files=[("gtk", "g.css", "~/.g/gtk.css", "B-GTK")])
    c = make_theme(sandbox.tmp, "ccc", files=[("c", "c.conf", "~/c.conf", "C")])

    apply_mod.apply(a)
    apply_mod.apply(b, only={"gtk"})
    assert wall.read_text() == "A-WALL"  # overlay left the rest alone
    assert (sandbox.home / ".g/gtk.css").read_text() == "B-GTK"
    assert set(backup.read_ledger()) == {"aaa", "bbb"}

    # A later FULL apply still cleans up across ALL ledger entries.
    apply_mod.apply(c)
    assert wall.read_text() == "PRISTINE-WALL"
    assert not (sandbox.home / ".g/gtk.css").exists()
    assert list(backup.read_ledger()) == ["ccc"]


def test_only_ledger_accumulates(sandbox):
    theme = make_theme(sandbox.tmp, "alpha", files=[
        ("c1", "a.conf", "~/a.conf", "A"),
        ("c2", "b.conf", "~/b.conf", "B"),
    ])
    apply_mod.apply(theme, only={"c1"})
    apply_mod.apply(theme, only={"c2"})
    ent = backup.read_ledger()["alpha"]
    assert set(ent["files"]) == {str(sandbox.home / "a.conf"), str(sandbox.home / "b.conf")}


def test_reapply_is_idempotent(sandbox):
    dest = sandbox.home / "a.conf"
    dest.write_text("PRISTINE")
    theme = make_theme(sandbox.tmp, "alpha", files=[("c", "a.conf", "~/a.conf", "THEMED")])
    apply_mod.apply(theme)
    apply_mod.apply(theme)
    assert _blobs(sandbox) == ["0001"]  # snapshot never overwritten or duplicated
    assert (paths.BASELINE_DIR / "files" / "0001").read_text() == "PRISTINE"
    _, _, hard = apply_mod.restore()
    assert not hard and dest.read_text() == "PRISTINE"


# ------------------------------------------------------------- bug regressions ---
def test_restore_reapply_keeps_user_edits(sandbox):
    # BL1: apply -> restore -> user edits -> apply -> restore must return the
    # EDITED state (the pre-gtheme state of the second epoch), not the ancient v0.
    dest = sandbox.home / "gtk.css"
    dest.write_text("PRISTINE-v0")
    theme = make_theme(sandbox.tmp, "alpha", files=[("c", "g.css", "~/gtk.css", "THEMED")])

    apply_mod.apply(theme)
    apply_mod.restore()
    dest.write_text("USER-EDIT-v1")
    apply_mod.apply(theme)
    assert dest.read_text() == "THEMED"
    _, _, hard = apply_mod.restore()
    assert not hard and dest.read_text() == "USER-EDIT-v1"


def test_as4_rollback_keeps_prior_epoch(sandbox, monkeypatch):
    # BL3: a no-bus re-apply must not destroy ownership from earlier applies.
    theme = make_theme(
        sandbox.tmp, "tx",
        files=[("gtk", "g.css", "~/.g/gtk.css", "T")],
        settings_=[{"component": "looks", "backend": "gsettings",
                    "key": "org.x looks", "value": "'v'"}],
    )
    apply_mod.apply(theme, only={"gtk"})
    monkeypatch.setattr(apply_mod, "_has_session_bus", lambda: False)
    res = apply_mod.apply(theme, only={"looks"})
    assert res.failed
    assert backup.read_current() == "tx"
    assert backup.read_ledger()["tx"]["files"] == [str(sandbox.home / ".g/gtk.css")]


def test_as4_overlay_restores_prev_current(sandbox, monkeypatch):
    # BL3 cross-theme: an overlay that applied nothing re-points current at the
    # still-fully-applied previous theme (no switch-cleanup ran).
    a = make_theme(sandbox.tmp, "aaa", files=[("c", "a.conf", "~/a.conf", "A")])
    b = make_theme(sandbox.tmp, "bbb", settings_=[
        {"component": "s", "backend": "gsettings", "key": "org.x k", "value": "'v'"}])
    apply_mod.apply(a)
    monkeypatch.setattr(apply_mod, "_has_session_bus", lambda: False)
    res = apply_mod.apply(b, only={"s"})
    assert res.failed
    assert backup.read_current() == "aaa"
    assert list(backup.read_ledger()) == ["aaa"]
    assert (sandbox.home / "a.conf").read_text() == "A"


def test_missing_blob_never_wedges_restore(sandbox):
    # BL4: one lost blob must not block the rest of the revert or state clearing.
    d1 = sandbox.home / "a.conf"
    d1.write_text("PRISTINE-A")
    d2 = sandbox.home / "b.conf"
    d2.write_text("PRISTINE-B")
    theme = make_theme(sandbox.tmp, "alpha", files=[
        ("c", "a.conf", "~/a.conf", "A"), ("c", "b.conf", "~/b.conf", "B")])
    apply_mod.apply(theme)
    blob = backup.Baseline().load().files[str(d1)]["backup"]
    (paths.BASELINE_DIR / "files" / blob).unlink()

    log, warns, hard = apply_mod.restore()
    assert not hard  # completes despite the dead record
    assert any("blob missing" in w for w in warns)
    assert any("dropped 1 baseline record" in w for w in warns)
    assert d2.read_text() == "PRISTINE-B"
    assert backup.read_current() is None and backup.read_ledger() == {}
    # A second restore has nothing left to trip over.
    _, warns2, hard2 = apply_mod.restore()
    assert not hard2 and any("nothing to restore" in w for w in warns2)


def test_transient_failure_keeps_recovery_state(sandbox):
    # R1 with the new per-key logic: a transient failure keeps record + blob +
    # current, and a later retry succeeds.
    prot = sandbox.home / "protected"
    prot.mkdir()
    dest = prot / "a.conf"
    dest.write_text("PRISTINE")
    theme = make_theme(sandbox.tmp, "alpha", files=[("c", "a.conf", "~/protected/a.conf", "A")])
    apply_mod.apply(theme)
    prot.chmod(0o555)
    try:
        _, warns, hard = apply_mod.restore()
    finally:
        prot.chmod(0o755)
    assert hard and any("failed to restore" in w for w in warns)
    assert backup.read_current() == "alpha"
    assert str(dest) in backup.Baseline().load().files
    _, _, hard2 = apply_mod.restore()
    assert not hard2 and dest.read_text() == "PRISTINE"


# ------------------------------------------------------------ hardening extras ---
def test_process_lock_fails_fast(sandbox):
    theme = make_theme(sandbox.tmp, "alpha", files=[("c", "a.conf", "~/a.conf", "A")])
    paths.ensure_state_dirs()
    fd = os.open(paths.STATE_DIR / "lock", os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        with pytest.raises(GthemeError, match="another gtheme"):
            apply_mod.apply(theme)
        with pytest.raises(GthemeError, match="another gtheme"):
            apply_mod.restore()
        assert not (sandbox.home / "a.conf").exists()  # nothing was written
    finally:
        os.close(fd)


def test_special_file_dest_is_skipped(sandbox):
    fifo = sandbox.home / "pipe.conf"
    os.mkfifo(fifo)
    theme = make_theme(sandbox.tmp, "alpha", files=[
        ("c", "p.conf", "~/pipe.conf", "X"), ("c", "a.conf", "~/a.conf", "A")])
    res = apply_mod.apply(theme)
    assert not res.failed  # a stray FIFO must not fail (or hang) the apply
    assert any("special file" in w for w in res.warnings)
    import stat
    assert stat.S_ISFIFO(fifo.lstat().st_mode)  # untouched
    assert str(fifo) not in backup.Baseline().load().files  # no junk record
    assert (sandbox.home / "a.conf").read_text() == "A"  # rest applied


def test_double_slash_dconf_key_is_skipped(sandbox):
    # live-probe-0 engine guard: an empty placeholder collapsed to '//'.
    theme = make_theme(sandbox.tmp, "alpha",
                       files=[("c", "a.conf", "~/a.conf", "A")],
                       settings_=[{"component": "term", "backend": "dconf",
                                   "key": "/org/gnome/Ptyxis/Profiles//palette",
                                   "value": "'p'"}])
    res = apply_mod.apply(theme)
    assert not res.failed
    assert any("invalid dconf path" in w for w in res.warnings)
    assert not any("/Profiles//" in k for k in sandbox.store)
    assert not backup.Baseline().load().settings
    assert backup.read_ledger()["alpha"]["settings"] == []


def test_missing_schema_is_soft_skip(sandbox, monkeypatch):
    # docs-themes-5: 'No such schema/key' is a per-setting skip, not a failure.
    real_set = settings.gsettings_set

    def flaky_set(schema, key, val):
        if schema == "org.gnome.Ptyxis":
            return False, "No such schema “org.gnome.Ptyxis”"
        return real_set(schema, key, val)

    monkeypatch.setattr(settings, "gsettings_set", flaky_set)
    theme = make_theme(sandbox.tmp, "alpha", settings_=[
        {"component": "c", "backend": "gsettings", "key": "org.gnome.Ptyxis font", "value": "'m'"},
        {"component": "c", "backend": "gsettings", "key": "org.x k", "value": "'v'"},
    ])
    res = apply_mod.apply(theme)
    assert not res.failed
    assert any("not on this system" in w for w in res.warnings)
    assert res.applied_settings == 1
    assert "gsettings:org.gnome.Ptyxis font" not in backup.Baseline().load().settings


def test_enabled_extensions_merge(sandbox):
    # docs-themes-3a: merge into the user's list; baseline restores the exact old value.
    sandbox.store["g:org.gnome.shell enabled-extensions"] = "['user@ext']"
    theme = make_theme(sandbox.tmp, "alpha", settings_=[
        {"component": "shell", "backend": "gsettings",
         "key": "org.gnome.shell enabled-extensions", "value": "['a@theme', 'b@theme']"}])
    res = apply_mod.apply(theme)
    assert not res.failed
    assert sandbox.store["g:org.gnome.shell enabled-extensions"] == \
        "['user@ext', 'a@theme', 'b@theme']"
    _, _, hard = apply_mod.restore()
    assert not hard
    assert sandbox.store["g:org.gnome.shell enabled-extensions"] == "['user@ext']"


def test_enabled_extensions_merge_falls_back_on_garbage(sandbox):
    sandbox.store["g:org.gnome.shell enabled-extensions"] = "@as []"  # unparsable
    theme = make_theme(sandbox.tmp, "alpha", settings_=[
        {"component": "shell", "backend": "gsettings",
         "key": "org.gnome.shell enabled-extensions", "value": "['a@theme']"}])
    apply_mod.apply(theme)
    assert sandbox.store["g:org.gnome.shell enabled-extensions"] == "['a@theme']"


def test_check_requires_extensions(sandbox, monkeypatch):
    # docs-themes-3b: [requires].extensions is verified (warn-only).
    ext = paths.XDG_DATA_HOME / "gnome-shell" / "extensions" / "present@here"
    ext.mkdir(parents=True)
    monkeypatch.setattr(apply_mod.shutil, "which", lambda name: None)
    theme = make_theme(sandbox.tmp, "reqs",
                       requires={"extensions": ["present@here", "missing@nope"]})
    warns = apply_mod.check_requires(theme)
    assert any("missing@nope" in w for w in warns)
    assert not any("present@here" in w for w in warns)


def test_corrupt_files_json_recovers_from_bak(sandbox):
    d1 = sandbox.home / "a.conf"
    d1.write_text("PA")
    d2 = sandbox.home / "b.conf"
    d2.write_text("PB")
    theme = make_theme(sandbox.tmp, "alpha", files=[
        ("c", "a.conf", "~/a.conf", "A"), ("c", "b.conf", "~/b.conf", "B")])
    apply_mod.apply(theme)
    (paths.BASELINE_DIR / "files.json").write_text("{ not json")
    b = backup.Baseline().load()
    assert any("recovered" in w for w in b.warnings)
    assert len(b.files) == 2  # final save's .bak had both records
