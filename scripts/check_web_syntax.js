const fs = require('fs');
const vm = require('vm');

const babelContext = {};
vm.createContext(babelContext);
vm.runInContext(
  fs.readFileSync('draft_assistant/web/static/vendor/babel.min.js', 'utf8'),
  babelContext,
);

for (const path of [
  'draft_assistant/web/static/tweaks-panel.jsx',
  'draft_assistant/web/static/components/app-components.jsx',
  'draft_assistant/web/static/components/draft-screen.jsx',
]) {
  babelContext.Babel.transform(fs.readFileSync(path, 'utf8'), { presets: ['react'] });
}

for (const path of [
  'draft_assistant/web/static/components/shared-utils.js',
  'draft_assistant/web/static/components/opponent-model.js',
]) {
  new Function(fs.readFileSync(path, 'utf8'));
}

const helperContext = {};
vm.createContext(helperContext);
vm.runInContext(
  fs.readFileSync('draft_assistant/web/static/components/shared-utils.js', 'utf8'),
  helperContext,
);
const [scored] = helperContext.withProjections(
  [{ pos: 'DST', stdPts: 0, recPts: 0, stats: { sack: 2, def_int: 1 } }],
  { scoringType: 'standard', importedScoring: { sack: 2, def_int: 3 } },
);
if (scored.projPts !== 7) {
  throw new Error(`Imported scoring parity failed: expected 7, got ${scored.projPts}`);
}

console.log('Browser JavaScript and JSX syntax: PASS');
