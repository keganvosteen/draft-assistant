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

// The app's startup news refresh, run for real against a controlled server.
// It has to ask for "now" -- no season, no week -- and let the server work out
// both. It used to echo the cached context's own season and week straight
// back, so a cache from last season was refreshed as last season and the week
// never advanced past the one it was saved at.
(async () => {
  const app = fs.readFileSync('draft_assistant/web/static/components/app-components.jsx', 'utf8');
  const from = app.indexOf('    const newsFailed = detail => toast(');
  const to = app.indexOf('  }, [refreshPlayers]);', from);
  assert.ok(from > 0 && to > from, 'startup news refresh must be found');
  const launch = async cached => {
    const posts = [], toasts = [];
    let reloads = 0;
    const reply = body => Promise.resolve({json: () => Promise.resolve(body)});
    vm.runInContext(app.slice(from, to), vm.createContext({
      toast: (message, tone) => toasts.push({message, tone}),
      refreshPlayers: () => { reloads++; },
      setTimeout: fn => fn(),
      fetch(url, options) {
        if (url === '/api/context') return reply(cached);
        if (url === '/api/context/refresh') { posts.push(JSON.parse(options.body)); return reply({taskId: 'news'}); }
        if (url === '/api/task/news') return reply({status: 'done'});
        throw new Error(`unexpected request: ${url}`);
      },
    }));
    for (let turn = 0; turn < 12; turn++) await settle();
    return {posts, toasts, reloads};
  };

  // Whatever the cache says about itself -- last season, a week long gone --
  // none of it may come back as a request.
  for (const cached of [{season: 2025, week: 9, stale: true}, {season: 2026, week: 3, stale: true}]) {
    const started = await launch(cached);
    assert.deepEqual(started.posts, [{}], 'the startup refresh must not name a season or a week');
    assert.equal(started.reloads, 1, 'the board reloads once the refresh lands');
    assert.deepEqual(started.toasts, []);
  }
  const fresh = await launch({season: 2026, week: 6, stale: false});
  assert.deepEqual(fresh.posts, [], 'a fresh context is not refreshed');
  assert.equal(fresh.reloads, 0);
  const failed = await launch({error: 'context unreadable'});
  assert.deepEqual(failed.posts, []);
  assert.deepEqual(failed.toasts.map(t => t.tone), ['error'], 'a dead news feed still says so');
  console.log('Startup news refresh leaves season and week to the server: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
