const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const load = (file, injected = {}) => {
  const ctx = vm.createContext({console, ...injected});
  vm.runInContext(fs.readFileSync(file, 'utf8').replace(/^\.import .*$/gm, ''), ctx);
  return ctx;
};
const catalogCtx = load('js/Catalog.js');
const m = load('js/Dashboard.js', {Catalog: catalogCtx});
vm.runInContext(fs.readFileSync('js/Theme.js', 'utf8'), m);
vm.runInContext(fs.readFileSync('js/Menus.js', 'utf8').replace(/^\.import .*$/gm, ''), m);
const fmtCtx = load('js/Format.js');
const paceCtx = load('js/Pace.js');
const layoutCtx = load('js/Layout.js');
const fmt = {number: fmtCtx.number, stringFor: fmtCtx.stringFor, currency: fmtCtx.currency,
  compactDuration: fmtCtx.compactDuration, whenLabel: fmtCtx.whenLabel,
  deadlineLabel: fmtCtx.deadlineLabel, resetRelativeLabel: fmtCtx.resetRelativeLabel,
  resetAbsoluteLabel: fmtCtx.resetAbsoluteLabel, normalizeResetMode: fmtCtx.normalizeResetMode,
  IMMINENT: fmtCtx.IMMINENT};
const pace = {meterState: paceCtx.meterState, severityOf: paceCtx.severityOf,
  tooltipOf: paceCtx.tooltipOf, paceTick: paceCtx.paceTick,
  expirySeverity: paceCtx.expirySeverity, isFreshSession: paceCtx.isFreshSession,
  sessionSignalFor: paceCtx.sessionSignalFor, roundedAtPrecision: paceCtx.roundedAtPrecision};
const layoutMod = {displayMetrics: layoutCtx.displayMetrics};
const deps = {fmt, pace, layout: layoutMod};
const norm = (x) => JSON.parse(JSON.stringify(x));
const catalog = JSON.parse(fs.readFileSync('catalog.json', 'utf8'));
const NOW = Date.parse('2026-09-23T09:00:00Z');
const WEEK = 7 * 24 * 3600;
const resetsAt = (elapsed, period = WEEK) => NOW + period * 1000 * (1 - elapsed);
const progress = (used, limit, extra = {}) => Object.assign(
  {type: 'progress', used, limit, format: {kind: 'percent'}}, extra);
const values = (items, extra = {}) => Object.assign({type: 'values', values: items}, extra);
const dollars = (n, estimated = false) => ({number: n, kind: 'dollars', estimated});
const tokens = (n) => ({number: n, kind: 'count', label: 'tokens'});
const opts = {display: 'Used', resetMode: 'Countdown', timeFormat: 'Auto',
  alwaysShowPacing: false, now: NOW};

