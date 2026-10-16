// Theme gate for the web UI.
//
// The app's look is four themes (Classic on :root, then Sleeper, ESPN and
// Yahoo under :root[data-theme=…] in styles.css), and every component colours
// itself through `T`, whose entries are var(--…) references. Three ways that
// silently breaks, each checked here:
//
//   1. A theme block forgets a token. It then inherits Classic's value — a
//      white card inside the dark Sleeper theme, say — and nothing errors.
//   2. A palette tweak drops a text/background pair below WCAG AA (4.5:1).
//   3. A component writes a raw colour ('#fff', rgba(…)) instead of a token,
//      which looks right in the theme it was written in and wrong in the rest.

const fs = require('fs');
const path = require('path');

const STATIC_DIR = 'draft_assistant/web/static';
const css = fs.readFileSync(path.join(STATIC_DIR, 'styles.css'), 'utf8')
  .replace(/\/\*[\s\S]*?\*\//g, '');

// ── Parse the theme blocks ───────────────────────────────────────────────────
function tokensOf(body) {
  const out = {};
  for (const m of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) out[m[1]] = m[2].trim();
  return out;
}

const blocks = {};
for (const m of css.matchAll(/:root(?:\[data-theme="([\w-]+)"\])?\s*\{([^}]*)\}/g)) {
  blocks[m[1] || 'classic'] = tokensOf(m[2]);
}
const base = blocks.classic;
if (!base || !Object.keys(base).length) throw new Error('styles.css has no :root token block.');
const themeNames = Object.keys(blocks);
for (const expected of ['classic', 'sleeper', 'espn', 'yahoo']) {
  if (!blocks[expected]) throw new Error(`styles.css is missing the "${expected}" theme block.`);
}

// Fonts are shared on purpose: the themes borrow no platform typefaces.
const SHARED = new Set(['--font', '--mono']);
const failures = [];
for (const name of themeNames) {
  if (name === 'classic') continue;
  const missing = Object.keys(base).filter(k => !SHARED.has(k) && !(k in blocks[name]));
  if (missing.length) failures.push(`${name}: does not define ${missing.join(', ')}`);
  const extra = Object.keys(blocks[name]).filter(k => !(k in base));
  if (extra.length) failures.push(`${name}: defines ${extra.join(', ')}, which :root (Classic) lacks`);
}

// ── Contrast ─────────────────────────────────────────────────────────────────
function rgb(value) {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value || '');
  if (!m) return null;
  const hex = m[1].length === 3 ? m[1].replace(/./g, c => c + c) : m[1];
  return [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16));
}
function luminance([r, g, b]) {
  const lin = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}
function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

// [text, background] pairs that actually occur in the UI. All are body-size
// text, so all need 4.5:1.
const PAIRS = [
  ...['--bg', '--surface', '--surface-alt'].flatMap(bg =>
    ['--text', '--muted', '--muted-light'].map(fg => [fg, bg])),
  ['--muted', '--border-light'],           // gray Badge
  ['--primary', '--surface'],              // links, "Open league →"
  ['--primary', '--primary-light'],        // pressed chips, top impact badge
  ['--on-primary', '--primary'],           // primary buttons, the pick on the clock
  ['--green', '--green-light'], ['--amber', '--amber-light'],
  ['--red', '--red-light'], ['--blue', '--blue-light'],
  ['--red', '--surface'], ['--amber', '--surface'], ['--green', '--surface'],
  ['--appbar-fg', '--appbar-bg'], ['--appbar-muted', '--appbar-bg'],
  ['--appbar-btn-fg', '--appbar-btn-bg'],
  ...['qb', 'rb', 'wr', 'te', 'k', 'dst'].map(p => [`--pos-${p}-fg`, `--pos-${p}-bg`]),
];

const report = [];
for (const name of themeNames) {
  const tokens = { ...base, ...blocks[name] };
  let worst = Infinity;
  for (const [fg, bg] of PAIRS) {
    const a = rgb(tokens[fg]), b = rgb(tokens[bg]);
    if (!a || !b) { failures.push(`${name}: ${fg} / ${bg} must both be #hex to be contrast-checked`); continue; }
    const ratio = contrast(a, b);
    worst = Math.min(worst, ratio);
    if (ratio < 4.5) {
      failures.push(`${name}: ${fg} (${tokens[fg]}) on ${bg} (${tokens[bg]}) is ${ratio.toFixed(2)}:1, needs 4.5:1`);
    }
  }
  report.push(`${name} ${worst.toFixed(2)}:1`);
}

// ── No raw colours in components ─────────────────────────────────────────────
// ui-kit.jsx may hold literals between `theme-literals:start` and `:end` (the
// picker's swatches preview themes that are not active, so they cannot be
// tokens). Everything else goes through T.
const COMPONENTS = path.join(STATIC_DIR, 'components');
for (const file of fs.readdirSync(COMPONENTS)) {
  if (!/\.jsx?$/.test(file)) continue;
  const source = fs.readFileSync(path.join(COMPONENTS, file), 'utf8')
    .replace(/theme-literals:start[\s\S]*?theme-literals:end/g, '');
  source.split(/\r?\n/).forEach((line, i) => {
    const code = line.replace(/\/\/.*$/, '');
    const hit = /(?<![&\w])#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/.exec(code);
    if (hit) failures.push(`${file}:${i + 1}: raw colour "${hit[0]}" — use a T token (ui-kit.jsx) instead`);
  });
}

if (failures.length) {
  console.error(`Theme tokens: FAIL\n  ${failures.join('\n  ')}`);
  process.exit(1);
}
console.log(`Theme tokens: PASS (${themeNames.length} themes; lowest contrast ${report.join(', ')})`);
