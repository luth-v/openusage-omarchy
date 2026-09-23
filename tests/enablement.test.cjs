const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const layout = vm.createContext({});
vm.runInContext(fs.readFileSync('js/Layout.js', 'utf8'), layout);
const catalog = JSON.parse(fs.readFileSync('catalog.json', 'utf8'));
const cases = JSON.parse(fs.readFileSync('tests/fixtures/enablement.json', 'utf8'));
for (const sample of cases) {
  let state = layout.merge(sample.layout, catalog, sample.detected);
  if (!state.firstRunCompleted)
    state = layout.firstRunComplete(state, catalog, sample.detected);
  const enabled = state.order.filter((id) => state.cards[id].enabled).sort();
  assert.deepEqual(JSON.parse(JSON.stringify(enabled)), sample.enabled.slice().sort());
}
console.log('Enablement tests passed');
