# OpenUsage for Omarchy

Plan Quotas and Spend for coding Providers in the Omarchy bar. A port of
[OpenUsage](https://github.com/robinebers/openusage) (Robin Ebers, MIT) for
[Omarchy](https://omarchy.org/): the same Quota UX as the macOS menu-bar app,
rebuilt natively for Linux. It is not a git fork of the Swift sources.

Eleven Providers in upstream order: Claude, Codex, Cursor, Antigravity,
Copilot, Devin, Grok, Ollama, OpenCode, OpenRouter, and Z.ai. The bar shows
your Starred Metrics; a click opens the Dashboard with Total Spend and every
enabled Provider. Behaviour, layout, features, and settings match upstream
(see `docs/parity.md`), drawn in the Omarchy theme only.

Requires Omarchy/Quickshell, Python 3 (stdlib only — no pip packages),
`wl-copy`, `notify-send`, and `secret-tool` (libsecret). Hyprland is needed
only for the optional global shortcut.

## Install

The workspace root is the plugin. Install by copying (symlinks are rejected):

```sh
rsync -a --delete --exclude .git /home/luth-v/Work/slop/openusage-omarchy/ ~/.config/omarchy/plugins/luth-v.openusage-omarchy/
omarchy plugin validate ~/.config/omarchy/plugins/luth-v.openusage-omarchy
omarchy-shell shell rescanPlugins
omarchy plugin enable luth-v.openusage-omarchy --section right
```

`enable` puts the widget on the bar and starts its service (refresh engine,
notifications, update checks, local API). If the strip reads "enable the
service in shell.json plugins[]", the service did not start — rescan and
enable again.

To keep the service running without the bar widget (API and notifications
only), add an entry to `plugins[]` in `~/.config/omarchy/shell.json` —
**after** enabling, since `enable` skips bar placement when any entry
already exists:

```json
"plugins": [{ "id": "luth-v.openusage-omarchy" }]
```

Position the widget with `omarchy bar move luth-v.openusage-omarchy --after
<neighbour>`. Settings hot-reload; nothing under `/usr/share/omarchy/` is
modified. Code changes need a shell restart, because hot reload keeps
serving stale nested QML. `dev/install.sh` copies, validates, and restarts
in one step.

## Use

- Left-click: Dashboard. Right-click: Customize. Middle-click: force refresh.
- Click a headline to switch Used ↔ Left, a reset label to switch countdown ↔
  exact time. Both flip everywhere.
- `z` undo, `r` refresh, `,` Settings; Return and Esc move between panels.
- The Konami code (↑↑↓↓←→←→BA) toggles party mode: meter fills cycle theme
  colours.
- `docs/parity.md` lists every upstream feature and where this port stands.

### CLI

```sh
openusage-omarchy                # every enabled Provider, refreshing stale entries
openusage-omarchy codex          # one Provider (exact id or family id)
openusage-omarchy codex --force  # bypass the freshness gate
```

Prints the `/v1/limits` JSON and exits; exit codes are 0, 2 (bad arguments
or unknown Provider), and 4 (a matched card has no data). Put it on `PATH`
with a symlink — never as `openusage`, which belongs to an unrelated tool:

```sh
ln -s ~/.config/omarchy/plugins/luth-v.openusage-omarchy/bin/openusage-omarchy ~/.local/bin/openusage-omarchy
```

### Global shortcut

Record a combination in Settings → General. The daemon writes the bind to
`~/.config/openusage-omarchy/hyprland.conf` (a plugin-owned file). Add this
line to your Hyprland config yourself, then `hyprctl reload`:

```
source = $HOME/.config/openusage-omarchy/hyprland.conf
```

Clearing the shortcut removes the bind file. The plugin never touches
`~/.config/hypr/*`.

### Multiple Claude accounts

Claude Code keeps one login per config dir, so give each Account its own
dir and log in once there (ADR 0006):

```sh
alias claude-work='CLAUDE_CONFIG_DIR=~/.claude-work claude'
claude-work   # then /login with the second account
```

`~/.claude` and every `~/.claude-<name>` dir with a login (plus any
`CLAUDE_CONFIG_DIR` entries) are found on the next refresh. Each Account
gets its own Claude card with its own Quotas and Spend; the same login in
two dirs is one card with the Spend of both. Cards read "Claude — work"
(the dir suffix, `~/.claude` is "Default"); rename or hide a dir in
Settings → Claude Accounts, stored in shell.json as:

```json
"claudeAccounts": { "~/.claude-work": { "label": "Work", "hidden": false } }
```

With several Claude cards enabled, each Star on the bar gets the label's
initial ("W 42%"). Emails are never shown.

### Local HTTP API

Read-only JSON on `http://127.0.0.1:6736` (loopback only, fixed port):
`GET /v1/limits`, `/v1/limits/:id`, `/v1/usage`, `/v1/usage/:id`. An exact
card id names one card; a family id names every card of that family. Display
names never carry emails. If the port is taken, the feature stays off for
that session.

### Proxy

Optional, file only, `http://` and `https://` (SOCKS5 is not supported).
Create `~/.config/openusage-omarchy/config.json` (mode 0600 — the URL may
embed credentials) and restart the shell:

```json
{ "proxy": { "enabled": true, "url": "http://127.0.0.1:8080" } }
```

Loopback hosts always bypass the proxy. A missing, disabled, invalid, or
unreadable config leaves proxying off.

### Updates

Settings → Updates: automatic hourly checks (on by default), an opt-in beta
channel, and manual checks. Installing never runs on its own — the banner's
**Install Update** button runs `omarchy plugin update
luth-v.openusage-omarchy --yes`, on git installs only. **Update with
Omarchy** (off by default, git installs only) adds one hook file so the
plugin updates with `omarchy update`; turning it off removes the file.

### Antigravity token refresh

Antigravity works while its app or `agy` is running. To also refresh an
expired Cloud Code token on its own, give the collector the Google OAuth client
of your Antigravity install. It is not bundled here. Set
`OPENUSAGE_OMARCHY_ANTIGRAVITY_CLIENT_ID` and
`OPENUSAGE_OMARCHY_ANTIGRAVITY_CLIENT_SECRET`, or write
`{"client_id": "…", "client_secret": "…"}` to
`~/.config/openusage-omarchy/antigravity-oauth.json` with mode 0600. Without it,
an expired sign-in shows "sign-in expired" until Antigravity refreshes it.

### Logging

`~/.config/openusage-omarchy` holds settings-adjacent files;
`~/.local/state/openusage-omarchy/` holds `state.json`, `layout.json`, and
`openusage-omarchy.log` (rotated at ~10 MB). The Log Level picker applies
immediately. Secrets never reach the log. Settings → Advanced copies the log
path or opens its folder.

## Verify

```sh
./tests/run.sh
```

This runs the node suites, the Python suite, `bash -n`, the
no-`__pycache__` check, and `omarchy plugin validate .`. Fixtures are
synthetic (`test-only-*`); no test reads your logins.

## Upgrading from the old tree

An earlier version of this plugin cached a Grok token at
`~/.cache/openusage/grok-oauth.json`. Tokens no longer live in any cache
directory; delete that file by hand if it exists. `~/.local/state/openusage/`,
`~/.config/openusage/`, and `~/.local/bin/openusage` belong to an unrelated
`openusage` tool — this plugin never reads, modifies, or deletes them, and
all its own paths use `openusage-omarchy`.

The glossary lives in `CONTEXT.md` and the decisions in `docs/adr/`.

MIT license. See `LICENSE` for upstream attribution.
