// Exercise the actual React effect with controlled network completion order.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('draft_assistant/web/static/components/draft-screen.jsx', 'utf8');
const start = source.indexOf('  React.useEffect(() => {', source.indexOf('const handleRefreshRecs'));
const end = source.indexOf('  const tweakSig', start);
assert.ok(start > 0 && end > start, 'recommendation effect must be found');
let previousDependencies, cleanup, state = {rows: {old: {id: 'old'}}};
let timerId = 0;
const timers = new Map(), requests = [];
const context = vm.createContext({
  AbortController,
  picks: [], allPlayers: [{id: 'same', projPts: 100}], untilMyTurn: 0, trackingBlocked: false,
  league: {numTeams: 12, draftPosition: 1, rosterSlots: {RB: 1}, scoringType: 'ppr', draftType: 'snake'},
  adpNoise: 0, tweaks: {sims: 8}, refreshNonce: 0,
  setSuggest(value) { state = typeof value === 'function' ? value(state) : value; },
  setTimeout(fn) { timers.set(++timerId, fn); return timerId; },
  clearTimeout(id) { timers.delete(id); },
  fetch(url, options) {
    return new Promise((resolve, reject) => requests.push({url, options, resolve, reject}));
  },
  React: {useEffect(effect, dependencies) {
    if (previousDependencies && dependencies.every((value, i) => Object.is(value, previousDependencies[i]))) return;
    if (cleanup) cleanup();
    previousDependencies = dependencies;
    cleanup = effect();
  }},
});
const render = () => vm.runInContext(source.slice(start, end), context);
const flushTimers = () => { for (const [id, fn] of timers) { timers.delete(id); fn(); } };
const settle = () => new Promise(resolve => setImmediate(resolve));
const respond = (request, data) => request.resolve({json: () => Promise.resolve(data)});

(async () => {
  render(); flushTimers();
  assert.equal(Object.keys(state.rows).length, 0, 'old scores clear while new scores load');
  assert.equal(requests.length, 1);
  render(); flushTimers();
  assert.equal(requests.length, 1, 'unchanged dependencies do not recompute');

  // Same player IDs, different projection data: the audited stale-score case.
  context.allPlayers = [{id: 'same', projPts: 200}];
  render(); flushTimers();
  assert.equal(requests.length, 2, 'data refresh must recompute with unchanged picks/IDs');
  assert.equal(requests[0].options.signal.aborted, true);
  respond(requests[1], {suggestions: [{id: 'same', immediateGain: 200}], rosterFeasible: false});
  await settle();
  assert.equal(state.rows.same.immediateGain, 200);
  assert.equal(state.rosterFeasible, false);
  respond(requests[0], {suggestions: [{id: 'same', immediateGain: 100}], rosterFeasible: true});
  await settle();
  assert.equal(state.rows.same.immediateGain, 200, 'late response must not overwrite refreshed scores');

  context.league = {...context.league, importedScoring: {rec: 0.5}};
  render(); flushTimers();
  assert.equal(requests.length, 3, 'imported scoring changes recompute');
  assert.equal(JSON.parse(requests[2].options.body).league.importedScoring.rec, 0.5);
  context.adpNoise = 10;
  render(); flushTimers();
  assert.equal(requests.length, 4, 'ADP noise changes recompute');
  requests[2].reject(new Error('late network failure'));
  await settle();
  assert.equal(state.err, null, 'aborted request errors must not replace pending state');
  context.untilMyTurn = 1;
  render(); flushTimers();
  assert.equal(requests[3].options.signal.aborted, true);
  assert.equal(state.stale, true);
  assert.equal(requests.length, 4, 'off-turn render must not request suggestions');
  console.log('Recommendation refresh and response ordering: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