// WidgetData.boundedHeadline: value plus Used/Left word, tooltip flips it.
{
  const row = m.rowModel(catalog, 'claude', 'session',
    progress(67, 100, {resetsAt: new Date(resetsAt(0.9)).toISOString(), periodMs: WEEK * 1000}), opts, deps);
  assert.equal(row.layout, 'meter');
  assert.equal(row.headline, '67% used');
  assert.equal(row.headlineTip, '33% left');
  assert.equal(row.headlineToggle, true);
  const left = m.rowModel(catalog, 'claude', 'session',
    progress(67, 100, {resetsAt: new Date(resetsAt(0.9)).toISOString(), periodMs: WEEK * 1000}),
    Object.assign({}, opts, {display: 'Left'}), deps);
  assert.equal(left.headline, '33% left');
  assert.equal(left.headlineTip, '67% used');
}
// Reset label follows Countdown/Exact and tooltips the opposite (dashboard.md).
{
  const metric = progress(10, 100, {resetsAt: new Date(NOW + 3 * 3600 * 1000).toISOString(), periodMs: WEEK * 1000});
  const rel = m.rowModel(catalog, 'codex', 'session', metric, opts, deps);
  assert.equal(rel.trailing, 'Resets in 3h');
  assert.ok(rel.trailingToggle);
  assert.ok(rel.trailingTip.startsWith('Resets '));
  const abs = m.rowModel(catalog, 'codex', 'session', metric,
    Object.assign({}, opts, {resetMode: 'Exact Time'}), deps);
  assert.ok(abs.trailing.includes(' at '));
  assert.equal(abs.trailingTip, 'Resets in 3h');
}
// Fresh Claude session reads Not started with the explainer tooltip.
{
  const row = m.rowModel(catalog, 'claude', 'session', progress(0, 100), opts, deps);
  assert.equal(row.trailing, 'Not started');
  assert.equal(row.trailingTip, 'Sessions start after you send your first message.');
  assert.equal(row.trailingToggle, false);
  assert.equal(row.note, null);
}
// Pace notes: spare, flame with run-out, spent (WidgetRowView.warning).
{
  const amber = m.rowModel(catalog, 'codex', 'weekly',
    progress(46, 100, {resetsAt: new Date(resetsAt(0.5)).toISOString(), periodMs: WEEK * 1000}), opts, deps);
  assert.deepEqual(norm(amber.note), {text: '~8% spare', tone: 'spare', tip: '~92% used at reset', action: null});
  assert.equal(amber.meter.severity, 'warning');
  assert.ok(Math.abs(amber.meter.tick - 0.5) < 0.01);
  const red = m.rowModel(catalog, 'codex', 'weekly',
    progress(60, 100, {resetsAt: new Date(resetsAt(0.5)).toISOString(), periodMs: WEEK * 1000}), opts, deps);
  assert.equal(red.note.tone, 'flame');
  assert.ok(red.note.text.startsWith('Limit in '));
  assert.equal(red.note.action, 'toggleReset');
  assert.equal(red.meter.severity, 'critical');
  const spent = m.rowModel(catalog, 'codex', 'weekly',
    progress(100, 100, {resetsAt: new Date(resetsAt(0.5)).toISOString(), periodMs: WEEK * 1000}), opts, deps);
  assert.equal(spent.note.text, 'Limit reached');
  const blue = m.rowModel(catalog, 'codex', 'weekly',
    progress(30, 100, {resetsAt: new Date(resetsAt(0.5)).toISOString(), periodMs: WEEK * 1000}), opts, deps);
  assert.equal(blue.note, null);
  assert.equal(blue.meter.tick, null);
  const shown = m.rowModel(catalog, 'codex', 'weekly',
    progress(30, 100, {resetsAt: new Date(resetsAt(0.5)).toISOString(), periodMs: WEEK * 1000}),
    Object.assign({}, opts, {alwaysShowPacing: true}), deps);
  assert.equal(shown.note.text, '~40% left at reset');
  assert.equal(shown.note.tone, 'projection');
}
// Missing metric: bounded kinds keep an empty meter, others read No data.
{
  const meter = m.rowModel(catalog, 'claude', 'session', null, opts, deps);
  assert.equal(meter.layout, 'meter');
  assert.equal(meter.hasData, false);
  assert.equal(meter.headline, '—');
  assert.equal(meter.trailing, 'No data');
  assert.equal(meter.meter.fraction, 0);
  assert.equal(meter.meter.severity, null);
  const text = m.rowModel(catalog, 'claude', 'today', null, opts, deps);
  assert.equal(text.layout, 'text');
  assert.equal(text.detail, 'No data');
}
// Unbounded values: combined spend, lone dollar word, bare count (WidgetData.unboundedDetail).
{
  const spend = m.rowModel(catalog, 'claude', 'today',
    values([dollars(4.08), tokens(1200000)]), opts, deps);
  assert.equal(spend.detail, '$4.08 · 1.2M tokens');
  assert.equal(spend.interactive, false);
  const balance = m.rowModel(catalog, 'devin', 'extra', values([dollars(12.34)]), opts, deps);
  assert.equal(balance.detail, '$12.34 left');
  const bare = m.rowModel(catalog, 'openrouter', 'today', values([dollars(4.08)]), opts, deps);
  assert.equal(bare.detail, '$4.08');
  const count = m.rowModel(catalog, 'codex', 'rateLimitResets',
    values([{number: 2, kind: 'count', label: 'available'}]), opts, deps);
  assert.equal(count.detail, '2 available');
  assert.equal(count.interactive, true);
  assert.equal(count.resets.count, 2);
  assert.equal(count.resets.claimable, true);
  const readOnly = m.rowModel(catalog, 'claude', 'rateLimitResets',
    values([{number: 1, kind: 'count', label: 'available'}]), opts, deps);
  assert.equal(readOnly.resets.claimable, false);
}
// Figures tooltip plus source notes; breakdown/resets rows drop it (WidgetRowView).
{
  const big = m.rowModel(catalog, 'claude', 'today', values([dollars(2059.07)]), opts, deps);
  assert.equal(big.detail, '$2.1K');
  assert.equal(big.detailTip, '$2,059.07');
  const est = m.rowModel(catalog, 'claude', 'today', values([dollars(4.08, true)]), opts, deps);
  assert.equal(est.detailTip, 'Estimated locally, so it may be off');
  const cursor = m.rowModel(catalog, 'cursor', 'today', values([dollars(4.08)]), opts, deps);
  assert.equal(cursor.detailTip, 'From your Cursor usage history.');
  const withBreakdown = m.rowModel(catalog, 'claude', 'today',
    values([dollars(2059.07)], {breakdown: {models: [{model: 'a', totalTokens: 1, costUSD: 1}], sourceNote: 'n'}}),
    opts, deps);
  assert.equal(withBreakdown.detailTip, null);
  assert.equal(withBreakdown.interactive, true);
  const idle = m.rowModel(catalog, 'claude', 'today',
    values([dollars(0), tokens(0)]), opts, deps);
  assert.equal(idle.detailTip, 'No usage in this period');
}
// Unknown models ride beside the label with a hover list.
{
  const row = m.rowModel(catalog, 'claude', 'today',
    values([dollars(4.08)], {unknownModels: ['mystery-1', 'mystery-2']}), opts, deps);
  assert.equal(row.unknown.tip, 'Unknown models found\n- mystery-1\n- mystery-2');
}
// ModelUsageDetail.shares: cost basis only when every model is priced.
assert.deepEqual(norm(m.breakdownShares([
  {model: 'a', totalTokens: 100, costUSD: 3},
  {model: 'b', totalTokens: 100, costUSD: 1}])), [0.75, 0.25]);
