"""Booting a private GNOME Shell, and talking to it.

This is the Python port of ``~/gtheme-rebuild/harness/sandbox-proof.sh``, which
was proven end to end on this machine on 2026-08-25. Every mitigation in that
script is here on purpose; none of them is decoration. In particular:

**The isolation rule.** ``XDG_CONFIG_HOME=<tmp>`` on its own does *nothing*. A
``gsettings set`` goes over D-Bus to the dconf-service that is already running,
which has the real ``XDG_CONFIG_HOME``, and the write lands in the real store.
Isolation comes from ``dbus-run-session``: a fresh bus activates a *fresh*
dconf-service that inherits the sandbox environment. Both are required, and the
environment has to be set **on the ``dbus-run-session`` invocation itself**,
not exported inside it. Note what that rule does *not* require: a shell. A
settings write is isolated by the bus alone, so :meth:`SandboxSession.
start_bus_only` gives the dconf tier the same guarantee without booting
GNOME — which is why that tier runs in CI and this one never will.

**The overview.** A headless shell has no seat, so nothing ever produces the
interaction that dismisses the startup Overview, and every screenshot shows
overview thumbnails instead of a desktop. ``window-calls``' ``Activate`` does
not fix it (measured). The ``gtheme-sandbox@gtheme.local`` extension in
``ext-root/`` turns on ``unsafe_mode`` so ``org.gnome.Shell.Eval`` works, and
``Main.overview.hide()`` does.

**Screenshots.** ``org.gnome.Shell.Screenshot`` is sender-gated. A plain
``gdbus call`` owns no well-known bus name and gets ``AccessDenied``. Under
unsafe mode the check short-circuits and the plain call works, which is why it
is tried first and kept as a live regression probe; ``shot.py`` is the fallback
that acquires ``org.gnome.SettingsDaemon.MediaKeys`` first and waits ~1.2s for
the shell's asynchronous name-watcher before calling.

**``GetFrameRect``** returns 0x0 for 4-6 seconds after a window maps. Poll for a
non-zero width; never trust the first answer.

**Teardown** kills recorded PIDs and nothing else. No ``pkill -f``: the pattern
matches the harness's own shell and takes the session down with it.

**Two data modes** (DESIGN.md F6). ``DataMode.SHARED`` reroots only
``XDG_CONFIG_HOME``/``CACHE``/``STATE``, so the user's real extensions stay
visible read-only — that is what the page-walk wants. ``DataMode.PRIVATE``
reroots ``XDG_DATA_HOME`` as well and copies in what the shell needs, so
anything that installs, enables or stages an extension cannot reach the real
one.
"""

from __future__ import annotations

import enum
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
import zipfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "BUS_ONLY_TOOLS",
    "DataMode",
    "EXT_ROOT",
    "SANDBOX_EXT_UUID",
    "SandboxSession",
    "SandboxUnavailable",
    "WINDOW_CALLS_UUID",
    "require_tools",
    "sandbox_env",
    "unique_wayland_display",
]

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]

#: The test-only extension that unlocks Eval. Reached only via XDG_DATA_DIRS.
EXT_ROOT = HERE / "ext-root"
SANDBOX_EXT_UUID = "gtheme-sandbox@gtheme.local"
WINDOW_CALLS_UUID = "window-calls@domandoman.xyz"

#: Where the user's real extensions live. READ-ONLY source, always.
USER_EXT_DIR = Path.home() / ".local/share/gnome-shell/extensions"

#: Metadata-only extension fixtures, committed in Wave 0 (DESIGN.md F5). Copied
#: into a private data root so pages that enumerate installed extensions have
#: real content to render instead of a vacuously-passing empty state (F15).
FIXTURE_EXT_DIR = REPO_ROOT / "tests/fixtures/schemas"

REQUIRED_TOOLS = ("dbus-run-session", "gnome-shell", "gdbus", "gsettings", "dconf")

