/* Hive Monitor — a top-bar indicator for a kubestellar/hive instance.
 *
 * Deliberately NOT bound to any particular hive: every endpoint, credential
 * and target repo comes from GSettings, so the same extension works against
 * a self-hosted spoke, the hosted hub, or a colleague's instance.
 *
 * Two things it does:
 *   1. Polls GET /api/widget — the hive's own compact status endpoint
 *      ({issues, prs, mode, running, paused, last_eval}) — and renders it.
 *   2. Files an idea as a GitHub issue on a configured repo, labelled so the
 *      hive's governor treats it as work. Ideas go to GitHub rather than to a
 *      hive bead because GitHub issues ARE the hive's work queue: the governor
 *      polls them and its SURGE/BUSY modes are driven by their depth. Beads
 *      are per-agent internal state, and Inception is for scaffolding whole
 *      new projects — neither is an intake channel for "I had an idea".
 */

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Soup from 'gi://Soup?version=3.0';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as ModalDialog from 'resource:///org/gnome/shell/ui/modalDialog.js';

import {
    Extension,
    gettext as _,
} from 'resource:///org/gnome/shell/extensions/extension.js';

const AGENT_URL = 'gnome-shell-hive-monitor/1';

/* A single Soup session for the extension. Created once and cancelled on
 * disable(), so no request outlives the extension (the "no lingering async
 * work after disable" rule extensions get unlisted for breaking). */
function newSession() {
    const s = new Soup.Session({timeout: 15});
    s.user_agent = AGENT_URL;
    return s;
}

/* ── Idea entry dialog ────────────────────────────────────────────────── */
const IdeaDialog = GObject.registerClass(
class IdeaDialog extends ModalDialog.ModalDialog {
    _init(onSubmit) {
        super._init({styleClass: 'hive-idea-dialog'});
        this._onSubmit = onSubmit;

        const box = new St.BoxLayout({
            vertical: true,
            style: 'spacing: 12px; min-width: 420px;',
        });
        this.contentLayout.add_child(box);

        box.add_child(new St.Label({
            text: _('New idea'),
            style: 'font-weight: 800; font-size: 1.1em;',
        }));
        box.add_child(new St.Label({
            text: _('Becomes a labelled issue the hive can pick up.'),
            style: 'color: rgba(255,255,255,0.7);',
        }));

        this._title = new St.Entry({
            hint_text: _('Title'),
            can_focus: true,
            style: 'margin-top: 6px;',
        });
        box.add_child(this._title);

        this._body = new St.Entry({
            hint_text: _('Detail (optional)'),
            can_focus: true,
        });
        // St.Entry is single-line; keep the body one line rather than pretend
        // otherwise. Anything longer belongs in the issue itself on the web.
        box.add_child(this._body);

        this._status = new St.Label({text: '', style: 'color: #f66;'});
        box.add_child(this._status);

        this.setButtons([
            {
                label: _('Cancel'),
                action: () => this.close(),
                key: Clutter.KEY_Escape,
            },
            {
                label: _('File Idea'),
                action: () => this._submit(),
                default: true,
            },
        ]);
        this.setInitialKeyFocus(this._title.clutter_text);
    }

    _submit() {
        const title = this._title.get_text().trim();
        if (!title) {
            this._status.set_text(_('A title is required.'));
            return;
        }
        this.close();
        this._onSubmit(title, this._body.get_text().trim());
    }
});