assert.deepEqual(norm(m.breakdownShares([
  {model: 'a', totalTokens: 30, costUSD: null},
  {model: 'b', totalTokens: 70, costUSD: 1}])), [0.3, 0.7]);
assert.deepEqual(norm(m.breakdownShares([
  {model: 'a', totalTokens: 0}, {model: 'b', totalTokens: 0}])), [0, 0]);
// Largest-remainder percents always sum to 100.
assert.deepEqual(norm(m.wholePercents([0.75, 0.25])), [75, 25]);
assert.deepEqual(norm(m.wholePercents([1 / 3, 1 / 3, 1 / 3])), [34, 33, 33]);
assert.deepEqual(norm(m.wholePercents([0, 0])), [0, 0]);
// RateLimitResetsDetail.entries: soonest first, imminent reads Expiring soon.
{
  const entries = m.expiryEntries(
    [new Date(NOW + 10 * 86400000).toISOString(), new Date(NOW + 86400000).toISOString()],
    NOW, fmt, pace, 'Countdown', 'Auto');
  assert.equal(entries.length, 2);
  assert.equal(entries[0].severity, 'critical');
  assert.equal(entries[1].severity, 'normal');
  assert.ok(entries[0].countdown);
  const soon = m.expiryEntries([new Date(NOW + 60000).toISOString()], NOW, fmt, pace, 'Countdown', 'Auto');
  assert.equal(soon[0].time, 'Expiring soon');
  assert.equal(soon[0].countdown, null);
  assert.deepEqual(norm(m.expiryEntries([], NOW, fmt, pace, 'Countdown', 'Auto')), []);
}
// Condensed text rows cluster; the caret breaks the run (condensedTextRowOffsets).
assert.deepEqual(norm(m.condensedFlags(['meter', 'text', 'text', 'chart'])), [false, false, true, true]);
assert.deepEqual(norm(m.condensedFlags(['text'])), [false]);
// Stale-while-revalidate: Outdated past two intervals, never while refreshing.
{
  assert.equal(m.stalenessHint(new Date(NOW - 5 * 60000).toISOString(), NOW, fmt), null);
  const stale = m.stalenessHint(new Date(NOW - 11 * 60000).toISOString(), NOW, fmt);
  assert.equal(stale.label, 'Outdated');
  assert.equal(stale.tooltip, 'Last updated 11m ago');
  assert.equal(m.stalenessHint(null, NOW, fmt), null);
}
// Sections: enabled cards in layout order with header bits and split rows.
{
  const layout = layoutCtx.defaults(catalog, {claude: true});
  layout.cards.claude.expanded = true;
  const state = {schema: 'openusage-omarchy.state.v1',
    refresh: {inFlight: [], nextAt: null, lastBatchEndedAt: null},
    cards: [{cardId: 'claude', family: 'claude', label: 'Claude', plan: 'Pro',
      fetchedAt: new Date(NOW - 60000).toISOString(),
      error: {category: 'auth', message: 'Login expired'},
      lastClaim: {status: 'ok', message: 'Reset claimed. Enjoy!', at: new Date(NOW).toISOString()},
      metrics: {session: progress(10, 100)}}]};
  const view = m.sections(layout, catalog, state, opts, deps);
  assert.equal(view.isEmpty, false);
  assert.deepEqual(norm(view.sections.map((s) => s.cardId)), ['claude']);
  const card = view.sections[0];
  assert.equal(card.plan, 'Pro');
  assert.equal(card.warning, 'Login expired');
  assert.equal(card.staleness, null);
  assert.equal(card.lastClaim.status, 'ok');
  assert.ok(card.always.length > 0 && card.expanded.length > 0);
  assert.equal(card.showCaret, true);
  assert.equal(card.isExpanded, true);
  assert.deepEqual(norm(card.links.map((l) => l.label)), ['Status', 'Dashboard']);
  const off = layoutCtx.defaults(catalog, {claude: true});
  off.cards.claude.enabled = false;
  assert.equal(m.sections(off, catalog, state, opts, deps).isEmpty, true);
}
// A refreshing card hides Outdated and flags the spinner.
{
  const layout = layoutCtx.defaults(catalog, {claude: true});
  const state = {refresh: {inFlight: ['claude']},
    cards: [{cardId: 'claude', family: 'claude', label: 'Claude', plan: null,
      fetchedAt: new Date(NOW - 3600000).toISOString(), error: null, metrics: {}}]};
  const card = m.sections(layout, catalog, state, opts, deps).sections[0];
  assert.equal(card.refreshing, true);
  assert.equal(card.staleness, null);
  assert.equal(m.isRefreshing({inFlight: ['codex']}, 'codex'), true);
  assert.equal(m.isRefreshing({inFlight: []}, 'codex', 'codex'), false);
}
// Caret hides when a provider has neither On Demand rows nor links.
{
  const layout = layoutCtx.defaults(catalog, {antigravity: true});
  const slot = layout.cards.antigravity;
  slot.disabled = slot.metricOrder.filter((id) => slot.alwaysVisible.indexOf(id) < 0);
  const state = {refresh: {inFlight: []}, cards: []};
  const card = m.sections(layout, catalog, state, opts, deps).sections[0];
  assert.equal(card.expanded.length, 0);
  assert.equal(card.showCaret, false);
}
// Footer countdown mirrors PopoverFooter.updateStatusText.
{
  assert.equal(m.footerModel({refresh: {inFlight: ['codex']}, daemon: {version: '0.1.0'}}, NOW).text, 'Updating…');
  assert.equal(m.footerModel({refresh: {inFlight: [], nextAt: new Date(NOW + 180000).toISOString()}, daemon: {version: '0.1.0'}}, NOW).text, 'Next update in 3m');
  assert.equal(m.footerModel({refresh: {inFlight: [], nextAt: new Date(NOW + 45000).toISOString()}, daemon: {version: '0.1.0'}}, NOW).text, 'Next update in 45s');
  assert.equal(m.footerModel({refresh: {inFlight: [], nextAt: null, lastBatchEndedAt: new Date(NOW - 60000).toISOString()}, daemon: {version: ''}}, NOW).text, 'Next update in 4m');
  assert.equal(m.footerModel({refresh: {inFlight: []}, daemon: {version: ''}}, NOW).text, 'Next update in …');
}
// Menus carry upstream's verbs in upstream's order (dashboard.md).
assert.deepEqual(norm(m.rowMenuItems({starrable: true, starred: false, providerName: 'Claude'}).map((i) => i.label || '|')),
  ['Hide', 'Star for menu bar', '|', 'Refresh Claude', 'Customize…']);
