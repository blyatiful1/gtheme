# DO NOT INSTALL ANYTHING IN THIS DIRECTORY

## `gtheme-sandbox@gtheme.local` MUST NEVER BE COPIED INTO A REAL SESSION.

This directory is not an extensions directory. It is a fake `XDG_DATA_DIRS`
entry that exists only so a **private, headless, throwaway** GNOME Shell —
started by `tests/sandbox/` inside its own `dbus-run-session` — can find one
test-only extension. It is reached by *prepending* this path to
`XDG_DATA_DIRS`, never by installing anything anywhere.

### Why it is dangerous

`gtheme-sandbox@gtheme.local` sets:

```js
global.context.unsafe_mode = true;
```

**Unsafe mode means any client on the session bus can execute arbitrary
JavaScript inside gnome-shell**, via `org.gnome.Shell.Eval`. Inside a private
bus that nothing else can reach, that is a test instrument. On your real session
bus it is a remote-code-execution hole in your desktop, permanently on, for
every process you run.

### Why it exists anyway

A headless `gnome-shell` has no seat, so nothing ever produces the interaction
that dismisses the startup Overview. It sits in the Overview forever and every
screenshot shows window thumbnails instead of a desktop. `window-calls`'
`Activate` does not dismiss it — that was measured, not assumed. `Eval` does:

```
Main.overview.hide(); Main.overview.visible   ->  (true, 'false')
```

The extension also hides the Overview itself on a 500 ms × 10 timer, so the
usual case needs no `Eval` call at all.

### The rules

1. Never copy this directory, or anything in it, into
   `~/.local/share/gnome-shell/extensions/`.
2. Never add `gtheme-sandbox@gtheme.local` to the **live**
   `org.gnome.shell enabled-extensions`. The sandbox writes that key only
   inside its own private dconf store, and the isolation canary
   (`tests/sandbox/canary.py`) asserts the live value is byte-identical before
   and after every single sandbox test.
3. Never point the harness at the live session bus. `SandboxSession` refuses to
   continue if the bus address it got equals `DBUS_SESSION_BUS_ADDRESS`.
4. Nothing in `tests/sandbox/` may write below `~/.local/share/gnome-shell/`.
   The user's extensions directory is a **read-only source**: the private data
   mode copies `window-calls` *out* of it and never writes back.

If you are reading this because you are debugging an extension and thought this
looked like a convenient place to drop it: it is not. Use
`~/.local/share/gnome-shell/extensions/`, and log out and back in.
