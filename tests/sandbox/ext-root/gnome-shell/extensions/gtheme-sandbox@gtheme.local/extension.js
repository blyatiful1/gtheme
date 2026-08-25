/* gtheme sandbox control — TEST-ONLY extension.
 *
 * Purpose: a headless gnome-shell started with no seat comes up showing the
 * Overview and never leaves it (nothing ever generates the user interaction
 * that would dismiss it), so every screenshot shows overview thumbnails
 * instead of the real desktop. window-calls' Activate does NOT dismiss it.
 *
 * Rather than reimplement half the shell over D-Bus, this extension flips
 * `global.context.unsafe_mode`, which unlocks org.gnome.Shell.Eval. The harness
 * can then drive the shell directly:
 *     gdbus call ... --method org.gnome.Shell.Eval "Main.overview.hide()"
 *
 * It also proactively hides the overview on startup so the common case needs
 * no Eval call at all.
 *
 * SECURITY: unsafe mode means any client on the session bus can execute
 * arbitrary JS inside gnome-shell. That is acceptable here ONLY because this
 * extension is never on the live session's search path — it is reached solely
 * through XDG_DATA_DIRS pointing at harness/ext-root, and only ever inside a
 * private dbus-run-session. Do not copy it into ~/.local/share/gnome-shell.
 */

import GLib from 'gi://GLib';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

export default class GthemeSandboxExtension extends Extension {
    enable() {
        global.context.unsafe_mode = true;
        log('gtheme-sandbox: unsafe_mode enabled, Eval is available');

        this._tries = 0;
        // The overview can be (re)shown a little after startup-complete, so
        // hide it a few times over the first ~5s rather than exactly once.
        this._timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 500, () => {
            this._tries++;
            if (Main.overview.visible)
                Main.overview.hide();
            if (this._tries >= 10) {
                this._timer = null;
                return GLib.SOURCE_REMOVE;
            }
            return GLib.SOURCE_CONTINUE;
        });
    }

    disable() {
        if (this._timer) {
            GLib.source_remove(this._timer);
            this._timer = null;
        }
        global.context.unsafe_mode = false;
    }
}
