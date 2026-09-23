const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const m = vm.createContext({});
vm.runInContext(fs.readFileSync('js/Drag.js', 'utf8'), m);
const rows = [
  {id: 'a', top: 0, bottom: 30},
  {id: 'b', top: 30, bottom: 60},
  {id: 'c', top: 60, bottom: 90}
];
assert.equal(m.rowAt(rows, 10), 'a');
assert.equal(m.rowAt(rows, 30), 'b');
assert.equal(m.rowAt(rows, 89), 'c');
assert.equal(m.rowAt(rows, 90), null);
assert.equal(m.rowAt(rows, -1), null);
assert.equal(m.rowAt([], 10), null);
// Drop target skips the dragged row and clamps past the ends.
assert.equal(m.dropTarget(rows, 65, 'a'), 'c');
assert.equal(m.dropTarget(rows, 10, 'a'), 'b');
assert.equal(m.dropTarget(rows, -50, 'a'), 'b');
assert.equal(m.dropTarget(rows, 500, 'a'), 'c');
assert.equal(m.dropTarget([{id: 'a', top: 0, bottom: 30}], 10, 'a'), null);
assert.equal(m.dropTarget([], 10, 'a'), null);
// Empty-section zones locate the section id.
const zones = [{id: 'always', top: 0, bottom: 40}, {id: 'demand', top: 40, bottom: 80}];
assert.equal(m.zoneAt(zones, 10), 'always');
assert.equal(m.zoneAt(zones, 50), 'demand');
assert.equal(m.zoneAt(zones, 80), null);
console.log('Drag tests passed');
