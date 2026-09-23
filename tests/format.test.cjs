const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const m = vm.createContext({});
vm.runInContext(fs.readFileSync('js/Format.js', 'utf8'), m);
const norm = (x) => JSON.parse(JSON.stringify(x));
// Cases from MetricFormatterTests.swift and ResetDisplayTests.swift.
// MetricFormatterTests.testDollarsAbbreviateAboveAThousandPerStyle
assert.equal(m.number(42, 'dollars', 'tray'), '$42');
assert.equal(m.number(129.81, 'dollars', 'tray'), '$130');
assert.equal(m.number(2059.07, 'dollars', 'tray'), '$2.1K');
assert.equal(m.number(40.76, 'dollars', 'row'), '$40.76');
assert.equal(m.number(2059.07, 'dollars', 'row'), '$2.1K');
assert.equal(m.number(2059.07, 'dollars', 'full'), '$2,059.07');
// MetricFormatterTests.testCountsAbbreviateInTrayAndRowButKeepEveryDigitInFull
assert.equal(m.number(56904995, 'count', 'tray'), '56.9M');
assert.equal(m.number(56904995, 'count', 'row'), '56.9M');
assert.equal(m.number(56904995, 'count', 'full'), '56,904,995');
assert.equal(m.number(1485201513, 'count', 'row'), '1.5B');
assert.equal(m.number(820.6, 'count', 'row'), '820.6');
// MetricFormatterTests.testPercentRoundsToWholeInEveryStyle
assert.equal(m.number(95, 'percent', 'full'), '95%');
assert.equal(m.number(95.4, 'percent', 'tray'), '95%');
// MetricFormatterTests.testPercentClampsOutOfRangeSamples
assert.equal(m.number(-5, 'percent', 'full'), '0%');
assert.equal(m.number(130, 'percent', 'full'), '100%');
assert.equal(m.number(100.6, 'percent', 'row'), '100%');
// MetricFormatterTests.testValueStringAppendsUnitLabelWhenPresent
assert.equal(m.stringFor({number: 772, kind: 'count', label: 'credits'}, 'row'), '772 credits');
assert.equal(m.stringFor({number: 56904995, kind: 'count'}, 'row'), '56.9M');
assert.equal(m.stringFor({number: 56904995, kind: 'count'}, 'full'), '56,904,995');
// MetricFormatterTests.testCostPerMtokAppendsUnitToDollarFormatting
assert.equal(m.costPerMtok(32, 'tray'), '$32/MTok');
assert.equal(m.costPerMtok(32.1, 'row'), '$32.10/MTok');
assert.equal(m.costPerMtok(2059.07, 'tray'), '$2.1K/MTok');
assert.equal(m.costPerMtok(2059.07, 'full'), '$2,059.07/MTok');
// MetricFormatterTests.testTotalSpendRingCenterSplitsValueAndUnit
assert.deepEqual(norm(m.totalSpendRingCenter(533, 'cost')), {primary: '$533', unit: 'dollars'});
assert.deepEqual(norm(m.totalSpendRingCenter(2059.07, 'cost')), {primary: '$2.1K', unit: 'dollars'});
assert.deepEqual(norm(m.totalSpendRingCenter(12400000, 'tokens')), {primary: '12.4', unit: 'million'});
assert.deepEqual(norm(m.totalSpendRingCenter(1500000000, 'tokens')), {primary: '1.5', unit: 'billion'});
assert.deepEqual(norm(m.totalSpendRingCenter(820.6, 'tokens')), {primary: '820.6', unit: 'tokens'});
assert.deepEqual(norm(m.totalSpendRingCenter(1.37, 'costPerMtok')), {primary: '$1.37', unit: 'MTok'});
// ResetDisplayTests.testCompactDurationAlwaysShowsHoursAtDayScale
assert.equal(m.compactDuration(4 * 86400 + 52 * 60), '4d 0h');
assert.equal(m.compactDuration(7 * 86400), '7d 0h');
assert.equal(m.compactDuration(9 * 86400 + 21 * 3600), '9d 21h');
assert.equal(m.compactDuration(5 * 3600), '5h');
assert.equal(m.compactDuration(52 * 60), '52m');
assert.equal(m.compactDuration(0), null);
// ResetDisplayTests.testDeadlineLabelSharesFormatAcrossPrefixesAndModes
const noon = new Date(2024, 5, 1, 12, 0, 0);
assert.equal(m.deadlineLabel('Runs out', new Date(noon.getTime() + (2 * 3600 + 360) * 1000), 'relative', noon), 'Runs out in 2h 6m');
assert.equal(m.deadlineLabel('Runs out', new Date(noon.getTime() + 60 * 1000), 'relative', noon), 'Runs out soon');
assert.equal(m.deadlineLabel('Runs out', new Date(noon.getTime() - 1000), 'absolute', noon), 'Runs out soon');
assert.ok(m.deadlineLabel('Runs out', new Date(noon.getTime() + 2 * 3600 * 1000), 'absolute', noon).startsWith('Runs out today at '));
assert.equal(m.resetAbsoluteLabel(new Date(noon.getTime() - 1000), noon), 'Resets soon');
// Time format honors 12h and 24h (TimeFormatSetting.swift).
const afternoon = new Date(2024, 5, 1, 17, 30, 0);
assert.equal(m.shortTime(afternoon, '12h'), '5:30 PM');
assert.equal(m.shortTime(afternoon, '24h'), '17:30');
assert.equal(m.whenLabel(new Date(noon.getTime() + 2 * 3600 * 1000), 'Countdown', noon), '2h');
console.log('Format tests passed');
