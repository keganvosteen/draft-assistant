// Behavioral checks for identity and ownership across provider-order refreshes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync('draft_assistant/web/static/components/shared-utils.js', 'utf8'), context);
const plain = value => JSON.parse(JSON.stringify(value));

const original = {teamIds:['9','3'], teamNames:['Same','Same'], draftPosition:2,
  importedScoring:{rec:1}, rosterSlots:{QB:1,BN:2}};
const patch = {teamIds:['3','9'], teamNames:['Same','Same'], draftOrderReady:true};
const reordered = context.mergeLeagueSettings(original, patch);
assert.equal(reordered.draftPosition, 1, 'selected team must follow its provider ID');
assert.equal(reordered.importedScoring.rec, 1, 'live metadata must preserve scoring');
assert.equal(original.draftPosition, 2, 'refresh must not mutate its input');
assert.deepEqual(plain(context.remapLeaguePicks([{pickNum:1,teamNum:2,playerId:'a'}], original, reordered)),
  [{pickNum:1,teamNum:1,playerId:'a'}], 'recorded ownership must follow the same team');

const renamed = context.mergeLeagueSettings(original, {teamIds:['9','3'], teamNames:['New A','New B']});
assert.equal(renamed.draftPosition, 2, 'a team rename must not lose the selection');
const missing = context.mergeLeagueSettings(original, {teamIds:['8','4'], teamNames:['Same','Same']});
assert.equal(missing.draftPosition, null, 'unknown IDs must not fall back to duplicate names');
assert.equal(missing.teamSelectionRequired, true);
assert.throws(() => context.remapLeaguePicks([{teamNum:2}], original, missing), /Could not match/);

const legacy = {teamNames:['Alpha','Bravo'], draftPosition:1};
assert.equal(context.mergeLeagueSettings(legacy, {teamNames:['Bravo','Alpha'],teamIds:['3','9']}).draftPosition, 2);
const imported = context.mergeLeagueSettings({teamNames:[],draftPosition:5}, patch);
assert.equal(imported.draftPosition, null, 'new imports must ask which team belongs to the user');

context.setEspnAccess('first', {espnS2:'test-session',swid:'test-owner'});
assert.deepEqual(plain(context.getEspnAccess('second')), {}, 'a second league must not inherit access');
const access = context.getEspnAccess('first');
access.espnS2 = 'changed';
assert.equal(context.getEspnAccess('first').espnS2, 'test-session', 'callers receive a copy');
context.setEspnAccess('first', null);
assert.deepEqual(plain(context.getEspnAccess('first')), {}, 'clearing access must remove both cookies');
const app = fs.readFileSync('draft_assistant/web/static/components/app-components.jsx', 'utf8');
vm.runInContext(app.slice(app.indexOf('function migratePickIds('), app.indexOf('// Current ownership')), context);
const saved = {league:[{playerId:'ffc:77',teamNum:2,pickNum:4}]};
const refreshed = context.migratePickIds(saved, [{id:'sleeper:11',legacyId:'Receiver|WR',aliases:['ffc:77']}]);
assert.equal(refreshed.league[0].playerId, 'sleeper:11');
assert.equal(refreshed.league[0].teamNum, 2);
assert.equal(saved.league[0].playerId, 'ffc:77', 'migration does not mutate snapshots');
assert.equal(context.migratePickIds(saved, [{id:'a',aliases:['ffc:77']},{id:'b',aliases:['ffc:77']}]), saved,
  'ambiguous aliases must not guess ownership');
assert.equal(context.migratePickIds(saved, [{id:'ffc:77'},{id:'b',aliases:['ffc:77']}]), saved,
  'an existing canonical identity must win');
console.log('League sync identity and session access: PASS');
const crossed = [{id:'wr',pos:'WR',projPts:110},{id:'te',pos:'TE',projPts:100},{id:'rb',pos:'RB',projPts:1}];
for (const players of [crossed, crossed.slice().reverse(), [crossed[1],crossed[0],crossed[2]]]) {
  const lineup = context.buildLineup(players, {WRTE:1,RBWR:1});
  assert.equal(lineup.reduce((sum,row) => sum+(row.player?.projPts || 0),0), 210);
  assert.deepEqual(plain(context.getRosterNeeds(players.slice().filter(p => p.pos!=='RB'), {WRTE:1,RBWR:1})), []);
}
assert.deepEqual(plain(context.getRosterNeeds([{id:'rb',pos:'RB',projPts:100}], {RB:1,TE:1,BN:1})), ['TE']);
console.log('Browser roster assignment and needs: PASS');

// The "load bye weeks" notice shows for a board whose byes the server could
// not verify (every byeWeek null) -- never for one that is empty, still
// loading, or already carrying a bye.
assert.equal(context.boardLacksByes([{id:'a',byeWeek:null},{id:'b'}]), true);
assert.equal(context.boardLacksByes([{id:'a',byeWeek:null},{id:'b',byeWeek:7}]), false,
  'one verified bye means the board has been stamped');
