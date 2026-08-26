# Words you might not know

This is the one place in gtheme where technical words are allowed to appear —
because here they are the thing being explained. The app itself never says any
of them.

If you are brand new to all of this, read [docs/start-here.md](docs/start-here.md)
first; it is the gentler version.

---

### Linux

The engine underneath. It is not a program you see; it is the part of the
computer that makes everything else possible, the same way Windows and macOS
are. On its own it has no desktop, no windows and no buttons — those come from
a *desktop* (below).

### Distro (distribution)

A complete, ready-to-use computer system built around Linux: the engine, a
desktop, a web browser, an app installer and a few hundred other pieces,
assembled and tested by one group of people and handed to you as one thing.

Windows comes from Microsoft, macOS from Apple, and there is one of each. Linux
has hundreds of distros — Fedora, Ubuntu, Arch, Debian, Linux Mint, CachyOS —
made by different people with different tastes. They can all run the same
programs. You are running one right now, and which one you have decides how you
install things.

### GNOME

The desktop gtheme is for: the bar across the top of your screen, the clock in
the middle, the view you get when you press the **Super** key, the window
buttons, and the Settings app. It is what turns Linux into something you can
point at and click.

GNOME is one of several desktops for Linux. gtheme only works with this one,
and says so plainly if it finds itself somewhere else.

### GNOME version (49, 50, …)

GNOME gets a new version twice a year, and each one moves the settings around a
little. gtheme is built for versions 49 and 50 and checks which one you have
when it starts. To find yours: **Settings → System → About**.

### libadwaita

One of the building blocks GNOME itself is made from — the code that draws the
buttons, lists and sliders you see in GNOME's own apps. gtheme uses it too,
which is why it looks like it belongs. It is not something you install
separately; a GNOME 49 or 50 desktop already has the version gtheme needs
(1.9 or newer).

### Add-on (elsewhere called an "extension")

A small extra that adds a feature to your desktop: a dock down the side, a
clipboard history, temperature readings in the top bar, a wobble when you drag
a window. GNOME calls these *extensions*; gtheme calls them **add-ons**,
because "extension" already means a browser plugin to most people.

They are written by other people, published at extensions.gnome.org, and gtheme
can search, install, configure and switch them off from inside the app. Being
third-party code that your desktop loads, they are the one part of this whole
picture that can genuinely misbehave — which is why gtheme keeps a record of
every one it switched on, so it can switch them all off again without help.

### Look

gtheme's word for a whole desktop appearance as one thing: background picture,
colours, icons, text and add-ons, all decided together, applied in one click,
undone in one click.

A Look is a folder of pictures and a text file listing settings. **It cannot
contain a program and cannot run one.** That is a deliberate design decision,
not a promise — see [SECURITY.md](SECURITY.md).

### Restore point / saved moment

A recording of how your entire desktop looked at one moment: every setting
gtheme knows about, plus a copy of every file it is about to change. Going back
to one puts all of it back.

gtheme takes one automatically before every change, and you can take one
yourself whenever you like. The oldest are pruned when there are too many —
except **Before gtheme**, the one from before this app ever touched your
computer, which is kept forever.

### Terminal

A window where you type commands instead of clicking. Nothing in gtheme
requires one — except `gtheme rescue`, which exists precisely for the moment
when the graphical part of your computer has stopped working and typing is all
you have left.

[docs/start-here.md](docs/start-here.md#opening-a-terminal) shows how to open
one.

### Wayland

The modern machinery GNOME uses to draw things on your screen and to hear your
mouse and keyboard. It replaced an older system called X11. You will never need
to think about it; it appears here because you will see the word in error
messages from other software, and now you know it is not about you.

### Arch Linux / the AUR / PKGBUILD

Arch is a distro (above) for people who like assembling their own system;
CachyOS, EndeavourOS and Manjaro are built on it. The **AUR** is its
community-run collection of build recipes for software that is not in the
official catalogue. A **PKGBUILD** is one such recipe: a short text file saying
how to build and install one program. gtheme ships one, so on Arch you can
install it as a proper package that `pacman -R` removes cleanly.

If none of those words apply to you, use
[the easy way](README.md#-the-easy-way-recommended) instead.

### dconf

Your desktop's settings database — the place GNOME keeps every preference you
have ever set. gtheme manages it for you, so you never have to touch it.

(You may see the word in advice on the internet telling you to "run
`dconf write …`". You do not need to. Anything worth changing there has a
row in gtheme with a sentence explaining it, and gtheme records what was there
first so you can undo it.)

### Highlight colour (elsewhere called "accent colour")

The colour GNOME uses for selected items, switches that are on, and the button
it wants you to press. GNOME offers exactly nine and no way to add a tenth;
gtheme shows them as nine coloured dots and tells you about the limit rather
than letting you look for a colour wheel that is not there.

### Top bar style (elsewhere called a "shell theme")

The appearance of the bar across the top of your screen and its menus — a
separate thing from the appearance of your app windows, confusingly. Changing
it needs one GNOME add-on switched on; when it is off, gtheme offers the button
that switches it on instead of naming a component you have never heard of.

### App style (elsewhere called a "GTK theme")

The appearance of the insides of app windows: the buttons, lists, sliders and
backgrounds. Some apps follow it, some are built to follow GNOME's own look
instead, and a Look sets both so they agree with each other.

### Overview (elsewhere called "Activities")

The view you get when you press the **Super** key — every open window shrunk
down, a search box, and your app list. It is roughly what the Start menu and
Task View are on Windows, folded into one screen.
