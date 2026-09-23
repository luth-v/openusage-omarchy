# Upstream parity

Upstream is [OpenUsage](https://github.com/robinebers/openusage) at commit
`f762ec5b359874d56d943a123e07844fe502ba84` (v0.7.13-beta.2). The goal is
equivalent behaviour, layout, features, and settings, drawn in the Omarchy
theme only — not pixel-perfection.

Status legend: **done** (same behaviour), **equivalent** (same behaviour
through a platform-native seam), **omitted** (deliberately dropped, with the
ADR reference), **deviation** (differs; reason below).

## Providers

Catalog order follows upstream `ProviderCatalog.swift`. All 11 collectors
are owned in-repo (ADR 0002) and ported from the upstream Swift providers.

| Provider | Status | Notes |
|---|---|---|
| Claude | done | Session, Weekly, Sonnet, Fable, Extra Usage, Rate Limit Resets, spend tiles, Usage Trend; Swap discovery, Desktop org cards, live plan, 429 and missing-scope mapping. |
| Codex | done | Session, Weekly, Spark pair, credits, credit value, Rate Limit Resets, spend tiles, Usage Trend; multi-home auth, JWT refresh, classified windows, reset claim. |
| Cursor | done | Total Usage (percent / requests / dollars by plan), Models pair, Grok Bot, API usage, on-demand, Requests, Credits; SQLite auth with refresh write-back, team dollar meter, usage-CSV spend. |
| Antigravity | done | Session/Weekly pairs per pool, spend tiles, Usage Trend; language-server discovery, Cloud Code plus Google OAuth refresh (equivalent: the OAuth client is user-supplied at run time, not bundled, per the secrets rule), quota-summary-first with legacy fallback. |
| Copilot | done | Premium credits, extra usage, org credits/spend, chat, completions; editor files, gh token, org billing. |
| Devin | done | Daily, Weekly, extra-usage balance; credentials file then app database, weekly fallbacks. |
| Grok | done | Weekly meter, pay-as-you-go badge, spend tiles, Usage Trend; multi-candidate auth, JWT-aware refresh, settings plan call. |
| Ollama | done | Session, Weekly, Monthly, Last-4-Weeks spend; ed25519-signed local API. Never auto-enables. |
| OpenCode | done | Session, Weekly, Monthly, spend tiles, Usage Trend; strict 3-window mapper, `opencode-go` login, OpenCode→Codex attribution. |
| OpenRouter | done | Credits, balance, key limit, Today/Week/Month API spend; key from libsecret, file fallback, or env. |
| Z.ai | done | Session, Weekly, web searches; quota plus best-effort subscription, key from libsecret, file fallback, or env. |

Platform omissions (all Linux-no-equivalent, no ADR — too small to merit one):
the Claude Code, Cursor, and Codex keychain paths (those tools use files on
Linux) and the Claude Desktop token decrypt (Desktop org cards authenticate
through CLI or Swap logins instead).

## Refresh and caching

| Feature | Status | Notes |
|---|---|---|
| 5-minute fixed cadence, no setting | done | `REFRESH_INTERVAL_S = 300`. |
| Parallel fetch, last-good kept on failure | done | Engine plus stale-while-revalidate snapshot cache. |
| 120 s per-provider deadline | done | Late threads can never publish (batch generation gate). |
| Login-session freshness | equivalent | Keyed to `$XDG_RUNTIME_DIR/openusage-omarchy/session`, not the daemon PID, so a shell hot-reload does not re-hit 11 APIs (ADR 0003). |
| Wrong-account cache guard | done | Claude/Codex identity keys; a swapped login starts empty. |
| Log-scan parse cache (totals only) | done | Offsets and counts only; no prompt text. |
| "Outdated" tag at ~10 minutes | done | With "Last updated … ago" hover. |
| Spinners while fetching | done | Per-section plus the footer countdown spinner glyph; the footer shows "Updating…" while fetching. |
| Slow-provider 10 s warning | done | Warning-level `[refresh]` line with provider and milliseconds. |
| Footer countdown click / ⌘R refresh | equivalent | Click triggers a force refresh; spinner glyph while fetching; `r` is the key equivalent. |

## Bar strip

| Feature | Status | Notes |
|---|---|---|
| Up to 2 Stars per provider, no Lead model | done | |
| Text and Bars styles | done | Bars shows bounded stars only, first four with a limit. |
| Empty-data rules | done | Stars without data drop out; an empty strip shows the app name. |
| Default Stars per provider | done | Upstream `DefaultLayout.swift` set. |
| Click bindings | equivalent | Left toggles the Dashboard, right opens Customize, middle force-refreshes (upstream right-click opens a Settings/Quit menu; Quit cannot exist in-process). |

## Dashboard

| Feature | Status | Notes |
|---|---|---|
| Update banner | done | Install runs `omarchy plugin update --yes` on click only; dismiss snoozes until the next check finds the update again (upstream semantics). |
| First-run hint card | done | Dismisses only via its ✕ button. |
| Total Spend card | done | Cost / Cost-per-MTok / Tokens, Today / Yesterday / 30 Days, donut, legend, ⓘ, share; quiet empty states; fixed brand colours. |
| Spend metric/period persistence | done | Choice persists in `layout.json` via the `setSpend` reducer action; Settings Reset All restores Today/Cost. |
| Provider sections, plan badge, caret | done | Open carets persist across restarts. |
| Quick links (up to 3 across) | done | |
| Meter, Used/Left, countdown/exact flips | done | Clicks flip globally; default Left; default countdown. |
| Usage Trend + model breakdown | done | Click-to-expand details instead of hover popovers (desktop panel). |
| Rate Limit Resets + Codex claim | done | Exact upstream wording; per-card result banners. |
| Row / header / Options context menus | done | Upstream verbs in upstream order; Customize deep-links. |
| About / Quit in Options menu | equivalent | About opens a small sheet with version, MIT license, upstream credit and repo links; Quit stays omitted (cannot exist in-process). |
| Live countdowns | equivalent | Rows re-render every second (upstream ticks every 30 s). |

## Pace

| Feature | Status | Notes |
|---|---|---|
| Projected-burn verdict | done | Port of `Support/Pace.swift`: blue / yellow + `~N% spare` / red flame + `Limit in …`. |
| Even-pace tick, hover projections | done | |
| Level fallback (80 % / 90 %) | done | For windowless balances and fresh sessions. |
| Theme-role colours | equivalent | Omarchy accent / yellow / urgent instead of the system palette. |

## Customize

| Feature | Status | Notes |
|---|---|---|
| Provider list, detail, per-provider Reset, Reset All with confirmation | done | Reset All re-detects installed tools. |
| Drag reorder (Customize + Dashboard) | done | Metrics across the caret boundary, whole sections. |
| Third-Star shake pill | done | "Up to 2 stars per provider". |
| API Key section (OpenRouter, Z.ai) | deviation | Add / replace / clear, but no reveal: typed keys are write-only into the daemon and QML only ever sees presence (secrets rule). |
| Codex Fallback Model picker | done | `pricing.codexFallbackOptions` state extension; a change forces a full rescan via a cache marker (the shell reloads on persist, so QML cannot force it). |
| Undo (session-only) | done | `z` anywhere in the panel; reset clears it. |

## Settings

| Feature | Status | Notes |
|---|---|---|
| Density Default / Compact | done | |
| Reduce Animations | done | |
| Time Format Auto / 12h / 24h | done | Auto reads as 12-hour. |
| Display Used / Left, default Left | done | |
| Reset display countdown / exact, default countdown | done | |
| Always Show Pacing | done | |
| Notifications ×3, all off by default | done | |
| Updates (auto, beta, manual check) | done | Plus the Omarchy-native "Update with Omarchy" toggle (G1). |
| Log Level + Copy Log Path + Show Log in Files | equivalent | "Show Log in Files" replaces "Reveal in Finder". |
| Global shortcut recorder | done | Writes a plugin-owned Hyprland bind file; the user adds the `source =` line. |
| Show Total Spend | done | |
| Reset All Settings | done | One shell.json write plus layout reset plus shortcut clear. |
| Launch at Login | equivalent | No toggle: an enabled plugin starts with the shell, which is the same guarantee. |
| Command Line helper install | equivalent | No Settings row: the README documents the `~/.local/bin/openusage-omarchy` symlink. |
| Theme Light/Dark switch | omitted | ADR 0005: the Omarchy theme is the only palette. |
| Increase Transparency | omitted | ADR 0005: layer rules own opacity. |
| Hide From Screen Share | omitted | ADR 0005. |
| Telemetry / analytics rows | omitted | ADR 0005. |
| iCloud Sync section | omitted | ADR 0005. |
| Haptics | omitted | ADR 0005: no Force Touch drag taps. |

## Keys

| Feature | Status | Notes |
|---|---|---|
| `z` undo, `r` refresh, `,` Settings | done | Plain letters, active only with no text focus. |
| Return / Esc navigation | done | Upstream's panel table across the three panels. |
| Global shortcut toggles the panel | done | `omarchy-shell luth-v.openusage-omarchy toggle`. |

## Notifications

| Feature | Status | Notes |
|---|---|---|
| Almost Out / Cutting It Close / Will Run Out | done | Ports `PaceNotificationLogic` + evaluator: edges, primed launch baseline, 1 s reset jitter tolerance, per-window dedup, improvement re-arm, toggle-off consume guard. |
| Dedup across restarts | equivalent | State persists in `notify.json`; upstream keeps it in memory. A hot-reload never re-fires. |
| Grouped delivery | equivalent | One `notify-send` call per pass instead of a stacked macOS banner. |
| Permission prompt / denied warning | equivalent | `notify-send` needs no permission; nothing to prompt for. A missing `notify-send` skips delivery and the edge re-fires next pass. |
| Tap opens the Dashboard | equivalent | `notify-send --action=default=Open --wait` in a bounded daemon worker; the tap runs `omarchy-shell luth-v.openusage-omarchy open`. |

## Updates

| Feature | Status | Notes |
|---|---|---|
| Hourly background checks | done | Against this repo's GitHub releases, unauthenticated, with 403/429 backoff. |
| "Update Automatically" means automatic checks | equivalent | G1: installs never run on their own; Install runs only on click. |
| Beta channel | equivalent | G1: selects stable-only vs stable-plus-prereleases; installs fast-forward to `origin HEAD`, which cannot select a release build. |
| Install Update button | done | Runs `omarchy plugin update luth-v.openusage-omarchy --yes`, git installs only. |
| Update with Omarchy toggle (default off) | equivalent | G1: writes exactly one hook file under `~/.config/omarchy/hooks/post-update.d/`; off removes it. |
| Signature verification | omitted | No Sparkle on Linux; `omarchy plugin update` fast-forwards unsigned remote code (accepted in G1). |

## Local HTTP API

| Feature | Status | Notes |
|---|---|---|
| `GET /v1/limits`, `/v1/limits/:id` | done | Same envelope the CLI prints; stable resource keys per the upstream table. |
| `GET /v1/usage`, `/v1/usage/:id` (legacy) | done | UI-oriented snapshots; values rows read as combined text; always-an-array single-id shape. |
| Loopback-only 127.0.0.1:6736, fixed port | done | A taken port disables the feature for the session. |
| GET/OPTIONS only, 16-connection cap, CORS `*` | done | Error codes `provider_not_found`, `not_found`, `method_not_allowed`, `server_busy`. |
| Account emails in `displayName` | deviation | G2: the API serves "<Family> <n>" / family names only; emails appear solely in the local Dashboard label. |

## CLI

| Feature | Status | Notes |
|---|---|---|
| `openusage-omarchy [id] [--force]` | done | Same engine and cache, no daemon needed; exit codes 0 / 2 / 4. |
| Plain string matching (exact or family id) | done | |

## Proxy

| Feature | Status | Notes |
|---|---|---|
| `http://` / `https://` proxy from config file | done | `$XDG_CONFIG_HOME/openusage-omarchy/config.json`; loopback bypasses; credentials never logged; read once per process (restart after editing). |
| `socks5://` | omitted | No stdlib support; a socks5 URL parses but stays inert with a warning (no ADR — pre-review blessed this exact trade). |

## Logging

| Feature | Status | Notes |
|---|---|---|
| File log with levels, subsystem tags | done | `$XDG_STATE_HOME/openusage-omarchy/openusage-omarchy.log`; Error / Warning / Info (default) / Debug, applied immediately. |
| Redaction | done | Handler-level; tokens, key=value pairs, URL userinfo, and emails masked; bodies never logged. |
| ~10 MB rotation with one archive | done | `<name>.1.log`; an oversize file rotates once at launch. |

## Share and party mode

| Feature | Status | Notes |
|---|---|---|
| Share Screenshot (provider + Total Spend) | equivalent | `grabToImage` → 0600 temp PNG → `wl-copy` → delete; captures the live card pixels as-is with a "Copied to clipboard" pill. |
| Party mode (Konami) | equivalent | Cycles the meter fills through theme colours and pulses the provider marks (scale); no transparency (ADR 0005); static under Reduce Motion. |

## Storage and secrets

| Feature | Status | Notes |
|---|---|---|
| Settings in `shell.json`, layout in `layout.json` | done | Layout versioned with `migrate(v)`; undo in memory only. |
| API keys in libsecret, 0600 file fallback | done | Values on stdin only; never in QML, argv, logs, or fixtures. |
| Old settings not migrated | done | Starts clean from upstream defaults, as settled. |
| Unrelated `openusage` paths untouched | done | `telemetry.db`, `daemon.env`, `settings.json`, `~/.local/bin/openusage` are never read, modified, or deleted. |

## Follow-ups

None — pass 9 fixed the footer click, spend persistence, notification tap,
party pulse, and About sheet. The API Key no-reveal rule stays as a
documented deviation (secrets rule); SOCKS5 stays inert; signature
verification stays omitted.