/* ── Panel indicator ──────────────────────────────────────────────────── */
const HiveIndicator = GObject.registerClass(
class HiveIndicator extends PanelMenu.Button {
    _init(ext) {
        super._init(0.0, 'Hive Monitor');
        this._ext = ext;
        this._settings = ext.getSettings();
        this._session = newSession();
        this._cancel = new Gio.Cancellable();
        this._timer = null;
        this._last = null;

        const box = new St.BoxLayout({style_class: 'panel-status-menu-box'});
        this._icon = new St.Icon({
            icon_name: 'system-run-symbolic',
            style_class: 'system-status-icon',
        });
        this._label = new St.Label({
            text: '…',
            y_align: Clutter.ActorAlign.CENTER,
            style: 'margin-left: 4px;',
        });
        box.add_child(this._icon);
        box.add_child(this._label);
        this.add_child(box);

        this._buildMenu();

        // Re-read on any settings change: a corrected URL or token should take
        // effect immediately, not after the next poll interval.
        this._settingsId = this._settings.connect('changed', () => {
            this._restartTimer();
            this._refresh();
        });

        this._restartTimer();
        this._refresh();
    }

    _buildMenu() {
        this._statusItem = new PopupMenu.PopupMenuItem('', {
            reactive: false,
            style_class: 'popup-inactive-menu-item',
        });
        this.menu.addMenuItem(this._statusItem);

        this._detailItem = new PopupMenu.PopupMenuItem('', {
            reactive: false,
            style_class: 'popup-inactive-menu-item',
        });
        this.menu.addMenuItem(this._detailItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const idea = new PopupMenu.PopupMenuItem(_('New Idea…'));
        idea.connect('activate', () => this._openIdeaDialog());
        this.menu.addMenuItem(idea);

        const open = new PopupMenu.PopupMenuItem(_('Open Dashboard'));
        open.connect('activate', () => {
            const url = this._url();
            if (url)
                Gio.AppInfo.launch_default_for_uri(url, null);
        });
        this.menu.addMenuItem(open);

        const refresh = new PopupMenu.PopupMenuItem(_('Refresh Now'));
        refresh.connect('activate', () => this._refresh());
        this.menu.addMenuItem(refresh);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const prefs = new PopupMenu.PopupMenuItem(_('Settings'));
        prefs.connect('activate', () => this._ext.openPreferences());
        this.menu.addMenuItem(prefs);
    }

    _url() {
        return this._settings.get_string('hive-url').trim().replace(/\/+$/, '');
    }

    _restartTimer() {
        if (this._timer) {
            GLib.Source.remove(this._timer);
            this._timer = null;
        }
        const secs = this._settings.get_int('poll-seconds');
        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, secs, () => {
            this._refresh();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _setUnconfigured(msg) {
        this._label.set_text(_('hive?'));
        this._icon.icon_name = 'dialog-question-symbolic';
        this._statusItem.label.set_text(msg);
        this._detailItem.label.set_text(_('Open Settings to configure.'));
    }

    _refresh() {
        const url = this._url();
        const token = this._settings.get_string('hive-token').trim();
        if (!url) {
            this._setUnconfigured(_('No hive URL set.'));
            return;
        }
        if (!token) {
            this._setUnconfigured(_('No hive token set.'));
            return;
        }

        const msg = Soup.Message.new('GET', `${url}/api/widget`);
        if (!msg) {
            this._setUnconfigured(_('That hive URL is not valid.'));
            return;
        }
        msg.request_headers.append('X-Hive-Internal', token);

        this._session.send_and_read_async(
            msg, GLib.PRIORITY_DEFAULT, this._cancel, (session, res) => {
                let bytes;
                try {
                    bytes = session.send_and_read_finish(res);
                } catch (e) {
                    if (!e.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                        this._showError(_('Cannot reach the hive.'), String(e.message ?? e));
                    return;
                }
                const code = msg.get_status();
                if (code === 401 || code === 403) {
                    // Distinguished on purpose: "unreachable" and "your token is
                    // wrong" need different fixes, and a single generic error
                    // sends people to debug the network for an auth problem.
                    this._showError(_('Hive rejected the token.'),
                        _('Check the hive token in Settings (HTTP %d).').format(code));
                    return;
                }
                if (code !== 200) {
                    this._showError(_('Hive returned HTTP %d.').format(code), '');
                    return;
                }
                try {
                    const txt = new TextDecoder().decode(bytes.get_data());
                    this._render(JSON.parse(txt));
                } catch (e) {
                    this._showError(_('Unreadable response.'), String(e.message ?? e));
                }
            });
    }

    _showError(short, detail) {
        this._icon.icon_name = 'dialog-warning-symbolic';
        this._label.set_text(_('hive!'));
        this._statusItem.label.set_text(short);
        this._detailItem.label.set_text(detail || '');
    }

    _render(d) {
        this._last = d;
        const mode = String(d.mode ?? '?').toUpperCase();
        const issues = Number(d.issues ?? 0);
        const prs = Number(d.prs ?? 0);
        const running = Number(d.running ?? 0);
        const paused = Number(d.paused ?? 0);

        this._label.set_text(
            this._settings.get_boolean('show-counts')
                ? `${mode} ${issues}/${prs}`
                : mode);

        // A paused agent is the quiet failure this widget exists to surface:
        // the hive looks alive while some of its lanes do nothing.
        this._icon.icon_name = paused > 0
            ? 'dialog-warning-symbolic'
            : 'system-run-symbolic';

        this._statusItem.label.set_text(
            _('%s — %d issues, %d PRs').format(mode, issues, prs));

        const agents = paused > 0
            ? _('%d agents running, %d paused').format(running, paused)
            : _('%d agents running').format(running);
        this._detailItem.label.set_text(
            d.last_eval
                ? `${agents} · ${_('last eval %s').format(this._ago(d.last_eval))}`
                : agents);
    }

    _ago(iso) {
        const then = Date.parse(iso);
        if (Number.isNaN(then))
            return iso;
        const s = Math.max(0, Math.round((Date.now() - then) / 1000));
        if (s < 60)
            return _('%ds ago').format(s);
        if (s < 3600)
            return _('%dm ago').format(Math.round(s / 60));
        return _('%dh ago').format(Math.round(s / 3600));
    }

    _openIdeaDialog() {
        const repo = this._settings.get_string('github-repo').trim();
        const tok = this._settings.get_string('github-token').trim();
        if (!repo || !tok) {
            Main.notify(_('Hive Monitor'),
                _('Set a repository and GitHub token in Settings first.'));
            this._ext.openPreferences();
            return;
        }
        new IdeaDialog((title, body) => this._fileIdea(repo, tok, title, body)).open();
    }

    _fileIdea(repo, token, title, body) {
        const labels = this._settings.get_string('idea-labels')
            .split(',').map(s => s.trim()).filter(s => s.length > 0);

        const msg = Soup.Message.new('POST', `https://api.github.com/repos/${repo}/issues`);
        if (!msg) {
            Main.notify(_('Hive Monitor'), _('“%s” is not a valid owner/name.').format(repo));
            return;
        }
        msg.request_headers.append('Authorization', `Bearer ${token}`);
        msg.request_headers.append('Accept', 'application/vnd.github+json');
        // GitHub 403s a request with no User-Agent, which reads as a bad token
        // rather than a missing header. Always send one.
        msg.request_headers.append('User-Agent', AGENT_URL);

        const payload = JSON.stringify({
            title,
            body: `${body ? body + '\n\n' : ''}— filed from the GNOME Hive Monitor`,
            labels,
        });
        msg.set_request_body_from_bytes(
            'application/json',
            new GLib.Bytes(new TextEncoder().encode(payload)));

        this._session.send_and_read_async(
            msg, GLib.PRIORITY_DEFAULT, this._cancel, (session, res) => {
                let bytes;
                try {
                    bytes = session.send_and_read_finish(res);
                } catch (e) {
                    if (!e.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                        Main.notify(_('Hive Monitor'), _('Could not file the idea: %s').format(String(e.message ?? e)));
                    return;
                }
                const code = msg.get_status();
                if (code === 201) {
                    let num = '';
                    try {
                        const j = JSON.parse(new TextDecoder().decode(bytes.get_data()));
                        num = j.number ? `#${j.number}` : '';
                        if (j.html_url)
                            this._lastIssueUrl = j.html_url;
                    } catch { /* the issue exists either way */ }
                    Main.notify(_('Hive Monitor'),
                        _('Filed %s on %s.').format(num, repo));
                    // Ideas change the queue depth, so reflect it immediately
                    // instead of waiting out the poll interval.
                    this._refresh();
                    return;
                }
                let why = `HTTP ${code}`;
                try {
                    const j = JSON.parse(new TextDecoder().decode(bytes.get_data()));
                    if (j.message)
                        why = j.message;
                } catch { /* keep the status code */ }
                Main.notify(_('Hive Monitor'), _('GitHub refused the idea: %s').format(why));
            });
    }

    destroy() {
        if (this._timer) {
            GLib.Source.remove(this._timer);
            this._timer = null;
        }
        if (this._settingsId) {
            this._settings.disconnect(this._settingsId);
            this._settingsId = null;
        }
        // Cancel in-flight requests, then drop the session: a reply arriving
        // after destroy() would touch freed actors.
        this._cancel.cancel();
        this._session?.abort();
        this._session = null;
        super.destroy();
    }
});

export default class HiveMonitorExtension extends Extension {
    enable() {
        this._indicator = new HiveIndicator(this);
        Main.panel.addToStatusArea(this.uuid, this._indicator);
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
