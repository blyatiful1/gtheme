# Security

## The promise

**Looks only change settings. They can't run programs on your computer.**

That sentence appears on the app's own welcome screen, and it is a property of
the design rather than a policy someone has to remember.

A Look is a folder containing pictures and one text file. The text file lists
settings to change and files to copy. There is no section in the format for
running a command, and there is no code anywhere in gtheme that could run one:

- the format is defined by strict models that reject any field they do not
  recognise, so a Look with a `[[hooks]]` section — the section version 1 of
  this project had, which really did run scripts — fails to load rather than
  being ignored;
- a Look compiles to exactly four kinds of operation: write a file, write a
  setting, switch an add-on on, install an add-on. There is no fifth a Look can
  reach. The layer underneath knows three more — delete a file, put a symbolic
  link back, clear a setting — and those exist so that *undoing* can restore an
  absence: they are produced only by a restore point or by the undo path, never
  by anything a Look says. Seven in total, the set is closed, and **not one of
  the seven runs anything**;
- version 1 Looks are converted, not accepted. The converter drops each script
  and prints a warning naming what that script used to do. Nothing survives the
  conversion silently.

This is a direct answer to a real incident elsewhere: a downloadable "global
theme" for another Linux desktop ran a delete command and wiped users' mounted
drives, because on that desktop a theme can contain executable code. Here it
cannot.

## What a Look can still do, and what stops it going further

A Look can copy files into your home folder and change your desktop's
settings. Three boundaries constrain that, and all of them are checked before
the first byte is written, not as it goes:

**Where files may land.** Every destination is resolved — following `..` and
following symbolic links — and must come out below your home folder. A Look
asking to write to `~/../../etc/sudoers`, or shipping a link that points
outside its own folder, is refused. The whole operation is refused, before
anything has happened, rather than partway through.

**Where files may come from.** Sources are resolved the same way and must stay
inside the Look's own folder, so a Look cannot use a symbolic link as a siphon
to copy your private keys out into somewhere it can publish them.

**What may be written, not only where.** Inside your home folder there are
places where putting a file *is* arranging for a program to run, and settings
that decide what your desktop runs. A Look may not touch either: the autostart,
background-service and command folders, the start-up files of a command window,
anything named `.desktop` or `.service`, the command behind a keyboard
shortcut, which program opens when your desktop needs one, and any raw settings
location outside the add-on areas a decorative Look legitimately reaches into.
A Look asking for one of these does not apply at all — not "minus that part" —
and the reason is named before anything happens. The list is one documented
file, `src/gtheme/core/policy.py`, so it can be read and argued with.

The same list has a second half, for a case where refusing would be wrong: a
Look may theme your command window by writing that program's own settings file,
and some of those formats can also name a command for that program to run —
`~/.config/starship.toml` is the example, and three of the four Looks shipped
with gtheme write it. Those are allowed and are **named one by one** in the
preview, never folded into "23 files". Being able to see them is what makes
allowing them reasonable.

**Everything is recorded first.** Before gtheme changes anything, it records
what was there. Any Look can be completely undone, including one that turns out
to be malicious rather than merely ugly.

**Nothing is silently overwritten through a link.** If the place a file would
land is a symbolic link into some other project, gtheme replaces the link
rather than writing through it — and for the specific case of a settings folder
managed by another tool, it refuses to write at all until you say otherwise.

## Add-ons are a different matter, and we say so

Add-ons (GNOME calls them extensions) are third-party code that your desktop
loads and runs. That is what they are for; it is also what makes them the
riskiest thing gtheme can help you install, and no amount of care on our side
changes that.

What gtheme does about it:

- **Nothing is installed unless you ask for it, and it can only come from one
  place.** There are two ways an add-on arrives, and they are not the same.
  Adding one from the Add-ons page asks the desktop to do it: GNOME shows you
  its own confirmation box, naming the add-on, and gtheme cannot install one
  behind that box. Adding the add-ons a Look asks for works differently —
  gtheme downloads them itself from extensions.gnome.org and hands each one to
  the desktop's own installer program, with **no** GNOME confirmation box in
  between. On that path the button you press is the confirmation: nothing is
  fetched until you press it, extensions.gnome.org is the only address gtheme
  ever downloads an add-on from, and a Look can therefore only ask for add-ons
  that are already published there. What that button cannot yet do is name the
  add-ons it is about to fetch — it says how many; naming them is being fixed,
  and until it is, the Add-ons page is where you can look each one up first.
- **A Look never carries add-on code.** It can name an add-on it would like,
  and gtheme offers to fetch that add-on from extensions.gnome.org — the same
  place GNOME's own website installs from. A Look that names a private add-on
  you do not have is applied without it, and says which part will therefore not
  work.
- **gtheme remembers which add-ons it switched on**, so `gtheme rescue` can
  switch exactly those back off from a text console when the desktop itself is
  unusable.

