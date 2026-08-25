# gtheme

**Change how your desktop looks — safely.**

gtheme is an app for GNOME that lets you change your wallpaper, colours, icons,
fonts, and add-ons from one window, and undo any of it with one click.

> **This is the v2 rebuild, and it is not finished.** The window opens and the
> pages are placeholders. If you are looking for the working v1 command-line
> tool, it is preserved in full on the [`legacy-v1`](../../tree/legacy-v1)
> branch and at the [`v1-final`](../../releases/tag/v1-final) tag.

## Safety promise

Looks only change settings. They can't run programs on your computer.

Before gtheme changes anything, it saves how your desktop looked, so you can
always go back.

## Requirements

- GNOME 49 or 50, with libadwaita 1.9 or newer
- Python 3.11 or newer

## Running it from a checkout

```sh
git clone https://github.com/blyatiful1/gtheme
cd gtheme
uv venv --system-site-packages .venv
uv pip install -e '.[dev]'
./bin/gtheme
```

`--system-site-packages` is required: the graphical parts come from your
distribution's PyGObject/GTK packages, not from pip.

## If something looks broken

Run `gtheme rescue` in a terminal. It puts your desktop back the way it was
before gtheme touched it, without needing the app's window to open.

## Licence

MIT — see [LICENSE](LICENSE).
