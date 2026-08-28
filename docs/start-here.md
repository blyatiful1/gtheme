# Start here

For people whose first Linux computer is the one in front of them. Nothing here
is about gtheme yet — it is the handful of things everything else assumes you
already know. Five minutes.

If a word in the rest of the documentation is unfamiliar, it is probably in
[GLOSSARY.md](../GLOSSARY.md).

---

## What you are actually running

Windows comes from Microsoft. macOS comes from Apple. There is one of each, and
everybody's copy is the same.

Linux is not like that. **Linux** itself is only the engine — the part that
talks to your hardware. It has no desktop, no windows and no buttons. Those
come from other projects, and somebody has to assemble the engine, a desktop,
a browser, an app installer and a few hundred other pieces into something you
can actually switch on.

That assembled whole is called a **distribution**, or **distro**. Fedora,
Ubuntu, Arch, Debian, Linux Mint and CachyOS are distros. They differ in which
pieces they pick, how new those pieces are, and how you install more software —
but they run the same programs, and a program written for one usually works on
all of them.

**Why this matters to you:** when instructions on the internet say "install
this", the *how* depends on your distro. Nearly always you want your system's
own app installer — the one with the shopping-bag icon, usually called
**Software** — rather than downloading something from a website. That is the
opposite habit from Windows, and it is the safer one.

**gtheme is an exception, and it is worth knowing why.** It is not in any
distro's catalogue yet, so installing it means downloading it from its own
project page and running its installer from a terminal, once. What makes that
safe is that you can read what you downloaded before you run it — the
[install steps](../README.md#install) are written around exactly that, and
gtheme deliberately offers no "paste this line and it downloads and runs
something" shortcut. On Arch and its relatives there is a package recipe
instead, which is closer to the normal habit.

To find out which distro you have: open **Settings**, then **System**, then
**About**.

## The desktop, and which one is yours

The bar across the top of the screen, the clock, the window buttons, the
Settings app — that is your **desktop**, and it is a separate thing from Linux
underneath. gtheme is for the one called **GNOME**.

You are probably on GNOME if: there is a bar across the very top of the screen
with a clock in the middle, the top-left says **Activities** or has a dot
indicator, and pressing the **Super** key (the one with a Windows logo on most
keyboards) zooms out to show all your windows and a search box.

The same **Settings → System → About** screen tells you for certain.

## Opening a terminal

A **terminal** is a window where you type commands instead of clicking. You do
not need one to use gtheme — you need one to install it, and you need one on
the bad day when the graphical part of your computer has stopped working.

Three ways, any of which works:

1. **From your app list.** Press **Super**, type `terminal`, press **Enter**.
   Depending on your distro the app is called Terminal, Console, Ptyxis or
   Ghostty. They are all the same kind of thing.
2. **From a folder.** In the **Files** app, right-click an empty part of a
   folder and choose **Open in Terminal**. This is the useful one, because the
   terminal opens *already inside that folder* — which is exactly what the
   gtheme install steps need.
3. **The keyboard shortcut.** Hold **Ctrl** and **Alt** and press **T**. Many
   distros set this up; some do not, so if nothing happens, use one of the
   first two.

## What you see when it opens

Something like this:

```
you@your-computer ~ $
```

That is the **prompt**. It is telling you your username, your computer's name,
and which folder you are currently in (`~` means your home folder). It is
waiting.

You type a command, press **Enter**, and it does the thing and prints what
happened. Then it shows the prompt again, waiting for the next one.

**Nothing happens until you press Enter.** If you have typed something wrong,
hold **Backspace** until the line is empty, or press **Ctrl+C** to abandon the
line and start again. Neither of those breaks anything.

## Copying and pasting into a terminal

The normal **Ctrl+V** does not paste in most terminals — it means something
else there, for historical reasons nobody is happy about.

Use **Ctrl+Shift+V** instead. Or right-click and choose **Paste**. Copying out
of a terminal is **Ctrl+Shift+C** the same way.

When you paste a command, look at it before pressing Enter. A pasted command
that came from a web page is code you have not read, running as you. This is
worth a habit, not a fright: read it, then press Enter.

## The two commands the gtheme instructions use

**`cd` — go into a folder.**

```sh
cd Downloads
```

Moves you into the `Downloads` folder that is inside where you are now. `cd ..`
goes back up one. You can see where you are from the prompt, which changes as
you move.

If you opened the terminal with **Open in Terminal** from the Files app, you
are already where you need to be and can skip this entirely.

**`./something.sh` — run a file that is in the folder you are in.**

```sh
./install.sh
```

The `./` part means "the one right here", not "some program installed on the
system". It is a small deliberate speed bump: it makes running a downloaded
file look different from running a normal command, so you always know which
one you are doing.

## Two habits worth having

**Never paste a command you have not read.** Especially not one that starts by
downloading something and immediately running it. gtheme deliberately offers no
such command, so that this documentation is not teaching you the habit.

**`sudo` means "as the administrator".** A command starting with `sudo` asks
for your password and then has permission to change anything on the computer,
including things that stop it starting. gtheme never needs it — installing it
the easy way touches nothing outside your own home folder. If instructions for
anything ask you for `sudo`, that is your cue to read the command properly
before pressing Enter.

## Now go install gtheme

[Back to the README](../README.md#install). If anything on the way uses a word
you do not recognise, it is in [GLOSSARY.md](../GLOSSARY.md).
