# OpenUsage

A status-bar view of plan Quotas for coding Providers. This context is the product language for the Omarchy plugin. It is not a Mac application description.

## Language

**Provider**:
A coding product that reports a plan Quota. The first Providers are Claude, Codex, Cursor, OpenCode, and Grok.
_Avoid_: Agent, vendor, service

**Quota**:
A plan limit for one Window. A Quota is used or left. It is not money and it is not a token total.
_Avoid_: Usage, allowance, credit

**Window**:
The time range of one Quota. Typical Windows are Session, Weekly, and Monthly.
_Avoid_: Period, cycle, interval

**Spend**:
Money or tokens that a Provider consumed. Spend is out of scope for the first version.
_Avoid_: Cost, usage, billing

**Metric**:
One named Quota number that the user can show or hide. Example: Claude Session.
_Avoid_: Stat, tile, field

**Star**:
A Metric that is pinned to the Bar strip. A Provider can have at most two Stars.
_Avoid_: Pin, favorite, shortcut

**Lead Metric**:
The Metric with the highest Used percent for a Provider. It is live. It is the default Star. It changes when another Window has a higher Used percent.
_Avoid_: Headline, binding window, hot window

**Display**:
Whether a Quota is shown as Used or Left. One global toggle sets Display for the Bar strip and the Dashboard. The first version default is Used.
_Avoid_: Mode, format

**Pace**:
How Used compares to an even burn through the Window. Pace is shown as blue, yellow, or red.
_Avoid_: Burn, health, severity

**Bar strip**:
The always-visible Stars on the Omarchy status bar.
_Avoid_: Navbar, menu bar, widget

**Dashboard**:
The panel that opens on a click and shows every enabled Provider together.
_Avoid_: Popup, popover, overlay

**Customize**:
The surface where the user enables Providers, shows or hides Metrics, and sets Stars.
_Avoid_: Settings, preferences, config
