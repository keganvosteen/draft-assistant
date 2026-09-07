// Syntax gate for the browser assets.
//
// There is no build step: the browser transpiles the JSX at load time, so a
// syntax error ships silently and only shows up as a blank page. This parses
// every script the page loads, the same way the page will.
//
// The file list is DERIVED, never hardcoded. It used to be three literal paths,
// which meant deleting a web file broke CI and adding one left it unchecked.
// Instead we read index.html — the actual source of truth for what loads — and
// cross-check it against what is on disk in both directions.

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const STATIC_DIR = 'draft_assistant/web/static';
const INDEX = path.join(STATIC_DIR, 'index.html');

// ── What does the page actually load? ────────────────────────────────────────
const html = fs.readFileSync(INDEX, 'utf8');
const referenced = [...html.matchAll(/<script[^>]*\bsrc="([^"]+)"/g)].map(m => m[1]);
if (referenced.length === 0) {
  throw new Error(`No <script src> tags found in ${INDEX} — did the markup change?`);
}

const isVendor = rel => rel.startsWith('vendor/');
const toDisk = rel => path.join(STATIC_DIR, rel);

for (const rel of referenced) {
  if (!fs.existsSync(toDisk(rel))) {
    throw new Error(`${INDEX} loads "${rel}", which does not exist on disk.`);
  }
}

// ── Is anything on disk NOT loaded? ──────────────────────────────────────────
// An orphaned component is dead weight at best and a file someone forgot to
// wire up at worst; either way it never gets syntax-checked below.
const onDisk = [];
for (const dir of ['', 'components']) {
  const abs = path.join(STATIC_DIR, dir);
  for (const name of fs.readdirSync(abs)) {
    if (!/\.jsx?$/.test(name)) continue;
    onDisk.push(dir ? `${dir}/${name}` : name);
  }
}
const loaded = new Set(referenced);
const orphans = onDisk.filter(rel => !loaded.has(rel));
if (orphans.length > 0) {
  throw new Error(
    `These web scripts exist but index.html never loads them: ${orphans.join(', ')}. ` +
    'Add them to index.html or delete them.'
  );
}

// ── Load order: the UI kit publishes the globals every other file uses ───────
// Each Babel script gets its own scope, so a file that runs before ui-kit.jsx
// sees none of T/Btn/Modal/... and the app dies on first render.
const kitAt = referenced.indexOf('components/ui-kit.jsx');
if (kitAt === -1) {
  throw new Error('index.html no longer loads components/ui-kit.jsx.');
}
const babelScripts = referenced.filter(rel => rel.endsWith('.jsx'));
if (babelScripts[0] !== 'components/ui-kit.jsx') {
  throw new Error(
    `components/ui-kit.jsx must be the first .jsx loaded (it publishes the shared ` +
    `globals); index.html loads "${babelScripts[0]}" first.`
  );
}

// ── Parse everything ─────────────────────────────────────────────────────────
const babelContext = {};
vm.createContext(babelContext);
vm.runInContext(fs.readFileSync(path.join(STATIC_DIR, 'vendor/babel.min.js'), 'utf8'), babelContext);

let checked = 0;
for (const rel of referenced) {
  if (isVendor(rel)) continue; // integrity is covered by check_vendor_assets.py
  const source = fs.readFileSync(toDisk(rel), 'utf8');
  if (rel.endsWith('.jsx')) {
    babelContext.Babel.transform(source, { presets: ['react'] });
  } else {
    new Function(source); // parses without executing
  }
  checked++;
}

// ── Behavioural parity check: imported league scoring on a DST ───────────────
const helperContext = {};
vm.createContext(helperContext);
vm.runInContext(
  fs.readFileSync(path.join(STATIC_DIR, 'components/shared-utils.js'), 'utf8'),
  helperContext,
);
const [scored] = helperContext.withProjections(
  [{ pos: 'DST', stdPts: 0, recPts: 0, stats: { sack: 2, def_int: 1 } }],
  { scoringType: 'standard', importedScoring: { sack: 2, def_int: 3 } },
);
if (scored.projPts !== 7) {
  throw new Error(`Imported scoring parity failed: expected 7, got ${scored.projPts}`);
}

// IR is a roster slot but never a draft round; counting it inflated the
// "N slots" summaries and drew a phantom extra round on the pick ticker.
const slots = { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 2, K: 1, DST: 1, BN: 7, IR: 1 };
if (helperContext.rosterTotal(slots) !== 17) {
  throw new Error(`rosterTotal must skip IR: expected 17, got ${helperContext.rosterTotal(slots)}`);
}

console.log(`Browser JavaScript and JSX syntax: PASS (${checked} files)`);
