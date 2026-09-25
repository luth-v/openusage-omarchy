const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const m = vm.createContext({});
vm.runInContext(fs.readFileSync('js/Format.js', 'utf8'), m);
vm.runInContext(fs.readFileSync('js/Strip.js', 'utf8'), m);
vm.runInContext(fs.readFileSync('js/Layout.js', 'utf8'), m);
const norm = (x) => JSON.parse(JSON.stringify(x));
const catalog = JSON.parse(fs.readFileSync('catalog.json', 'utf8'));
const fmt = {number: m.number, stringFor: m.stringFor};
assert.equal(m.MAX_BARS, 4);
// MenuBarContentTests.testTrayLabelsShortenLongTimeWindows
assert.equal(m.trayLabel('Today'), 'T');
assert.equal(m.trayLabel('Yesterday'), 'Y');
assert.equal(m.trayLabel('Last 30 Days'), 'M');
assert.equal(m.trayLabel('Session'), 'Session');
// ResetDisplayTests wiring pin: both reset rows use the "resets" suffix.
assert.equal(m.traySuffixFor('claude', 'rateLimitResets'), 'resets');
assert.equal(m.traySuffixFor('codex', 'rateLimitResets'), 'resets');
assert.equal(m.traySuffixFor('claude', 'session'), null);
const progress = (used, limit, kind = 'percent') => ({type: 'progress', used, limit, format: {kind}});
const values = (items) => ({type: 'values', values: items});
const stateFor = (metrics) => ({schema: 'openusage-omarchy.state.v1', cards: [{cardId: 'claude', family: 'claude', metrics}]});
const layoutFor = (stars) => {
  const base = m.defaults(catalog, {claude: true});
  base.cards.claude.stars = stars;
  return base;
};
// MenuBarContentTests.testBoundedTrayValuesStayUnitAware
assert.equal(m.valueFor('claude', 'session', progress(67, 100), 'Used', fmt), '67%');
assert.equal(m.valueFor('claude', 'extra', progress(12000, 18000, 'dollars'), 'Used', fmt), '$12K');
assert.equal(m.valueFor('claude', 'extra', progress(412, 500, 'count'), 'Used', fmt), '412');
assert.equal(m.valueFor('codex', 'rateLimitResets', values([{number: 2, kind: 'count', label: 'available'}]), 'Used', fmt), '2 resets');
// Display Left flips the shown share (WidgetDisplayMode).
assert.equal(m.valueFor('claude', 'session', progress(67, 100), 'Left', fmt), '33%');
// Empty-data rules: missing metrics skip, empty providers drop (menu-bar.md).
{
  const layout = layoutFor(['session', 'weekly']);
  const state = stateFor({session: progress(41, 100)});
  const content = m.build(layout, catalog, state, 'Used', fmt);
  assert.equal(content.isEmpty, false);
  assert.deepEqual(norm(content.groups.map((g) => g.cardId)), ['claude']);
  assert.deepEqual(norm(content.groups[0].metrics.map((x) => x.id)), ['claude.session']);
  assert.equal(content.groups[0].metrics[0].value, '41%');
  assert.deepEqual(norm(content.bars.map((x) => x.id)), ['claude.session']);
  assert.equal(content.accessibilityText, 'Claude Session 41%');
}
{
  const layout = layoutFor(['session']);
  const content = m.build(layout, catalog, stateFor({}), 'Used', fmt);
  assert.equal(content.isEmpty, true);
  assert.equal(content.bars.length, 0);
}
// MenuBarContentTests.testBarsIncludeBoundedMetricsAndDropUnbounded
{
  const layout = layoutFor(['session', 'today']);
  layout.cards.claude.stars = ['session', 'today'];
  const state = stateFor({session: progress(40, 100), today: values([{number: 42, kind: 'dollars'}])});
  const content = m.build(layout, catalog, state, 'Used', fmt);
  assert.equal(content.groups[0].metrics.length, 2);
  assert.deepEqual(norm(content.bars.map((x) => x.id)), ['claude.session']);
}
// MenuBarContentTests.testBarsCappedToFourInOrder
{
  const base = m.defaults(catalog, {claude: true, codex: true, cursor: true});
  const state = {schema: 'openusage-omarchy.state.v1', cards: [
    {cardId: 'claude', family: 'claude', metrics: {session: progress(10, 100), weekly: progress(20, 100)}},
    {cardId: 'codex', family: 'codex', metrics: {session: progress(30, 100), weekly: progress(40, 100)}},
    {cardId: 'cursor', family: 'cursor', metrics: {auto: progress(50, 100), api: progress(60, 100)}},
  ]};
  const content = m.build(base, catalog, state, 'Used', fmt);
  assert.equal(content.bars.length, 4);
  assert.deepEqual(norm(content.bars.map((x) => x.id)), ['claude.session', 'claude.weekly', 'codex.session', 'codex.weekly']);
}
// Stars follow Customize order: Always Visible first, then On Demand.
{
  const layout = layoutFor(['today', 'session']);
  const state = stateFor({session: progress(10, 100), today: values([{number: 3, kind: 'dollars'}])});
  const content = m.build(layout, catalog, state, 'Used', fmt);
  assert.deepEqual(norm(content.groups[0].metrics.map((x) => x.id)), ['claude.session', 'claude.today']);
}
// MenuBarBarsTests: near-full quantization and minimum tail.
assert.equal(m.fill(100, 0).fillW, 0);
assert.equal(m.fill(100, -0.5).fillW, 0);
{
  const full = m.fill(100, 1);
  assert.equal(full.fillW, 100);
  assert.equal(full.remainderW, 0);
  assert.equal(full.dividerX, null);
}
{
  const near = m.fill(100, 0.97);
  assert.ok(near.fillW < 100);
  assert.ok(near.remainderW >= 20);
}
assert.ok(Math.abs(m.visualFraction(0.5) - 0.5) < 0.0001);
assert.ok(Math.abs(m.visualFraction(0.97) - 0.85) < 0.0001);
assert.ok(Math.abs(m.visualFraction(1) - 1) < 0.0001);
{
  const geo = m.barsLayout(18, 2);
  assert.equal(geo.trackW, 18 - 2 * geo.pad);
  assert.ok(geo.trackH >= 1 && geo.rx >= 1);
}
// ADR 0006: several enabled Accounts in a family get a short prefix per Star.
{
  let layout = m.defaults(catalog, {claude: true});
  layout = m.ensureCards(layout, catalog, ['claude:aaaa1111', 'claude:bbbb2222']);
  for (const id of ['claude', 'claude:aaaa1111', 'claude:bbbb2222'])
    layout.cards[id].stars = ['session'];
  const card = (cardId, label, used) => ({cardId, family: 'claude', label, metrics: {session: progress(used, 100)}});
  const state = {schema: 'openusage-omarchy.state.v1', cards: [
    card('claude', 'Claude — Default', 10), card('claude:aaaa1111', 'Claude — work', 42),
    card('claude:bbbb2222', 'Claude — Wife', 5)]};
  const content = m.build(layout, catalog, state, 'Used', fmt);
  assert.deepEqual(norm(content.groups.map((g) => g.metrics[0].value)), ['D 10%', 'Wo 42%', 'Wi 5%']);
  assert.deepEqual(norm(content.groups.map((g) => g.family)), ['claude', 'claude', 'claude']);
  assert.ok(content.accessibilityText.startsWith('Claude — Default Session D 10%'));
  // One enabled Account: output unchanged, no prefix.
  layout.cards['claude:aaaa1111'].enabled = false;
  layout.cards['claude:bbbb2222'].enabled = false;
  const single = m.build(layout, catalog, state, 'Used', fmt);
  assert.deepEqual(norm(single.groups.map((g) => g.metrics[0].value)), ['10%']);
  assert.equal(single.accessibilityText, 'Claude Session 10%');
  assert.deepEqual(norm(m.accountPrefixes({a: 'work', b: 'Default'})), {a: 'W', b: 'D'});
  assert.equal(m.accountLabel('Claude'), '');
}
console.log('Strip tests passed');
// Bar text: one line per group, shared "%" kept once, Account prefix in front.
assert.equal(m.inlineText('W', ['74%', '45%']), 'W 74·45%');
assert.equal(m.inlineText('', ['74%', '45%']), '74·45%');
assert.equal(m.inlineText('', ['27%']), '27%');
assert.equal(m.inlineText('', ['40%', '$42']), '40%·$42');
