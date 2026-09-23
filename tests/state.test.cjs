const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const m = vm.createContext({});
vm.runInContext(fs.readFileSync('js/State.js', 'utf8'), m);
const norm = (x) => JSON.parse(JSON.stringify(x));
assert.equal(m.SCHEMA, 'openusage-omarchy.state.v1');
const good = {schema: 'openusage-omarchy.state.v1', cards: [
  {cardId: 'cursor', family: 'cursor', label: 'Cursor', detected: true, metrics: {auto: {type: 'progress', used: 40, limit: 100}}},
  {cardId: 'grok', family: 'grok', label: 'Grok', detected: false, metrics: {}},
  {cardId: 'claude:abc', family: 'claude', label: 'Claude Work', detected: true, metrics: {}},
]};
assert.equal(m.parseState(JSON.stringify(good)).ok, true);
const at = Date.parse('2026-09-23T14:00:00Z');
assert.equal(m.freshDetected(null, at), null);
assert.equal(m.freshDetected({...good, generatedAt: '2026-09-23T13:59:59Z'}, at), null);
assert.equal(m.freshDetected({...good}, at), null);
assert.deepEqual(norm(m.freshDetected({...good, generatedAt: '2026-09-23T14:00:01+00:00'}, at)), {cursor: true, grok: false, claude: true});
assert.equal(m.parseState('{bad').ok, false);
assert.equal(m.parseState(JSON.stringify({schema: 'x', cards: []})).ok, false);
assert.equal(m.parseState(JSON.stringify({schema: 'openusage-omarchy.state.v1'})).ok, false);
assert.deepEqual(norm(m.cardIds(m.parseState(JSON.stringify(good)).state)), ['cursor', 'grok', 'claude:abc']);
assert.deepEqual(norm(m.detectedMap(m.parseState(JSON.stringify(good)).state)), {cursor: true, grok: false, claude: true});
assert.equal(m.cardById(m.parseState(JSON.stringify(good)).state, 'grok').family, 'grok');
assert.equal(m.cardById(null, 'grok'), null);
console.log('State tests passed');
