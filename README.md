# OpenUsage for Omarchy

This repository is a port of [OpenUsage](https://github.com/robinebers/openusage) for [Omarchy](https://omarchy.org/). The original project is a macOS menu-bar app by Robin Ebers (MIT). This tree is a new Linux implementation. It keeps the same Quota UX. It is not a git fork of the Swift sources.

Plan Quotas for Claude, Codex, Cursor, OpenCode, and Grok in the Omarchy bar.
The bar shows each enabled Provider's highest Used Metric, plus an optional
sticky second Star. All enabled Providers and all available Windows appear
together in the Dashboard, including login or refresh errors.

- Left-click: Dashboard. Right-click: Customize. Middle-click: force refresh.
- Click Display or a Dashboard Metric to switch Used ↔ Left globally.
- Click a reset label to switch countdown ↔ exact local time.
- Customize enables Providers and selects one sticky Metric per Provider.
  The live Lead is always shown; when it equals the sticky Metric, it appears once.
- Escape closes either panel. `r` or the Dashboard footer forces a refresh.
- Refresh defaults to 300 seconds. The stock widget settings expose 30–3600 seconds.
- Empty Providers have no number in the bar; an entirely empty bar shows ◉.

Settings persist inline in `~/.config/omarchy/shell.json`. Providers start enabled,
Display starts Used, and reset labels start as countdowns. Spend and notifications
are outside this version.

## Collectors

Requires Omarchy/Quickshell, Python 3, Bash, jq, and flock. The uniform updater
calls packaged Claude/Codex collectors and this plugin's Cursor/Grok/OpenCode
collectors in parallel. It accepts `--force` or `--limits-only`.

State is published atomically with mode 0600 in `~/.local/state/openusage/`.
An updater lock serializes overlapping runs. Invalid/failed collector output does
not replace the previous file. Panels retain the last parsed numbers and show
refresh errors. Cursor/Grok/OpenCode probe caches are isolated in
`~/.cache/openusage/` (or `$XDG_CACHE_HOME/openusage/`). Packaged collectors retain
their own private Omarchy caches. No stock updater is called.

Cursor reads the signed-in IDE's state database; Grok reads its CLI login.
These MIT collectors were adapted from Jan Hoon's `janhoon.agents`; conversation
scans and local statistics were removed. The existing quota-cap probes remain.

OpenCode reads `$OPENCODE_DATA_DIR/auth.json`, defaulting to
`~/.local/share/opencode/auth.json`, using the `opencode-go` or `opencode` API-key
entry. It calls the Go/Zen usage endpoint for Session, Weekly, and Monthly
Windows. Without that login it displays **Not logged in**; use OpenCode's
[/connect flow](https://github.com/anomalyco/opencode/blob/dev/packages/web/src/content/docs/providers.mdx)
to sign in. A local OpenCode conversation database alone does not supply quotas.
Credentials never pass through QML or command arguments.

Pace compares Used to elapsed time inferred from Session (5h), Weekly (7d), and
Monthly (30d) labels. Unknown-duration Windows only alarm at 90% Used. An even-burn
projection exceeding quota before reset also alarms; approaching even burn (90%
of elapsed fraction) is ahead. Colors come from the shell foreground, theme
warning/yellow, and bar urgent roles. A monochrome theme keeps them monochrome.

## Install on this desktop

The workspace root is the plugin; installation copies it, without symlinks:

```sh
rsync -a --delete --exclude .git /home/luth-v/Work/slop/openusage/ ~/.config/omarchy/plugins/luth-v.openusage/
omarchy plugin validate ~/.config/omarchy/plugins/luth-v.openusage
omarchy-shell shell rescanPlugins
omarchy plugin enable luth-v.openusage --section right
omarchy bar move luth-v.openusage --after omarchy.tailscale
omarchy plugin disable janhoon.agents
```

`akitaonrails.ai-usagebar` remains disabled. Code and shell settings hot-reload.
The glossary and ADR ship as inert documentation. Nothing under
`/usr/share/omarchy/` is modified.

## Verify

```sh
node tests/model.test.cjs
PYTHONDONTWRITEBYTECODE=1 python3 tests/collectors_test.py
PYTHONDONTWRITEBYTECODE=1 python3 tests/updater_test.py
bash -n bin/openusage-update
omarchy plugin validate .
```

Tests cover percent units, invalid/missing data, live Lead and sticky deduplication,
Pace, reset-aware cache fallback, missing OpenCode login, atomic state publication,
failed collectors, and concurrent updater runs. A live refresh requires the
normal Provider logins. OpenCode's authenticated request cannot be live-tested
on this desktop until a Go/Zen key exists.

MIT license. See `LICENSE` for upstream collector attribution.
