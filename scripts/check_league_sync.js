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
console.log('League sync identity and session access: PASS');
