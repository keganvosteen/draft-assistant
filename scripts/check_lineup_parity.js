// Parity gate: the browser's lineup assignment against the Python engine's.
//
// buildLineup/getRosterNeeds in shared-utils.js re-implement what
// draft_assistant/slot_assignment.py does for the engine. They fill the draft
// room's team panel and the waiver roster panel, so if the two drift the user
// is shown a lineup, or a "needs" chip, that the recommendations were not
// computed against - and nothing used to fail when that happened.
//
// tests/fixtures/lineup_parity.json is generated from the Python side and
// checked against an exhaustive search by tests/test_lineup_parity.py. This
// replays every case through the browser code. The file's "about" header says
// what is pinned and what deliberately is not.
const fs = require('node:fs');
const vm = require('node:vm');

const FIXTURES = 'tests/fixtures/lineup_parity.json';
const context = vm.createContext({});
vm.runInContext(fs.readFileSync('draft_assistant/web/static/components/shared-utils.js', 'utf8'), context);
const fixtures = JSON.parse(fs.readFileSync(FIXTURES, 'utf8'));
// Copies into this realm too: arrays built inside the vm context are not
// instances of this file's Array.
const sorted = values => Array.from(values).sort();
const show = value => JSON.stringify(value);

// The fixtures only seat the flex types that existed when they were written.
// One added to a single side would never appear in a case, so compare the
// eligibility tables themselves.
const eligibility = (table, read) => show(Object.fromEntries(
  Object.keys(table).sort().map(key => [key, sorted(read(table[key]))])));
const engineFlex = eligibility(fixtures.flexTypes, positions => positions);
const browserFlex = eligibility(context.FLEX_TYPES_JS, type => type.elig);
if (engineFlex !== browserFlex) {
  throw new Error(
    'Flex slot eligibility differs between models.FLEX_TYPES and FLEX_TYPES_JS.\n' +
    `  engine:  ${engineFlex}\n  browser: ${browserFlex}`);
}

const failures = [];
let checked = 0;
for (const roster of fixtures.rosters) {
  for (const fixture of roster.cases) {
    checked++;
    const players = fixture.players.map(([id, pos, projPts]) => ({ id, pos, projPts }));
    const lineup = context.buildLineup(players, roster.slots);
    const starterRows = lineup.filter(row => !row.slot.bench);
    const seated = starterRows.filter(row => row.player);
    const expected = {
      starters: fixture.starters, points: fixture.points, open: fixture.open,
      needs: sorted(fixture.needs), bench: fixture.bench,
    };
    const actual = {
      starters: sorted(seated.map(row => row.player.id)),
      points: seated.reduce((sum, row) => sum + row.player.projPts, 0),
      open: starterRows.length - seated.length,
      needs: sorted(context.getRosterNeeds(players, roster.slots)),
      bench: sorted(lineup.filter(row => row.slot.bench && row.player).map(row => row.player.id)),
    };
    // The right starters in the wrong rows would still total correctly.
    const misplaced = seated
      .filter(row => !(row.slot.elig || [row.slot.pos]).includes(row.player.pos))
      .map(row => `${row.player.id} in a ${row.slot.label} slot`);
    if (show(actual) !== show(expected) || misplaced.length) {
      failures.push(
        `${roster.name}/${fixture.name}\n` +
        `  slots:    ${show(roster.slots)}\n` +
        `  players:  ${show(fixture.players)}\n` +
        `  expected: ${show(expected)}\n` +
        `  actual:   ${show(actual)}` +
        (misplaced.length ? `\n  ineligible: ${misplaced.join(', ')}` : ''));
    }
  }
}

// A renamed key or an emptied file must not read as "nothing disagreed".
if (checked === 0) throw new Error(`${FIXTURES} contains no cases.`);
if (failures.length > 0) {
  console.error(failures.slice(0, 5).join('\n'));
  throw new Error(
    `Browser lineup disagrees with the Python engine on ${failures.length} of ${checked} fixtures ` +
    `(first ${Math.min(5, failures.length)} shown above). "expected" is what slot_assignment.py produces ` +
    'and an exhaustive search confirms, so fix buildLineup/getRosterNeeds in shared-utils.js. ' +
    `If the engine itself changed, regenerate first: ${fixtures.regenerate}`);
}
console.log(`Browser and engine lineup parity: PASS (${checked} fixtures)`);
