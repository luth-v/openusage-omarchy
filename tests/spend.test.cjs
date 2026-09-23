const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const m = vm.createContext({});
vm.runInContext(fs.readFileSync('js/Spend.js', 'utf8'), m);
const norm = (x) => JSON.parse(JSON.stringify(x));
// Cases from TotalSpendAggregatorTests.swift.
const claude = {id: 'claude', displayName: 'Claude'};
const codex = {id: 'codex', displayName: 'Codex'};
const cursor = {id: 'cursor', displayName: 'Cursor'};
const line = (dollars, tokens = 1000000, estimated = false) => {
  const items = [];
  if (dollars !== null && dollars !== undefined)
    items.push({number: dollars, kind: 'dollars', estimated});
  if (tokens !== null && tokens !== undefined)
    items.push({number: tokens, kind: 'count', label: 'tokens'});
  return {type: 'values', values: items};
};
const card = (id, metrics) => ({cardId: id, family: id, metrics});
// TotalSpendAggregatorTests.testSumsDollarsAndTokensAcrossProviders
{
  const total = m.totalFor('today', [card('claude', {today: line(2.5, 100000, true)}), card('cursor', {today: line(7.25, 500000)})], [claude, codex, cursor]);
  assert.deepEqual(norm(total.slices.map((s) => s.provider.id).sort()), ['claude', 'cursor']);
  assert.ok(Math.abs(total.totalUSD - 9.75) < 0.0001);
  assert.ok(Math.abs(total.totalTokens - 600000) < 0.0001);
  assert.deepEqual(norm(m.projection(total, 'cost').slices.map((s) => s.provider.id)), ['cursor', 'claude']);
}
// TotalSpendAggregatorTests.testProviderWithoutPeriodLineIsExcludedNotZero
{
  const total = m.totalFor('today', [card('claude', {today: line(1)}), card('codex', {yesterday: line(3)})], [claude, codex]);
  assert.deepEqual(norm(total.slices.map((s) => s.provider.id)), ['claude']);
}
// TotalSpendAggregatorTests.testTokensOnlyLineContributesTokensButNotSpendOrCostPerMtok
{
  const total = m.totalFor('today', [card('claude', {today: line(null, 500000)})], [claude]);
  assert.equal(total.isEmpty, false);
  assert.equal(m.projection(total, 'cost').isEmpty, true);
  assert.equal(m.projection(total, 'costPerMtok').isEmpty, true);
  assert.equal(m.projection(total, 'tokens').centerValue, 500000);
}
// TotalSpendAggregatorTests.testDollarsOnlyLineContributesSpendButNotCostPerMtok
{
  const total = m.totalFor('today', [card('claude', {today: line(4, null)})], [claude]);
  assert.equal(m.projection(total, 'cost').centerValue, 4);
  assert.equal(m.projection(total, 'tokens').isEmpty, true);
  assert.equal(m.projection(total, 'costPerMtok').isEmpty, true);
}
// TotalSpendAggregatorTests.testTotalIsEstimatedWhenAnySliceIsEstimated
{
  const total = m.totalFor('today', [card('claude', {today: line(2, 1000000, true)}), card('cursor', {today: line(4)})], [claude, cursor]);
  assert.equal(total.isEstimated, true);
  assert.equal(m.projection(total, 'cost').isEstimated, true);
  assert.equal(m.projection(total, 'costPerMtok').isEstimated, true);
  assert.equal(m.projection(total, 'tokens').isEstimated, false);
}
// TotalSpendAggregatorTests.testCostPerMtokRanksByRateAndBlendsTotals
{
  const total = m.totalFor('today', [card('claude', {today: line(10, 1000000)}), card('cursor', {today: line(30, 1000000)})], [claude, cursor]);
  const rates = m.projection(total, 'costPerMtok');
  assert.deepEqual(norm(rates.slices.map((s) => s.provider.id)), ['cursor', 'claude']);
  assert.ok(Math.abs(rates.centerValue - 20) < 0.0001);
}
// TotalSpendAggregatorTests.testCostPerMtokExcludesIncompleteProvidersFromBlend
{
  const total = m.totalFor('today', [card('claude', {today: line(10, 1000000)}), card('codex', {today: line(null, 9000000)}), card('cursor', {today: line(5, null)})], [claude, codex, cursor]);
  const rates = m.projection(total, 'costPerMtok');
  assert.deepEqual(norm(rates.slices.map((s) => s.provider.id)), ['claude']);
  assert.ok(Math.abs(rates.centerValue - 10) < 0.0001);
}
// TotalSpendAggregatorTests.testTokensProjectionRanksByTokenCount
{
  const total = m.totalFor('today', [card('claude', {today: line(50, 100000)}), card('cursor', {today: line(1, 900000)})], [claude, cursor]);
  assert.deepEqual(norm(m.projection(total, 'tokens').slices.map((s) => s.provider.id)), ['cursor', 'claude']);
}
// TotalSpendAggregatorTests.testEmptyProjectionWhenNothingQualifies
{
  const total = m.totalFor('today', [], [claude]);
  assert.equal(total.isEmpty, true);
  assert.equal(m.projection(total, 'cost').isEmpty, true);
}
// Non-spend families never mix in (dashboard.md Total Spend).
{
  const total = m.totalFor('today', [card('openrouter', {today: line(99)})], [{id: 'openrouter', displayName: 'OpenRouter', spend: false}]);
  assert.equal(total.isEmpty, true);
}
assert.equal(m.emptyMessageFor('cost'), 'No cost data for this period');
assert.equal(m.PERIODS.last30.short, '30 Days');
// TotalSpendRingContent.arcs: ranked fractions, minimum sliver, ring closes.
{
  const arcs = m.donutArcs([
    {provider: claude, displayAmount: 97},
    {provider: codex, displayAmount: 1},
    {provider: cursor, displayAmount: 2},
  ]);
  assert.equal(arcs.length, 3);
  assert.ok(Math.abs(arcs[2].end - 1) < 0.000001);
  assert.ok(arcs[1].end - arcs[1].start > 0.01);
  assert.deepEqual(norm(m.donutArcs([])), []);
  assert.deepEqual(norm(m.donutArcs([{provider: claude, displayAmount: 0}])), []);
}
// UsageSparkline.barHeight: proportional with a floor, stub for true zero.
{
  const bars = m.trendBars([
    {label: 'a', value: 0, readout: '0'},
    {label: 'b', value: 5, readout: '5'},
    {label: 'c', value: 100, readout: '100'},
  ]);
  assert.equal(bars[0].fraction, 0);
  assert.equal(bars[1].fraction, 0.18);
  assert.equal(bars[2].fraction, 1);
}
console.log('Spend tests passed');
