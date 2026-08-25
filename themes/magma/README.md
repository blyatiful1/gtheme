# MAGMA — Obsidian Flow

Obsidian glass over a living magma chamber: ember orange, lava gold, one cool
teal vein. Converted from the v1 gtheme theme format.

## What applying this Look does

Sets the wallpaper (a slideshow of three obsidian-and-lava renders), switches
the desktop to dark with an orange highlight and Papirus-Dark icons, installs
the Magma shell theme, sets MesloLGS Nerd Font as the system monospace, writes
Ptyxis and Alacritty colour schemes, and configures ten add-ons — molten-glass
blur behind the terminals and Nautilus, a bottom dock with ember running dots,
wobbly windows, the desktop cube, and the flame emblem in the top-left menu.

It changes settings and copies files. It cannot run a program on your computer.

## What this Look does NOT include

**The seven terminal toys.** `magma-doomfire`, `magma-embers`, `magma-eruption`,
`magma-fissure`, `magma-lavalamp`, `magma-thermal` and `magma-vitals` are
Python programs — a DOOM-fire cellular automaton, a metaball lava-lamp fluid
simulation, an animated login greeting. v1 copied them into place and wired
them up through a fish configuration. v2 Looks change settings and nothing
else, so both the programs and the fish configuration that called them were
left behind. They are still in the v1 theme if you want them.

**The ASCII art folder.** A Look copies one file at a time; a whole folder of
quotes and volcano art has no single destination.

**The Plymouth boot splash.** It was never wired into the v1 manifest either —
installing it needs an administrator password and a rebuild of the boot image.
Permanently manual.

**Programs it expects you to already have.** alacritty, starship, btop, micro,
fastfetch, cava, ptyxis, papirus-icon-theme, papirus-folders, adw-gtk-theme. A
Look cannot install software.

**The orange folder recolour.** The icon theme is set to Papirus-Dark, but the
original also ran `papirus-folders -C orange` once, as an administrator. Do that
yourself if you want orange folders.

**Fonts.** MesloLGS Nerd Font must be installed already.

## The live wallpaper

The Hanabi add-on plays `magma-loop.mp4` as a moving background. It is listed
among the add-ons this Look wants, and the file is shipped. If Hanabi is not
installed or is switched off, the desktop falls back to the still slideshow,
which is what the wallpaper setting actually points at — that was the original
design and it is preserved here.
