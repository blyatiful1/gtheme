"""gtheme — change how your GNOME desktop looks, safely.

The version below is the single source of truth: ``pyproject.toml`` reads it
via ``[tool.hatch.version]``, and the app surfaces it in the About dialog.
Two files outside Python's reach must be kept equal to it by hand — ``PKGBUILD``
(``pkgver``) and ``data/io.github.blyatiful1.Gtheme.metainfo.xml`` (the newest
``<release>``) — because ``pacman -Qi`` and the About dialog naming different
builds is how a bug report stops being traceable to one.

It is a plain ``2.0.0`` and not ``2.0.0.dev0``: the three places now agree, and
this is the version a build of this tree calls itself, tag or no tag.
"""

__version__ = "2.0.0"

#: Reverse-DNS application id. This exact string is used in three places that
#: must agree or the shell will not group the window with its launcher:
#: ``Adw.Application(application_id=...)``, the ``.desktop`` file's ``Icon=``
#: and ``StartupWMClass=``, and the installed icon filename.
APP_ID = "io.github.blyatiful1.Gtheme"

__all__ = ["APP_ID", "__version__"]
