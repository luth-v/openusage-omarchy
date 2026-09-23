const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const m = vm.createContext({});
vm.runInContext(fs.readFileSync('js/Pace.js', 'utf8'), m);
const norm = (x) => JSON.parse(JSON.stringify(x));
// Cases from PaceTests.swift and MeterSeverityTests.swift.
const NOW = 1700000000 * 1000;
const WEEK = 7 * 24 * 3600;
const resetsAt = (elapsed, period) => NOW + period * 1000 * (1 - elapsed);
const paced = (used, elapsed = 0.5, period = WEEK, extra = {}) => ({
  used, limit: 100, kind: 'percent', resetsAt: resetsAt(elapsed, period),
  periodMs: period * 1000, hasData: true, display: 'Used', now: NOW, ...extra,
});
// PaceTests.testZeroUsageHasNoPaceSignal
assert.equal(m.evaluate(0, 100, resetsAt(0.5, WEEK), WEEK, NOW), null);
// PaceTests.testEarlyInWindowStillProjectsPace
assert.equal(m.evaluate(5, 100, resetsAt(0.02, WEEK), WEEK, NOW).status, 'behind');
// PaceTests.testAheadOnTrackBehindThresholds (half elapsed, projected = used * 2)
for (const [used, status] of [[44, 'ahead'], [46, 'onTrack'], [50, 'onTrack'], [60, 'behind'], [100, 'behind'], [130, 'behind']])
  assert.equal(m.evaluate(used, 100, resetsAt(0.5, WEEK), WEEK, NOW).status, status, `used ${used}`);
// PaceTests.testEvaluateProjectsEndOfPeriodUsage
{
  const r = m.evaluate(30, 100, resetsAt(0.5, WEEK), WEEK, NOW);
  assert.equal(r.status, 'ahead');
  assert.ok(Math.abs(r.projectedUsage - 60) < 0.01);
}
// PaceTests.testWindowAlreadyResetReturnsNil
assert.equal(m.evaluate(50, 100, NOW - 60000, WEEK, NOW), null);
assert.equal(m.evaluate(50, 100, NOW, WEEK, NOW), null);
// PaceTests.testEvenPaceTickAppearsForAmberAndRed
{
  const amber = m.meterState(paced(46));
  assert.equal(amber.kind, 'closeToLimit');
  assert.ok(Math.abs(m.paceTick(paced(46), amber) - 0.5) < 0.001);
  const red = m.meterState(paced(60));
  assert.ok(Math.abs(m.paceTick(paced(60), red) - 0.5) < 0.001);
  const blue = m.meterState(paced(30));
  assert.equal(m.paceTick(paced(30), blue), null);
}
// PaceTests.testNoTickWithoutAResetWindow
assert.equal(m.paceTick({used: 12, limit: 20}, {kind: 'level', severity: 'normal'}), null);
// PaceTests.testTooltipShowsNumericProjectionAtReset
assert.equal(m.tooltipOf(m.meterState(paced(30))), '~40% left at reset');
assert.equal(m.tooltipOf(m.meterState(paced(46))), '~92% used at reset');
assert.equal(m.tooltipOf(m.meterState(paced(60))), '~20% over limit at reset');
// PaceTests.testZeroUsageFallsBackToPlainLevelBar
assert.deepEqual(norm(m.meterState(paced(0))), {kind: 'level', severity: 'normal'});
assert.equal(m.tooltipOf(m.meterState(paced(0))), null);
// PaceTests.testTooltipRedOverageFlooredToOnePercent
assert.equal(m.tooltipOf(m.meterState(paced(50.2))), '~1% over limit at reset');
// PaceTests.testSpentReadsLimitReached
assert.equal(m.meterState(paced(100)).kind, 'spent');
assert.equal(m.tooltipOf(m.meterState(paced(100))), 'Limit reached');
assert.equal(m.meterState({used: 99.999, limit: 100, kind: 'dollars', hasData: true}).kind, 'spent');
// PaceTests.testSpareCopyOnlyWhenAmber
assert.equal(m.meterState(paced(46)).spare, '~8% spare');
assert.equal(m.meterState(paced(30)).spare, undefined);
assert.equal(m.meterState(paced(60)).spare, undefined);
// PaceTests.testProjectionAtOrRoundedToLimitIsRedWithoutAnEta
for (const used of [49.8, 50]) {
  const st = m.meterState(paced(used));
  assert.equal(st.kind, 'runningOut', `used ${used}`);
  assert.equal(st.etaSec, null);
  assert.equal(m.tooltipOf(st), '~100% used at reset');
}
// PaceTests.testSmallButRealCushionStaysAmber
assert.equal(m.meterState(paced(49)).spare, '~2% spare');
// PaceTests.testRunningOutCarriesAnEtaBeforeReset
assert.notEqual(m.meterState(paced(60)).etaSec, null);
// PaceTests.testRunsOutOnlyWhenBehindAndBeforeReset
{
  const eta = m.secondsToRunOut(50, 100, resetsAt(0.33, WEEK), WEEK, NOW);
  assert.ok(Math.abs(eta - 0.33 * WEEK) < WEEK * 0.01);
  assert.equal(m.secondsToRunOut(30, 100, resetsAt(0.33, WEEK), WEEK, NOW), null);
}
// PaceTests.testPlentyRemainingSuppressesFalseRunOutFlame (5h window, 4 min in, 2 used)
{
  const session = 5 * 3600;
  assert.deepEqual(norm(m.meterState(paced(2, 240 / session, session))), {kind: 'level', severity: 'normal'});
}
// PaceTests.testOnePercentAtProjectionGateDoesNotBecomeRed
{
  const session = 5 * 3600;
  assert.deepEqual(norm(m.meterState(paced(1, 0.01, session))), {kind: 'level', severity: 'normal'});
}
// PaceTests.testRunOutFlameShowsOnceFivePercentUsedDespiteHighRemaining
{
  const session = 5 * 3600;
  assert.equal(m.meterState(paced(6, 240 / session, session)).kind, 'runningOut');
}
// PaceTests.testPaceProjectionWaitsUntilWindowHasMateriallyStarted
{
  const session = 5 * 3600;
  assert.equal(m.evaluate(1, 100, resetsAt(60 / session, session), session, NOW), null);
}
// PaceTests.testAlwaysShowPacingAddsEvenPaceTickToHealthyBar
{
  const blue = m.meterState(paced(30, 0.4, WEEK, {alwaysShowPacing: true}));
  assert.ok(Math.abs(m.paceTick(paced(30, 0.4, WEEK, {alwaysShowPacing: true}), blue) - 0.4) < 0.001);
  const left = m.meterState(paced(30, 0.4, WEEK, {alwaysShowPacing: true, display: 'Left'}));
  assert.ok(Math.abs(m.paceTick(paced(30, 0.4, WEEK, {alwaysShowPacing: true, display: 'Left'}), left) - 0.6) < 0.001);
}
// PaceTests.testAlwaysShowPacingStaysSilentOnUntouchedMeter
{
  const st = m.meterState(paced(0, 0.03, WEEK, {alwaysShowPacing: true}));
  assert.deepEqual(norm(st), {kind: 'level', severity: 'normal'});
  assert.equal(m.paceTick(paced(0, 0.03, WEEK, {alwaysShowPacing: true}), st), null);
}
// MeterSeverityTests.testPaceVerdictOverridesAbsoluteUsageBands
assert.equal(m.severityOf(m.meterState(paced(66, 0.363))), 'critical');
assert.equal(m.severityOf(m.meterState(paced(85, 0.96))), 'normal');
assert.equal(m.severityOf(m.meterState(paced(88, 0.9))), 'warning');
// MeterSeverityTests.testAbsoluteSeverityThresholdsUseRoundedPercentages
for (const [used, sev] of [[0, 'normal'], [79, 'normal'], [79.6, 'warning'], [80, 'warning'], [89.4, 'warning'], [89.6, 'critical'], [90, 'critical']])
  assert.equal(m.severityOf(m.meterState({used, limit: 100, kind: 'percent', hasData: true})), sev, `used ${used}`);