assert.deepEqual(norm(m.rowMenuItems({starrable: true, starred: true, providerName: 'Claude'})[1]),
  {kind: 'item', id: 'unstar', label: 'Unstar'});
assert.equal(m.rowMenuItems({starrable: false, providerName: 'Claude'}).length, 4);
assert.deepEqual(norm(m.headerMenuItems({providerName: 'Codex'}).map((i) => i.label || '|')),
  ['Hide Codex', '|', 'Refresh Codex', 'Customize…', '|', 'Share Screenshot']);
{
  const items = m.optionsMenuItems({providers: [{cardId: 'claude', label: 'Claude'}]});
  assert.deepEqual(norm(items.map((i) => i.label || '|')),
    ['Customize', 'Settings', '|', 'Share Screenshot', 'Check for Updates…', '|', 'About OpenUsage']);
  assert.deepEqual(norm(items[3].children), [{kind: 'item', id: 'share:claude', label: 'Claude'}]);
}
// Menu picks route to a layout dispatch, a refresh, or a panel switch.
{
  const anchor = {cardId: 'claude', metricId: 'session'};
  assert.deepEqual(norm(m.menuAction('row', 'hide', anchor)),
    {route: 'dispatch', action: {type: 'setMetricEnabled', cardId: 'claude', metricId: 'session', enabled: false}});
  assert.deepEqual(norm(m.menuAction('row', 'star', anchor)),
    {route: 'dispatch', action: {type: 'toggleStar', cardId: 'claude', metricId: 'session'}});
  assert.deepEqual(norm(m.menuAction('row', 'unstar', anchor)),
    {route: 'dispatch', action: {type: 'toggleStar', cardId: 'claude', metricId: 'session'}});
  assert.deepEqual(norm(m.menuAction('row', 'refresh', anchor)), {route: 'refresh', cardId: 'claude'});
  assert.deepEqual(norm(m.menuAction('row', 'customize', anchor)), {route: 'customize', cardId: 'claude'});
  assert.deepEqual(norm(m.menuAction('header', 'customize', {cardId: 'codex'})), {route: 'customize', cardId: 'codex'});
  assert.deepEqual(norm(m.menuAction('options', 'customize', {})), {route: 'customize', cardId: null});
  assert.deepEqual(norm(m.menuAction('header', 'hide', {cardId: 'codex'})),
    {route: 'dispatch', action: {type: 'setCardEnabled', cardId: 'codex', enabled: false}});
  assert.deepEqual(norm(m.menuAction('header', 'refresh', {cardId: 'codex'})), {route: 'refresh', cardId: 'codex'});
  assert.deepEqual(norm(m.menuAction('options', 'settings', {})), {route: 'settings'});
  assert.deepEqual(norm(m.menuAction('options', 'checkUpdates', {})), {route: 'checkUpdates'});
  assert.deepEqual(norm(m.menuAction('options', 'about', {})), {route: 'about'});
  assert.deepEqual(norm(m.menuAction('header', 'share', {cardId: 'codex'})), {route: 'share', cardId: 'codex'});
  assert.deepEqual(norm(m.menuAction('options', 'share:claude', {})), {route: 'share', cardId: 'claude'});
  assert.deepEqual(norm(m.menuAction('options', 'share:', {})), {route: 'none'});
  assert.deepEqual(norm(m.menuAction('header', 'share', {})), {route: 'none'});
  assert.deepEqual(norm(m.menuAction('row', 'hide', {})), {route: 'none'});
  assert.deepEqual(norm(m.menuAction('nope', 'hide', anchor)), {route: 'none'});
}
// Row menu star state comes from the catalog plus the layout slot.
{
  const layout = layoutCtx.defaults(catalog, {claude: true});
  assert.deepEqual(norm(m.menuStarState(catalog, layout, 'claude', 'session')), {starrable: true, starred: true});
  assert.deepEqual(norm(m.menuStarState(catalog, layout, 'claude', 'weekly').starrable), true);
  assert.deepEqual(norm(m.menuStarState(catalog, layout, 'claude', 'nope')), {starrable: false, starred: false});
}
// Claim correlation: only results newer than the click resolve the spinner.
assert.equal(m.claimTone('ok'), 'positive');
assert.equal(m.claimTone('not_needed'), 'info');
assert.equal(m.claimTone('unavailable'), 'warning');
assert.equal(m.claimTone('error'), 'critical');
{
  const claim = {status: 'ok', message: 'Reset claimed. Enjoy!', at: new Date(NOW).toISOString()};
  assert.equal(m.claimReady(claim, NOW), claim);
  assert.equal(m.claimReady(claim, NOW + 1000), null);
  assert.equal(m.claimReady(null, NOW), null);
}
// Total Spend surfaces: visibility, providers, and the ⓘ tip.
{
  assert.equal(m.spendVisible(layoutCtx.defaults(catalog, {claude: true}), true, catalog), true);
  assert.equal(m.spendVisible(layoutCtx.defaults(catalog, {claude: true}), false, catalog), false);
  assert.equal(m.spendVisible(layoutCtx.defaults(catalog, {copilot: true}), true, catalog), false);
  assert.deepEqual(norm(m.spendProviders(layoutCtx.defaults(catalog, {claude: true, codex: true}), catalog)),
    [{id: 'claude', displayName: 'Claude', spend: true},
     {id: 'codex', displayName: 'Codex', spend: true}]);
  assert.equal(m.spendInfoTip([{displayName: 'Claude'}]), 'Only includes Claude.');
  assert.equal(m.joinList(['A', 'B']), 'A and B');
  assert.equal(m.joinList(['A', 'B', 'C']), 'A, B and C');
}
// Update banner shows for a newer unsnoozed release only.
{
  const base = {daemon: {version: '0.1.0'}, update: {latest: '0.2.0', snoozed: null, installable: true}};
  assert.deepEqual(norm(m.updateBannerModel(base)), {version: '0.2.0', installable: true});
  assert.equal(m.updateBannerModel({daemon: {version: '0.1.0'}, update: {latest: '0.2.0', snoozed: '0.2.0'}}), null);
  assert.equal(m.updateBannerModel({daemon: {version: '0.2.0'}, update: {latest: '0.2.0', snoozed: null}}), null);
  assert.equal(m.updateBannerModel({daemon: {version: '0.1.0'}, update: {latest: null}}), null);
}
// Usage trend readout: hovered day, else the peak (UsageTrendDetail).
{
  const points = [{label: 'Sep 1', value: 10, readout: '10'}, {label: 'Sep 2', value: 50, readout: '50'}];
  assert.equal(m.trendReadout(points, 0), 'Sep 1 · 10');
  assert.equal(m.trendReadout(points, null), 'peak 50');
  assert.equal(m.trendReadout([], null), '');
  assert.equal(m.trendSummary(points).last, 'Sep 2');
}
// Idempotency keys mint UUIDv4.
assert.match(m.makeUuid(), /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
// Theme: terminal yellow wins, else the accent; brands keep upstream hexes.
assert.equal(m.parseYellow('foreground = "#ffffff"\nyellow = "#eab308"\n'), '#eab308');
assert.equal(m.parseYellow('foreground = "#ffffff"\n'), null);
assert.equal(m.meterColor('critical', {accent: 'a', warning: 'w', urgent: 'u'}), 'u');
assert.equal(m.meterColor('warning', {accent: 'a', warning: 'w', urgent: 'u'}), 'w');
assert.equal(m.meterColor('warning', {accent: 'a', urgent: 'u'}), 'a');
assert.equal(m.meterColor('normal', {accent: 'a', urgent: 'u'}), 'a');
assert.equal(m.meterColor(null, {accent: 'a', track: 't'}), 't');
assert.equal(m.spendColor('claude'), '#DE7356');
assert.equal(m.spendColor('cursor', true), '#13120A');
assert.equal(m.spendColor('cursor', false), '#F5F5F7');
assert.equal(m.spendColor('mystery-x'), m.spendColor('mystery-x'));
assert.equal(m.isLight({r: 1, g: 1, b: 1, a: 1}), true);
assert.equal(m.isLight({r: 0.05, g: 0.05, b: 0.05, a: 1}), false);
console.log('Dashboard tests passed');