for (const notLoaded of [null, undefined, [], {}, 'players']) {
  assert.equal(context.boardLacksByes(notLoaded), false, 'nothing to repair before players load');
}
console.log('Bye weeks notice predicate: PASS');

// Ownership helpers are plain JavaScript inside the JSX file.
const ownershipSource = app.slice(app.indexOf('function rosterSyncKey('), app.indexOf('// ─── DRAFT ORDER EDITOR'));
vm.runInContext(ownershipSource, context);

// A saved snapshot may stand in for a live roster sync only when that sync
// failed, and only one the screen can label truthfully.
const linked = {id:'league', platform:'Yahoo', yahooLeagueKey:'nfl.l.1', season:2026, numTeams:2,
  teamIds:['1','2'], teamNames:['Mine','Theirs']};
const savedRosters = {picks:[{playerId:'a',teamNum:1}], syncedAt:'2026-10-12T14:00:00.000Z',
  leagueKey:context.rosterSyncKey(linked)};
const withSnapshot = patch => ({...linked, rosterSnapshot:patch && {...savedRosters, ...patch}});
assert.equal(context.fallbackRosterSnapshot({...linked, rosterSnapshot:savedRosters}), savedRosters,
  'a snapshot taken under the same provider/season/seat mapping is the fallback');
assert.equal(context.fallbackRosterSnapshot({...linked, yahooLeagueKey:'nfl.l.2', rosterSnapshot:savedRosters}), null,
  're-linked league must not rank against the old league\'s rosters');
assert.equal(context.fallbackRosterSnapshot({...linked, teamIds:['2','1'], rosterSnapshot:savedRosters}), null,
  'a changed seat map makes the saved teamNums someone else\'s');
assert.equal(context.fallbackRosterSnapshot(withSnapshot({leagueKey:undefined})), null);
assert.equal(context.fallbackRosterSnapshot(withSnapshot(null)), null, 'no snapshot, no fallback');
for (const picks of [undefined, null, {}, 'a', 3]) {
  assert.equal(context.fallbackRosterSnapshot(withSnapshot({picks})), null, 'picks must be a list');
}
// An hour-old "nobody is rostered" would put every owned player on the wire
// and leaves no roster to rank a pickup against: the sync error says more.
assert.equal(context.fallbackRosterSnapshot(withSnapshot({picks:[]})), null,
  'an empty saved snapshot is not worth falling back to');
for (const syncedAt of [undefined, null, '', 'yesterday']) {
  assert.equal(context.fallbackRosterSnapshot(withSnapshot({syncedAt})), null,
    'a snapshot that cannot be dated cannot be labelled');
}
console.log('Waiver roster fallback decision: PASS');

