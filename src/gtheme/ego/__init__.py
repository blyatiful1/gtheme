"""The add-on library and the desktop's add-on service.

Four modules, in the order they depend on each other:

* :mod:`gtheme.ego.models` — what extensions.gnome.org sends back, as types.
* :mod:`gtheme.ego.client` — asking it things, asynchronously, on the main loop.
* :mod:`gtheme.ego.shelldbus` — what the running desktop has loaded right now.
* :mod:`gtheme.ego.install` — adding an add-on, and saying truthfully what
  happened.
* :mod:`gtheme.ego.updates` — checking for newer builds and staging them.

Nothing here is imported at package level: the client pulls in libsoup and the
desktop service pulls in Gio, and a page that only needs one of them should not
pay for the other. Import the module you want.
"""
