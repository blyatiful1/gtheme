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
<img src="https://img.shields.io/badge/looks-can't%20run%20programs-brightgreen" alt="Looks only change settings">

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
[When something is wrong](#when-something-is-not-working) ·
[Accessibility](#getting-around-without-a-mouse-or-without-seeing-the-screen) ·
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
- You do not want to edit a config file or learn what "gsettings" means. You
  never have to. Installing gtheme takes a terminal window once — that is the one
  command-line step, and [docs/start-here.md](docs/start-here.md) walks you
  through opening one. After that, using the app needs no commands at all, except
  on the bad day when the app itself will not open.
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
| **Terminal colours** | Give your terminal, its prompt and its little status tools the same colours as the rest of your desktop: Ghostty, Ptyxis, GNOME Terminal, Console and Alacritty, plus fish, Starship, btop, cava and fastfetch. |
| **Night light, sound, power** | Warmer colours in the evening, the sounds your desktop plays, when the screen sleeps. |
| **Whole "Looks"** | Change all of the above at once. Six are built in — DAYBREAK, HEARTH, HYPERCLASS, MAGMA, NETRUNNER and NIGHTBLOOM — and you can save your own desktop as a Look and share it. |

Anything the other pages did not cover lands on a **More Settings** page
automatically, so nothing on your desktop is hidden from you.

## Why it's safe to try

This is the part that makes gtheme different from every other GNOME
customisation tool, so it is worth thirty seconds of your time:

- **Everything is saved first.** Before the first byte moves, gtheme records
  exactly what was there. That is not only true of whole Looks: a single switch
  you flip on one of the pages is written down the same way, before it takes
  effect. Even a power cut halfway through leaves a complete record of what had
  changed by then.
- **One click puts it back.** **Ctrl+Z** undoes the last change, from anywhere in
  the app — a whole Look or a single switch.
- **"Before gtheme" is kept forever.** The first time you open the app, before you
  have touched a thing, gtheme saves how this computer looks. That record is never
  overwritten and never deleted, however many Looks you try afterwards. A year
  later, it still means *before gtheme*.
- **Nothing happens that you haven't seen.** Applying a Look opens a list of every
  setting it will change as before → after, every file it will write by
  destination, and every add-on by name — before it changes anything.
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
| **About 60 MB of disk space** | Most of that is the pictures the six built-in Looks use. |
| **English** | Everything *inside* the window is English only today — every label, every explanation, every warning — and there is no translation machinery behind it yet: no language files, nothing for a translator to fill in. The one part that is already translated is how you find the app: the launcher entry and the software-store listing carry German, Brazilian Portuguese, Spanish and French names, descriptions and search words, so typing "Thema", "aparência", "fondo de pantalla" or "apparence" turns gtheme up in your applications list. If you would like the app itself in your language, [say so in an issue](https://github.com/blyatiful1/gtheme/issues) — knowing somebody is waiting is what decides when that groundwork gets built. |

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
Everything gtheme installs is in that folder, in plain text you can read if you
would like to look first.

**3. Open a terminal in that folder.**
Right-click the `gtheme-main` folder and choose **Open in Terminal**. A window
with a text prompt appears. This is the only time you will need it.

> No **Open in Terminal** in the menu? [docs/start-here.md](docs/start-here.md#opening-a-terminal)
> shows two other ways, and explains how to copy and paste into a terminal.

**4. Run the installer.** Type this and press **Enter**:

```sh
./install.sh
```

It checks that the pieces it needs are present — and it asks libadwaita its
version, so a desktop older than GNOME 49 is refused before anything is created
rather than left with an app that cannot open — then sets itself up in its own
private corner of that folder so it cannot disturb anything else, and adds
**Gtheme** to your list of applications. It prints what it
is doing as it goes. If something is missing it stops and tells you the exact
command to install it — it never installs system packages behind your back.

**5. Open it.**
Press the **Super** key (the one with the Windows logo on most keyboards), type
`gtheme`, and press **Enter**.

> [!NOTE]
> Keep the `gtheme-main` folder where it is — the app runs from it. If **Gtheme**
> is not in your app list yet, log out and back in.

<details>
<summary><b>The Arch way</b> — Arch, CachyOS, EndeavourOS</summary>

<br>

The repository ships a `PKGBUILD`, so:

```sh
git clone https://github.com/blyatiful1/gtheme
cd gtheme
makepkg -si
```

That builds the released source archive for the version named in the `PKGBUILD`
and installs it with `pacman`, which means `sudo pacman -R gtheme` removes it
completely later. Dependencies are declared in the recipe and `makepkg -s` pulls
them in, and the build runs the test suite before it packages anything.

There is a second recipe beside it, `PKGBUILD-git`, which builds **the checkout
you have** rather than a release — for following the main branch, or testing a
change of your own:

```sh
makepkg -si -p PKGBUILD-git
```

That one installs a package called `gtheme-git`, removed with
`sudo pacman -R gtheme-git`.

</details>

<details>
<summary><b>Keeping it up to date</b></summary>

<br>

gtheme never updates itself, and nothing in it phones home to see whether a new
version exists. Updating is you doing the same thing you did to install it.

**Installed the easy way.** Download the new ZIP, unpack it over the same folder
(or unpack it fresh and delete the old folder afterwards), then run the installer
again from that folder:

```sh
./install.sh
```

Running it a second time is safe and is the intended way to update. It reuses the
private folder it made last time — rebuilding it only if your system's Python
changed underneath it — repoints the `gtheme` command at the folder you just ran
it from, and rewrites the app-list entry. **Keep the folder.** gtheme runs *out
of* it: deleting it after installing breaks the command and the launcher.

**Installed with `makepkg`.** Pull and rebuild with the same recipe you used the
first time (`makepkg -si`, or `makepkg -si -p PKGBUILD-git`).

**What an update does to your desktop: nothing.** Your saved moments, the "Before
gtheme" record and the ownership ledger live in `~/.local/state/gtheme/v2/`,
outside both the program folder and the package, so they survive an update, a
reinstall and a removal. A new version reads the same records the old one wrote.

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
cards:

1. **Change how your desktop looks.** What the app is for.
2. **You can always go back.** The important one: *before anything changes, gtheme
   saves how your desktop looks right now. One click puts it back.*
3. **Two ways to work.** Pick a whole look at once, or change one thing at a time
   from the list down the side.
4. **Save how it looks now.** One button, and it does a real thing: it saves your
   desktop exactly as it is at this moment, so you have somewhere to return to
   before you have changed anything at all. **Press it.**

Then try this:

1. Open **Looks** in the list on the left and click one of the six built-in Looks.
   It will *ask* before it changes anything, and tell you exactly what it is about
   to change.
2. Look at your new desktop.
3. Don't like it? Press **Ctrl+Z**.

Two shortcuts worth learning on day one:

- **Ctrl+F** searches everything — every setting, every explanation, every Look,
  every add-on, in the words you would actually use. Type "taskbar", "make text
  bigger" or "dark mode" and it takes you straight to the row and flashes it. You
  never have to learn where things live.
- **Ctrl+Z** undoes the last change, from anywhere in the app.

You can skip the introduction, and bring it back any time from the **☰** menu →
**Show the introduction again**.

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

A Look changes your background, colours, icons, text and add-ons all at once. Six
are built in, and **Get more** lists what the community has published:

| | |
|---|---|
| **DAYBREAK** | First light: warm white surfaces, palest sage underfoot, a leaf-green highlight. Sunrise through a glasshouse roof. |
| **HEARTH** | Banked embers: cream surfaces, amber light low in the frame, a terracotta highlight. It turns Night Light on so the evening matches the picture. |
| **HYPERCLASS** | Gilded void: first class aboard a starliner, champagne brass on deep-space ink, one vein of ice. |
| **MAGMA** | Obsidian flow: obsidian glass over a living magma chamber, ember orange and lava gold, one cool teal vein. |
| **NETRUNNER** | Jack in: a netrunner's deck in Night City, HUD cyan on a desaturated navy void, one cyber-yellow signature per surface. |
| **NIGHTBLOOM** | The glasshouse after dark: glass panes over deep green, bioluminescent jade, exactly one amber firefly on every surface. |

DAYBREAK and HEARTH are the two light ones, and they use only what a stock GNOME
desktop already has: no add-ons, nothing to download.

Clicking one does not apply it. It opens a dialog that says, in your words, what
is about to change ("Wallpaper, highlight colour, icons, and 3 add-ons"). Only
then does it run, as one all-or-nothing operation: if any part of it fails, the
whole thing is rolled back and you are told what happened. A saved moment is taken
automatically first, and the message afterwards has an **Undo** button in it.

You can also save your own desktop as a Look and share it. gtheme scans what it
captured for anything private — your username in a file location, a key some
add-on stored — and shows you what it found before you send it anywhere.

A Look is nothing mysterious once you have one: a folder with a `theme.toml` file
in it and the pictures it uses beside it, kept in
`~/.local/share/gtheme/v2/themes`. You can open it, read it and edit it in any
text editor; `gtheme validate <folder>` checks one over before you share it; and
[docs/preset-format.md](docs/preset-format.md) explains every field.

If you keep your setup in a repository, `gtheme apply <name-or-folder>` puts a
Look on from a terminal, with `--dry-run` to see what it would change first. It
is the same machinery the tiles on this page use, down to the saved moment taken
before anything moves — "Can I use a Look without opening the app?" under
[Questions people ask](#questions-people-ask) has the details.

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

Icon sets are shown as a row of their own actual icons. A name in a dropdown tells
you nothing about what you are about to get. Pointer styles are tiles with a size
choice; the page admits that a pointer cannot be drawn from inside an app, and
that most computers have exactly one installed, rather than looking broken and
saying nothing.

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

- Every add-on gets a sentence saying what it does, in plain words. Their internal
  identifiers are never shown anywhere in gtheme.
- Twenty-four popular add-ons have a hand-written settings panel, so their options
  are explained the same way everything else in the app is. The rest get an honest
  generic panel labelled "these settings come from the add-on author".
- Add-ons that fight each other (two docks, two clipboard managers) are offered as
  either/or on this page, with an offer to switch the other one off. The same
  check runs before a whole Look is applied: a Look that brings a dock you already
  have says so in its preview, by name, rather than leaving you with two of them.
- Combinations known to break things carry a warning that says what will happen to
  you, not what will happen internally.
- Adding an add-on **from this page** goes through GNOME's own confirmation box:
  the desktop shows it, naming the add-on, and gtheme cannot install one behind
  it. Adding the add-ons a whole Look asks for is the other path — there gtheme
  downloads them itself from extensions.gnome.org after you press the button that
  says so, and no GNOME box appears. On that path the Look's own preview names
  each one — what it is called, who wrote it and where it comes from — before
  anything is fetched, so the list you press the button under is the list you get.
  See [SECURITY.md](SECURITY.md) for what that means.

### Terminal

![The Terminal page, one card per terminal program actually installed](docs/media/screenshots/terminal-light.png)

If you use a terminal, gtheme can give it, its prompt and its little status tools
the same colours as your Look: **Ghostty**, **Ptyxis**, **GNOME Terminal**,
**Console** and **Alacritty**, plus **fish**, **Starship**, **btop**, **cava** and
**fastfetch**. One card per program that is *actually installed* — a list of ten
with nine greyed out is a list of things you cannot do.

Two honest notes on that list. GNOME Terminal, the one Ubuntu ships, takes the
Look's colours in full. Console, the one GNOME ships, chooses its own colours to
go with light or dark mode and offers no palette anyone else may write, so the
one thing gtheme changes there is the see-through background — and Console's card
says that on the page, next to the colours it is not going to give you.

Each card says honestly when you will see the change: some terminals update while
you watch, some within a second, some only when you open a new window.

One card goes further. Ghostty keeps its settings in a folder that dotfile setups
often own outright, so gtheme checks: if that folder belongs to another tool, it
refuses to write, names the tool, and offers to take over — a deliberate act, and
an undoable one. The other cards do not make that check yet, and neither does
applying a whole Look.

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
generated, not written: every setting a GNOME 50 desktop has is accounted for in a
list the test suite checks, and anything with no home lands here automatically,
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
this app ever changed anything. It is saved the first time you open gtheme, before
you have touched a single thing, and it is never deleted and never pruned. If you
are coming from the old command-line gtheme, that row is read from version 1's own
records instead, so it reaches back to before *that* ever ran.

There is one way not to get that row, and gtheme would rather leave it out than
put the wrong name on it: if you used `gtheme apply` in a terminal before ever
opening the window, your desktop had already been changed by the time the app
first ran, and a snapshot taken then would not be "before gtheme" at all. So it is
not taken. The first-touch record below still covers you, and so does the saved
moment that `gtheme apply` took before it changed anything.

Underneath it there is a second, independent way back that needs no saved moment
at all: the **first-touch record**. The first time gtheme changes any setting or
file — a whole Look, or one switch on one page — it writes down what was there and
never writes over that note, so `gtheme rescue` puts all of it back however many
Looks you try afterwards.

</details>

## I changed something and I want it back

Three ways, from easiest to most stubborn. **Any one of them is enough**, you do
not have to reinstall anything, and none of them deletes a thing.

### 1. The app opens

Press **Ctrl+Z**, or click **Undo last change** at the top of the window. Or open
**Undo & Restore Points** in the list on the left and pick the moment you want
back — including *Before gtheme*, how your desktop looked before this app ever
changed anything.

### 2. The app won't open, but the desktop works

Open a terminal window (hold **Ctrl**, **Alt** and press **T**; if that does
nothing, [docs/start-here.md](docs/start-here.md) shows another way) and type:

```sh
gtheme rescue
```

That puts every setting and file gtheme touched back the way it was, and switches
off every add-on gtheme switched on. It needs no window, no mouse, and no graphics
at all.

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

## When something is not working

Recovery is [just above](#i-changed-something-and-i-want-it-back). This is the
step before it: finding out what actually happened.

<details>
<summary><b>Six things to try, in order</b></summary>

<br>

**1. What did gtheme actually do?** Open the app, then the menu in the top right
(☰) → **Copy details for a bug report**. That puts on your clipboard: the gtheme
version, your GNOME and libadwaita versions, your Python version, and the last 40
lines of gtheme's own log. No setting values, no file contents, nothing about your
desktop beyond its version numbers — it is written to be safe to paste into a
public issue.

**2. The log itself.** `~/.local/state/gtheme/v2/gtheme.log`, plain text, and
everything gtheme does goes into it including `gtheme rescue`. To get more detail
out of a run that misbehaves:

```sh
GTHEME_LOG_LEVEL=DEBUG gtheme
```

**3. The app will not open at all.** Run it from a terminal — `gtheme` — and read
what it prints. Two answers are common and neither is a bug: your GNOME is older
than 49 (gtheme says so and stops, rather than half-working), or the window opened
on a desktop that is not GNOME.

**4. "Permission denied".** Nothing gtheme does needs `sudo`, and it never asks
for it, so a permission error is almost always one of these:

- **`./install.sh` says `Permission denied`** — the downloaded file is not marked
  runnable, which is what unpacking a ZIP often does. Either `chmod +x install.sh`
  and run it again, or run it without the mark: `bash install.sh`.
- **`gtheme: command not found`** — a different problem with a similar feel:
  `~/.local/bin` is not in your `PATH`. The installer says so at the end and
  prints the line to add; logging out and back in fixes it on most systems.
- **A control says the change was refused** — your settings store is locked (some
  managed or corporate desktops do this with a *dconf lock*). gtheme shows the
  row's real value again and says the change did not happen, rather than showing
  you a switch that lies. It cannot get past that lock and will not pretend to.
- **A Look will not write a file** — a folder somewhere in the destination is
  read-only, or is a symbolic link into a place gtheme will not write. The whole
  Look is rolled back and the reason names the file.

**5. Checking a Look before blaming the app.** If it is a Look you wrote or
downloaded:

```sh
gtheme validate ~/dotfiles/my-look
```

It reads `theme.toml`, prints every mistake the format does not allow — each one
naming the field it is in — and warns about colour pairs nobody could read against
each other, all without changing anything. What a Look is allowed to contain,
field by field, is [docs/preset-format.md](docs/preset-format.md).

For "this Look asks for an icon set this computer does not have", open the Look in
the app instead: the preview dialog says so before it applies, which is a check
that needs your actual desktop and so cannot be done from a file alone.

**6. Still wrong?** [Open an issue](https://github.com/blyatiful1/gtheme/issues)
with the details from step 1 pasted in.

</details>

## Getting around without a mouse, or without seeing the screen

This is the accessibility section, and it is an honest one rather than a
reassuring one: some of this is done, some of it is not, and the difference is
written down here so you can decide before you install rather than after.

**What works today.**

| | |
|---|---|
| **The keyboard** | Every page is reachable from the keyboard. **Ctrl+?** opens the list of every key gtheme answers — the same window every GNOME app opens on that key. **F6** puts the keyboard into the list of pages on the left, which on a narrow window means showing that list first. **Ctrl+F** searches every setting in the app by name, and Enter takes you to the control itself. **Ctrl+Z** undoes the last change gtheme made. |
| **Pictures have words** | Every picture the app shows — your background on the Home page, the tiles on Wallpaper, Icons & Pointer and Looks — carries a description for a screen reader, naming what it is a picture *of* rather than "image". |
| **A Look is told not to take your settings away** | If you have high contrast on, larger text, or animations turned off, and a Look would write over one of those, the preview says so in words **before** anything happens. It is one of the lines in the "here is what is about to change" dialog, not a footnote afterwards. |
| **Colours that cannot be read are caught** | `gtheme validate` checks a Look's colours against the WCAG contrast ratio and warns about pairs that are not a mood but a mistake. |
| **The window fits your screen** | gtheme opens at a size that fits the space your desktop actually gives it, rather than a fixed size that can put its buttons off the bottom of a small or scaled screen. |

**What is missing, plainly.**

- gtheme has not been tested with **Orca**, GNOME's screen reader. Widgets are
  built out of libadwaita's own rows, which carry their names and roles for free,
  so much of it should work — but "should" is not "was tried", and it would be
  dishonest to print anything stronger here.
- The app is **English only**, with no translation machinery behind it yet. See
  the English row under [Install](#install).
- There is no high-contrast styling of gtheme's own window beyond what GNOME gives
  every app.

If you use one of these and something is wrong,
[an issue](https://github.com/blyatiful1/gtheme/issues) naming the tool and what
happened is worth more than any amount of guessing on this side.

## Questions people ask

<details>
<summary><b>Will this break my desktop?</b></summary>

<br>

Not permanently, and it is designed so that it cannot.

- **Nothing is applied that you have not seen first.** Every Look shows you what
  it is about to change, in your words, before it changes it.
- **Everything is saved first.** Before the first byte moves, gtheme records
  exactly what was there. That recording is written as it goes, so even a power
  cut halfway through leaves a complete record of what had changed by then.
- **Changes are all-or-nothing.** If any step of applying a Look fails, the whole
  thing is rolled back. gtheme never leaves you with a half-changed desktop.
- **The first record is never overwritten.** The first time gtheme changes anything
  it writes down what was there and never writes over that note, however many
  changes you make afterwards — so `gtheme rescue` a year later still puts back
  what this computer looked like before gtheme first touched it. That record is not
  only about Looks: a switch you flip by hand on one of the individual pages
  (Wallpaper, Colours & Style, Fonts, Terminal and the rest) is written down the
  same way, before it takes effect, and comes back with everything else. A saved
  moment is still the more thorough route, and for a different reason: **Undo &
  Restore Points** captures every setting gtheme knows how to change, not only the
  ones something has touched, so a moment saved before an afternoon of tweaking
  takes you back to exactly that afternoon rather than to the day you installed the
  app.
- **Looks cannot run programs.** See [SECURITY.md](SECURITY.md).

The honest limits: a badly-behaved *add-on* — third-party code, published by
someone else, that GNOME loads into your desktop — can still misbehave, and that is
true whether you install it through gtheme, through GNOME's own app, or from a
website. gtheme's answer is that it always knows which add-ons it switched on, so
`gtheme rescue` can switch them all back off without the desktop's help.

</details>

<details>
<summary><b>Do I need to know anything about Linux, the terminal, or GitHub?</b></summary>

<br>

No. You need a terminal exactly once, to run the installer, and step 3 of
[the easy way](#the-easy-way-recommended) shows you how to open one by
right-clicking a folder. After that the app is a window like any other.

If a word in this README is unfamiliar, [GLOSSARY.md](GLOSSARY.md) explains it,
and [docs/start-here.md](docs/start-here.md) covers what a Linux system is, how to
open a terminal, and how to copy and paste into one.

</details>

<details>
<summary><b>Does it send anything anywhere?</b></summary>

<br>

No. gtheme has no account, no server and no telemetry. It talks to the internet in
exactly two situations, both of which you start: searching the add-on library at
extensions.gnome.org, and fetching the list of community Looks — which is one
public file published with gtheme's own code, because there is no server to run.

If you publish a Look, gtheme scans it first for anything private and shows you
what it found before you share it.

</details>

<details>
<summary><b>Why does an add-on need me to log out?</b></summary>

<br>

Because of how GNOME itself works, and gtheme will not pretend otherwise.

Your desktop looks for add-ons in its folders **once**, when it starts. An add-on
that arrives after that is invisible to it — there is no way to make it look again.
This is not a gtheme limitation; it was measured directly against GNOME 50 and the
test suite still checks it on every full run, so that if a future GNOME changes it,
gtheme notices.

So there are two cases and gtheme tells you which one you are in:

- An add-on already on your computer can be switched on right now. "It's on."
- An add-on gtheme has just downloaded usually starts working immediately, because
  GNOME's own installer loads it for you. When it cannot, gtheme says "it starts
  working after you log out and back in" — and means it.

Those two sentences differ by one clause and by the entire question of whether the
app is telling you the truth.

</details>

<details>
<summary><b>Why is something greyed out?</b></summary>

<br>

Because it would not do anything, and gtheme would rather tell you than let you
press it. Every greyed-out control carries the reason: the add-on that owns it is
switched off, the program is not installed, or another setting has to change first.

</details>

<details>
<summary><b>Why do some of my apps still look wrong?</b></summary>

<br>

Almost always because they are **Flatpaks or Snaps**, and that is a boundary gtheme
cannot cross — nor should it.

A Look changes how apps look by writing `~/.config/gtk-4.0/gtk.css`,
`~/.config/gtk-3.0/gtk.css` and sometimes a theme folder under
`~/.local/share/themes/`, and by setting your icon theme and font. An ordinary app
reads all of that. A Flatpak or a Snap runs in a container that deliberately cannot
see those files: the Flatpak has its own private `~/.var/app/…/config`, and a Snap
sees only the themes shipped inside the `gtk-common-themes` snap. So the same
button is one colour in your text editor and another in the Flatpak one, with
nothing anywhere saying why. Ubuntu ships a good number of Snaps preinstalled,
which is why this bites hardest there.

gtheme does not reach into either sandbox, because doing so means punching holes in
a security boundary somebody else set up on purpose. If you want to punch one
anyway, that is Flatpak's own job and it is one command per thing you want visible:

```sh
flatpak override --user --filesystem=xdg-config/gtk-4.0:ro
flatpak override --user --filesystem=xdg-config/gtk-3.0:ro
flatpak override --user --filesystem=xdg-data/themes:ro
flatpak override --user --filesystem=xdg-data/icons:ro
```

Read `man flatpak-override` before running them; `--user` makes them yours rather
than the system's, and `:ro` makes them read-only. Snap has no equivalent for a
theme you installed yourself. Neither is something gtheme can undo for you, so
neither is something gtheme does.

</details>

<details>
<summary><b>I changed something in GNOME's own Settings — which one wins?</b></summary>

<br>

Whichever moved last, because there is nothing to fight over: gtheme and GNOME's
Settings write **the same settings**, in the same place. gtheme has no private copy
of your desktop's configuration and no daemon reapplying anything behind you.

What that means in practice:

- Change your highlight colour in GNOME Settings while gtheme is open and the
  gtheme window updates itself as you watch. It subscribes to every setting on a
  page you have opened, and refreshes that control rather than leaving a stale
  value on screen.
- Change it in gtheme and GNOME's Settings shows the new value next time you open
  it, for the same reason.
- Nothing is "locked" by gtheme. Applying a Look does not stop you changing any of
  it afterwards, from anywhere.

The one thing gtheme knows that Settings does not is *what it changed and what was
there before*. That is the whole ownership ledger and the first-touch record:
change something in GNOME's Settings and nothing writes it down, so nothing can put
it back. Change it in gtheme and both are true.

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
<summary><b>Can I use a Look without opening the app?</b></summary>

<br>

Yes, from a terminal window:

```sh
gtheme apply nightbloom
gtheme apply ~/dotfiles/my-look
gtheme apply ~/dotfiles/my-look --dry-run
```

Give it the name of a Look you have, or the folder one lives in. `--dry-run` prints
exactly what would change and changes nothing — including, by name, any file the
Look would write that can start a program.

It is the same machinery the button in the window uses: the same saved moment taken
before anything changes, the same refusal of anything a Look may not do, and the
same putting-everything-back if a step fails. It prints the reason and stops with a
failure code if the Look cannot be used, so a script can tell. This is for people
who keep their setup in a repository or rebuild a computer from a script; everyone
else should use the window.

</details>

<details>
<summary><b>Where did the old command-line gtheme go?</b></summary>

<br>

Nowhere. v1 is preserved in full on the
[`legacy-v1`](https://github.com/blyatiful1/gtheme/tree/legacy-v1) branch and at the
[`v1-final`](https://github.com/blyatiful1/gtheme/releases/tag/v1-final) tag. See
[CHANGELOG.md](CHANGELOG.md) for what changed and why.

</details>

## Removing gtheme

It leaves nothing behind. Do it in this order — the first step is the one that
matters.

**1. Put your desktop back first.** Open **Undo & Restore Points** and go back to
the moment you want — that is the thorough route, because a saved moment covers
every setting gtheme knows how to change, whether or not anything has touched it.
`gtheme rescue` in a terminal is the route that needs no window: it returns
everything gtheme changed — settings and files alike, a whole Look and a switch you
flipped by hand on a page — to how it was before gtheme first touched it, and
switches off every add-on gtheme switched on. Do this *before* removing anything,
because removing the app takes away the only thing that can read those records.

**2. Then remove it.**

- **Installed the easy way** — run the installer again with one extra word, from
  the same folder:

  ```sh
  ./install.sh --uninstall
  ```

  It takes back exactly what it put outside that folder, which is five things: the
  `gtheme` command (`~/.local/bin/gtheme`), the app-list entry
  (`~/.local/share/applications/io.github.blyatiful1.Gtheme.desktop`), the app-store
  listing (`~/.local/share/metainfo/io.github.blyatiful1.Gtheme.metainfo.xml`) and
  two icons (`~/.local/share/icons/hicolor/scalable/apps/io.github.blyatiful1.Gtheme.svg`
  and `~/.local/share/icons/hicolor/symbolic/apps/io.github.blyatiful1.Gtheme-symbolic.svg`).
  It refuses to run while gtheme still has a Look on your desktop, rather than
  stranding you — that is what step 1 is for. Then delete the folder you unpacked,
  and the program is gone.

  (Deleting the folder by hand instead leaves those five behind, and the app-store
  listing is enough to keep gtheme showing in your software app.)
- **Installed with `makepkg`** — `sudo pacman -R gtheme`, or
  `sudo pacman -R gtheme-git` if you built it with `PKGBUILD-git`.

**3. Your own things, if you want them gone.** Neither route deletes these,
deliberately:

| | |
|---|---|
| `~/.local/state/gtheme/` | your saved moments and the record of what your desktop was before gtheme changed it |
| `~/.local/share/gtheme/` | Looks you saved or downloaded |
| `~/.local/share/backgrounds/gtheme/` | copies of background pictures you added yourself |
| `~/.local/share/gnome-background-properties/gtheme.xml` | the entry naming those pictures in the desktop-wide list, so GNOME's own settings can find them too |
| `~/.config/gtheme/` | the app's own preferences |
| `~/.cache/gtheme/` | cached answers from extensions.gnome.org; safe to delete at any time |
| `~/.local/state/gtheme.v1-backup/` | only if you ever ran the old command-line gtheme. It is the one surviving record of this computer from before *that* ever ran, and nothing can rebuild it — keep it unless you are certain |

The full list of everywhere gtheme writes, and why, is in
[SECURITY.md](SECURITY.md#where-gtheme-keeps-things).

## Getting help

- **A question, or you want to show off your desktop?**
  [Discussions](https://github.com/blyatiful1/gtheme/discussions) — no question is
  too basic there.
- **Something is broken?**
  [Open an issue](https://github.com/blyatiful1/gtheme/issues/new/choose). Say what
  you clicked and what happened; you do not need to know why.
- **A word you do not know?** [GLOSSARY.md](GLOSSARY.md).
- **Never used Linux before?** [docs/start-here.md](docs/start-here.md).
- **Found a security problem?** [SECURITY.md](SECURITY.md) — please do not open a
  public issue for it.

## For people who want to help

You do not have to be a programmer. **Most contributions are data files, not
code**: a Look, a plain-English description for an add-on, a setting that needs a
better sentence.

- [CONTRIBUTING.md](CONTRIBUTING.md) — how to add a Look, an add-on panel or a
  setting, and how to run the tests.
- [docs/preset-format.md](docs/preset-format.md) — writing a Look.
- [docs/architecture.md](docs/architecture.md) and
  [docs/testing.md](docs/testing.md) — how it works inside.
- **Want gtheme in your language?** It is English only today and has no translation
  machinery yet, so there is nothing to fill in — but an issue saying which
  language you want is the thing that decides when that groundwork gets built.

## Licence

MIT — see [LICENSE](LICENSE). Copyright © 2026 blyatiful1.
