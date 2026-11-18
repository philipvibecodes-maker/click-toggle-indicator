import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const OBJECT_PATH = '/org/gnome/Shell/Extensions/ClickToggleIndicator';
const INTERFACE = `<node>
    <interface name="org.gnome.Shell.Extensions.ClickToggleIndicator">
        <method name="SetState">
            <arg name="state" type="u" direction="in"/>
        </method>
    </interface>
</node>`;

// Logical pixels, measured from the pointer hotspot to the circle's center.
const DIAMETER = 18;
const OFFSET_X = 28;
const OFFSET_Y = 18;
const LEASE_US = 2000000;

export default class ClickToggleIndicator extends Extension {
    enable() {
        this._state = 0;
        this._last_update = 0;
        try {
            this._dot = new St.DrawingArea({
                width: DIAMETER,
                height: DIAMETER,
                reactive: false,
                can_focus: false,
                visible: false,
            });
            this._dot.connect('repaint', area => this._draw(area));
            // Above windows and overview, without adding an input region.
            Main.layoutManager.addTopChrome(this._dot, {
                affectsInputRegion: false,
                trackFullscreen: false,
            });
            // A timeline schedules frame-clock updates only while a hold is active.
            // No pointer image, theme, visibility, or application cursor is changed.
            this._timeline = new Clutter.Timeline({
                actor: this._dot,
                duration: 1000,
                repeat_count: -1,
            });
            this._timeline.connect('new-frame', () => this._update_position());
            this._dbus = Gio.DBusExportedObject.wrapJSObject(INTERFACE, this);
            this._dbus.export(Gio.DBus.session, OBJECT_PATH);
        } catch (error) {
            this.disable();
            throw error;
        }
    }

    SetState(state) {
        if (![0, 1, 2].includes(state))
            throw new Error('Expected 0 (off), 1 (left), or 2 (right)');
        this._last_update = GLib.get_monotonic_time();
        this._state = state;
        if (state === 0) {
            this._dot.hide();
            this._timeline.stop();
            return;
        }
        this._update_position();
        this._dot.show();
        if (!this._timeline.is_playing())
            this._timeline.start();
    }

    _update_position() {
        // Expire the display if the bridge disappears, even after SIGKILL.
        if (GLib.get_monotonic_time() - this._last_update > LEASE_US) {
            this.SetState(0);
            return;
        }
        const [x, y] = global.get_pointer();
        const side = this._state === 1 ? -1 : 1;
        this._dot.set_position(
            Math.round(x + side * OFFSET_X - DIAMETER / 2),
            Math.round(y + OFFSET_Y - DIAMETER / 2));
    }

    _draw(area) {
        const cr = area.get_context();
        const [width, height] = area.get_surface_size();
        const radius = Math.min(width, height) / 2;
        // Cairo antialiases the alpha edge; contrasting rings remain readable
        // against light and dark application content.
        cr.arc(width / 2, height / 2, radius - 0.5, 0, Math.PI * 2);
        cr.setSourceRGBA(0.06, 0.09, 0.16, 0.95);
        cr.setLineWidth(1);
        cr.stroke();
        cr.arc(width / 2, height / 2, radius - 1.5, 0, Math.PI * 2);
        cr.setSourceRGBA(1, 1, 1, 0.95);
        cr.stroke();
        cr.arc(width / 2, height / 2, radius - 2.5, 0, Math.PI * 2);
        cr.setSourceRGBA(0.23, 0.51, 0.96, 0.65);
        cr.fill();
        cr.$dispose();
    }

    disable() {
        this._dbus?.unexport();
        this._dbus = null;
        this._timeline?.stop();
        this._timeline = null;
        if (this._dot) {
            Main.layoutManager.removeChrome(this._dot);
            this._dot.destroy();
            this._dot = null;
        }
        this._state = 0;
    }
}
