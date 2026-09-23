const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const m = vm.createContext({});
vm.runInContext(fs.readFileSync('js/Notices.js', 'utf8'), m);
const norm = (x) => JSON.parse(JSON.stringify(x));
// Timeouts from LayoutStore.swift pin/share/customize notices.
assert.equal(m.timeoutFor('pin'), 3000);
assert.equal(m.timeoutFor('share'), 2500);
assert.equal(m.timeoutFor('customize'), 2500);
assert.equal(m.messageFor('starDenied'), 'Up to 2 stars per provider');
assert.equal(m.messageFor('starred'), 'Starred for menu bar');
assert.equal(m.messageFor('unstarred'), 'Removed from menu bar');
assert.equal(m.messageFor('copied'), 'Copied to clipboard');
assert.equal(m.toneFor('starDenied'), 'notice');
assert.equal(m.toneFor('starred'), 'positive');
console.log('Notices tests passed');
