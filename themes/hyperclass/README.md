# HYPERCLASS — Gilded Void

First class aboard a starliner crossing the void: champagne brass on deep-space
ink, ivory starlight, one vein of ice. The shell chrome is the cool platinum
hull; the apps are the warm champagne cabin. Converted from the v1 gtheme theme
format.

## What applying this Look does

Sets the wallpaper (a slideshow of three starliner renders), switches the
desktop to dark with a slate highlight and Papirus-Dark icons, sets Iosevka
Nerd Font as the system monospace, writes Ptyxis and Alacritty colour schemes
and a single GTK stylesheet used by both old and new apps, ships a Burn My
Windows effect profile — a champagne hexagon-lattice open/close animation, the
airlock iris — and configures six add-ons.

Files are written before settings, always. This Look needs that: the Burn My
Windows setting points at a profile file this Look ships, and pointing an
add-on at a file that is not there yet gives you a broken animation until the
next login.

It changes settings and copies files. It cannot run a program on your computer.

## A gap the conversion fixed

The v1 theme listed the add-ons it wanted but never actually turned them on —
it had no `enabled-extensions` block, unlike its two siblings. The converted
Look does turn them on, because in v2 the add-on list is a first-class part of
the format rather than a setting the author had to remember to write.

## What this Look does NOT include

**`hyperclass-boarding`, `hyperclass-orrery` and `hyperclass-warp`.** A
receipt-style boarding pass, a working brass planetarium clock, and a fullscreen
hyperspace animation. All three are programs and were left behind, along with
the fish configuration that called them.

**The ASCII art folder.** A Look copies one file at a time.

**Programs it expects you to already have.** alacritty, starship, btop, micro,
fastfetch, cava, ptyxis, papirus-icon-theme, papirus-folders.

**The brass folder recolour.** The original ran `papirus-folders` once as an
administrator. Do that yourself if you want it.

**Fonts.** Iosevka Nerd Font must be installed already.

## No live wallpaper

Unlike MAGMA and NETRUNNER, this Look has no moving background and does not ask
for the Hanabi add-on. The slideshow is the whole wallpaper.

## Window borders, on purpose

This is the one Look of the four that turns window borders *on* — a two-pixel
gold hairline around the focused window, from Tiling Shell. It is a deliberate
style choice, not an oversight, and it is the opposite of NETRUNNER's rule.