#: What :meth:`SandboxSession.start_bus_only` needs — no shell, no compositor,
#: no seat. A private bus plus a private dconf is the whole isolation story for
#: a settings *write*, and every one of these exists in the Arch CI container,
#: which is why the ``dconf`` tier can run there while the sandbox tier cannot.
BUS_ONLY_TOOLS = ("dbus-run-session", "gsettings", "dconf", "glib-compile-schemas")

#: How long a bus-only session's placeholder process lives if nobody stops it.
#: Teardown kills it by pid; this is only the backstop for a crashed run.
BUS_ONLY_LIFETIME = 3600

#: Measured on this box: bus 200ms, shell Ping 0-200ms, window listed 400ms,
#: frame geometry 4-6s. The caps are generous multiples, not expectations.
BUS_TIMEOUT = 20.0
SHELL_TIMEOUT = 60.0
STARTUP_LINE_TIMEOUT = 90.0
WINDOW_TIMEOUT = 60.0
FRAME_TIMEOUT = 30.0
POLL = 0.2

STARTUP_LINE = "GNOME Shell started at"


class SandboxUnavailable(Exception):
    """The machine cannot host a sandbox session. Tests skip on this."""


class DataMode(enum.StrEnum):
    """Which XDG roots a session reroots. See DESIGN.md F6."""

    #: Config/cache/state private; ``XDG_DATA_HOME`` left alone, so the user's
    #: installed extensions and themes are visible READ-ONLY.
    SHARED = "shared"
    #: ``XDG_DATA_HOME`` private too. Everything the shell needs is copied in.
    PRIVATE = "private"


def require_tools(tools: Iterable[str] = REQUIRED_TOOLS) -> None:
    """Raise :class:`SandboxUnavailable` naming the first missing tool."""
    for tool in tools:
        if shutil.which(tool) is None:
            raise SandboxUnavailable(f"{tool} is not installed")


def unique_wayland_display() -> str:
    """A display name no other test session can collide with.

    Several headless shells may run at once — a second pytest process, or a
    session-scoped fixture that outlives a function-scoped one. They share
    ``XDG_RUNTIME_DIR``, so the socket name has to be unique per session or the
    second shell fails to bind and the first one's window is what you test.
    """
    return f"gtheme-sb-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def sandbox_env(
    *,
    root: Path,
    mode: DataMode,
    bus: str | None,
    wayland_display: str | None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """The environment every sandbox client gets.

    The shell equivalent is ``env -u DISPLAY VAR=... cmd`` — and note the order,
    because GNU ``env`` stops parsing options at the first non-option argument,
    so ``env FOO=1 -u DISPLAY cmd`` tries to execute a program literally named
    ``-u``. That bug silently broke the first run of the original proof script:
    every sandbox call failed, readiness never polled true, and the log said the
    shell had started fine. Building a dict in Python cannot make that mistake,
    which is the main reason this is Python and not shell.
    """
    env = dict(os.environ)
    # A live X11 display would let a client connect to the user's real session.
    for name in ("DISPLAY", "DBUS_STARTER_ADDRESS", "DBUS_STARTER_BUS_TYPE"):
        env.pop(name, None)
    # Test-suite seams must not leak into a sandbox process and silently
    # redirect it somewhere the canary is not watching.
    for name in ("GTHEME_DEST_ROOT", "GTHEME_CONFIG_DIR", "GTHEME_STATE_DIR"):
        env.pop(name, None)

    env["XDG_CONFIG_HOME"] = str(root / "config")
    env["XDG_CACHE_HOME"] = str(root / "cache")
    env["XDG_STATE_HOME"] = str(root / "state")
    if mode is DataMode.PRIVATE:
        env["XDG_DATA_HOME"] = str(root / "data")

    # ext-root FIRST, system defaults KEPT — drop them and the shell loses its
    # icons and stylesheet. A per-session schema root is prepended too, so a
    # test can compile a throwaway schema the machine does not have.
    defaults = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    env["XDG_DATA_DIRS"] = os.pathsep.join([str(root / "share"), str(EXT_ROOT), defaults])

    if bus:
        env["DBUS_SESSION_BUS_ADDRESS"] = bus
    if wayland_display:
        env["WAYLAND_DISPLAY"] = wayland_display
    env["LC_ALL"] = "C"
    if extra:
        env.update(extra)
    return env


