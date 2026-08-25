# STOP. DO NOT INSTALL THIS EXTENSION.

This extension turns on `global.context.unsafe_mode`, which lets **any process
on your session bus run arbitrary JavaScript inside gnome-shell**.

It is safe in exactly one place: a private, headless, throwaway GNOME Shell
started by `tests/sandbox/` on a `dbus-run-session` bus that nothing else can
reach. It is loaded from there by prepending `tests/sandbox/ext-root` to
`XDG_DATA_DIRS`.

Copying this directory into `~/.local/share/gnome-shell/extensions/` — or
adding `gtheme-sandbox@gtheme.local` to your live `enabled-extensions` — leaves
that hole open in your real desktop for as long as you are logged in.

See `../../../README.md` for why it exists at all.
