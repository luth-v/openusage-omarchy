const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const m = vm.createContext({});
vm.runInContext(fs.readFileSync('js/Layout.js', 'utf8'), m);
const norm = (x) => JSON.parse(JSON.stringify(x));
const catalog = JSON.parse(fs.readFileSync('catalog.json', 'utf8'));
assert.equal(m.SCHEMA, 'openusage-omarchy.layout.v1');
assert.equal(m.STAR_LIMIT, 2);
assert.deepEqual(norm(m.parse(JSON.stringify({a: 1}))), {a: 1});
assert.equal(m.parse('{bad'), null);
assert.equal(m.migrate({schema: 'other'}), null);
// Fresh starter set: Claude, Codex, Cursor on; Ollama never on.
{
  const layout = m.defaults(catalog, null);
  assert.equal(layout.firstRunCompleted, false);
  assert.deepEqual(norm(layout.order.slice(0, 3)), ['claude', 'codex', 'cursor']);
  assert.equal(layout.cards.claude.enabled, true);
  assert.equal(layout.cards.codex.enabled, true);
  assert.equal(layout.cards.cursor.enabled, true);
  assert.equal(layout.cards.ollama.enabled, false);
  assert.deepEqual(norm(layout.cards.claude.stars), ['session', 'weekly']);
  assert.ok(layout.cards.claude.disabled.includes('sonnet'));
  assert.ok(layout.cards.claude.alwaysVisible.includes('session'));
  assert.ok(!layout.cards.claude.alwaysVisible.includes('sonnet'));
}
// Detection wins; empty detection falls back to starter (provider-enablement.md).
{
  const layout = m.defaults(catalog, {copilot: true, zai: true});
  assert.equal(layout.firstRunCompleted, true);
  assert.equal(layout.cards.copilot.enabled, true);
  assert.equal(layout.cards.zai.enabled, true);
  assert.equal(layout.cards.claude.enabled, false);
  const none = m.defaults(catalog, {});
  assert.equal(none.cards.claude.enabled, true);
  assert.equal(none.cards.copilot.enabled, false);
  const ollama = m.defaults(catalog, {ollama: true, claude: true});
  assert.equal(ollama.cards.ollama.enabled, false);
  assert.equal(ollama.cards.claude.enabled, true);
}
// Merge drops unknown ids and adds new providers disabled (LayoutBootstrap).
{
  const stored = {schema: m.SCHEMA, order: ['claude', 'nope'], cards: {claude: {enabled: true, metricOrder: ['session', 'nope'], disabled: [], alwaysVisible: ['session'], stars: ['session'], expanded: true}}, firstRunCompleted: true};
  const merged = m.merge(stored, catalog);
  assert.ok(!merged.order.includes('nope'));
  assert.ok(merged.order.includes('codex'));
  assert.equal(merged.cards.codex.enabled, false);
  assert.ok(!merged.cards.claude.metricOrder.includes('nope'));
  assert.equal(merged.cards.claude.expanded, true);
  assert.equal(merged.cards.claude.enabled, true);
}
// New default metric arrives once in its section (DefaultLayout.expandedMetricIDs).
{
  const stored = {schema: m.SCHEMA, order: ['claude'], cards: {claude: {enabled: true, metricOrder: ['session'], disabled: [], alwaysVisible: ['session'], stars: [], expanded: false}}, firstRunCompleted: true};
  const merged = m.merge(stored, catalog);
  assert.ok(merged.cards.claude.metricOrder.includes('weekly'));
  assert.ok(merged.cards.claude.alwaysVisible.includes('weekly'));
  assert.ok(merged.cards.claude.metricOrder.includes('today'));
  assert.ok(!merged.cards.claude.alwaysVisible.includes('today'));
}
// Account cards inherit the family card (DefaultLayout.expandingAccounts).
{
  const base = m.defaults(catalog, {claude: true});
  const next = m.ensureCards(base, catalog, ['claude:abc']);
  assert.deepEqual(norm(next.cards['claude:abc'].metricOrder), norm(next.cards.claude.metricOrder));
  assert.equal(next.cards['claude:abc'].enabled, true);
  assert.equal(next.order.indexOf('claude:abc'), next.order.indexOf('claude') + 1);
  assert.equal(m.ensureCards(next, catalog, ['claude:abc']), next);
}
// First-run merge flips enablement once, then sticks (provider-enablement.md).
{
  const base = m.defaults(catalog, null);
  const done = m.firstRunComplete(base, catalog, {copilot: true});
  assert.equal(done.firstRunCompleted, true);
  assert.equal(done.cards.copilot.enabled, true);
  assert.equal(done.cards.claude.enabled, false);
  assert.equal(m.firstRunComplete(done, catalog, {claude: true}), done);
}
// Reducer: provider reorder (LayoutStore.reordered).
{
  const base = m.defaults(catalog, null);
  const r = m.reduce(base, {type: 'moveProvider', dragged: 'claude', target: 'codex'}, catalog);
  assert.equal(r.undoable, true);
  assert.deepEqual(norm(r.layout.order.slice(0, 3)), ['codex', 'claude', 'cursor']);
  assert.equal(m.reduce(base, {type: 'moveProvider', dragged: 'claude', target: 'claude'}, catalog).layout, base);
}
// Reducer: metric reorder moves across the caret with the target (reorderMetric).
{
  const base = m.defaults(catalog, null);
  const r = m.reduce(base, {type: 'moveMetric', cardId: 'claude', dragged: 'today', target: 'session'}, catalog);
  assert.ok(r.layout.cards.claude.alwaysVisible.includes('today'));
  assert.equal(r.undoable, true);
}
// Reducer: third star is rejected with a StarNotice (maxPinsPerProvider).
{
  const base = m.defaults(catalog, null);
  assert.deepEqual(norm(base.cards.claude.stars), ['session', 'weekly']);
  const denied = m.reduce(base, {type: 'setStar', cardId: 'claude', metricId: 'fable', starred: true}, catalog);
  assert.equal(denied.layout, base);
  assert.deepEqual(norm(denied.notice), {kind: 'starDenied'});
  const chart = m.reduce(base, {type: 'setStar', cardId: 'claude', metricId: 'trend', starred: true}, catalog);
  assert.equal(chart.layout, base);
  assert.equal(chart.notice, null);
  const unstar = m.reduce(base, {type: 'setStar', cardId: 'claude', metricId: 'session', starred: false}, catalog);
  assert.deepEqual(norm(unstar.layout.cards.claude.stars), ['weekly']);
}
// Reducer: enable, section, expanded (expanded skips undo like upstream).
{
  const base = m.defaults(catalog, null);
  const off = m.reduce(base, {type: 'setCardEnabled', cardId: 'claude', enabled: false}, catalog);
  assert.equal(off.layout.cards.claude.enabled, false);
  const hide = m.reduce(base, {type: 'setMetricEnabled', cardId: 'claude', metricId: 'session', enabled: false}, catalog);
  assert.ok(hide.layout.cards.claude.disabled.includes('session'));
  const show = m.reduce(hide.layout, {type: 'setMetricEnabled', cardId: 'claude', metricId: 'session', enabled: true}, catalog);
  assert.ok(!show.layout.cards.claude.disabled.includes('session'));
  const caret = m.reduce(base, {type: 'setExpanded', cardId: 'claude', expanded: true}, catalog);
  assert.equal(caret.undoable, false);
}
// Reducer: reset provider keeps enablement; reset all clears undo.
{
  const base = m.defaults(catalog, null);
  const moved = m.reduce(base, {type: 'moveMetric', cardId: 'claude', dragged: 'today', target: 'session'}, catalog).layout;
  const reset = m.reduce(moved, {type: 'resetProvider', cardId: 'claude'}, catalog);
  assert.equal(reset.clearUndo, true);
  assert.ok(!reset.layout.cards.claude.alwaysVisible.includes('today'));
  assert.equal(reset.layout.cards.claude.enabled, true);
  const all = m.reduce(base, {type: 'resetAll', detected: {copilot: true}}, catalog);
  assert.equal(all.clearUndo, true);
  assert.equal(all.layout.cards.copilot.enabled, true);
}
// Selectors: disabled split and empty-top promotion (displayGroups).
{
  const base = m.defaults(catalog, null);
  const shown = m.displayMetrics(base.cards.claude);
  assert.ok(shown.alwaysVisible.includes('session'));
  assert.ok(shown.onDemand.includes('today'));
  const allHidden = {metricOrder: ['a', 'b'], disabled: [], alwaysVisible: []};
  assert.deepEqual(norm(m.displayMetrics(allHidden)), {alwaysVisible: ['a', 'b'], onDemand: []});
}
// Undo history caps at 40 and pops in order (LayoutUndoHistory).
{
  let stack = [];
  assert.equal(m.canUndo(stack), false);
  for (let i = 0; i < 45; i++)
    stack = m.pushHistory(stack, {n: i});
  assert.equal(stack.length, 40);
  const popped = m.popHistory(stack);
  assert.equal(popped.snapshot.n, 44);
  assert.equal(popped.stack.length, 39);
}
// First-run hint: fresh layouts show it, existing completed ones never do.
{
  const fresh = m.defaults(catalog, null);
  assert.equal(fresh.hintDismissed, false);
  const seen = m.defaults(catalog, {claude: true});
  assert.equal(seen.hintDismissed, false);
  const old = {schema: m.SCHEMA, order: ['claude'], cards: {}, firstRunCompleted: true};
  assert.equal(m.merge(old, catalog).hintDismissed, true);
  const mid = {schema: m.SCHEMA, order: ['claude'], cards: {}, firstRunCompleted: false};
  assert.equal(m.merge(mid, catalog).hintDismissed, false);
  const kept = {schema: m.SCHEMA, order: ['claude'], cards: {}, firstRunCompleted: true, hintDismissed: false};
  assert.equal(m.merge(kept, catalog).hintDismissed, false);
  const done = m.reduce(fresh, {type: 'dismissHint'}, catalog);
  assert.equal(done.layout.hintDismissed, true);
  assert.equal(done.undoable, false);
  assert.equal(m.reduce(done.layout, {type: 'dismissHint'}, catalog).layout, done.layout);
  const reset = m.reduce(done.layout, {type: 'resetAll', detected: {claude: true}}, catalog);
  assert.equal(reset.layout.hintDismissed, true);
}
// Total Spend choice persists in layout.json, not shell.json (TotalSpendSetting).
{
  const fresh = m.defaults(catalog, null);
  assert.deepEqual(norm(fresh.spend), {period: 'today', metric: 'cost'});
  const old = {schema: m.SCHEMA, order: ['claude'], cards: {}, firstRunCompleted: true};
  assert.deepEqual(norm(m.merge(old, catalog).spend), {period: 'today', metric: 'cost'});
  const bad = {schema: m.SCHEMA, order: ['claude'], cards: {}, spend: {period: 'nope', metric: 'nope'}, firstRunCompleted: true};
  assert.deepEqual(norm(m.merge(bad, catalog).spend), {period: 'today', metric: 'cost'});
  const kept = {schema: m.SCHEMA, order: ['claude'], cards: {}, spend: {period: 'last30', metric: 'tokens'}, firstRunCompleted: true};
  assert.deepEqual(norm(m.merge(kept, catalog).spend), {period: 'last30', metric: 'tokens'});
  const picked = m.reduce(fresh, {type: 'setSpend', period: 'last30'}, catalog);
  assert.deepEqual(norm(picked.layout.spend), {period: 'last30', metric: 'cost'});
  assert.equal(picked.undoable, false);
  const both = m.reduce(fresh, {type: 'setSpend', period: 'yesterday', metric: 'tokens'}, catalog);
  assert.deepEqual(norm(both.layout.spend), {period: 'yesterday', metric: 'tokens'});
  const invalid = m.reduce(fresh, {type: 'setSpend', period: 'nope', metric: 'nope'}, catalog);
  assert.equal(invalid.layout, fresh);
  const same = m.reduce(fresh, {type: 'setSpend', period: 'today', metric: 'cost'}, catalog);
  assert.equal(same.layout, fresh);
  const changed = m.reduce(fresh, {type: 'setSpend', period: 'last30', metric: 'tokens'}, catalog).layout;
  const resetKept = m.reduce(changed, {type: 'resetAll', detected: {claude: true}}, catalog);
  assert.deepEqual(norm(resetKept.layout.spend), {period: 'last30', metric: 'tokens'});
  const providerReset = m.reduce(changed, {type: 'resetProvider', cardId: 'claude'}, catalog);
  assert.deepEqual(norm(providerReset.layout.spend), {period: 'last30', metric: 'tokens'});
}
console.log('Layout tests passed');