// Execute the real waiver-wire sync handler with controlled provider outcomes.
// The fallback is for a sync that FAILED; a success is authoritative however
// empty, and a superseded or abandoned sync may not touch the screen at all.
(async () => {
  const waiverSource = fs.readFileSync('draft_assistant/web/static/components/waiver-screen.jsx', 'utf8');
  const from = waiverSource.indexOf('  const syncSeq = React.useRef(0);');
  const to = waiverSource.indexOf('  React.useEffect(() => {', from);
  assert.ok(from > 0 && to > from, 'waiver sync handler must be found');
  const state = {}, toasts = [], pending = [];
  const set = key => value => { state[key] = value; };
  const waiver = vm.createContext({
    React:{useRef:value => ({current:value})}, scanSeq:{current:0}, linkedTo:'Yahoo',
    league:{...linked, rosterSnapshot:savedRosters},
    onSyncLeague:() => new Promise((resolve, reject) => pending.push({resolve, reject})),
    setRosterSnapshot:set('rosterSnapshot'), setSyncFailure:set('syncFailure'), setData:set('data'),
    setError:set('error'), setLoading:set('loading'), setSyncing:set('syncing'),
    toast:(message, tone) => toasts.push({message, tone}),
  });
  vm.runInContext(ownershipSource, waiver);
  const screen = vm.runInContext(
    `(function () {${waiverSource.slice(from, to)}\nreturn {runSync, syncSeq, latestLeague};})()`, waiver);
  const settle = () => new Promise(resolve => setImmediate(resolve));
  const live = picks => ({message:'Synced.', rosterSnapshot:{picks, syncedAt:'2026-10-12T15:00:00.000Z', leagueKey:savedRosters.leagueKey}});
  const outage = new Error('Yahoo authorization expired.');

  screen.runSync(false);
  assert.deepEqual(plain(state), {rosterSnapshot:null, syncFailure:null, data:null, error:null, loading:false, syncing:true});
  pending[0].reject(outage); await settle();
  assert.equal(state.rosterSnapshot, savedRosters, 'a failed sync ranks against the saved rosters');
  assert.equal(state.syncFailure, 'Yahoo authorization expired.', 'and says why it is doing so');
  assert.equal(state.error, null);
  assert.equal(state.syncing, false);
  assert.deepEqual(toasts, [], 'the sync a visit starts on its own does not toast');

  screen.runSync();
  assert.equal(state.rosterSnapshot, null, 'a retry stops ranking against the saved rosters while it runs');
  assert.equal(state.syncFailure, null);
  const fresh = live([{playerId:'b',teamNum:2}]);
  pending[1].resolve(fresh); await settle();
  assert.equal(state.rosterSnapshot, fresh.rosterSnapshot);
  assert.equal(state.syncFailure, null, 'a successful retry clears the fallback and its warning');
  assert.deepEqual(toasts.map(t => t.tone), ['ok']);

  screen.runSync(false);
  const nobody = live([]);
  pending[2].resolve(nobody); await settle();
  assert.equal(state.rosterSnapshot, nobody.rosterSnapshot, 'an empty roster list is authoritative');
  assert.equal(state.syncFailure, null, 'a sync that succeeded with zero players never falls back');

  screen.runSync(false);
  screen.runSync(false);
  pending[4].resolve(fresh); await settle();
  pending[3].reject(outage); await settle();
  assert.equal(state.rosterSnapshot, fresh.rosterSnapshot, 'a superseded sync failing late must not replace the fresh result');
  assert.equal(state.syncFailure, null);

  screen.runSync(false);
  screen.syncSeq.current++;  // what the screen's effect cleanup does on the way out
  const left = plain(state);
  pending[5].reject(outage); await settle();
  assert.deepEqual(plain(state), left, 'a sync that outlives the screen must not set state');

  // The hub's own sync can land while this one is in flight: fall back to the
  // snapshot saved by the time of the failure, not the one the visit began with.
  const newer = {...savedRosters, syncedAt:'2026-10-12T14:30:00.000Z'};
  screen.runSync();
  screen.latestLeague.current = {...linked, rosterSnapshot:newer};
  pending[6].reject(outage); await settle();
  assert.equal(state.rosterSnapshot, newer);
  assert.deepEqual(toasts.slice(1), [{message:'Could not sync current rosters from Yahoo. Yahoo authorization expired.', tone:'error'}]);

  // No usable snapshot: exactly the error the screen showed before the fallback existed.
  for (const rosterSnapshot of [null, {...savedRosters, leagueKey:'another league'}, {...savedRosters, picks:[]}]) {
    screen.latestLeague.current = {...linked, rosterSnapshot};
    screen.runSync(false);
    pending[pending.length - 1].reject(outage); await settle();
    assert.equal(state.rosterSnapshot, null);
    assert.equal(state.syncFailure, null);
    assert.equal(state.error, 'Could not sync current rosters from Yahoo. Yahoo authorization expired. '
      + 'Check the league connection in League settings, then retry Sync.');
  }
  console.log('Waiver sync failure fallback and sequencing: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });

// Execute the real restore handler: old provider IDs must resolve immediately,
// without waiting for a board refresh or app restart to exclude drafted players.
(async () => {
  const restoreSource = app.slice(app.indexOf('  const restoreBackup = async event => {'), app.indexOf('  const saveLeague = lg => {'));
  const restoredState = {};
  const backup = {
    schemaVersion:1, preferences:{},
    leagues:[{id:'league', name:'Saved league', numTeams:2, rosterSlots:{WR:1},
      rosterSnapshot:{picks:[{playerId:'ffc:77',teamNum:2}]}}],
    picks:{league:[{playerId:'ffc:77',teamNum:2,pickNum:1}]},
  };
  Object.assign(context, {
    players:[{id:'sleeper:11',legacyId:'Receiver|WR',aliases:['ffc:77']}],
    workspaceData:value => value,
    workspace:{restore:async value => value},
    workspaceGeneration:{current:0},
    confirmDialog:async () => true,
    setRestoreBusy:value => {restoredState.busy=value;},
    setLeagues:value => {restoredState.leagues=value;},
    setPicks:value => {restoredState.picks=value;},
    setPreferences:() => {}, setRoute:() => {}, setShowBackups:() => {},
    localStorage:{setItem:() => {}},
    toast:(message,kind) => {if(kind==='error') throw new Error(message);},
  });
  vm.runInContext(restoreSource.replace('const restoreBackup =', 'globalThis.restoreBackup ='), context);
  await context.restoreBackup({target:{value:'backup.json',files:[{
    size:100, name:'backup.json', text:async () => JSON.stringify(backup),
  }]}});
  assert.equal(restoredState.picks.league[0].playerId, 'sleeper:11');
  assert.equal(restoredState.leagues[0].rosterSnapshot.picks[0].playerId, 'sleeper:11');
  const owned = new Set(restoredState.picks.league.map(pick => pick.playerId));
  assert.equal(context.players.filter(player => !owned.has(player.id)).length, 0,
    'restored player must immediately disappear from the available draft board');
  assert.equal(context.workspaceGeneration.current, 1, 'restore invalidates in-flight roster syncs');
  assert.equal(restoredState.busy, false);
  assert.equal(backup.picks.league[0].playerId, 'ffc:77', 'restore migration preserves input backup');
  console.log('Backup restore provider identity migration: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
