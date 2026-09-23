const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const m = vm.createContext({});
vm.runInContext(fs.readFileSync('js/Settings.js', 'utf8'), m);
const norm = (x) => JSON.parse(JSON.stringify(x));
// Option labels match the upstream Setting enums.
assert.deepEqual(norm(m.STYLE_OPTIONS), [{value: 'Text', label: 'Text'}, {value: 'Bars', label: 'Bars'}]);
assert.deepEqual(norm(m.DENSITY_OPTIONS), [{value: 'Default', label: 'Default'}, {value: 'Compact', label: 'Compact'}]);
assert.deepEqual(norm(m.TIME_FORMAT_OPTIONS), [{value: 'Auto', label: 'Auto'}, {value: '12h', label: '12-hour'}, {value: '24h', label: '24-hour'}]);
assert.deepEqual(norm(m.DISPLAY_OPTIONS), [{value: 'Used', label: 'Used'}, {value: 'Left', label: 'Left'}]);
assert.deepEqual(norm(m.RESET_OPTIONS), [{value: 'Countdown', label: 'Countdown'}, {value: 'Exact Time', label: 'Exact Time'}]);
assert.deepEqual(norm(m.LOG_LEVEL_OPTIONS.map((o) => o.label)), ['Error', 'Warning', 'Info', 'Debug']);
// Notification rows match PaceMilestone labels and tooltips.
assert.deepEqual(norm(m.NOTIFICATIONS), [
  {key: 'notifyAlmostOut', label: 'Almost Out', tip: 'Alert when a limit drops below 10% remaining.'},
  {key: 'notifyCuttingClose', label: 'Cutting It Close', tip: 'Alert when a limit is projected to finish with little left.'},
  {key: 'notifyWillRunOut', label: 'Will Run Out', tip: 'Alert when a limit is projected to finish before it resets.'}
]);
// Reset copy matches SettingsScreen minus the omitted iCloud clause.
assert.equal(m.RESET_SETTINGS_TITLE, 'Reset All Settings?');
assert.equal(m.RESET_SETTINGS_MESSAGE, 'Restores every setting and customization to its default and turns providers back on for the tools you have installed. This cannot be undone.');
assert.equal(m.UPDATE_WITH_OMARCHY_NOTE, 'Update this plugin when Omarchy updates (git installs only).');
// Shortcut format/parse round-trips with canonical mod order.
assert.equal(m.formatShortcut(['SHIFT', 'SUPER'], 'o'), 'Super+Shift+O');
assert.equal(m.formatShortcut([], 'F5'), 'F5');
assert.equal(m.formatShortcut(['SUPER'], ''), '');
assert.deepEqual(norm(m.parseShortcut('Super+Shift+O')), {mods: ['SUPER', 'SHIFT'], key: 'O'});
assert.deepEqual(norm(m.parseShortcut('F5')), {mods: [], key: 'F5'});
assert.deepEqual(norm(m.parseShortcut('ctrl+alt+Delete')), {mods: ['CTRL', 'ALT'], key: 'Delete'});
assert.equal(m.parseShortcut(''), null);
assert.equal(m.parseShortcut('Super+Nope+O'), null);
assert.equal(m.parseShortcut('Super'), null);
assert.deepEqual(norm(m.shortcutPayload(['SUPER'], 'o')), {mods: ['SUPER'], key: 'O'});
assert.equal(m.shortcutPayload([], ''), null);
assert.equal(m.shortcutPayload(['SUPER'], ','), null);
assert.equal(m.shortcutPayload(['SUPER'], '$'), null);
assert.deepEqual(norm(m.shortcutPayload(['SUPER'], 'Delete')),
  {mods: ['SUPER'], key: 'DELETE'});
// Fallback picker titles match CodexPricingSection states.
{
  const options = [{id: 'gpt-5', title: 'GPT 5'}];
  assert.equal(m.fallbackTitle(options, ''), 'None');
  assert.equal(m.fallbackTitle(options, 'gpt-5'), 'GPT 5');
  assert.equal(m.fallbackTitle(options, 'gpt-9'), 'Unavailable Model');
  assert.equal(m.fallbackUnavailable(options, ''), false);
  assert.equal(m.fallbackUnavailable(options, 'gpt-5'), false);
  assert.equal(m.fallbackUnavailable(options, 'gpt-9'), true);
}
console.log('Settings tests passed');
