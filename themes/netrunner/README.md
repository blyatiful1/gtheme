# NETRUNNER — Jack In

A netrunner's deck in Night City: HUD cyan on desaturated navy void, one
cyber-yellow signature per surface, hot pink in the terminal's veins. Strictly
border-free. Converted from the v1 gtheme theme format.

## What applying this Look does

Sets the Night City wallpaper, switches the desktop to dark with a teal
highlight (the nearest built-in colour to the design's cyan — the exact shade
lives only in the shell theme's own stylesheet, and GNOME's highlight colour
cannot express it), installs the Netrunner shell theme, sets Iosevka Nerd Font
and Rajdhani as the system fonts, writes Ptyxis and Alacritty colour schemes,
and configures eight add-ons — glass blur behind the terminals only, a bottom
dock with cyber-yellow running dots and no borders anywhere, faster shell
animations, and the emblem in the top-left menu.

It changes settings and copies files. It cannot run a program on your computer.

## What this Look does NOT include

**`netrunner-ice` and `netrunner-jackin`.** A truecolor "ICE lamp" and a Breach
Protocol login greeting — both programs, both left behind. `netrunner-ice` also
wrapped `lavat`, a third-party tool that is not in any standard repository, so
even the v1 theme could not install it for you.

**The fish configuration** that called them.

**The ASCII quotes folder.** A Look copies one file at a time.

**Programs it expects you to already have.** alacritty, starship, btop, micro,
fastfetch, cava, ptyxis, papirus-icon-theme, and `lavat`.

**Fonts.** Iosevka Nerd Font and Rajdhani must be installed already.

## The live wallpaper

The Hanabi add-on plays `netrunner-loop.mp4` — a 57-second seamless loop — as a
moving background. It is listed among the add-ons this Look wants and the file
is shipped. Without Hanabi the desktop shows `netrunner-still.png`, which is
what the wallpaper setting points at. That graceful degrade was the original
design and is preserved here.