@dataclass
class SandboxSession:
    """One private bus + one headless GNOME Shell, and the tools to drive it.

    Args:
        root: a throwaway directory. Every private XDG root lives under it.
        mode: which data mode, per DESIGN.md F6.
        enabled_extensions: uuids to put in the private ``enabled-extensions``
            before the shell starts. The sandbox control extension is always
            added; ``window-calls`` is added when it is available, because the
            readiness gate and the boot smoke both need it.
        seed_fixture_extensions: copy the committed metadata-only fixture
            corpus into the private data root (PRIVATE mode only).
    """

    root: Path
    mode: DataMode = DataMode.SHARED
    enabled_extensions: Sequence[str] = ()
    seed_fixture_extensions: bool = False
    wayland_display: str = field(default_factory=unique_wayland_display)

    bus: str | None = None
    shell_pid: int | None = None
    _wrapper: subprocess.Popen[bytes] | None = None
    _children: list[subprocess.Popen[bytes]] = field(default_factory=list)
    _started: bool = False

    # -- paths -------------------------------------------------------------

    @property
    def config_home(self) -> Path:
        return self.root / "config"

    @property
    def data_home(self) -> Path:
        """The data root the shell sees. The real one in SHARED mode."""
        if self.mode is DataMode.PRIVATE:
            return self.root / "data"
        return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")

    @property
    def extensions_dir(self) -> Path:
        return self.data_home / "gnome-shell/extensions"

    @property
    def schema_root(self) -> Path:
        """A prepended ``XDG_DATA_DIRS`` entry for throwaway gschemas."""
        return self.root / "share/glib-2.0/schemas"

    @property
    def dconf_store(self) -> Path:
        return self.config_home / "dconf/user"

    @property
    def log_path(self) -> Path:
        return self.root / "shell.log"

    def log(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return ""

    # -- lifecycle ---------------------------------------------------------

    def prepare(self, *, for_shell: bool = True) -> None:
        """Lay out the private roots. Safe to call before :meth:`start`.

        Args:
            for_shell: whether a GNOME Shell is going to be booted in these
                roots. When it is not — :meth:`start_bus_only` — the extension
                corpus and ``window-calls`` are pointless, and demanding them
                would make the bus-only tier skip on every machine that has no
                ``window-calls`` installed, CI included.
        """
        for sub in ("config", "cache", "state", "share/glib-2.0/schemas"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        if self.mode is DataMode.PRIVATE and for_shell:
            self.extensions_dir.mkdir(parents=True, exist_ok=True)
            self._copy_window_calls()
            if self.seed_fixture_extensions:
                self.seed_fixtures()

    def _copy_window_calls(self) -> None:
        """Copy window-calls out of the user's extensions dir. READ-ONLY source."""
        source = USER_EXT_DIR / WINDOW_CALLS_UUID
        if not source.is_dir():
            raise SandboxUnavailable(
                f"{WINDOW_CALLS_UUID} is not installed; the harness needs it to see windows"
            )
        target = self.extensions_dir / WINDOW_CALLS_UUID
        if not target.exists():
            shutil.copytree(source, target, symlinks=True)

    def seed_fixtures(self) -> list[str]:
        """Copy the committed fixture corpus in. Returns the uuids copied.

        These carry ``metadata.json`` and ``schemas/`` but no ``extension.js``:
        enough for the app to enumerate and describe them, not enough for the
        shell to load them — which is exactly right, since a sandbox must never
        run third-party extension code.
        """
        copied: list[str] = []
        if not FIXTURE_EXT_DIR.is_dir():
            return copied
        for source in sorted(FIXTURE_EXT_DIR.iterdir()):
            if not source.is_dir() or "@" not in source.name:
                continue
            target = self.extensions_dir / source.name
            if not target.exists():
                shutil.copytree(source, target)
            copied.append(source.name)
        return copied

    def install_schema(self, xml_text: str, filename: str = "gtheme-test.gschema.xml") -> None:
        """Compile a gschema into the session's private schema root.

        Must be called before :meth:`start` for the shell to see it; clients
        started later pick it up either way, because GLib scans every
        ``XDG_DATA_DIRS`` entry's ``glib-2.0/schemas``.
        """
        self.schema_root.mkdir(parents=True, exist_ok=True)
        (self.schema_root / filename).write_text(xml_text, encoding="utf-8")
        result = subprocess.run(
            ["glib-compile-schemas", str(self.schema_root)],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if result.returncode != 0:
            raise SandboxUnavailable(f"glib-compile-schemas failed: {result.stderr}")

    def env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        return sandbox_env(
            root=self.root,
            mode=self.mode,
            bus=self.bus,
            wayland_display=self.wayland_display,
            extra=extra,
        )

    def start(self, pre_start: Callable[[SandboxSession], None] | None = None) -> None:
        """Boot the private bus and the headless shell, then wait for readiness.

        Args:
            pre_start: called after the roots are laid out and before the shell
                is launched. This is where an experiment puts an extension it
                wants present at the shell's startup scan.
        """
        require_tools()
        self.prepare()
        if pre_start is not None:
            pre_start(self)

        uuids = [SANDBOX_EXT_UUID, *self.enabled_extensions]
        if (self.extensions_dir / WINDOW_CALLS_UUID).is_dir() and WINDOW_CALLS_UUID not in uuids:
            uuids.insert(0, WINDOW_CALLS_UUID)
        enabled = json.dumps(uuids).replace('"', '\\"')

        script = f"""
set -u
printf '%s' "$DBUS_SESSION_BUS_ADDRESS" > {self.root}/bus.addr.tmp
mv {self.root}/bus.addr.tmp {self.root}/bus.addr
dconf write /org/gnome/shell/disable-user-extensions false
dconf write /org/gnome/shell/disabled-extensions "@as []"
dconf write /org/gnome/shell/allow-extension-installation true 2>/dev/null || true
dconf write /org/gnome/shell/enabled-extensions "{enabled}"
echo "$$" > {self.root}/shell.pid
exec gnome-shell --headless --virtual-monitor 1920x1080 \
     --wayland-display={self.wayland_display}
"""
        env = sandbox_env(
            root=self.root, mode=self.mode, bus=None, wayland_display=None
        )
        log = self.log_path.open("wb")
        # start_new_session so a stray signal to the test process group cannot
        # take the shell with it, and so teardown can reap a whole subtree.
        self._wrapper = subprocess.Popen(  # noqa: S603
            ["dbus-run-session", "--", "sh", "-c", script],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self._started = True
        try:
            self._wait_for_bus()
            self._wait_for_shell()
        except Exception:
            self.stop()
            raise

    def start_bus_only(self) -> None:
        """Boot the private bus, and nothing else. No shell, no compositor.

        A settings write is isolated by the bus, not by the environment: the
        fresh bus activates a fresh dconf-service that inherits this session's
        ``XDG_CONFIG_HOME``, so the write lands in ``root/config/dconf/user``
        and nowhere else. A headless GNOME Shell adds nothing to that guarantee
        — it costs sixty seconds and a machine that has one.

        Splitting it out is what lets the dconf round-trip and the backend
        write-parity tests run in a plain ``pytest`` and in CI (the ``dconf``
        marker) while the tests that genuinely need a shell stay local-only
        (the ``sandbox`` marker). See docs/testing.md.
        """
        require_tools(BUS_ONLY_TOOLS)
        self.prepare(for_shell=False)

        # `echo $$` before `exec` records the pid of the process that *becomes*
        # the placeholder, so stop() reaps it exactly the way it reaps a shell.
        # dbus-run-session tears its bus down when that child exits.
        script = f"""
set -u
printf '%s' "$DBUS_SESSION_BUS_ADDRESS" > {self.root}/bus.addr.tmp
mv {self.root}/bus.addr.tmp {self.root}/bus.addr
echo "$$" > {self.root}/shell.pid
exec sleep {BUS_ONLY_LIFETIME}
"""
        env = sandbox_env(root=self.root, mode=self.mode, bus=None, wayland_display=None)
        log = self.log_path.open("wb")
        self._wrapper = subprocess.Popen(  # noqa: S603
            ["dbus-run-session", "--", "sh", "-c", script],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self._started = True
        try:
            self._wait_for_bus()
        except Exception:
            self.stop()
            raise

    def _wait_for_bus(self) -> None:
        bus_file = self.root / "bus.addr"
        deadline = time.monotonic() + BUS_TIMEOUT
        while time.monotonic() < deadline:
            if bus_file.is_file() and bus_file.stat().st_size:
                break
            if self._wrapper is not None and self._wrapper.poll() is not None:
                raise SandboxUnavailable(
                    f"dbus-run-session exited early:\n{self.log()[-3000:]}"
                )
            time.sleep(POLL)
        else:
            raise SandboxUnavailable(f"private bus never appeared:\n{self.log()[-3000:]}")

        self.bus = bus_file.read_text(encoding="utf-8").strip()
        live = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
        if not self.bus or self.bus == live:
            raise SandboxUnavailable(
                f"the sandbox bus is the LIVE bus ({self.bus!r}); refusing to continue"
            )
        pid_file = self.root / "shell.pid"
        if pid_file.is_file():
            self.shell_pid = int(pid_file.read_text(encoding="utf-8").strip())

    def _wait_for_shell(self) -> None:
        deadline = time.monotonic() + SHELL_TIMEOUT
        while time.monotonic() < deadline:
            probe = self.gdbus(
                "org.gnome.Shell", "/org/gnome/Shell", "org.freedesktop.DBus.Peer.Ping"
            )
            if probe.returncode == 0:
                return
            time.sleep(POLL)
        raise SandboxUnavailable(
            f"org.gnome.Shell never appeared on the private bus:\n{self.log()[-3000:]}"
        )

    def wait_for_startup_complete(self, settle: float = 3.0) -> float:
        """Block until the shell logs that it finished starting.

        ``Peer.Ping`` succeeds roughly 1.5s *before* the extension directory
        scan runs. The first version of the runtime-load experiment gated on
        Ping, raced the scan, and concluded that extensions runtime-load — the
        opposite of the truth. Gate on the shell's own startup line.
        """
        deadline = time.monotonic() + STARTUP_LINE_TIMEOUT
        started = time.monotonic()
        while time.monotonic() < deadline:
            if STARTUP_LINE in self.log():
                break
            time.sleep(POLL)
        else:
            raise SandboxUnavailable(
                f"shell never reported {STARTUP_LINE!r}:\n{self.log()[-3000:]}"
            )
        while time.monotonic() < deadline:
            if "({" in self.ext_call("ListExtensions").stdout:
                break
            time.sleep(POLL)
        time.sleep(settle)
        return time.monotonic() - started

    def stop(self) -> None:
        """Kill only what this session started. Recorded PIDs, never patterns."""
        for child in self._children:
            self._terminate(child)
        self._children.clear()
        if self.shell_pid is not None:
            self._signal_pid(self.shell_pid, signal.SIGTERM)
        if self._wrapper is not None:
            self._terminate(self._wrapper)
            self._wrapper = None
        if self.shell_pid is not None:
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline and self._alive(self.shell_pid):
                time.sleep(POLL)
            if self._alive(self.shell_pid):
                self._signal_pid(self.shell_pid, signal.SIGKILL)
        self._started = False

    @staticmethod
    def _alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    @staticmethod
    def _signal_pid(pid: int, sig: int) -> None:
        try:
            os.kill(pid, sig)
        except OSError:
            pass

    @staticmethod
    def _terminate(proc: subprocess.Popen[bytes]) -> None:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    # -- running things inside ---------------------------------------------

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float = 60.0,
        extra_env: dict[str, str] | None = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Run a command inside the sandbox and wait for it."""
        return subprocess.run(  # noqa: S603
            list(argv),
            env=self.env(extra_env),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )

    def spawn(
        self, argv: Sequence[str], *, extra_env: dict[str, str] | None = None
    ) -> subprocess.Popen[bytes]:
        """Start a long-lived client inside the sandbox. Torn down with it."""
        proc = subprocess.Popen(  # noqa: S603
            list(argv),
            env=self.env(extra_env),
            stdout=(self.root / f"client-{len(self._children)}.log").open("wb"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self._children.append(proc)
        return proc

    def gdbus(
        self, dest: str, path: str, method: str, *args: str, timeout: float = 40.0
    ) -> subprocess.CompletedProcess[str]:
        return self.run(
            [
                "gdbus", "call", "--session",
                "--dest", dest,
                "--object-path", path,
                "--method", method,
                *args,
            ],
            timeout=timeout,
        )

    def shell_eval(self, javascript: str) -> str:
        """Run JS in the shell. Works only because unsafe mode is on."""
        result = self.gdbus(
            "org.gnome.Shell", "/org/gnome/Shell", "org.gnome.Shell.Eval", javascript
        )
        return (result.stdout or result.stderr).strip()

    def ext_call(
        self, method: str, *args: str, timeout: float = 40.0
    ) -> subprocess.CompletedProcess[str]:
        return self.gdbus(
            "org.gnome.Shell",
            "/org/gnome/Shell",
            f"org.gnome.Shell.Extensions.{method}",
            *args,
            timeout=timeout,
        )

    def win_call(self, method: str, *args: str) -> subprocess.CompletedProcess[str]:
        return self.gdbus(
            "org.gnome.Shell",
            "/org/gnome/Shell/Extensions/Windows",
            f"org.gnome.Shell.Extensions.Windows.{method}",
            *args,
        )

    def gsettings(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.run(["gsettings", *args])

    # -- shell state -------------------------------------------------------

    _STATE_RE = re.compile(r"'state': <([0-9.]+)>")

    def extension_state(self, uuid_: str) -> float | None:
        """``GetExtensionInfo`` state, or None when the shell has never heard of it.

        The shell answers an unknown uuid with an empty dict, not an error — the
        distinction the whole runtime-load verdict rests on. D-Bus numbers come
        back as doubles, hence the float.
        """
        out = self.ext_call("GetExtensionInfo", uuid_).stdout
        match = self._STATE_RE.search(out)
        return float(match.group(1)) if match else None

    def known_uuids(self) -> list[str]:
        out = self.ext_call("ListExtensions").stdout
        return sorted(set(re.findall(r"'([^']+@[^']+)':", out)))

    def wait_for_window(self, needle: str, timeout: float = WINDOW_TIMEOUT) -> dict:
        """Poll ``window-calls`` List until a window matches, and return it."""
        deadline = time.monotonic() + timeout
        last = ""
        while time.monotonic() < deadline:
            last = self.win_call("List").stdout
            for window in _parse_window_list(last):
                haystack = " ".join(
                    str(window.get(field_, "")) for field_ in ("title", "wm_class", "wm_class_instance")
                )
                if needle.lower() in haystack.lower():
                    return window
            time.sleep(POLL)
        raise AssertionError(
            f"no window matching {needle!r} appeared within {timeout}s.\n"
            f"last List: {last[:600]}\nshell log tail:\n{self.log()[-2000:]}"
        )

    def wait_for_frame(self, window_id: int, timeout: float = FRAME_TIMEOUT) -> dict:
        """Poll ``GetFrameRect`` until the width is non-zero.

        It answers 0x0 for the first 4-6 seconds after a window maps. Trusting
        the first answer makes a mapped window look like a failed one.
        """
        deadline = time.monotonic() + timeout
        rect: dict = {}
        while time.monotonic() < deadline:
            out = self.win_call("GetFrameRect", str(window_id)).stdout
            rect = _parse_gdbus_json(out) or {}
            if rect.get("width"):
                return rect
            time.sleep(POLL)
        raise AssertionError(f"frame rect never became non-zero: {rect}")

    def hide_overview(self) -> bool:
        """Leave the Overview a headless shell would otherwise never leave."""
        answer = self.shell_eval("Main.overview.hide(); Main.overview.visible")
        return "true" in answer and "'false'" in answer

    def screenshot(self, path: Path) -> Path:
        """Capture the session to a PNG. Tries both proven routes.

        Route A (plain ``gdbus``) works only while unsafe mode is on and is kept
        first deliberately: if it ever starts working *without* the sandbox
        extension, the shell relaxed its SenderChecker and this harness should
        find out. Route B is ``shot.py``, which owns an allow-listed name.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        self.gdbus(
            "org.gnome.Shell",
            "/org/gnome/Shell/Screenshot",
            "org.gnome.Shell.Screenshot.Screenshot",
            "false", "false", str(path),
        )
        if path.is_file() and path.stat().st_size:
            return path
        result = self.run([sys.executable, str(HERE / "shot.py"), str(path)], timeout=180)
        if not (path.is_file() and path.stat().st_size):
            raise AssertionError(
                f"no screenshot produced: {result.stdout}\n{result.stderr}\n"
                f"shell log tail:\n{self.log()[-1500:]}"
            )
        return path


def _parse_gdbus_json(text: str) -> dict | None:
    """Pull the JSON payload out of a ``gdbus call`` reply like ``('{...}',)``."""
    text = text.strip()
    match = re.match(r"^\('(.*)',\s*\)$", text, re.DOTALL)
    payload = match.group(1) if match else text
    try:
        return json.loads(payload.encode().decode("unicode_escape"))
    except (ValueError, UnicodeDecodeError):
        return None


def _parse_window_list(text: str) -> list[dict]:
    text = text.strip()
    match = re.match(r"^\('(.*)',\s*\)$", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(1).encode().decode("unicode_escape"))
    except (ValueError, UnicodeDecodeError):
        return []
    return data if isinstance(data, list) else []


def make_probe_extension(directory: Path, uuid_: str, marker: str) -> Path:
    """Write a minimal loadable extension that logs a marker when enabled.

    The runtime-load experiment needs extensions whose *loading* is observable
    in the shell log, and nothing else.
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "metadata.json").write_text(
        json.dumps(
            {
                "uuid": uuid_,
                "name": f"runtime-load probe {marker}",
                "description": "TEST-ONLY probe for the runtime-load regression.",
                "shell-version": ["48", "49", "50", "51"],
                "session-modes": ["user", "unlock-dialog"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (directory / "extension.js").write_text(
        "import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';\n"
        "\n"
        f"export default class Probe{marker} extends Extension {{\n"
        "    enable() {\n"
        f"        log('PROBE_{marker}_ENABLE_MARKER');\n"
        "    }\n"
        "\n"
        "    disable() {\n"
        f"        log('PROBE_{marker}_DISABLE_MARKER');\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    return directory


def zip_extension(source: Path, target: Path) -> Path:
    """Pack an extension directory the way e.g.o serves them: a flat zip."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source))
    return target