// MeterSeverityTests.testSeverityIgnoresTheUsedLeftDisplayMode
assert.equal(m.severityOf(m.meterState({used: 95, limit: 100, kind: 'percent', hasData: true, display: 'Left'})), 'critical');
assert.equal(m.severityOf(m.meterState({used: 85, limit: 100, kind: 'percent', hasData: true, display: 'Left'})), 'warning');
// MeterSeverityTests.testUnboundedAndZeroLimitMetricsStayNormal
assert.equal(m.severityOf(m.meterState({used: 99, limit: null, hasData: true})), 'normal');
assert.equal(m.severityOf(m.meterState({used: 99, limit: 0, hasData: true})), 'normal');
// MeterSeverityTests.testNoDataHasNoSeverity
assert.equal(m.severityOf(m.meterState({used: 50, limit: 100, hasData: false})), null);
// ResetDisplayTests.testSessionWindowSignalIsWiredOnExactlyTheShippingSessionDescriptors
assert.equal(m.sessionSignalFor('claude', 'session'), 'missingResetDate');
assert.equal(m.sessionSignalFor('antigravity', 'geminiPro'), 'zeroUsage');
assert.equal(m.sessionSignalFor('antigravity', 'claude'), 'zeroUsage');
assert.equal(m.sessionSignalFor('opencode', 'session'), 'zeroUsage');
assert.equal(m.sessionSignalFor('codex', 'session'), null);
// ResetDisplayTests.testMissingResetDateSignalKeepsCountdownForSubOnePercentSession
assert.equal(m.isFreshSession({used: 0, limit: 100, hasData: true, sessionSignal: 'missingResetDate', resetsAt: NOW + 7200000, now: NOW}), false);
assert.equal(m.isFreshSession({used: 0, limit: 100, hasData: true, sessionSignal: 'missingResetDate', resetsAt: null, now: NOW}), true);
assert.equal(m.isFreshSession({used: 0, limit: 100, hasData: true, sessionSignal: 'zeroUsage', resetsAt: NOW + 9000000, now: NOW}), true);
// ResetDisplayTests.testExpirySeverityTracksSoonestExpiry
assert.equal(m.expirySeverity(3600), 'critical');
assert.equal(m.expirySeverity(3 * 86400), 'warning');
assert.equal(m.expirySeverity(10 * 86400), 'normal');
console.log('Pace tests passed');
