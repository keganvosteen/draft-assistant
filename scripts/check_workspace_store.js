const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {window:{}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('draft_assistant/web/static/components/workspace-store.js', 'utf8'), context);
const create = context.window.createWorkspaceClient;
const clone = value => JSON.parse(JSON.stringify(value));
const league = {id:'league-a', name:'My saved league', numTeams:10, rosterSlots:{QB:1, BN:6},
  keepers:[{playerId:'keeper|RB', round:4}], importedScoring:{rec:0.5}};
const original = {schemaVersion:1, leagues:[league], picks:{'league-a':[{pickNum:1, teamNum:4, playerId:'keeper|RB'}]},
  preferences:{tweaks:{sims:32}}};
function storage(entries = {}) {
  const values = new Map(Object.entries(entries));
  return {getItem:key => values.get(key) || null, setItem:(key, value) => values.set(key, value)};
}
function server(initial) {
  let state = clone(initial || {schemaVersion:1, exists:false, revision:0, leagues:[], picks:{}, preferences:{}});
  const posts = [];
  let fail = false, release = null;
  return {
    posts, state:() => clone(state), fail:() => { fail = true; },
    hold:() => new Promise(resolve => { release = resolve; }),
    async request(url, options) {
      assert.equal(url, '/api/workspace');
      if (options.method === 'POST') {
        const value = JSON.parse(options.body);
        posts.push(value);
        if (release) { const resolve = release; release = null; await new Promise(done => resolve(done)); }
        if (fail) { fail = false; throw new Error('disk unavailable'); }
        if (value.revision !== state.revision) return {ok:false, json:async () => ({error:'revision conflict'})};
        state = {...value, exists:true, revision:state.revision + 1};
      }
      return {ok:true, json:async () => clone(state)};
    },
  };
}

(async () => {
  // Upgrade imports legacy browser fields without changing team/pick identity.
  const local = storage({fda_leagues:JSON.stringify(original.leagues), fda_picks:JSON.stringify(original.picks),
    fda_tweaks:JSON.stringify(original.preferences.tweaks)});
  const disk = server();
  const first = create({storage:local, request:disk.request});
  await first.load();
  assert.deepEqual(disk.state().leagues, original.leagues);
  assert.deepEqual(disk.state().picks, original.picks);
  assert.deepEqual(disk.state().preferences, original.preferences);

  // New app port/profile has no localStorage and still loads the same leagues.
  const reopened = create({storage:storage(), request:disk.request});
  assert.deepEqual(clone((await reopened.load()).leagues), original.leagues);
  assert.equal(disk.posts.length, 1);

  // Changes made during an active save serialize using the new revision.
  const held = disk.hold();
  first.save({...original, leagues:[{...league, name:'First edit'}]});
  const release = await held;
  first.save({...original, leagues:[{...league, name:'Latest edit'}]});
  release();
  await first.flush();
  assert.equal(disk.state().leagues[0].name, 'Latest edit');
  assert.deepEqual(disk.posts.map(p => p.revision), [0, 1, 2]);

  // Failed writes remain recoverable; next load retries the matching revision.
  disk.fail();
  first.save({...original, leagues:[{...league, name:'Recovered edit'}]});
  await assert.rejects(first.flush(), /disk unavailable/);
  assert.equal(JSON.parse(local.getItem('fda_workspace')).pending, true);
  const recovered = create({storage:local, request:disk.request});
  await recovered.load();
  assert.equal(disk.state().leagues[0].name, 'Recovered edit');
  assert.equal(JSON.parse(local.getItem('fda_workspace')).pending, false);

  // A stale window cannot overwrite a newer save, and can export its own copy.
  reopened.save({...original, leagues:[{...league, name:'Stale edit'}]});
  await assert.rejects(reopened.flush(), /revision conflict/);
  assert.equal(reopened.snapshot().leagues[0].name, 'Stale edit');
  assert.equal(disk.state().leagues[0].name, 'Recovered edit');
  await reopened.useDiskCopy();
  assert.equal(reopened.hasPending(), false);
  assert.equal(reopened.snapshot().leagues[0].name, 'Recovered edit');

  // Restore is saved first; invalid/future data leaves the current copy intact.
  const before = disk.state();
  await assert.rejects(recovered.restore({...original, schemaVersion:2}), /supported/);
  assert.deepEqual(disk.state(), before);
  await recovered.restore(original);
  assert.deepEqual(disk.state().picks, original.picks);

  // A restore serializes with pending saves and excludes stale background updates.
  const beforeRestorePosts = disk.posts.length;
  const heldSave = disk.hold();
  recovered.save({...original, leagues:[{...league, name:'Edit before restore'}]});
  const releaseSave = await heldSave;
  const restore = recovered.restore(original);
  recovered.save({...original, leagues:[{...league, name:'Old background update'}]});
  assert.equal(recovered.hasPending(), true);
  releaseSave();
  await restore;
  await recovered.flush();
  assert.equal(disk.posts.length, beforeRestorePosts + 2);
  assert.equal(disk.state().leagues[0].name, league.name);
  assert.equal(recovered.snapshot().leagues[0].name, league.name);
  assert.equal(recovered.hasPending(), false);

  // Closing/flush also waits for an otherwise idle restore already in flight.
  const heldRestore = disk.hold();
  const restoring = recovered.restore({...original, leagues:[{...league, name:'Restored backup'}]});
  const releaseRestore = await heldRestore;
  const duringRestorePosts = disk.posts.length;
  recovered.save({...original, leagues:[{...league, name:'Stale poll result'}]});
  let flushed = false;
  const waitingFlush = recovered.flush().then(() => { flushed = true; });
  await Promise.resolve();
  assert.equal(flushed, false);
  assert.equal(disk.posts.length, duringRestorePosts);
  releaseRestore();
  await restoring;
  await waitingFlush;
  assert.equal(disk.state().leagues[0].name, 'Restored backup');

  // A failed flush before restore retains the original pending journal.
  disk.fail();
  recovered.save({...original, leagues:[{...league, name:'Unsaved before restore'}]});
  await assert.rejects(recovered.restore(original), /disk unavailable/);
  assert.equal(recovered.snapshot().leagues[0].name, 'Unsaved before restore');
  assert.equal(JSON.parse(local.getItem('fda_workspace')).pending, true);
  await recovered.flush();
  assert.equal(disk.state().leagues[0].name, 'Unsaved before restore');

  // Deleting all leagues is a saved state; a later launch must not resurrect old browser data.
  await recovered.restore({schemaVersion:1, leagues:[], picks:{}, preferences:{}});
  const empty = create({storage:storage({fda_leagues:JSON.stringify(original.leagues)}), request:disk.request});
  assert.deepEqual(clone((await empty.load()).leagues), []);

  // Unreadable legacy data is never replaced with a fresh empty workspace.
  const untouched = server();
  const malformed = create({storage:storage({fda_leagues:'broken JSON'}), request:untouched.request});
  await assert.rejects(malformed.load());
  assert.equal(untouched.posts.length, 0);
  console.log('Workspace migration, restart, save ordering and recovery: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
