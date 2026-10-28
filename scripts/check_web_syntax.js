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

// ── Read the page ────────────────────────────────────────────────────────────
// A small scanner rather than regexes over the markup: it skips comments the
// way a browser does (a commented-out tag loads nothing), reads tag and
// attribute names in any case, and ends a <script> body at the first
// "</script", however it is spelled. Enough HTML for a page we write ourselves.
function scanTags(source) {
  const lower = source.toLowerCase();
  const tags = [];
  let i = 0;
  while ((i = lower.indexOf('<', i)) !== -1) {
    if (lower.startsWith('<!--', i)) {
      // Closes at the first --> (which is how <!--> and <!---> close at once)
      // or --!>. One that never closes runs to the end of the file.
      const ends = [[lower.indexOf('-->', i + 2), 3], [lower.indexOf('--!>', i + 4), 4]]
        .filter(([at]) => at !== -1);
      if (!ends.length) break;
      const [at, length] = ends.reduce((a, b) => (b[0] < a[0] ? b : a));
      i = at + length;
      continue;
    }
    const name = /^[a-z][a-z0-9-]*/.exec(lower.slice(i + 1, i + 64));
    if (!name) {
      i++;
      continue;
    }
    // The attributes run to the first > outside quotes.
    const start = i + 1 + name[0].length;
    let end = start;
    for (let quote = null; end < source.length; end++) {
      const c = source[end];
      if (quote) {
        if (c === quote) quote = null;
      } else if (c === '"' || c === "'") {
        quote = c;
      } else if (c === '>') {
        break;
      }
    }
    const attrs = {};
    const attrText = source.slice(start, end);
    for (const m of attrText.matchAll(/([^\s"'=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g)) {
      attrs[m[1].toLowerCase()] = m[2] ?? m[3] ?? m[4] ?? '';
    }
    const tag = { name: name[0], attrs, body: '' };
    i = end + 1;
    if (tag.name === 'script') {
      const close = lower.indexOf('</script', i);
      tag.body = source.slice(i, close === -1 ? source.length : close);
      i = close === -1 ? source.length : close;
    }
    tags.push(tag);
  }
  return tags;
}

// ── What does the page actually load? ────────────────────────────────────────
const tags = scanTags(fs.readFileSync(INDEX, 'utf8'));
const isExternalScript = tag => tag.name === 'script' && 'src' in tag.attrs;
const referenced = tags.filter(isExternalScript).map(tag => tag.attrs.src);
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

// ── The boot guard listens before anything can fail ──────────────────────────
// It records every script or stylesheet that fails to load, so the page shows
// an error instead of coming up blank. One that fails ahead of it is missed.
const inlineScripts = tags.filter(tag => tag.name === 'script' && !isExternalScript(tag));
const guardAt = tags.indexOf(inlineScripts.find(tag => tag.body.includes('window.__fdaBoot =')));
if (guardAt === -1) {
  throw new Error('index.html no longer defines the boot guard (window.__fdaBoot).');
}
if (guardAt > tags.findIndex(tag => tag.name === 'link' || isExternalScript(tag))) {
  throw new Error(
    'The boot guard in index.html must come before every <link> and <script src>: ' +
    'a file that fails to load ahead of it goes unrecorded.'
  );
}

// ── Parse everything ─────────────────────────────────────────────────────────
const babelContext = {};
vm.createContext(babelContext);
vm.runInContext(fs.readFileSync(path.join(STATIC_DIR, 'vendor/babel.min.js'), 'utf8'), babelContext);

const parse = (source, babel) => {
  if (babel) {
    babelContext.Babel.transform(source, { presets: ['react'] });
  } else {
    new Function(source); // parses without executing
  }
};

let checked = 0;
for (const rel of referenced) {
  if (isVendor(rel)) continue; // integrity is covered by check_vendor_assets.py
  parse(fs.readFileSync(toDisk(rel), 'utf8'), rel.endsWith('.jsx'));
  checked++;
}

// index.html's own scripts: theme bootstrap, boot guard, engine defaults, mount.
for (const tag of inlineScripts) {
  parse(tag.body, tag.attrs.type === 'text/babel');
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

console.log(`Browser JavaScript and JSX syntax: PASS (${checked} files, ${inlineScripts.length} inline scripts)`);
