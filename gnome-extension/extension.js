import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const OBJECT_PATH = '/org/gnome/Shell/Extensions/ClickToggleIndicator';
const INTERFACE = `<node>
    <interface name="org.gnome.Shell.Extensions.ClickToggleIndicator">
        <method name="Configure">
            <arg name="settings" type="s" direction="in"/>
        </method>
        <method name="SetState">
            <arg name="state" type="u" direction="in"/>
        </method>
    </interface>
</node>`;

// Offsets locate the circle's top-left relative to the pointer hotspot.
const DEFAULT_APPEARANCE = {
    size: 18, opacity: 0.65,
    left_x: -26, left_y: 18, right_x: 30, right_y: 18,
    left_color: '#3b82f6', right_color: '#3b82f6',
};
const LEASE_US = 2000000;

export default class ClickToggleIndicator extends Extension {
    enable() {
        this._appearance = {...DEFAULT_APPEARANCE};
        this._state = 0;
        this._last_update = 0;
        try {
            this._dot = new St.DrawingArea({
                width: this._appearance.size,
                height: this._appearance.size,
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

    Configure(settings) {
        const values = JSON.parse(settings);
        const appearance = {};
        for (const key of Object.keys(DEFAULT_APPEARANCE)) {
            const value = values[key];
            if (key.endsWith('_color')) {
                if (typeof value !== 'string' || !/^#[0-9a-fA-F]{6}$/.test(value))
                    throw new Error(`Invalid color: ${key}`);
            } else {
                const min = key === 'size' ? 8 : key === 'opacity' ? 0.05 : -512;
                const max = key === 'size' ? 96 : key === 'opacity' ? 1 : 512;
                if (!Number.isFinite(value) || value < min || value > max ||
                    (key !== 'opacity' && !Number.isInteger(value)))
                    throw new Error(`Invalid appearance: ${key}`);
            }
            appearance[key] = value;
        }
        this._appearance = appearance;
        this._dot.set_size(appearance.size, appearance.size);
        this._dot.queue_repaint();
        if (this._state !== 0)
            this._update_position();
    }

    SetState(state) {
        if (![0, 1, 2].includes(state))
            throw new Error('Expected 0 (off), 1 (left), or 2 (right)');
        this._last_update = GLib.get_monotonic_time();
        this._state = state;
        this._dot.queue_repaint();
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
        const side = this._state === 1 ? 'left' : 'right';
        this._dot.set_position(
            Math.round(x + this._appearance[`${side}_x`]),
            Math.round(y + this._appearance[`${side}_y`]));
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
        const side = this._state === 1 ? 'left' : 'right';
        const color = this._appearance[`${side}_color`];
        cr.setSourceRGBA(
            parseInt(color.slice(1, 3), 16) / 255,
            parseInt(color.slice(3, 5), 16) / 255,
            parseInt(color.slice(5, 7), 16) / 255,
            this._appearance.opacity);
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
