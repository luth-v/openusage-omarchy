# OpenUsage

A status-bar view of plan Quotas and Spend for coding Providers, ported to Omarchy. The language follows the upstream macOS OpenUsage app; the port aims for equivalent behaviour and layout, drawn in the Omarchy theme.

## Language

**Provider**:
A coding product that reports Quotas or Spend. The set matches upstream: Claude, Codex, Cursor, Antigravity, Copilot, Devin, Grok, Ollama, OpenCode, OpenRouter, and Z.ai.
_Avoid_: Agent, vendor, service

**Quota**:
A plan limit for one Window. A Quota is used or left.
_Avoid_: Usage, allowance, credit

**Window**:
The time range of one Quota, ending at a reset. Typical Windows are Session, Weekly, and Monthly. Some Quotas (credit balances) have no Window.
_Avoid_: Period, cycle, interval

**Spend**:
Money or tokens a Provider consumed, reported as totals over a period. Never conversation content.
_Avoid_: Cost, usage, billing

**Total Spend**:
The cross-Provider Spend card at the top of the Dashboard, by Cost, Cost/MTok, or Tokens, over Today, Yesterday, or 30 Days.
_Avoid_: Spend ring, summary

**Usage Trend**:
A per-Provider chart of the last 30 days of token Spend, one bar per day. It is a Metric but cannot be a Star.
_Avoid_: Diagram, sparkline, history

**Metric**:
One named row on a Provider card: a Quota meter, a Spend value, or a Usage Trend. Example: Claude Session.
_Avoid_: Stat, tile, field

**Always Visible**:
The Metrics shown on a Provider card by default.
_Avoid_: Pinned, primary

**On Demand**:
The Metrics tucked behind a Provider card's caret.
_Avoid_: Hidden, secondary, collapsed

**Star**:
A Metric the user pins to the Bar strip. A Provider can have at most two Stars.
_Avoid_: Pin, favorite, shortcut, Lead

**Display**:
Whether a Quota is shown as Used or Left. One global toggle sets Display everywhere. The default is Left.
_Avoid_: Mode, format, meter style

**Pace**:
A verdict on a Quota's projected burn to the end of its Window: blue (on course with at least 10% to spare), yellow (projected inside the last 10%), red (projected to run out). Quotas without a Window use level instead.
_Avoid_: Burn, health, severity

**Bar strip**:
The always-visible Stars on the Omarchy status bar, drawn as Text or Bars.
_Avoid_: Navbar, menu bar, widget

**Dashboard**:
The panel that opens on a click and shows Total Spend and every enabled Provider.
_Avoid_: Popup, popover, overlay

**Customize**:
The surface where the user enables and orders Providers, and arranges, hides, and Stars Metrics.
_Avoid_: Settings, preferences, config

**Settings**:
The surface for app-wide preferences: density, time format, Display, notifications, updates, and advanced options. Distinct from Customize.
_Avoid_: Preferences, config, Customize