## What gtheme sends, and where

Nothing, unless you ask, and then only these two:

| When | Where | What is sent |
|---|---|---|
| You search for add-ons, or open the Add-ons page's Discover or Updates view | `extensions.gnome.org` | your search words, and your GNOME version so that incompatible results can be filtered out |
| You open the "Get more" list of community Looks | `raw.githubusercontent.com` | nothing but the request for one public file |

There is no account, no server run by this project, no telemetry, no crash
reporting, and no identifier of any kind attached to those two requests.

When you publish a Look of your own, gtheme scans what it captured for things
you would not want to share — your username inside a file location, tokens or
keys some add-on stored in its settings — and shows you what it found before
you send it anywhere.

## Where gtheme keeps things

Everything gtheme writes for itself is in one of these. There is nothing
outside your home folder.

| | |
|---|---|
| `~/.local/state/gtheme/v2/` | the record of what your desktop looked like, the list of what gtheme currently owns, which Look is applied, your saved moments, and the lock file that stops two copies changing things at once |
| `~/.local/state/gtheme.v1-backup/` | a copy of version 1's records, **read-only, always**. It holds the only surviving record of this desktop before gtheme version 1 ever ran, and nothing in version 2 writes to it |
| `~/.config/gtheme/prefs.json` | the app's own preferences (window size, which one-off notices you have dismissed) |
| `~/.local/share/gtheme/v2/themes/` | Looks you saved or downloaded. The four that ship with gtheme are not here — they are inside the installed program |
| `~/.local/share/backgrounds/gtheme/` | copies of background pictures you added yourself, so that moving the original later cannot break your desktop |
| `~/.cache/gtheme/ego/` | the last few answers from extensions.gnome.org, so the Add-ons page does not re-ask for the same list. Deleting it costs nothing |
| `~/.local/share/gnome-shell/extension-updates/` | GNOME's own folder for an add-on update waiting to be moved into place at your next login. gtheme writes an update there rather than over a running add-on |

Two more places belong to somebody else:
`~/.local/share/gnome-shell/extensions/` and `/usr/share/gnome-shell/extensions/`,
where the add-ons on this computer live. gtheme reads them, and it also puts
add-ons into the first one — by handing the downloaded package to GNOME's own
`gnome-extensions install` command rather than unpacking files there itself.
Whether you are shown GNOME's own confirmation box first depends on the route:
the **Add-ons** page asks the desktop to install, so the desktop shows you its
dialog; the add-ons a **Look** fetches when you press its "Get the missing
ones" button are installed from the package without that dialog. Nothing in
`/usr/share/gnome-shell/extensions/` is ever written — that one is read-only to
gtheme, and would need administrator rights it never asks for.

Files a Look writes are a separate matter: those go where the Look says, which
may be anywhere below your home folder (`~/.config/alacritty/alacritty.toml`,
for instance) and never anywhere else — that is the boundary above. Every one
of them is written down in the ownership ledger first, which is what makes
`gtheme rescue` able to find them again.

If you have moved your home folders with the `XDG_*` variables, the paths above
follow them.

The launcher and app-list entry the installer adds are listed in the README,
under [Can I remove it?](README.md#can-i-remove-it).

gtheme runs entirely as you. It never asks for administrator rights, and
nothing it does needs them.

## Reporting a problem

**Please report privately first.**

Use GitHub's private vulnerability reporting: go to
<https://github.com/blyatiful1/gtheme/security/advisories/new> — or the
**Security** tab of the project page on GitHub, then **Report a vulnerability**. That
creates a report only the maintainers can see.

If that page is unavailable to you, open a normal issue at
<https://github.com/blyatiful1/gtheme/issues> saying only that you have a
security report and asking for a private channel. Do not put the details in a
public issue.

Please include, as far as you can: what you did, what happened, what you
expected, your distro and GNOME version, and whether a Look, an add-on or the
app itself was involved.

**What to expect.** This is a small project maintained by one person, so the
honest answer is that there is no guaranteed response time. Reports are read.
Anything that lets a Look escape the two boundaries above, or that gets code
running from something a user believed was decoration, is treated as the most
serious class of bug there is here and takes priority over everything else.

**In scope:** gtheme itself, the Look format, the change-applying layer, the
community list of Looks, and anything shipped with this project.

**Out of scope:** the behaviour of individual add-ons published on
extensions.gnome.org (report those to their authors and to GNOME), and bugs in
GNOME itself or in your distro. If gtheme *presents* one of those unsafely — makes
something dangerous look routine — that part is in scope, and worth telling us
about.

## Supported versions

Version 2 is the only line receiving fixes. Version 1 is preserved on the
`legacy-v1` branch for people who still depend on it, but it is not maintained,
and it is the version that could run scripts.
