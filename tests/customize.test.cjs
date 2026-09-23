const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const m = vm.createContext({});
vm.runInContext(fs.readFileSync('js/Customize.js', 'utf8'), m);
const norm = (x) => JSON.parse(JSON.stringify(x));
const catalog = JSON.parse(fs.readFileSync('catalog.json', 'utf8'));
const lm = vm.createContext({});
vm.runInContext(fs.readFileSync('js/Layout.js', 'utf8'), lm);
// Reset All copy matches PopoverTopBar.swift exactly.
assert.equal(m.RESET_ALL_TITLE, 'Reset All Customization?');
assert.equal(m.RESET_ALL_MESSAGE, 'Turns providers back on for the tools you have installed and resets every provider\'s metrics and order. Are you sure?');
assert.equal(m.RESET_ALL_CONFIRM, 'Reset All');
assert.equal(m.EMPTY_ZONE_TEXT, 'Drag metrics here');
// Provider rows: every card in order, catalog metric total (metricCount).
{
  const layout = lm.defaults(catalog, null);
  const rows = m.providerRows(layout, catalog, null);
  assert.equal(rows.length, 11);
  assert.deepEqual(norm(rows[0]), {cardId: 'claude', family: 'claude', displayName: 'Claude', enabled: true, metricCount: 10});
  assert.equal(rows[4].cardId, 'copilot');
  assert.equal(rows[4].enabled, false);
  assert.equal(rows[4].metricCount, 6);
  const multi = lm.ensureCards(layout, catalog, ['claude:abc']);
  const grown = m.providerRows(multi, catalog, {cards: [{cardId: 'claude:abc', label: 'Claude Work'}]});
  assert.equal(grown.length, 12);
  assert.equal(grown[1].cardId, 'claude:abc');
  assert.equal(grown[1].displayName, 'Claude Work');
  assert.equal(grown[1].metricCount, 10);
  assert.deepEqual(norm(m.providerRows(null, catalog, null)), []);
}
// Detail: every metric in order, split by section, flags set.
{
  const layout = lm.defaults(catalog, null);
  const detail = m.detailFor(layout, catalog, 'claude');
  assert.equal(detail.family, 'claude');
  assert.equal(detail.displayName, 'Claude');
  assert.equal(detail.enabled, true);
  assert.ok(detail.always.length > 0 && detail.onDemand.length > 0);
  assert.equal(detail.always.length + detail.onDemand.length, 10);
  const session = detail.always.find((r) => r.metricId === 'session');
  assert.deepEqual(norm(session), {metricId: 'session', title: 'Session', starrable: true, starred: true, enabled: true, always: true});
  const sonnet = detail.onDemand.find((r) => r.metricId === 'sonnet');
  assert.equal(sonnet.enabled, false);
  assert.equal(m.metricTitle(catalog, 'claude', 'extra'), 'Extra usage spent');
  assert.equal(m.metricTitle(catalog, 'claude', 'nope'), 'nope');
  assert.equal(m.detailFor(layout, catalog, 'nope'), null);
  assert.equal(m.detailFor({cards: {}}, catalog, 'claude'), null);
}
// Star cap preview matches the reducer (maxPinsPerProvider).
{
  assert.equal(m.starDeniedPreview(['session', 'weekly'], 'fable', true), true);
  assert.equal(m.starDeniedPreview(['session'], 'fable', true), false);
  assert.equal(m.starDeniedPreview(['session', 'weekly'], 'session', true), false);
  assert.equal(m.starDeniedPreview(['session', 'weekly'], 'trend', false), false);
}
// Key presence hints never carry values.
assert.equal(m.keyStatusText('keyring'), 'Saved in keyring');
assert.equal(m.keyStatusText('file'), 'Saved in file');
assert.equal(m.keyStatusText('env'), 'From your environment');
assert.equal(m.keyStatusText('none'), '');
assert.equal(m.keyStatusText(undefined), '');
assert.equal(m.keyStatusSet('env'), true);
assert.equal(m.keyStatusSet('none'), false);
console.log('Customize tests passed');
