# gtheme

**Change how your desktop looks — safely.**

<p align="center">
  <img src="docs/media/screenshots/home-light.png" alt="The gtheme window: a list of pages down the left, and a card on the right reading back the wallpaper, colours, icons, text and add-ons this desktop is using right now." width="900">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/desktop-GNOME%2049%20%E2%80%93%2050-4a86cf" alt="Works on GNOME 49 and 50">
  <img src="https://img.shields.io/badge/licence-MIT-green" alt="MIT licence">
  <img src="https://img.shields.io/badge/looks-can't%20run%20programs-brightgreen" alt="Looks only change settings">
</p>

---

## 🆘 Something looks wrong? Put it back

Three ways, from easiest to most stubborn. Any one of them is enough.

1. **In the app** — press **Ctrl+Z**, or click **Undo last change** at the top
   of the window. Or open **Undo & Restore Points** in the list on the left and
   pick the moment you want back. (Upgraded from the old command-line gtheme?
   *Before gtheme* — how your desktop looked before version 1 ever ran — is in
   that list too, read from version 1's own records.)
2. **The app won't open, but the desktop works** — open a terminal window
   (hold **Ctrl**, **Alt** and press **T**; if that does nothing,
   [docs/start-here.md](docs/start-here.md) shows another way) and type:

   ```sh
   gtheme rescue
   ```

   That puts every setting and file gtheme touched back the way it was, and
   switches off every add-on gtheme switched on. It needs no window, no mouse,
   and no graphics at all.
3. **The screen is unusable — no bar, no windows, nothing responds** — hold
   **Ctrl** and **Alt** and press **F3**. You get a black screen with a text
   prompt. Type your username, press Enter, type your password (nothing appears
   as you type — that is normal), press Enter, then type `gtheme rescue` and
   press Enter. When it says it is done, hold **Ctrl** and **Alt** and press
   **F2** to get back to your desktop — on some systems it is **F1** instead,
   and trying both is harmless. Then log out and back in.

You do not have to reinstall anything, and nothing is deleted by any of the
three.

---

## What is this?

gtheme is an app for the GNOME desktop that changes how your computer looks —
the background picture, the colours, the icons, the mouse pointer, the text,
the bar across the top, and the small extras GNOME calls add-ons.

Today those things live in four different apps, three of which talk to you in
words you would have to look up, and none of which can put anything back. This
one puts them in a single window, explains every switch in a sentence, and
saves how your desktop looked before it changes anything.

If you have used Windows or a Mac and this is your first Linux computer: you
are the person this was written for. Installing it takes a terminal window
once — that is the one command-line step, and
[docs/start-here.md](docs/start-here.md) walks you through opening one. After
that, using gtheme needs no commands at all, except on the bad day above when
the app itself will not open. And nothing here can be broken so badly that the
**Undo** button cannot fix it.

## Contents

- [Put it back](#-something-looks-wrong-put-it-back)
- [What is this?](#what-is-this)
- [What you need](#what-you-need)
- [Install](#install)
- [The first time you open it](#the-first-time-you-open-it)
- [What's in the app](#whats-in-the-app)
- [Questions people ask](#questions-people-ask)
- [Words you might not know](GLOSSARY.md)
- [For people who want to help](#for-people-who-want-to-help)

## What you need

| | |
|---|---|
| **A GNOME desktop, version 49 or 50** | This is the desktop Fedora, Ubuntu and Arch ship by default. If your screen has a bar across the very top with a clock in the middle, that is probably GNOME. gtheme checks when it starts and says so plainly if it is somewhere else — it never half-works. |
| **libadwaita 1.9 or newer** | One of the building blocks GNOME itself is made of. GNOME 49 and 50 both include it; there is nothing separate to install. On an older GNOME the window will not open, and gtheme tells you that instead of misbehaving. |
| **Python 3.11 or newer** | Already on every desktop Linux system in use today. |
| **About 60 MB of disk space** | Three quarters of that is the pictures the four built-in Looks use. |
| **English** | Everything *inside* the window is English only today — every label, every explanation, every warning — and there is no translation machinery behind it yet: no language files, nothing for a translator to fill in. The one part that is already translated is how you find the app: the launcher entry and the software-store listing carry German, Brazilian Portuguese, Spanish and French names, descriptions and search words, so typing "Thema", "aparência", "fondo de pantalla" or "apparence" turns gtheme up in your applications list. That is a plain statement of what it is, not a hint that the app itself is coming in your language next month. If you would like it in yours, [say so in an issue](https://github.com/blyatiful1/gtheme/issues) — translations are welcome, and knowing somebody is waiting is what decides when the groundwork gets built. |

gtheme does **not** need an internet connection to change anything on your
computer. It only goes online if you ask it to look for new add-ons or new
Looks, and it says so when it does.

## Install

Pick the row that sounds like you.

| You | Go to |
|---|---|
| "I have no idea what any of this means." | [The easy way](#the-easy-way) |
| "I use Arch Linux / CachyOS / EndeavourOS." | [The Arch way](#the-arch-way) |
| "I want to work on gtheme itself." | [CONTRIBUTING.md](CONTRIBUTING.md) |

There is deliberately no "paste this one line into a terminal and it downloads
and runs a script" command anywhere in this project. That is a popular way to
install things and a bad habit to teach: it asks you to run code you have not
seen, from a web address you cannot check, as a matter of routine. The steps
below let you look at what you downloaded first.

### The easy way

**1. Download it.**
Open <https://github.com/blyatiful1/gtheme> in your web browser. Click the
green **Code** button near the top right, then click **Download ZIP**. Your
browser saves it to your **Downloads** folder.

**2. Unpack it.**
Open your **Files** app, go to **Downloads**, right-click `gtheme-main.zip` and
choose **Extract Here**. A folder called `gtheme-main` appears next to it.

**3. Look inside if you like.**
Everything gtheme installs is in that folder, in plain text you can read. The
file `install.sh` is the one the next step runs, and it is short enough to read
in a couple of minutes.

**4. Run the installer.**
Right-click the `gtheme-main` folder and choose **Open in Terminal**. (No such
menu entry? [docs/start-here.md](docs/start-here.md#opening-a-terminal) shows
two other ways.) A window with a text prompt opens. Type this and press
**Enter**:

```sh
./install.sh
```

It checks that the pieces it needs are present, sets itself up in its own
private corner of that folder so it cannot disturb anything else on your
system, and adds **Gtheme** to your list of applications. It prints what it is
doing as it goes. If something is missing it stops and tells you the exact
command to install it — it never installs system packages behind your back.

**5. Open it.**
Press the **Super** key (the one with the Windows logo on most keyboards),
type `gtheme`, and press **Enter**.

To remove it later, see [Can I remove it?](#can-i-remove-it) below.

### The Arch way

On Arch and its relatives, build a real package from the checkout:

```sh
git clone https://github.com/blyatiful1/gtheme
cd gtheme
makepkg -si -p PKGBUILD-git
```

`PKGBUILD-git` builds the copy you just cloned — no download of a release
archive, so it works today. That gives you a normal package, called
`gtheme-git`, installed with `pacman`, which means `sudo pacman -R gtheme-git`
removes it completely later. Dependencies are declared in the recipe and
`makepkg -s` pulls them in.

There is a plain `PKGBUILD` beside it that builds from a released source
archive instead. It is the one an AUR package would use, and it is waiting on
the first version 2 release tag — until that tag exists it cannot download
anything, so use `PKGBUILD-git`.

## The first time you open it

The first time — and only the first time — gtheme shows four short cards.

1. **Change how your desktop looks.** What the app is for.
2. **You can always go back.** The important one: *before anything changes,
   gtheme saves how your desktop looks right now. One click puts it back.*
3. **Two ways to work.** Pick a whole look at once, or change one thing at a
   time from the list down the side.
4. **Save how it looks now.** One button, and it does a real thing: it saves
   your desktop exactly as it is at this moment, so you have somewhere to
   return to before you have changed anything at all.

You can skip it, and you can bring it back any time from the **☰** menu at the
top of the window → **Show the introduction again**.

Two things worth knowing from the start:

- **Ctrl+F searches everything** — every setting, every explanation, every
  Look, every add-on, in the words you would actually use. Type "taskbar",
  "make text bigger" or "dark mode" and it takes you to the row and flashes it.
  You never have to learn where things live.
- **Ctrl+Z undoes the last change**, from anywhere in the app.

## What's in the app

Fifteen pages, in four groups down the left-hand side. Every screenshot below
is the real app, photographed by the test suite on the run that shipped this
version — not a mock-up.

### Welcome

#### Home

![The Home page, listing the current Look, light-or-dark, highlight colour, app style, icon set, mouse pointer, text style and add-on count](docs/media/screenshots/home-light.png)

Reads your desktop back to you in plain words: which Look is on, light or dark,
your highlight colour, your icons, your pointer, your text, how many add-ons
are switched on, and a picture of your background. Nothing here is a control —
it is the page that answers "what have I actually got?", which no other GNOME
app can tell you. The two safety buttons live here too.

#### Looks

![The Looks page showing large picture tiles for the built-in Looks, each with a title, a Built-in badge and a description](docs/media/screenshots/looks-dark.png)

A Look changes your background, colours, icons, text and add-ons all at once.
Four are built in — HYPERCLASS, MAGMA, NETRUNNER and NIGHTBLOOM — and **Get
more** lists what the community has published.

Clicking one does not apply it. It opens a dialog that says, in your words,
what is about to change ("Wallpaper, highlight colour, icons, and 3 add-ons").
Only then does it run, as one all-or-nothing operation: if any part of it
fails, the whole thing is rolled back and you are told what happened. A saved
moment is taken automatically first, and the message afterwards has an **Undo**
button in it.

You can also save your own desktop as a Look and share it. gtheme scans what it
captured for anything private — your username in a file location, a key some
add-on stored — and shows you what it found before you send it anywhere.

### Change one thing

#### Wallpaper

![The Wallpaper page: two grids of background pictures, one for the light look and one for the dark look](docs/media/screenshots/wallpaper-light.png)

Two separate grids: the picture for your light look, and the picture for your
dark look. GNOME's own picker ties those together; gtheme does not, so you can
have a completely different picture in the evening. Pictures that change during
the day are labelled as such. You can add your own — gtheme copies it somewhere
safe rather than pointing at a file you might later move.

#### Colours & Style

![The Colours and Style page: two large light/dark tiles, a row of nine coloured dots for the highlight colour, and style pickers](docs/media/screenshots/colors-light.png)

Light or dark as two tiles you look at, not a switch you read. The highlight
colour as nine coloured dots — the control *is* the preview. GNOME offers
exactly those nine and no way to add a tenth, and the page says so out loud
rather than leaving you hunting for a colour wheel that does not exist.

The light/dark tile writes two settings at once, together or not at all. That
is the classic split-brain bug — a dark desktop full of blinding white
windows — and it is impossible here by construction.

Also here: the style for the insides of windows, the style for the bar at the
top, stronger colours for readability, and less on-screen movement.

#### Icons & Pointer

![The Icons and Pointer page: icon sets shown as rows of their own real icons, and pointer styles as tiles](docs/media/screenshots/icons-light.png)

Icon sets are shown as a row of their own actual icons. A name in a dropdown
tells you nothing about what you are about to get. Pointer styles are tiles
with a size choice; the page admits that a pointer cannot be drawn from inside
an app, and that most computers have exactly one installed, rather than looking
broken and saying nothing.

#### Fonts & Text

![The Fonts and Text page, every option rendered in the lettering it is about](docs/media/screenshots/fonts-light.png)

Every choice is shown in the lettering it is about. Text size, and a "text
sharpness" choice with three samples — Softer, Balanced, Sharper — instead of
the two words GNOME uses that read like physics. Two settings here do nothing
until a second setting is changed first; gtheme writes both, in one operation,
and tells you it is doing it rather than leaving you with a control that
visibly moves and changes nothing.

#### Top Bar & Overview

![The Top Bar and Overview page with rows for the clock, the date, the battery percentage and the top-left corner shortcut](docs/media/screenshots/topbar-light.png)

The bar across the top and the view you get when you press Super: what the
clock shows, whether the weekday and the battery percentage appear, the
top-left corner shortcut, and the style of the bar itself.

That last one needs a GNOME add-on switched on. When it is off, the page does
not say "user-theme extension not enabled" and leave you to search the web —
it says what you cannot do and offers the button that fixes it.

#### Windows & Desktops

![The Windows and Desktops page: window button layouts, focus behaviour, desktops, and collapsed groups of keyboard shortcuts](docs/media/screenshots/windows-light.png)

Where the close/minimise/maximise buttons go, what double-clicking a window's
top bar does, how windows take focus, and how many desktops you have. Every
keyboard shortcut the desktop itself watches for is here too, in two collapsed
groups — 175 of them, which is why they are folded away rather than dumped in
a list.

#### Add-ons

![The Add-ons page: the Installed list, each add-on with a plain-English description, a switch and a settings button](docs/media/screenshots/addons-light.png)

Add-ons are small extras that add features to your desktop. Three views:
**Installed** with a switch each, **Discover** to search the online library,
and **Updates**.

- Every add-on gets a sentence saying what it does, in plain words. Their
  internal identifiers are never shown anywhere in gtheme.
- Twenty-four popular add-ons have a hand-written settings panel, so their
  options are explained the same way everything else in the app is. The rest
  get an honest generic panel labelled "these settings come from the add-on
  author".
- Add-ons that fight each other (two docks, two clipboard managers) are offered
  as either/or on this page, with an offer to switch the other one off. That
  check runs on the switches here; applying a whole Look does not run it yet,
  so a Look that brings a dock can leave you with the one your distro
  preinstalled as well.
- Combinations known to break things carry a warning that says what will
  happen to you, not what will happen internally.
- Adding an add-on **from this page** goes through GNOME's own confirmation
  box: the desktop shows it, naming the add-on, and gtheme cannot install one
  behind it. Adding the add-ons a whole Look asks for is the other path —
  there gtheme downloads them itself from extensions.gnome.org after you press
  the button that says so, and no GNOME box appears. See
  [SECURITY.md](SECURITY.md) for what that means.

#### Terminal

![The Terminal page, one card per terminal program actually installed](docs/media/screenshots/terminal-light.png)

If you use a terminal, gtheme can give it, its prompt and its little status
tools the same colours as your Look. One card per program that is *actually
installed* — a list of eight with seven greyed out is a list of things you
cannot do.

Each card says honestly when you will see the change: some terminals update
while you watch, some within a second, some only when you open a new window.

One card goes further. Ghostty keeps its settings in a folder that dotfile
setups often own outright, so gtheme checks: if that folder belongs to another
tool, it refuses to write, names the tool, and offers to take over — a
deliberate act, and an undoable one. The other cards do not make that check
yet, and neither does applying a whole Look.

### System

#### Night Light & Timing

![The Night Light page with times shown as clock times and a warmth slider](docs/media/screenshots/nightlight-light.png)

Warmer colours in the evening, on the sun's schedule or on yours. GNOME stores
those times as fractions of an hour — `20.25` — so the page shows you "Set to
8:15 pm" underneath and follows the slider as it moves.

#### Sound

![The Sound page: which set of short sounds the desktop plays, and six switches](docs/media/screenshots/sound-light.png)

Which set of short sounds your desktop plays, whether it plays them at all, and
whether it beeps.

#### Power & Screen

![The Power and Screen page, grouped as what happens to the screen, what happens to the computer, and locking](docs/media/screenshots/power-light.png)

When the screen dims, when it turns off, when the computer sleeps, and whether
it asks for a password afterwards. Grouped by the question you are actually
asking, not by which part of GNOME happens to own the setting. It warns you
about one combination people pick by accident and then find maddening: screen
off after a minute, lock immediately.

#### More Settings

![The More Settings page: collapsed, explained groups covering every remaining setting, searchable](docs/media/screenshots/more-light.png)

Everything the fourteen other pages did not put a hand-written row on. It is
generated, not written: every setting a GNOME 50 desktop has is accounted for
in a list the test suite checks, and anything with no home lands here
automatically, described in the system's own words and clearly labelled as
such.

This is what makes "nothing was left out" a fact rather than a claim. If gtheme
can see a setting, you can find it.

### Safety

#### Undo & Restore Points

![The Undo and Restore Points page: Save how it looks now, Undo the last change, and the list of saved moments](docs/media/screenshots/restore-light.png)

The page that makes the rest of the app safe to touch, and the one thing no
other GNOME customisation tool has.

A **saved moment** is how your whole desktop looked at one point in time. One
is taken automatically before anything changes, you can take one whenever you
like, and going back to one puts the background, the colours, the text and the
add-ons back the way they were. They are dated in words — "My desktop, 25
August" — never in a timestamp.

If you are coming from the old command-line gtheme, one more row sits at the
bottom on its own: **Before gtheme**, how this computer looked before version 1
ever ran. It is read from version 1's own records, and it is never deleted and
never pruned.

A fresh install has no such row, and it would be dishonest to draw one:
nothing was watching this computer before gtheme arrived, so there is no
recording of that moment to offer. What a fresh install has instead is the
first-touch record described under [Will this break my
desktop?](#will-this-break-my-desktop) — the first time gtheme changes any
setting or file it writes down what was there, and `gtheme rescue` puts all of
it back, whether or not you ever saved a moment. Taking your own moment on the
introduction's last card, before you change anything, is how you get a named
row to come back to.

## Questions people ask

### Will this break my desktop?

Not permanently, and it is designed so that it cannot.

- **Nothing is applied that you have not seen first.** Every Look shows you
  what it is about to change, in your words, before it changes it.
- **Everything is saved first.** Before the first byte moves, gtheme records
  exactly what was there. That recording is written as it goes, so even a power
  cut halfway through leaves a complete record of what had changed by then.
- **Changes are all-or-nothing.** If any step of applying a Look fails, the
  whole thing is rolled back. gtheme never leaves you with a half-changed
  desktop.
- **The first record is never overwritten.** The first time a Look changes
  anything it writes down what was there and never writes over that note,
  however many Looks you try afterwards — so `gtheme rescue` a year later still
  puts back what this computer looked like before the first Look was applied.
  Single settings you change by hand on one of the individual pages
  (Background, Fonts, Terminal and the rest) do not go into that first record
  yet, so `gtheme rescue` cannot put those back. A restore point does cover
  them: **Undo & Restore Points** saves every setting gtheme knows how to
  change, so a moment saved before an afternoon of tweaking takes you back to
  it.
- **Looks cannot run programs.** See [SECURITY.md](SECURITY.md).

The honest limits: a badly-behaved *add-on* — third-party code, published by
someone else, that GNOME loads into your desktop — can still misbehave, and
that is true whether you install it through gtheme, through GNOME's own app, or
from a website. gtheme's answer is that it always knows which add-ons it
switched on, so `gtheme rescue` can switch them all back off without the
desktop's help.

### Can I remove it?

Yes. Do it in this order — the first step is the one that matters.

**1. Put your desktop back first.** Open **Undo & Restore Points** and go back
to the moment you want — that is the thorough route, because a saved moment
covers every setting gtheme knows how to change, including ones you changed by
hand on an individual page. `gtheme rescue` in a terminal is the route that
needs no window: it returns everything *a Look* applied — settings and files
alike — to how it was before the first Look touched it, and switches off every
add-on gtheme switched on. Page-by-page edits are not in that record yet, so
finish with a restore point if you made any. Do this *before* removing
anything, because removing the app takes away the only thing that can read
those records.

**2. Then remove it.**

- **Installed the easy way** — run the installer again with one extra word,
  from the same folder:

  ```sh
  ./install.sh --uninstall
  ```

  It takes back exactly what it put outside that folder, which is five things:
  the `gtheme` command (`~/.local/bin/gtheme`), the app-list entry
  (`~/.local/share/applications/io.github.blyatiful1.Gtheme.desktop`), the
  app-store listing (`~/.local/share/metainfo/io.github.blyatiful1.Gtheme.metainfo.xml`)
  and two icons (`~/.local/share/icons/hicolor/scalable/apps/io.github.blyatiful1.Gtheme.svg`
  and `~/.local/share/icons/hicolor/symbolic/apps/io.github.blyatiful1.Gtheme-symbolic.svg`).
  It refuses to run while gtheme still has a Look on your desktop, rather than
  stranding you — that is what step 1 is for. Then delete the folder you
  unpacked, and the program is gone.

  (Deleting the folder by hand instead leaves those five behind, and the
  app-store listing is enough to keep gtheme showing in your software app.)
- **Installed with `makepkg`** — `sudo pacman -R gtheme-git` (or `gtheme`, if
  you built the release recipe rather than `PKGBUILD-git`).

**3. Your own things, if you want them gone.** Neither route deletes these,
deliberately:

| | |
|---|---|
| `~/.local/state/gtheme/` | your saved moments and the record of what your desktop was before gtheme changed it |
| `~/.local/share/gtheme/` | Looks you saved or downloaded |
| `~/.local/share/backgrounds/gtheme/` | copies of background pictures you added yourself |
| `~/.config/gtheme/` | the app's own preferences |
| `~/.cache/gtheme/` | cached answers from extensions.gnome.org; safe to delete at any time |
| `~/.local/state/gtheme.v1-backup/` | only if you ever ran the old command-line gtheme. It is the one surviving record of this computer from before *that* ever ran, and nothing can rebuild it — keep it unless you are certain |

The full list of everywhere gtheme writes, and why, is in
[SECURITY.md](SECURITY.md#where-gtheme-keeps-things).

### Why does an add-on need me to log out?

Because of how GNOME itself works, and gtheme will not pretend otherwise.

Your desktop looks for add-ons in its folders **once**, when it starts. An
add-on that arrives after that is invisible to it — there is no way to make it
look again. This is not a gtheme limitation; it was measured directly against
GNOME 50 and the test suite still checks it on every full run, so that if a
future GNOME changes it, gtheme notices.

So there are two cases and gtheme tells you which one you are in:

- An add-on already on your computer can be switched on right now. "It's on."
- An add-on gtheme has just downloaded usually starts working immediately,
  because GNOME's own installer loads it for you. When it cannot, gtheme says
  "it starts working after you log out and back in" — and means it.

Those two sentences differ by one clause and by the entire question of whether
the app is telling you the truth.

### Does it send anything anywhere?

No. gtheme has no account, no server and no telemetry. It talks to the internet
in exactly two situations, both of which you start: searching the add-on
library at extensions.gnome.org, and fetching the list of community Looks —
which is one public file published with gtheme's own code, because there is no server
to run.

If you publish a Look, gtheme scans it first for anything private and shows you
what it found before you share it.

### Why is something greyed out?

Because it would not do anything, and gtheme would rather tell you than let you
press it. Every greyed-out control carries the reason: the add-on that owns it
is switched off, the program is not installed, or another setting has to change
first.

### Can I use it on Ubuntu or Fedora?

If it is running GNOME 49 or 50, yes. To find out, open your **Settings** app
and look at **System → About** — it prints the GNOME version there.

Older releases ship an older libadwaita than gtheme needs. On one of those,
gtheme shows a screen saying so and changes nothing, rather than opening a
window that half-works. gtheme was built and tested on Arch; the easy-way
installer is written to work anywhere and says exactly what is missing if it
does not.

### Can I use a Look without opening the app?

Yes, from a terminal window:

```sh
gtheme apply nightbloom
gtheme apply ~/dotfiles/my-look
gtheme apply ~/dotfiles/my-look --dry-run
```

Give it the name of a Look you have, or the folder one lives in. `--dry-run`
prints exactly what would change and changes nothing — including, by name, any
file the Look would write that can start a program.

It is the same machinery the button in the window uses: the same saved moment
taken before anything changes, the same refusal of anything a Look may not do,
and the same putting-everything-back if a step fails. It prints the reason and
stops with a failure code if the Look cannot be used, so a script can tell.
This is for people who keep their setup in a repository or rebuild a computer
from a script; everyone else should use the window.

### Where did the old command-line gtheme go?

Nowhere. v1 is preserved in full on the
[`legacy-v1`](https://github.com/blyatiful1/gtheme/tree/legacy-v1) branch and at
the [`v1-final`](https://github.com/blyatiful1/gtheme/releases/tag/v1-final)
tag. See [CHANGELOG.md](CHANGELOG.md) for what changed and why.

## For people who want to help

- **New to all of this?** [docs/start-here.md](docs/start-here.md) — what a
  Linux system is, how to open a terminal, and how to copy and paste into one.
- **A word you do not know?** [GLOSSARY.md](GLOSSARY.md).
- **Want to add a Look, an add-on panel, or a setting?**
  [CONTRIBUTING.md](CONTRIBUTING.md). Most contributions are data files, not
  code.
- **Writing a Look?** [docs/preset-format.md](docs/preset-format.md).
- **Want gtheme in your language?** It is English only today and has no
  translation machinery yet, so there is nothing to fill in — but an issue
  saying which language you want is the thing that decides when that groundwork
  gets built.
- **Want to know how it works inside?**
  [docs/architecture.md](docs/architecture.md) and
  [docs/testing.md](docs/testing.md).
- **Found a security problem?** [SECURITY.md](SECURITY.md).

## Licence

MIT — see [LICENSE](LICENSE). Copyright © 2026 blyatiful1.
