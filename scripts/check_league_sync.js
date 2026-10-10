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

// Execute the real restore handler: old provider IDs must resolve immediately,
// without waiting for a board refresh or app restart to exclude drafted players.
(async () => {
  vm.runInContext(app.slice(app.indexOf('function rosterSyncKey('), app.indexOf('// ─── DRAFT ORDER EDITOR')), context);
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
