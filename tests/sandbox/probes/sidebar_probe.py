"""Build gtheme's window inside the sandbox and report what its sidebar holds.

Run as a subprocess with the sandbox environment. Prints one JSON object::

    {"count": 15, "titles": [...], "sections": [...], "manifest": [...]}

The window is constructed and then thrown away — ``present()`` is never called.
Counting the sidebar's real items rather than the manifest's entries is the
point: the manifest is data anyone can read, whereas this answers whether the
window actually built a sidebar row for each of them without raising.
"""

from __future__ import annotations

import json

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402


def main() -> int:
    Adw.init()
    if not Gtk.init_check():
        print(json.dumps({"error": "Gtk.init_check() failed — no display"}))
        return 1

    from gtheme.prefs import Prefs
    from gtheme.ui import registry
    from gtheme.window import Window

    window = Window(Prefs())
    items = window.sidebar.get_items()

    titles = []
    sections = []
    for index in range(items.get_n_items()):
        item = items.get_item(index)
        titles.append(item.get_title())
        section = item.get_section()
        sections.append(section.get_title() if section is not None else None)

    print(
        json.dumps(
            {
                "count": items.get_n_items(),
                "titles": titles,
                "sections": sections,
                "manifest": [page.title for page in registry.MANIFEST],
                "manifest_sections": [page.section for page in registry.MANIFEST],
                "page_ids": list(registry.page_ids()),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
