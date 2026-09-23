const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const m = vm.createContext({});
vm.runInContext(fs.readFileSync('js/Keys.js', 'utf8'), m);
const norm = (x) => JSON.parse(JSON.stringify(x));
// Panel map: z undo, r refresh, , settings; Return and Esc move (dashboard.md).
assert.equal(m.panelAction('z', {screen: 'dashboard'}), 'undo');
assert.equal(m.panelAction('Z', {screen: 'dashboard'}), 'undo');
assert.equal(m.panelAction('r', {screen: 'settings'}), 'refresh');
assert.equal(m.panelAction(',', {screen: 'dashboard'}), 'settings');
assert.equal(m.panelAction('z', {screen: 'dashboard', hasFocus: true}), null);
assert.equal(m.panelAction('r', {screen: 'dashboard', hasFocus: true}), null);
assert.equal(m.panelAction(',', {screen: 'dashboard', hasFocus: true}), null);
assert.equal(m.panelAction('Return', {screen: 'dashboard'}), 'openCustomize');
assert.equal(m.panelAction('Return', {screen: 'customizeDetail'}), 'back');
assert.equal(m.panelAction('Return', {screen: 'settings'}), 'back');
assert.equal(m.panelAction('Escape', {screen: 'dashboard'}), 'close');
assert.equal(m.panelAction('Escape', {screen: 'customizeDetail'}), 'back');
assert.equal(m.panelAction('Escape', {screen: 'dashboard', hasFocus: true}), 'close');
assert.equal(m.panelAction('x', {screen: 'dashboard'}), null);
assert.deepEqual(norm(m.CODE), ['up', 'up', 'down', 'down', 'left', 'right', 'left', 'right', 'b', 'a']);
// Cases from SecretCodeMatcherTests.swift.
{
  const matcher = m.createMatcher();
  for (const token of m.CODE.slice(0, -1))
    assert.equal(matcher.accept(token), false);
  assert.equal(matcher.accept(m.CODE[m.CODE.length - 1]), true);
}
for (const prefix of [['up', 'up'], ['up', 'up', 'down', 'left']]) {
  const matcher = m.createMatcher();
  let matched = false;
  for (const token of prefix.concat(m.CODE))
    matched = matcher.accept(token);
  assert.equal(matched, true);
}
{
  const matcher = m.createMatcher();
  matcher.accept('up');
  matcher.accept('up');
  matcher.reset();
  let matched = false;
  for (const token of m.CODE.slice(2))
    matched = matcher.accept(token) || matched;
  assert.equal(matched, false);
  for (const token of m.CODE)
    matched = matcher.accept(token);
  assert.equal(matched, true);
}
{
  const matcher = m.createMatcher();
  for (const token of m.CODE)
    matcher.accept(token);
  let matched = false;
  for (const token of m.CODE)
    matched = matcher.accept(token);
  assert.equal(matched, true);
}
console.log('Keys tests passed');
