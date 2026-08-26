<div align="center">

<img src="data/icons/hicolor/scalable/apps/io.github.blyatiful1.Gtheme.svg" width="88" alt="">

# gtheme

### Change how your desktop looks — safely.

Wallpaper, colours, icons, pointer, text, the top bar and add-ons —
in **one window**, explained in **plain words**, with an **Undo button that always works**.

<img src="https://img.shields.io/github/v/release/blyatiful1/gtheme?label=latest%20release&color=4a86cf" alt="Latest release">
<img src="https://img.shields.io/badge/desktop-GNOME%2049%20%E2%80%93%2050-4a86cf" alt="Works on GNOME 49 and 50">
<img src="https://img.shields.io/badge/licence-MIT-green" alt="MIT licence">
<img src="https://img.shields.io/badge/telemetry-none-brightgreen" alt="No telemetry">

<img src="docs/media/screenshots/home-light.png" width="900" alt="The gtheme window: a list of pages down the left, and a card on the right reading back the wallpaper, colours, icons, text and add-ons this desktop is using right now.">

</div>

> [!TIP]
> **Changed something and want it back?** Press **Ctrl+Z** in the app, or type
> `gtheme rescue` in a terminal window. Nothing gtheme does is permanent —
> [all three ways back are here](#i-changed-something-and-i-want-it-back).

**Contents** ·
[What is it?](#what-is-it) ·
[What it changes](#what-it-can-change) ·
[Why it's safe](#why-its-safe-to-try) ·
[Install](#install) ·
[First five minutes](#your-first-five-minutes) ·
[Tour](#a-tour-of-the-app) ·
[Undo](#i-changed-something-and-i-want-it-back) ·
[Questions](#questions-people-ask) ·
[Uninstall](#removing-gtheme) ·
[Help](#getting-help)

---

## What is it?

gtheme is an app for the GNOME desktop that changes how your computer looks: the
background picture, the colours, the icons, the mouse pointer, the text, the bar
across the top, and the small extras GNOME calls **add-ons**.

Today those things live in four different apps, three of which talk to you in
words you would have to look up, and none of which can put anything back. gtheme
puts them in a single window, explains every switch in a sentence, and saves how
your desktop looked *before* it changes anything.

**This was written for you if:**

- This is your first Linux computer, and you came from Windows or a Mac.
- You would like a nicer-looking desktop but you are afraid of breaking it.
- You do not want to open a terminal, edit a config file, or learn what
  "gsettings" means. You never have to.
- You cannot find where a setting lives. **Ctrl+F** searches every setting in
  the app, in the words you would actually use — try "taskbar" or "dark mode".

**You do not need:** an account, an internet connection (except to browse for new
add-ons), an administrator password, or any knowledge of Linux or GitHub.

## What it can change

| | |
|---|---|
| **Wallpaper** | A different picture for your light look and your dark look — GNOME's own picker ties those together, gtheme does not. |
| **Colours & style** | Light or dark as two tiles you *look at*, and the highlight colour as nine coloured dots. |
| **Icons & pointer** | Icon sets shown as rows of their own real icons, not names in a dropdown. |
| **Fonts & text** | Every choice shown in the lettering it is about, plus text size and sharpness. |
| **Top bar & overview** | What the clock shows, the battery percentage, the top-left corner shortcut. |
| **Windows & desktops** | Where the close and minimise buttons go, how many desktops you have, and every keyboard shortcut. |
| **Add-ons** | Browse, install and switch on GNOME extensions — each with a sentence saying what it actually does. |
| **Terminal colours** | Give your terminal and its prompt the same colours as the rest of your desktop. |
| **Night light, sound, power** | Warmer colours in the evening, the sounds your desktop plays, when the screen sleeps. |
| **Whole "Looks"** | Change all of the above at once. Four are built in — HYPERCLASS, MAGMA, NETRUNNER and NIGHTBLOOM — and you can save your own desktop as a Look and share it. |

Anything the other pages did not cover lands on a **More Settings** page
automatically, so nothing on your desktop is hidden from you.

## Why it's safe to try

This is the part that makes gtheme different from every other GNOME
customisation tool, so it is worth thirty seconds of your time:

- **Everything is saved first.** Before the first byte moves, gtheme records
  exactly what was there. Even a power cut halfway through leaves a complete
  record of what had changed by then.
- **One click puts it back.** **Ctrl+Z** undoes the last change, from anywhere in
  the app.
- **"Before gtheme" is kept forever.** The very first thing gtheme ever saw on
  your computer is never overwritten and never deleted, however many Looks you
  try afterwards. A year later, it still means *before gtheme*.
- **Nothing happens that you haven't seen.** Every Look tells you what it is
  about to change, in your words, before it changes it.
- **Changes are all-or-nothing.** If any step fails, the whole thing is rolled
  back. You are never left with a half-changed desktop.
- **Looks cannot run programs.** A Look is a list of settings, not code — see
  [SECURITY.md](SECURITY.md).
- **Nothing is sent anywhere.** No account, no server, no telemetry.

**The honest limit:** a badly-behaved *add-on* — third-party code published by
someone else — can still misbehave, whether you install it through gtheme,
through GNOME's own app, or from a website. gtheme's answer is that it always
knows which add-ons it switched on, so one command switches them all off again.

## Install

Takes about five minutes. You do not need an administrator password.

<details>
<summary><b>First, check your computer can run it</b> (click to open)</summary>

<br>

| You need | How to tell |
|---|---|
| **A GNOME desktop, version 49 or 50** | Open your **Settings** app → **System → About**. It prints the GNOME version there. This is the desktop Fedora, Ubuntu and Arch ship by default: if your screen has a bar across the very top with a clock in the middle, it is probably GNOME. |
| **libadwaita 1.9 or newer** | One of the building blocks GNOME itself is made of. GNOME 49 and 50 both include it — there is nothing separate to install. |
| **Python 3.11 or newer** | Already on every desktop Linux system in use today. |
| **About 60 MB of disk space** | Three quarters of that is the pictures the four built-in Looks use. |

You do not have to check any of this by hand. gtheme checks when it starts and
says so plainly if something is missing — it never half-works.

</details>

### The easy way (recommended)

**1. Download it.**
Open <https://github.com/blyatiful1/gtheme> in your web browser. Click the green
**Code** button near the top right, then **Download ZIP**. Your browser saves it
to your **Downloads** folder.

**2. Unpack it.**
Open your **Files** app, go to **Downloads**, right-click `gtheme-main.zip` and
choose **Extract Here**. A folder called `gtheme-main` appears next to it.

**3. Open a terminal in that folder.**
Right-click the `gtheme-main` folder and choose **Open in Terminal**. A window
with a text prompt appears. This is the only time you will need it.

> No **Open in Terminal** in the menu? [docs/start-here.md](docs/start-here.md#opening-a-terminal)
> shows two other ways, and explains how to copy and paste into a terminal.

**4. Run the installer.** Type this and press **Enter**:

```sh
./install.sh
```

It checks that the pieces it needs are present, sets itself up in its own private
corner of that folder so it cannot disturb anything else, and adds **Gtheme** to
your list of applications. It prints what it is doing as it goes. If something is
missing it stops and tells you the exact command to install it — it never
installs system packages behind your back.

**5. Open it.**
Press the **Super** key (the one with the Windows logo on most keyboards), type
`gtheme`, and press **Enter**.

> [!NOTE]
> Keep the `gtheme-main` folder where it is — the app runs from it. If **Gtheme**
> is not in your app list yet, log out and back in.

<details>
<summary><b>The Arch way</b> — Arch, CachyOS, EndeavourOS</summary>

<br>

The folder contains a `PKGBUILD`, so:

```sh
git clone https://github.com/blyatiful1/gtheme
cd gtheme
makepkg -si
```

That builds a normal package and installs it with `pacman`, which means
`pacman -R gtheme` removes it completely later. Dependencies are declared in the
`PKGBUILD`; `makepkg -s` pulls them in.

</details>

<details>
<summary><b>I want to work on gtheme itself</b></summary>

<br>

See [CONTRIBUTING.md](CONTRIBUTING.md) — it covers the development environment,
the test tiers and how to run them.

</details>

<details>
<summary><b>Why there is no "paste this one line into a terminal" command</b></summary>

<br>

You will see a lot of projects tell you to paste a single line that downloads and
runs a script from the internet. It is popular, and it is a bad habit to teach:
it asks you to run code you have not seen, from an address you cannot check, as a
matter of routine.

The steps above let you look at what you downloaded first. Everything gtheme
installs is in that folder, in plain text you can read, and `install.sh` is short
enough to read in a couple of minutes.

</details>

## Your first five minutes

The first time you open it — and only the first time — gtheme shows four short
cards. The last one has a button that does a real thing: it saves your desktop
exactly as it is right now, so you have somewhere to return to before you have
changed anything at all. **Press it.**

Then try this:

1. Open **Looks** in the list on the left and click one of the four built-in
   Looks. It will *ask* before it changes anything, and tell you exactly what it
   is about to change.
2. Look at your new desktop.
3. Don't like it? Press **Ctrl+Z**.

Two shortcuts worth learning on day one:

- **Ctrl+F** searches everything — every setting, every explanation, every Look,
  every add-on, in the words you would actually use. Type "taskbar", "make text
  bigger" or "dark mode" and it takes you straight to the row and flashes it. You
  never have to learn where things live.
- **Ctrl+Z** undoes the last change, from anywhere in the app.

You can bring the introduction back any time from the **☰** menu → **Show the
introduction again**.

## A tour of the app

Fifteen pages in four groups down the left-hand side. Every screenshot below is
the real app, photographed by the test suite on the run that shipped this
version — not a mock-up.

<details>
<summary><b>Welcome</b> — Home and Looks</summary>

<br>

### Home

![The Home page, listing the current Look, light-or-dark, highlight colour, app style, icon set, mouse pointer, text style and add-on count](docs/media/screenshots/home-light.png)

Reads your desktop back to you in plain words: which Look is on, light or dark,
your highlight colour, your icons, your pointer, your text, how many add-ons are
switched on, and a picture of your background. Nothing here is a control — it is
the page that answers "what have I actually got?", which no other GNOME app can
tell you. The two safety buttons live here too.

### Looks

![The Looks page showing large picture tiles for the built-in Looks, each with a title, a Built-in badge and a description](docs/media/screenshots/looks-dark.png)

A Look changes your background, colours, icons, text and add-ons all at once.
Four are built in — HYPERCLASS, MAGMA, NETRUNNER and NIGHTBLOOM — and **Get
more** lists what the community has published.

Clicking one does not apply it. It opens a dialog that says, in your words, what
is about to change ("Wallpaper, highlight colour, icons, and 3 add-ons"). Only
then does it run, as one all-or-nothing operation. A saved moment is taken
automatically first, and the message afterwards has an **Undo** button in it.

You can also save your own desktop as a Look and share it. gtheme scans what it
captured for anything private — your username in a file location, a key some
add-on stored — and shows you what it found before you send it anywhere.

</details>

<details>
<summary><b>Change one thing</b> — wallpaper, colours, icons, fonts, top bar, windows, add-ons, terminal</summary>

<br>

### Wallpaper

![The Wallpaper page: two grids of background pictures, one for the light look and one for the dark look](docs/media/screenshots/wallpaper-light.png)

Two separate grids: the picture for your light look, and the picture for your
dark look. GNOME's own picker ties those together; gtheme does not, so you can
have a completely different picture in the evening. Pictures that change during
the day are labelled as such. You can add your own — gtheme copies it somewhere
safe rather than pointing at a file you might later move.

### Colours & Style

![The Colours and Style page: two large light/dark tiles, a row of nine coloured dots for the highlight colour, and style pickers](docs/media/screenshots/colors-light.png)

Light or dark as two tiles you look at, not a switch you read. The highlight
colour as nine coloured dots — the control *is* the preview. GNOME offers exactly
those nine and no way to add a tenth, and the page says so out loud rather than
leaving you hunting for a colour wheel that does not exist.

The light/dark tile writes two settings at once, together or not at all. That is
the classic split-brain bug — a dark desktop full of blinding white windows — and
it is impossible here by construction.

Also here: the style for the insides of windows, the style for the bar at the
top, stronger colours for readability, and less on-screen movement.

### Icons & Pointer

![The Icons and Pointer page: icon sets shown as rows of their own real icons, and pointer styles as tiles](docs/media/screenshots/icons-light.png)

Icon sets are shown as a row of their own actual icons. A name in a dropdown
tells you nothing about what you are about to get. Pointer styles are tiles with
a size choice; the page admits that a pointer cannot be drawn from inside an app,
and that most computers have exactly one installed, rather than looking broken
and saying nothing.

### Fonts & Text

![The Fonts and Text page, every option rendered in the lettering it is about](docs/media/screenshots/fonts-light.png)

Every choice is shown in the lettering it is about. Text size, and a "text
sharpness" choice with three samples — Softer, Balanced, Sharper — instead of the
two words GNOME uses that read like physics. Two settings here do nothing until a
second setting is changed first; gtheme writes both, in one operation, and tells
you it is doing it rather than leaving you with a control that visibly moves and
changes nothing.

### Top Bar & Overview

![The Top Bar and Overview page with rows for the clock, the date, the battery percentage and the top-left corner shortcut](docs/media/screenshots/topbar-light.png)

The bar across the top and the view you get when you press Super: what the clock
shows, whether the weekday and the battery percentage appear, the top-left corner
shortcut, and the style of the bar itself.

That last one needs a GNOME add-on switched on. When it is off, the page does not
say "user-theme extension not enabled" and leave you to search the web — it says
what you cannot do and offers the button that fixes it.

### Windows & Desktops

![The Windows and Desktops page: window button layouts, focus behaviour, desktops, and collapsed groups of keyboard shortcuts](docs/media/screenshots/windows-light.png)

Where the close/minimise/maximise buttons go, what double-clicking a window's top
bar does, how windows take focus, and how many desktops you have. Every keyboard
shortcut the desktop itself watches for is here too, in two collapsed groups —
175 of them, which is why they are folded away rather than dumped in a list.

### Add-ons

![The Add-ons page: the Installed list, each add-on with a plain-English description, a switch and a settings button](docs/media/screenshots/addons-light.png)

Add-ons are small extras that add features to your desktop. Three views:
**Installed** with a switch each, **Discover** to search the online library, and
**Updates**.

- Every add-on gets a sentence saying what it does, in plain words. Their
  internal identifiers are never shown anywhere in gtheme.
- Twenty-four popular add-ons have a hand-written settings panel, so their
  options are explained the same way everything else in the app is. The rest get
  an honest generic panel labelled "these settings come from the add-on author".
- Add-ons that fight each other (two docks, two clipboard managers) are offered
  as either/or, with an offer to switch the other one off.
- Combinations known to break things carry a warning that says what will happen
  to you, not what will happen internally.
- Installing goes through GNOME's own confirmation box — gtheme never installs an
  add-on behind it.

### Terminal

![The Terminal page, one card per terminal program actually installed](docs/media/screenshots/terminal-light.png)

If you use a terminal, gtheme can give it, its prompt and its little status tools
the same colours as your Look. One card per program that is *actually installed*
— a list of eight with seven greyed out is a list of things you cannot do.

Each card says honestly when you will see the change: some terminals update while
you watch, some within a second, some only when you open a new window. And if a
program's settings are being managed by some other tool, gtheme refuses to write,
says so, and offers to take over — a deliberate act, and an undoable one.

</details>

<details>
<summary><b>System</b> — night light, sound, power, and everything else</summary>

<br>

### Night Light & Timing

![The Night Light page with times shown as clock times and a warmth slider](docs/media/screenshots/nightlight-light.png)

Warmer colours in the evening, on the sun's schedule or on yours. GNOME stores
those times as fractions of an hour — `20.25` — so the page shows you "Set to
8:15 pm" underneath and follows the slider as it moves.

### Sound

![The Sound page: which set of short sounds the desktop plays, and six switches](docs/media/screenshots/sound-light.png)

Which set of short sounds your desktop plays, whether it plays them at all, and
whether it beeps.

### Power & Screen

![The Power and Screen page, grouped as what happens to the screen, what happens to the computer, and locking](docs/media/screenshots/power-light.png)

When the screen dims, when it turns off, when the computer sleeps, and whether it
asks for a password afterwards. Grouped by the question you are actually asking,
not by which part of GNOME happens to own the setting. It warns you about one
combination people pick by accident and then find maddening: screen off after a
minute, lock immediately.

### More Settings

![The More Settings page: collapsed, explained groups covering every remaining setting, searchable](docs/media/screenshots/more-light.png)

Everything the fourteen other pages did not put a hand-written row on. It is
generated, not written: every setting a GNOME 50 desktop has is accounted for in
a list the test suite checks, and anything with no home lands here automatically,
described in the system's own words and clearly labelled as such.

This is what makes "nothing was left out" a fact rather than a claim. If gtheme
can see a setting, you can find it.

</details>

<details>
<summary><b>Safety</b> — Undo &amp; Restore Points</summary>

<br>

![The Undo and Restore Points page: Save how it looks now, Undo the last change, and the list of saved moments](docs/media/screenshots/restore-light.png)

The page that makes the rest of the app safe to touch, and the one thing no other
GNOME customisation tool has.

A **saved moment** is how your whole desktop looked at one point in time. One is
taken automatically before anything changes, you can take one whenever you like,
and going back to one puts the background, the colours, the text and the add-ons
back the way they were. They are dated in words — "My desktop, 25 August" — never
in a timestamp.

At the bottom, on its own, sits **Before gtheme**: how this computer looked before
this app ever ran. That one is never deleted and never pruned.

</details>

## I changed something and I want it back

Three ways, from easiest to most stubborn. **Any one of them is enough**, you do
not have to reinstall anything, and none of them deletes a thing.

### 1. The app opens

Press **Ctrl+Z**, or click **Undo last change** at the top of the window. Or open
**Undo & Restore Points** in the list on the left and pick the moment you want
back — including *Before gtheme*, how your desktop looked before this app ever
ran.

### 2. The app won't open, but the desktop works

Open a terminal window (hold **Ctrl**, **Alt** and press **T**; if that does
nothing, [docs/start-here.md](docs/start-here.md) shows another way) and type:

```sh
gtheme rescue
```

That puts every setting and file gtheme touched back the way it was, and switches
off every add-on gtheme switched on. It needs no window, no mouse, and no
graphics at all.

### 3. The screen is unusable — no bar, no windows, nothing responds

Hold **Ctrl** and **Alt** and press **F3**. You get a black screen with a text
prompt.

1. Type your username and press **Enter**.
2. Type your password and press **Enter**. Nothing appears as you type — that is
   normal.
3. Type `gtheme rescue` and press **Enter**.
4. When it says it is done, hold **Ctrl** and **Alt** and press **F2** to get back
   to your desktop. On some systems it is **F1** instead, and trying both is
   harmless.
5. Log out and back in.

## Questions people ask

<details>
<summary><b>Will this break my desktop?</b></summary>

<br>

Not permanently, and it is designed so that it cannot. Every change is recorded
before it happens, every Look shows you what it will change before it changes it,
and a failed step rolls the whole thing back. The full list of guarantees is in
[Why it's safe to try](#why-its-safe-to-try) above, and the one honest limit —
badly-behaved third-party add-ons — is at the end of it.

</details>

<details>
<summary><b>Do I need to know anything about Linux, the terminal, or GitHub?</b></summary>

<br>

No. You need a terminal exactly once, to run the installer, and step 3 of
[the easy way](#the-easy-way-recommended) shows you how to open
one by right-clicking a folder. After that the app is a window like any other.

If a word in this README is unfamiliar, [GLOSSARY.md](GLOSSARY.md) explains it,
and [docs/start-here.md](docs/start-here.md) covers what a Linux system is, how to
open a terminal, and how to copy and paste into one.

</details>

<details>
<summary><b>Does it send anything anywhere?</b></summary>

<br>

No. gtheme has no account, no server and no telemetry. It talks to the internet
in exactly two situations, both of which you start: searching the add-on library
at extensions.gnome.org, and fetching the list of community Looks — which is one
public file published with gtheme's own code, because there is no server to run.

If you publish a Look, gtheme scans it first for anything private and shows you
what it found before you share it.

</details>

<details>
<summary><b>Why does an add-on need me to log out?</b></summary>

<br>

Because of how GNOME itself works, and gtheme will not pretend otherwise.

Your desktop looks for add-ons in its folders **once**, when it starts. An add-on
that arrives after that is invisible to it — there is no way to make it look
again. This is not a gtheme limitation; it was measured directly against GNOME 50
and the test suite still checks it on every full run, so that if a future GNOME
changes it, gtheme notices.

So there are two cases and gtheme tells you which one you are in:

- An add-on already on your computer can be switched on right now. "It's on."
- An add-on gtheme has just downloaded usually starts working immediately,
  because GNOME's own installer loads it for you. When it cannot, gtheme says "it
  starts working after you log out and back in" — and means it.

</details>

<details>
<summary><b>Why is something greyed out?</b></summary>

<br>

Because it would not do anything, and gtheme would rather tell you than let you
press it. Every greyed-out control carries the reason: the add-on that owns it is
switched off, the program is not installed, or another setting has to change
first.

</details>

<details>
<summary><b>Can I use it on Ubuntu or Fedora?</b></summary>

<br>

If it is running GNOME 49 or 50, yes. To find out, open your **Settings** app and
look at **System → About** — it prints the GNOME version there.

Older releases ship an older libadwaita than gtheme needs. On one of those, gtheme
shows a screen saying so and changes nothing, rather than opening a window that
half-works. gtheme was built and tested on Arch; the easy-way installer is written
to work anywhere and says exactly what is missing if it does not.

</details>

<details>
<summary><b>Where did the old command-line gtheme go?</b></summary>

<br>

Nowhere. v1 is preserved in full on the
[`legacy-v1`](https://github.com/blyatiful1/gtheme/tree/legacy-v1) branch and at
the [`v1-final`](https://github.com/blyatiful1/gtheme/releases/tag/v1-final) tag.
See [CHANGELOG.md](CHANGELOG.md) for what changed and why.

</details>

## Removing gtheme

It leaves nothing behind.

**First, put your desktop back.** Open **Undo & Restore Points** and go back to
**Before gtheme**. That returns every setting and file gtheme ever touched to its
original state. (From a terminal: `gtheme rescue`.)

Then:

- **Installed the easy way** — open a terminal in the `gtheme-main` folder and
  run `./install.sh --uninstall`. That removes the `gtheme` command and the entry
  in your app list; delete the folder itself and it is gone. If your desktop is
  still using a Look, the installer stops and says so rather than stranding you
  without the app that can put it back.
- **Installed with `makepkg -si`** — `sudo pacman -R gtheme`.

gtheme's own saved moments live in `~/.local/state/gtheme/v2` and are yours to
delete once you no longer want them.

## Getting help

- **A question, or you want to show off your desktop?**
  [Discussions](https://github.com/blyatiful1/gtheme/discussions) — no question is
  too basic there.
- **Something is broken?**
  [Open an issue](https://github.com/blyatiful1/gtheme/issues/new/choose). Say
  what you clicked and what happened; you do not need to know why.
- **A word you do not know?** [GLOSSARY.md](GLOSSARY.md).
- **Never used Linux before?** [docs/start-here.md](docs/start-here.md).
- **Found a security problem?** [SECURITY.md](SECURITY.md) — please do not open a
  public issue for it.

## Helping out

You do not have to be a programmer. **Most contributions are data files, not
code**: a Look, a plain-English description for an add-on, a setting that needs a
better sentence.

- [CONTRIBUTING.md](CONTRIBUTING.md) — how to add a Look, an add-on panel or a
  setting, and how to run the tests.
- [docs/preset-format.md](docs/preset-format.md) — writing a Look.
- [docs/architecture.md](docs/architecture.md) and
  [docs/testing.md](docs/testing.md) — how it works inside.

## Licence

MIT — see [LICENSE](LICENSE). Copyright © 2026 blyatiful1.
