// ─── THEME ────────────────────────────────────────────────────────────────────
const T = {
  bg: '#f3f5fb',
  surface: '#ffffff',
  surfaceAlt: '#f8f9fd',
  border: '#e0e4ef',
  borderLight: '#eef0f7',
  primary: '#3a5bef',
  primaryHover: '#2d4ad4',
  primaryLight: '#eef1fd',
  green: '#16a34a',
  greenLight: '#dcfce7',
  amber: '#d97706',
  amberLight: '#fef3c7',
  red: '#dc2626',
  redLight: '#fee2e2',
  blue: '#0369a1',
  blueLight: '#e0f2fe',
  text: '#1a1d2e',
  muted: '#6b7280',
  mutedLight: '#9ca3af',
  r: '10px',
  rsm: '6px',
  rxs: '4px',
};

// ─── DEFAULT DATA ─────────────────────────────────────────────────────────────
const DEFAULT_SLOTS   = { QB:1, RB:2, WR:2, TE:1, FLEX:1, K:1, DST:1, BN:6 };
// Neutral starting template for a new custom league — NOT any one league's
// settings. Raw stats are league-agnostic; each league's own scoring (entered
// in the editor) is applied to them dynamically, so these are just defaults to
// tweak. New categories default to "off"/common so they only count once set.
const DEFAULT_CUSTOM  = { passTD:4, passYds:25, passInt:-2, sackTaken:0, rushTD:6, rushYds:10, recTD:6, recYds:10, reception:0.5, twoPt:2, fumbleLost:-2, fumble:0, fumRetTD:6 };
const SCORING_LABELS  = { standard:'Standard', ppr:'PPR', 'half-ppr':'Half PPR', custom:'Custom' };
const PLATFORMS       = ['ESPN','Yahoo','Sleeper','NFL.com','Other'];
const POSITIONS       = ['QB','RB','WR','TE','K','DST'];

function makeLeague(o = {}) {
  return {
    id: 'l' + Date.now(),
    name: 'My League',
    platform: 'ESPN',
    numTeams: 10,
    draftPosition: 5,
    draftType: 'snake',
    auctionBudget: 200,
    scoringType: 'ppr',
    importedScoring: null,
    customScoring: { ...DEFAULT_CUSTOM },
    rosterSlots: { ...DEFAULT_SLOTS },
    ...o,
  };
}

// Build a league from the backend's profile config
function leagueFromBackendConfig(cfg) {
  if (!cfg) return null;
  const roster = cfg.roster || {};
  const draft = cfg.draft || {};
  let scoringType = 'standard';
  const rec = (cfg.scoring || {}).rec;
  if (rec >= 0.9) scoringType = 'ppr';
  else if (rec >= 0.4) scoringType = 'half-ppr';
  return makeLeague({
    id: 'l_default',
    name: 'My League',
    numTeams: cfg.teams || 10,
    draftPosition: draft.slot || 5,
    scoringType,
    importedScoring: cfg.scoring || null,
    rosterSlots: { ...DEFAULT_SLOTS, ...roster },
  });
}

// Saved browser drafts from older builds used "name|POS" ids. Migrate them as
// soon as the current player board arrives so renames and punctuation changes
// no longer orphan picks.
function migratePickIds(picksByLeague, players) {
  const aliases = {};
  (players || []).forEach(player => {
    aliases[player.id] = player.id;
    if (player.legacyId) aliases[player.legacyId] = player.id;
  });
  let changed = false;
  const migrated = {};
  Object.entries(picksByLeague || {}).forEach(([leagueId, leaguePicks]) => {
    migrated[leagueId] = (Array.isArray(leaguePicks) ? leaguePicks : []).map(pick => {
      const stableId = aliases[pick.playerId] || pick.playerId;
      if (stableId === pick.playerId) return pick;
      changed = true;
      return { ...pick, playerId: stableId };
    });
  });
  return changed ? migrated : picksByLeague;
}

// ─── SMALL SHARED UI ─────────────────────────────────────────────────────────
function Btn({ children, onClick, variant='primary', size='md', disabled, style={} }) {
  const base = {
    border: 'none', borderRadius: T.rsm, cursor: disabled ? 'not-allowed' : 'pointer',
    fontFamily: 'inherit', fontWeight: 600, transition: 'all .15s', display:'inline-flex',
    alignItems:'center', gap:6, opacity: disabled ? 0.5 : 1,
    padding: size === 'sm' ? '5px 10px' : '8px 16px',
    fontSize: size === 'sm' ? 12 : 14,
  };
  const variants = {
    primary:  { background: T.primary, color:'#fff' },
    ghost:    { background: 'transparent', color: T.muted, border: `1px solid ${T.border}` },
    danger:   { background: T.redLight, color: T.red },
    green:    { background: T.greenLight, color: T.green },
  };
  return (
    <button style={{...base,...variants[variant],...style}} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  );
}

function Badge({ label, color='blue' }) {
  const colors = {
    blue:  { bg: T.blueLight,  fg: T.blue },
    green: { bg: T.greenLight, fg: T.green },
    amber: { bg: T.amberLight, fg: T.amber },
    red:   { bg: T.redLight,   fg: T.red },
    gray:  { bg: T.borderLight,fg: T.muted },
  };
  const c = colors[color] || colors.gray;
  return (
    <span style={{
      background: c.bg, color: c.fg, borderRadius: 99, padding:'2px 8px',
      fontSize:11, fontWeight:700, letterSpacing:.3, whiteSpace:'nowrap',
    }}>{label}</span>
  );
}

function Modal({ title, onClose, children, width=560 }) {
  return (
    <div style={{
      position:'fixed', inset:0, background:'rgba(0,0,0,.35)', zIndex:1000,
      display:'flex', alignItems:'center', justifyContent:'center', padding:24,
    }} onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={{
        background: T.surface, borderRadius:14, width:'100%', maxWidth:width,
        maxHeight:'90vh', overflowY:'auto', boxShadow:'0 20px 60px rgba(0,0,0,.18)',
      }}>
        <div style={{
          padding:'20px 24px', borderBottom:`1px solid ${T.border}`,
          display:'flex', alignItems:'center', justifyContent:'space-between',
        }}>
          <span style={{fontSize:16, fontWeight:700, color:T.text}}>{title}</span>
          <button onClick={onClose} style={{
            background:'none', border:'none', fontSize:20, cursor:'pointer',
            color:T.muted, lineHeight:1, padding:'0 4px',
          }}>×</button>
        </div>
        <div style={{padding:24}}>{children}</div>
      </div>
    </div>
  );
}

function Field({ label, hint, children }) {
  return (
    <div style={{marginBottom:18}}>
      <label style={{display:'block', fontSize:13, fontWeight:600, color:T.text, marginBottom:5}}>
        {label}
        {hint && <span style={{fontWeight:400, color:T.muted, marginLeft:6}}>{hint}</span>}
      </label>
      {children}
    </div>
  );
}

function Input({ value, onChange, type='text', style={}, ...rest }) {
  return (
    <input type={type} value={value} onChange={onChange}
      style={{
        width:'100%', boxSizing:'border-box', padding:'8px 12px',
        border:`1.5px solid ${T.border}`, borderRadius:T.rsm, fontSize:14,
        color:T.text, background:T.surface, fontFamily:'inherit', outline:'none',
        ...style,
      }} {...rest}
    />
  );
}

function Select({ value, onChange, options, style={} }) {
  return (
    <select value={value} onChange={onChange}
      style={{
        width:'100%', boxSizing:'border-box', padding:'8px 12px',
        border:`1.5px solid ${T.border}`, borderRadius:T.rsm, fontSize:14,
        color:T.text, background:T.surface, fontFamily:'inherit', outline:'none',
        ...style,
      }}>
      {options.map(o => (
        <option key={o.value !== undefined ? o.value : o} value={o.value !== undefined ? o.value : o}>
          {o.label !== undefined ? o.label : o}
        </option>
      ))}
    </select>
  );
}

// Draft-order + "which team is mine" editor. teamNames is stored in DRAFT-SLOT
// order (index i == slot i+1 == snake seat), and draftPosition points at the
// owner's slot. Imports (ESPN/Yahoo) arrive in the platform's own order, which
// is NOT draft order — so the owner reorders here and marks their team by name
// instead of guessing a raw slot number.
function DraftOrderEditor({ numTeams, teamNames, draftPosition, onChange }) {
  const names = Array.from({ length: numTeams }, (_, i) => (teamNames || [])[i] || '');
  const [pasteOpen, setPasteOpen] = React.useState(false);
  const [dragFrom, setDragFrom] = React.useState(null);
  const [dragOver, setDragOver] = React.useState(null);

  const setName = (i, v) => {
    const next = names.slice(); next[i] = v;
    onChange({ teamNames: next });
  };
  const move = (from, to) => {
    if (to < 0 || to >= numTeams || from === to) return;
    const order = names.map((_, idx) => idx);
    const [picked] = order.splice(from, 1);
    order.splice(to, 0, picked);
    // Keep "Me" pinned to the same team as it moves between slots.
    const dp = draftPosition >= 1 && draftPosition <= numTeams
      ? order.indexOf(draftPosition - 1) + 1
      : draftPosition;
    onChange({ teamNames: order.map(idx => names[idx]), draftPosition: dp });
  };
  const swap = (i, j) => move(i, j);
  const bulkPaste = text =>
    onChange({ teamNames: text.split('\n').map(s => s.trim()).slice(0, numTeams) });

  const arrow = disabled => ({
    width:24, height:24, lineHeight:'20px', textAlign:'center', padding:0,
    border:`1.5px solid ${T.border}`, borderRadius:T.rxs, background:T.surface,
    color: disabled ? T.borderLight : T.muted, cursor: disabled ? 'default' : 'pointer',
    fontFamily:'inherit', fontSize:12,
  });

  return (
    <div>
      <div style={{display:'flex', justifyContent:'space-between', alignItems:'baseline', marginBottom:8}}>
        <div style={{fontSize:12, fontWeight:700, color:T.muted, letterSpacing:.5}}>
          DRAFT ORDER · MY TEAM
        </div>
        <button type="button" onClick={() => setPasteOpen(o => !o)} style={{
          border:'none', background:'none', color:T.primary, cursor:'pointer',
          fontFamily:'inherit', fontSize:12, fontWeight:600, padding:0,
        }}>{pasteOpen ? 'Close paste' : 'Paste list'}</button>
      </div>

      <div style={{display:'flex', flexDirection:'column', gap:6}}>
        {names.map((nm, i) => {
          const isMe = draftPosition === i + 1;
          const isDragged = dragFrom === i;
          const isDropTarget = dragOver === i && dragFrom !== null && dragFrom !== i;
          return (
            <div key={i}
              onDragOver={e => {
                if (dragFrom === null) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                if (dragOver !== i) setDragOver(i);
              }}
              onDrop={e => {
                e.preventDefault();
                if (dragFrom !== null) move(dragFrom, i);
                setDragFrom(null); setDragOver(null);
              }}
              style={{
                display:'flex', alignItems:'center', gap:8, padding:'6px 8px', borderRadius:T.rsm,
                border:`1.5px ${isDropTarget ? 'dashed' : 'solid'} ${isDropTarget ? T.primary : isMe ? T.primary : T.border}`,
                background: isMe ? T.primaryLight : T.surface,
                opacity: isDragged ? .45 : 1,
              }}>
              <span draggable title="Drag to reorder"
                onDragStart={e => {
                  e.dataTransfer.effectAllowed = 'move';
                  e.dataTransfer.setData('text/plain', String(i)); // Firefox refuses to drag without data
                  const row = e.currentTarget.parentElement;
                  const r = row.getBoundingClientRect();
                  e.dataTransfer.setDragImage(row, e.clientX - r.left, e.clientY - r.top);
                  setDragFrom(i);
                }}
                onDragEnd={() => { setDragFrom(null); setDragOver(null); }}
                style={{cursor:'grab', color:T.muted, fontSize:13, lineHeight:1, padding:'4px 2px', userSelect:'none'}}
              >⠿</span>
              <span style={{width:20, textAlign:'center', fontSize:12, fontWeight:700, color:T.muted}}>{i + 1}</span>
              <input value={nm} onChange={e => setName(i, e.target.value)} placeholder={`Team ${i + 1}`}
                style={{
                  flex:1, minWidth:0, padding:'6px 10px', border:`1.5px solid ${T.border}`,
                  borderRadius:T.rxs, fontSize:13, color:T.text, background:T.surface,
                  fontFamily:'inherit', outline:'none',
                }} />
              <button type="button" title="Move up" onClick={() => swap(i, i - 1)} disabled={i === 0} style={arrow(i === 0)}>↑</button>
              <button type="button" title="Move down" onClick={() => swap(i, i + 1)} disabled={i === numTeams - 1} style={arrow(i === numTeams - 1)}>↓</button>
              <button type="button" onClick={() => onChange({ draftPosition: i + 1 })} style={{
                padding:'5px 11px', borderRadius:T.rxs, cursor:'pointer', fontFamily:'inherit',
                fontSize:12, fontWeight:700, whiteSpace:'nowrap',
                border:`1.5px solid ${isMe ? T.primary : T.border}`,
                background: isMe ? T.primary : T.surface,
                color: isMe ? '#fff' : T.muted,
              }}>{isMe ? '● ME' : 'Me'}</button>
            </div>
          );
        })}
      </div>

      {pasteOpen && (
        <textarea
          defaultValue={(teamNames || []).join('\n')}
          onChange={e => bulkPaste(e.target.value)}
          placeholder={'One team name per line — fills the slots above top-to-bottom.'}
          rows={Math.min(numTeams, 6)}
          style={{
            width:'100%', boxSizing:'border-box', marginTop:8, padding:'8px 12px',
            border:`1.5px solid ${T.border}`, borderRadius:T.rsm, fontSize:13, color:T.text,
            background:T.surface, fontFamily:'inherit', outline:'none', resize:'vertical',
          }}
        />
      )}

      <div style={{fontSize:11, color:T.muted, marginTop:6, lineHeight:1.45}}>
        Order = draft slot 1…N (snake seats). Reorder to match your draft, then mark your own
        team with <b style={{color:T.text}}>Me</b>. ESPN/Yahoo imports auto-fill names in platform
        order — drag them into draft order here. Sleeper imports arrive already in draft order.
      </div>
    </div>
  );
}

// ─── LEAGUE SETUP MODAL ──────────────────────────────────────────────────────
function LeagueSetupModal({ league, onSave, onClose }) {
  const [form, setForm] = React.useState(league
    ? {...league, rosterSlots:{...league.rosterSlots}, customScoring:{...DEFAULT_CUSTOM, ...league.customScoring}}
    : makeLeague());
  const set = (k, v) => setForm(f => ({...f, [k]: v}));
  const setSlot = (k, v) => setForm(f => ({...f, rosterSlots:{...f.rosterSlots, [k]: parseInt(v)||0}}));
  const setCustom = (k, v) => setForm(f => ({...f, customScoring:{...f.customScoring, [k]: parseFloat(v)||0}}));

  // Auto-fill the form from a public ESPN league (teams, roster, scoring, names).
  const [espnId, setEspnId] = React.useState(form.espnLeagueId || '');
  const [importing, setImporting] = React.useState(false);
  const [importMsg, setImportMsg] = React.useState(null);
  const importEspn = () => {
    const id = espnId.trim();
    if (!id) return;
    setImporting(true); setImportMsg(null);
    fetch('/api/import-espn', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ leagueId: id }),
    })
      .then(r => r.json())
      .then(d => {
        if (d.error) { setImportMsg({ ok: false, text: d.error }); return; }
        setForm(f => ({
          ...f,
          name: d.name || f.name,
          platform: 'ESPN',
          numTeams: d.numTeams || f.numTeams,
          scoringType: d.scoringType || f.scoringType,
          importedScoring: d.scoring || null,
          rosterSlots: { ...DEFAULT_SLOTS, ...(d.rosterSlots || {}) },
          teamNames: d.teamNames || [],
          espnLeagueId: d.espnLeagueId || id,
        }));
        setImportMsg({ ok: true,
          text: `Imported "${d.name}" — ${d.numTeams} teams, ${(d.teamNames || []).length} names, ${d.scoringType}` });
      })
      .catch(() => setImportMsg({ ok: false, text: 'Import failed — is the league public?' }))
      .finally(() => setImporting(false));
  };

  // ── Sleeper import (public API — a username or a league id is all it takes) ──
  const [sl, setSl] = React.useState({
    username: '', leagueId: form.sleeperLeagueId || '', leagues: null,
    busy: false, msg: null,
  });
  const slSet = patch => setSl(s => ({ ...s, ...patch }));
  const slPost = (url, body, onOk) => {
    slSet({ busy: true, msg: null });
    fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(r => r.json())
      .then(d => { if (d.error) slSet({ msg: { ok: false, text: d.error } }); else onOk(d); })
      .catch(() => slSet({ msg: { ok: false, text: 'Request failed' } }))
      .finally(() => setSl(s => ({ ...s, busy: false })));
  };
  const sleeperFindLeagues = () => {
    if (!sl.username.trim()) { slSet({ msg: { ok: false, text: 'Enter your Sleeper username' } }); return; }
    slPost('/api/sleeper/leagues', { username: sl.username.trim() }, d => {
      const lgs = d.leagues || [];
      slSet({
        leagues: lgs,
        leagueId: (lgs[0] && lgs[0].leagueId) || '',
        msg: { ok: lgs.length > 0, text: lgs.length ? `Found ${lgs.length} league(s) for ${d.season}.` : 'No leagues found for that username.' },
      });
    });
  };
  const sleeperImport = () => {
    const id = (sl.leagueId || '').trim();
    if (!id) return;
    slPost('/api/sleeper/import', { leagueId: id, username: sl.username.trim() || undefined }, d => {
      setForm(f => ({
        ...f,
        name: d.name || f.name,
        platform: 'Sleeper',
        numTeams: d.numTeams || f.numTeams,
        scoringType: d.scoringType || f.scoringType,
        importedScoring: d.scoring || null,
        rosterSlots: { ...DEFAULT_SLOTS, ...(d.rosterSlots || {}) },
        teamNames: d.teamNames || [],
        sleeperLeagueId: d.sleeperLeagueId || id,
        sleeperDraftId: d.sleeperDraftId || null,
        draftType: d.draftType || f.draftType,
        // Sleeper knows the real seating, so the draft slot comes back too.
        draftPosition: d.draftPosition || f.draftPosition,
      }));
      const seat = d.draftPosition ? `, your seat #${d.draftPosition}` : '';
      slSet({ leagueId: d.sleeperLeagueId || id, msg: { ok: true,
        text: `Imported "${d.name}" — ${d.numTeams} teams${seat}, ${d.scoringType}${d.sleeperDraftId ? ' · draft linked' : ''}` } });
    });
  };

  // ── Yahoo OAuth import (multi-step: credentials -> authorize -> pick league) ──
  const [yh, setYh] = React.useState({
    clientId: '', clientSecret: '', redirectUri: 'https://localhost/',
    authUrl: '', code: '', leagues: null, leagueKey: '', busy: false, msg: null,
    credsSaved: false, showCredForm: false,
  });
  const yhSet = patch => setYh(s => ({ ...s, ...patch }));
  // Pick up credentials already saved on this machine (so re-auth is one click).
  React.useEffect(() => {
    fetch('/api/yahoo/status').then(r => r.json()).then(d => {
      if (d && d.hasCredentials) yhSet({ credsSaved: true, redirectUri: d.redirectUri || 'https://localhost/' });
    }).catch(() => {});
  }, []);
  const yhPost = (url, body, onOk) => {
    yhSet({ busy: true, msg: null });
    fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(r => r.json())
      .then(d => { if (d.error) yhSet({ msg: { ok: false, text: d.error } }); else onOk(d); })
      .catch(() => yhSet({ msg: { ok: false, text: 'Request failed' } }))
      .finally(() => setYh(s => ({ ...s, busy: false })));
  };
  const yahooConnect = () => {
    const useStored = yh.credsSaved && !yh.showCredForm;
    if (!useStored && (!yh.clientId.trim() || !yh.clientSecret.trim())) { yhSet({ msg: { ok: false, text: 'Enter Client ID and Secret' } }); return; }
    const body = useStored
      ? { redirectUri: yh.redirectUri.trim() }
      : { clientId: yh.clientId.trim(), clientSecret: yh.clientSecret.trim(), redirectUri: yh.redirectUri.trim() };
    yhPost('/api/yahoo/connect', body,
      d => { yhSet({ authUrl: d.authUrl, msg: { ok: true, text: 'Authorize in the opened tab, then paste the code below.' } }); window.open(d.authUrl, '_blank'); });
  };
  const yahooExchange = () => {
    if (!yh.code.trim()) { yhSet({ msg: { ok: false, text: 'Paste the authorization code' } }); return; }
    yhPost('/api/yahoo/exchange', { code: yh.code.trim() }, d => {
      const lgs = d.leagues || [];
      yhSet({ leagues: lgs, leagueKey: (lgs[0] && lgs[0].league_key) || '', msg: { ok: true, text: `Connected — ${lgs.length} league(s) found.` } });
    });
  };
  const yahooImport = () => {
    if (!yh.leagueKey) return;
    yhPost('/api/yahoo/import', { leagueKey: yh.leagueKey }, d => {
      setForm(f => ({
        ...f, name: d.name || f.name, platform: 'Yahoo', numTeams: d.numTeams || f.numTeams,
        scoringType: d.scoringType || f.scoringType, rosterSlots: { ...DEFAULT_SLOTS, ...(d.rosterSlots || {}) },
        importedScoring: d.scoring || null,
        teamNames: d.teamNames || [], yahooLeagueKey: d.yahooLeagueKey,
      }));
      yhSet({ msg: { ok: true, text: `Imported "${d.name}" — ${d.numTeams} teams, ${(d.teamNames || []).length} names, ${d.scoringType}` } });
    });
  };

  const FLEX_SLOT_LABELS = { WRTE:'W/T flex', RBWR:'R/W flex', SUPERFLEX:'Superflex', OP:'Superflex' };
  const slotFields = [
    {k:'QB',label:'QB'},{k:'RB',label:'RB'},{k:'WR',label:'WR'},
    {k:'TE',label:'TE'},{k:'FLEX',label:'FLEX (RB/WR/TE)'},
    // Typed flex slots present on this league (e.g. an imported WR/TE slot).
    ...Object.keys(FLEX_SLOT_LABELS)
      .filter(fk => (form.rosterSlots[fk] || 0) > 0)
      .map(fk => ({ k: fk, label: FLEX_SLOT_LABELS[fk] })),
    {k:'K',label:'K'},{k:'DST',label:'DST'},{k:'BN',label:'Bench'},
  ];

  return (
    <Modal title={league ? 'Edit League' : 'Add New League'} onClose={onClose} width={600}>
      <div style={{marginBottom:16, padding:12, background:T.surfaceAlt, borderRadius:T.r, border:`1px solid ${T.border}`}}>
        <div style={{fontSize:12, fontWeight:700, color:T.muted, marginBottom:8, letterSpacing:.5}}>
          IMPORT FROM ESPN (public league)
        </div>
        <div style={{display:'flex', gap:8, alignItems:'center'}}>
          <Input value={espnId} onChange={e=>setEspnId(e.target.value)}
            placeholder="ESPN League ID (e.g. 75034031)" style={{flex:1}} />
          <Btn variant="ghost" onClick={importEspn} disabled={importing || !espnId.trim()}>
            {importing ? 'Importing…' : 'Import'}
          </Btn>
        </div>
        {importMsg && (
          <div style={{marginTop:8, fontSize:12, color: importMsg.ok ? T.primary : '#c0392b'}}>
            {(importMsg.ok ? '✓ ' : '⚠ ') + importMsg.text}
          </div>
        )}
        <div style={{marginTop:6, fontSize:11, color:T.muted}}>
          Auto-fills teams, roster, scoring, and your league-mates' names. Find the ID in your
          ESPN league URL (…/leagues/<b>THIS</b>).
        </div>
      </div>

      <div style={{marginBottom:16, padding:12, background:T.surfaceAlt, borderRadius:T.r, border:`1px solid ${T.border}`}}>
        <div style={{fontSize:12, fontWeight:700, color:T.muted, marginBottom:8, letterSpacing:.5}}>
          IMPORT FROM SLEEPER (no login needed)
        </div>
        <div style={{display:'flex', gap:8, alignItems:'center'}}>
          <Input value={sl.username} onChange={e=>slSet({username:e.target.value})}
            placeholder="Sleeper username" style={{flex:1}} />
          <Btn variant="ghost" onClick={sleeperFindLeagues} disabled={sl.busy || !sl.username.trim()}>
            {sl.busy ? '…' : 'Find leagues'}
          </Btn>
        </div>
        <div style={{display:'flex', gap:8, alignItems:'center', marginTop:8}}>
          <div style={{flex:1}}>
            {sl.leagues && sl.leagues.length ? (
              <Select value={sl.leagueId} onChange={e=>slSet({leagueId:e.target.value})}
                options={sl.leagues.map(l=>({value:l.leagueId, label:`${l.name} (${l.season}, ${l.totalRosters} teams)`}))} />
            ) : (
              <Input value={sl.leagueId} onChange={e=>slSet({leagueId:e.target.value})}
                placeholder="…or paste a Sleeper League ID" />
            )}
          </div>
          <Btn variant="ghost" onClick={sleeperImport} disabled={sl.busy || !(sl.leagueId||'').trim()}>Import</Btn>
        </div>
        {sl.msg && (
          <div style={{marginTop:8, fontSize:12, color: sl.msg.ok ? T.primary : '#c0392b'}}>
            {(sl.msg.ok ? '✓ ' : '⚠ ') + sl.msg.text}
          </div>
        )}
        <div style={{marginTop:6, fontSize:11, color:T.muted, lineHeight:1.45}}>
          Imports teams, roster, scoring, and league-mates — with names already in <b>draft-slot
          order</b> and your own seat set for you. Links the draft too, so the board can follow
          picks live from the draft screen.
        </div>
      </div>

      <div style={{marginBottom:16, padding:12, background:T.surfaceAlt, borderRadius:T.r, border:`1px solid ${T.border}`}}>
        <div style={{fontSize:12, fontWeight:700, color:T.muted, marginBottom:8, letterSpacing:.5}}>
          IMPORT FROM YAHOO (OAuth)
        </div>
        {!yh.leagues ? (
          <>
            {yh.credsSaved && !yh.showCredForm ? (
              <div style={{fontSize:12, color:T.text, marginBottom:4}}>
                ✓ Yahoo credentials saved on this machine.{' '}
                <a onClick={()=>yhSet({showCredForm:true})} style={{color:T.muted, cursor:'pointer', textDecoration:'underline'}}>use different</a>
              </div>
            ) : (
              <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8}}>
                <Input value={yh.clientId} onChange={e=>yhSet({clientId:e.target.value})} placeholder="Client ID (Consumer Key)" />
                <Input value={yh.clientSecret} onChange={e=>yhSet({clientSecret:e.target.value})} placeholder="Client Secret" type="password" />
              </div>
            )}
            <div style={{display:'flex', gap:8, marginTop:8, alignItems:'center'}}>
              <Input value={yh.redirectUri} onChange={e=>yhSet({redirectUri:e.target.value})} placeholder="Redirect URI" style={{flex:1}} />
              <Btn variant="ghost" onClick={yahooConnect} disabled={yh.busy}>{yh.busy?'…':(yh.credsSaved && !yh.showCredForm ?'Get authorize link':'Get link')}</Btn>
            </div>
            {yh.authUrl && (
              <div style={{marginTop:8}}>
                <a href={yh.authUrl} target="_blank" rel="noreferrer" style={{fontSize:12, color:T.primary, fontWeight:600}}>
                  Open Yahoo authorize page ↗
                </a>
                <div style={{display:'flex', gap:8, marginTop:8, alignItems:'center'}}>
                  <Input value={yh.code} onChange={e=>yhSet({code:e.target.value})} placeholder="Paste authorization code" style={{flex:1}} />
                  <Btn variant="ghost" onClick={yahooExchange} disabled={yh.busy}>Connect</Btn>
                </div>
              </div>
            )}
          </>
        ) : (
          <div style={{display:'flex', gap:8, alignItems:'center'}}>
            <div style={{flex:1}}>
              <Select value={yh.leagueKey} onChange={e=>yhSet({leagueKey:e.target.value})}
                options={yh.leagues.map(l=>({value:l.league_key, label:`${l.name}${l.season?` (${l.season})`:''}`}))} />
            </div>
            <Btn variant="ghost" onClick={yahooImport} disabled={yh.busy || !yh.leagueKey}>Import</Btn>
          </div>
        )}
        {yh.msg && (
          <div style={{marginTop:8, fontSize:12, color: yh.msg.ok ? T.primary : '#c0392b'}}>
            {(yh.msg.ok ? '✓ ' : '⚠ ') + yh.msg.text}
          </div>
        )}
        <div style={{marginTop:6, fontSize:11, color:T.muted, lineHeight:1.45}}>
          Register a free app at developer.yahoo.com (Installed App · Fantasy → Read · redirect
          <b> https://localhost/</b>). After authorizing, copy the <b>code</b> from the address bar.
          Imports settings + names (Yahoo has no projections — those stay from the consensus). Your
          secret is stored only on this machine.
        </div>
      </div>

      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:16}}>
        <Field label="League Name">
          <Input value={form.name} onChange={e=>set('name',e.target.value)} />
        </Field>
        <Field label="Platform">
          <Select value={form.platform} onChange={e=>set('platform',e.target.value)}
            options={PLATFORMS.map(p=>({value:p,label:p}))} />
        </Field>
        <Field label="Teams">
          <Select value={form.numTeams} onChange={e=>set('numTeams',parseInt(e.target.value))}
            options={[8,10,12,14,16,18,20].map(n=>({value:n,label:`${n} teams`}))} />
        </Field>
        <Field label="My Team">
          {(form.teamNames || []).some(Boolean) ? (
            <Select value={form.draftPosition}
              onChange={e=>set('draftPosition',parseInt(e.target.value)||1)}
              options={Array.from({length: form.numTeams}, (_, i) => {
                const nm = (form.teamNames || [])[i];
                return { value: i+1, label: nm ? `${i+1} — ${nm}` : `${i+1} — (slot ${i+1})` };
              })} />
          ) : (
            <Input type="number" value={form.draftPosition}
              onChange={e=>set('draftPosition',parseInt(e.target.value)||1)}
              min={1} max={form.numTeams} />
          )}
        </Field>
      </div>

      <Field label="Scoring Format">
        <div style={{display:'flex', gap:8}}>
          {Object.entries(SCORING_LABELS).map(([v,l]) => (
            <label key={v} style={{
              flex:1, border:`1.5px solid ${form.scoringType===v ? T.primary : T.border}`,
              borderRadius:T.rsm, padding:'8px 12px', cursor:'pointer', textAlign:'center',
              background: form.scoringType===v ? T.primaryLight : T.surface,
              color: form.scoringType===v ? T.primary : T.text,
              fontSize:13, fontWeight:600,
            }}>
              <input type="radio" name="scoring" value={v} checked={form.scoringType===v}
                onChange={()=>set('scoringType',v)} style={{display:'none'}} />
              {l}
            </label>
          ))}
        </div>
      </Field>

      <Field label="Draft Type">
        <div style={{display:'flex', gap:8, alignItems:'center'}}>
          {[['snake','Snake'],['auction','Auction']].map(([v,l]) => (
            <label key={v} style={{
              flex:1, border:`1.5px solid ${(form.draftType||'snake')===v ? T.primary : T.border}`,
              borderRadius:T.rsm, padding:'8px 12px', cursor:'pointer', textAlign:'center',
              background: (form.draftType||'snake')===v ? T.primaryLight : T.surface,
              color: (form.draftType||'snake')===v ? T.primary : T.text,
              fontSize:13, fontWeight:600,
            }}>
              <input type="radio" name="draftType" value={v} checked={(form.draftType||'snake')===v}
                onChange={()=>set('draftType',v)} style={{display:'none'}} />
              {l}
            </label>
          ))}
          {(form.draftType||'snake') === 'auction' && (
            <div style={{flex:1, display:'flex', alignItems:'center', gap:6}}>
              <span style={{fontSize:12, fontWeight:600, color:T.muted, whiteSpace:'nowrap'}}>Budget $</span>
              <Input type="number" value={form.auctionBudget || 200} min={1}
                onChange={e=>set('auctionBudget', Math.max(1, parseInt(e.target.value)||200))} />
            </div>
          )}
        </div>
      </Field>

      {form.scoringType === 'custom' && (
        <div style={{marginTop:16, padding:16, background:T.surfaceAlt, borderRadius:T.r, border:`1px solid ${T.border}`}}>
          <div style={{fontSize:12, fontWeight:700, color:T.muted, marginBottom:12, letterSpacing:.5}}>CUSTOM SCORING</div>
          <div style={{display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:12}}>
            {[
              {k:'passTD', l:'Pass TD'},
              {k:'passYds', l:'Yds/Pass Pt', hint:'yds per 1 pt'},
              {k:'passInt', l:'Interception'},
              {k:'sackTaken', l:'Sack (off)', hint:'per QB sack'},
              {k:'rushTD', l:'Rush TD'},
              {k:'rushYds', l:'Yds/Rush Pt', hint:'yds per 1 pt'},
              {k:'recTD', l:'Rec TD'},
              {k:'recYds', l:'Yds/Rec Pt', hint:'yds per 1 pt'},
              {k:'reception', l:'Reception (PPR)', step:0.05, hint:'e.g. 0.25'},
              {k:'twoPt', l:'2-PT Conv'},
              {k:'fumbleLost', l:'Fumble Lost'},
              {k:'fumble', l:'Fumble', hint:'any fumble'},
              {k:'fumRetTD', l:'Off Fum Ret TD'},
            ].map(({k,l,hint,step}) => (
              <Field key={k} label={l} hint={hint}>
                <Input type="number" value={form.customScoring[k]}
                  onChange={e=>setCustom(k,e.target.value)} step={step||0.5} />
              </Field>
            ))}
          </div>
        </div>
      )}

      <div style={{marginTop:20}}>
        <div style={{fontSize:12, fontWeight:700, color:T.muted, marginBottom:12, letterSpacing:.5}}>ROSTER SLOTS</div>
        <div style={{display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:12}}>
          {slotFields.map(({k,label}) => (
            <Field key={k} label={label}>
              <Input type="number" value={form.rosterSlots[k]||0}
                onChange={e=>setSlot(k,e.target.value)} min={0} max={10} />
            </Field>
          ))}
        </div>
      </div>

      <div style={{marginTop:20}}>
        <DraftOrderEditor
          numTeams={form.numTeams}
          teamNames={form.teamNames}
          draftPosition={form.draftPosition}
          onChange={patch => setForm(f => ({ ...f, ...patch }))}
        />
      </div>

      <div style={{display:'flex', justifyContent:'flex-end', gap:10, marginTop:24, paddingTop:20, borderTop:`1px solid ${T.border}`}}>
        <Btn variant="ghost" onClick={onClose}>Cancel</Btn>
        <Btn onClick={() => onSave(form)}>Save League</Btn>
      </div>
    </Modal>
  );
}

// ─── TASK POLLING HOOK ────────────────────────────────────────────────────────
function useTask() {
  const [taskId, setTaskId] = React.useState(null);
  const [status, setStatus] = React.useState(null); // null | 'running' | 'done' | 'error'
  const [result, setResult] = React.useState(null);
  const [error,  setError]  = React.useState(null);

  React.useEffect(() => {
    if (!taskId) return;
    setStatus('running');
    setResult(null);
    setError(null);
    let cancelled = false;
    const poll = () => {
      fetch(`/api/task/${taskId}`)
        .then(r => r.json())
        .then(data => {
          if (cancelled) return;
          if (data.status === 'running') {
            setTimeout(poll, 800);
          } else if (data.status === 'done') {
            setStatus('done');
            setResult(data.result);
          } else {
            setStatus('error');
            setError(data.error || 'Unknown error');
          }
        })
        .catch(err => {
          if (!cancelled) { setStatus('error'); setError(String(err)); }
        });
    };
    poll();
    return () => { cancelled = true; };
  }, [taskId]);

  const start = (id) => { setTaskId(id); };
  const reset = () => { setTaskId(null); setStatus(null); setResult(null); setError(null); };
  return { start, reset, status, result, error };
}

// Map a league's scoring type to the ADP board format (FFC/Sleeper publish
// separate ADP lists per format). Projections are raw stats either way.
function adpFormatForLeague(league) {
  if (!league) return 'ppr';
  if (league.scoringType === 'custom') {
    const rec = (league.customScoring && league.customScoring.reception) || 0;
    return rec >= 0.75 ? 'ppr' : rec >= 0.25 ? 'half-ppr' : 'standard';
  }
  return league.scoringType || 'ppr';
}

// ─── PULL DATA MODAL ─────────────────────────────────────────────────────────
function PullDataModal({ league, espnLeagueId, onClose, onComplete }) {
  const currentYear = new Date().getFullYear();
  const [mode, setMode]         = React.useState('free');
  const [season, setSeason]     = React.useState(currentYear);
  const [statsSeason, setStats] = React.useState(currentYear - 1);
  const [skipFf, setSkipFf]     = React.useState(false);
  const [history, setHistory]   = React.useState(3);
  const task = useTask();

  // ADP board + league size derived from league settings — not user-facing.
  const adpFormat = adpFormatForLeague(league);
  const teams     = (league && league.numTeams) || 12;

  const handlePull = () => {
    const endpoint = mode === 'free' ? '/api/pull-free-data' : '/api/collect-all';
    // Fold an imported ESPN league's projections into the consensus automatically.
    // Full Collect runs the same free-source pull and then enriches it, so both
    // modes take the identical options — sending less would shrink the board.
    const body = { season, statsSeason, history, teams, adpFormat,
                   scoring: adpFormat, skipFftoday: skipFf, espnLeagueId };
    fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) { alert(data.error); return; }
        task.start(data.taskId);
      })
      .catch(err => alert(String(err)));
  };

  const handleDone = () => {
    task.reset();
    onComplete();
    onClose();
  };

  return (
    <Modal title="Pull Player Data" onClose={onClose} width={520}>
      {task.status === 'running' && (
        <div style={{textAlign:'center', padding:'40px 0'}}>
          <div className="loading-spinner" style={{margin:'0 auto 16px'}} />
          <div style={{fontSize:14, fontWeight:600, color:T.text}}>Pulling data...</div>
          <div style={{fontSize:12, color:T.muted, marginTop:4}}>This may take 30-60 seconds.</div>
        </div>
      )}

      {task.status === 'done' && (
        <div style={{textAlign:'center', padding:'30px 0'}}>
          <div style={{fontSize:28, marginBottom:12, color:T.green}}>&#10003;</div>
          <div style={{fontSize:16, fontWeight:700, color:T.text, marginBottom:8}}>Data Pulled Successfully</div>
          <div style={{fontSize:14, color:T.muted, marginBottom:6}}>
            {task.result?.players} players loaded
          </div>
          {task.result?.consensusPlayers > 0 && (
            <div style={{fontSize:12, color:T.muted, marginBottom:6}}>
              Consensus projections: {task.result.consensusPlayers} players
            </div>
          )}
          {task.result?.historySeasons?.length > 0 && (
            <div style={{fontSize:12, color:T.muted, marginBottom:6}}>
              History seasons kept: {task.result.historySeasons.join(', ')}
            </div>
          )}
          {task.result?.warnings?.length > 0 && (
            <div style={{textAlign:'left', margin:'14px auto 0', maxWidth:400, background:T.amberLight,
              border:`1.5px solid ${T.amber}`, borderRadius:T.rsm, padding:'10px 14px'}}>
              <div style={{fontSize:13, fontWeight:700, color:T.amber, marginBottom:4}}>
                &#9888; Single-source projections
              </div>
              {task.result.warnings.map((w, i) => (
                <div key={i} style={{fontSize:12, color:T.text, lineHeight:1.5}}>{w}</div>
              ))}
            </div>
          )}
          {task.result?.reports && (
            <div style={{textAlign:'left', margin:'16px auto', maxWidth:400, background:T.surfaceAlt,
              borderRadius:T.rsm, padding:12, fontSize:12}}>
              {task.result.reports.map((r, i) => (
                <div key={i} style={{display:'flex', justifyContent:'space-between', padding:'3px 0',
                  color: r.ok ? T.text : T.muted}}>
                  <span>{r.source}</span>
                  <span>{r.ok ? `${r.records} records` : 'skipped'}</span>
                </div>
              ))}
            </div>
          )}
          <Btn onClick={handleDone}>Done</Btn>
        </div>
      )}

      {task.status === 'error' && (
        <div style={{textAlign:'center', padding:'30px 0'}}>
          <div style={{fontSize:28, marginBottom:12, color:T.red}}>!</div>
          <div style={{fontSize:14, fontWeight:600, color:T.red, marginBottom:8}}>Pull Failed</div>
          <div style={{fontSize:12, color:T.muted, marginBottom:16, maxWidth:400, margin:'0 auto 16px',
            wordBreak:'break-word'}}>{task.error}</div>
          <div style={{display:'flex', gap:8, justifyContent:'center'}}>
            <Btn variant="ghost" onClick={() => task.reset()}>Try Again</Btn>
            <Btn variant="ghost" onClick={onClose}>Close</Btn>
          </div>
        </div>
      )}

      {!task.status && (
        <>
          <Field label="Data Source">
            <div style={{display:'flex', gap:8}}>
              {[
                {v:'free', l:'Free Sources', hint:'No dependencies'},
                {v:'full', l:'Full Collect', hint:'Free sources + nfl_data_py'},
              ].map(({v, l, hint}) => (
                <label key={v} style={{
                  flex:1, border:`1.5px solid ${mode===v ? T.primary : T.border}`,
                  borderRadius:T.rsm, padding:'10px 14px', cursor:'pointer',
                  background: mode===v ? T.primaryLight : T.surface,
                }}>
                  <input type="radio" name="pullMode" value={v} checked={mode===v}
                    onChange={() => setMode(v)} style={{display:'none'}} />
                  <div style={{fontSize:13, fontWeight:600, color: mode===v ? T.primary : T.text}}>{l}</div>
                  <div style={{fontSize:11, color:T.muted, marginTop:2}}>{hint}</div>
                </label>
              ))}
            </div>
          </Field>

          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:16}}>
            <Field label="Projection Season">
              <Input type="number" value={season} onChange={e => setSeason(parseInt(e.target.value) || currentYear)} />
            </Field>
            <Field label="Stats Season" hint="most recent">
              <Input type="number" value={statsSeason} onChange={e => setStats(parseInt(e.target.value) || currentYear-1)} />
            </Field>
            <Field label="History Seasons" hint="years of stats">
              <Input type="number" value={history} onChange={e => setHistory(parseInt(e.target.value) || 3)}
                min={1} max={5} />
            </Field>
          </div>

          <div style={{marginTop:8}}>
            <label style={{display:'flex', alignItems:'center', gap:8, fontSize:13, color:T.text, cursor:'pointer'}}>
              <input type="checkbox" checked={skipFf} onChange={e => setSkipFf(e.target.checked)} />
              Skip FFToday scraping
            </label>
            <div style={{fontSize:11, color:T.muted, marginTop:4, marginLeft:24, lineHeight:1.4}}>
              FFToday is the only source pulled by scraping web pages — the rest are fast
              JSON/CSV feeds — so it's the slowest, most fragile step. Skip it for a quicker
              pull; leave it on to add another projection source that fills gaps. Either way,
              if it fails the pull still completes.
            </div>
          </div>

          <div style={{
            marginTop:16, padding:'10px 14px', background:T.surfaceAlt,
            border:`1px solid ${T.border}`, borderRadius:T.rsm, fontSize:12, color:T.muted, lineHeight:1.5,
          }}>
            Projections are pulled as raw stats — your league's scoring is applied
            automatically and updates in real time when you change league settings.
            ADP board matched to your league: <b style={{color:T.text}}>
            {adpFormat === 'ppr' ? 'PPR' : adpFormat === 'half-ppr' ? 'Half PPR' : 'Standard'} · {Math.min(teams,14)} teams</b>
          </div>

          <div style={{display:'flex', justifyContent:'flex-end', gap:10, marginTop:24, paddingTop:20, borderTop:`1px solid ${T.border}`}}>
            <Btn variant="ghost" onClick={onClose}>Cancel</Btn>
            <Btn onClick={handlePull}>Pull Data</Btn>
          </div>
        </>
      )}
    </Modal>
  );
}

// ─── AUCTION MODAL ───────────────────────────────────────────────────────────
function AuctionModal({ league, onClose }) {
  const [budget, setBudget] = React.useState((league && league.auctionBudget) || 200);
  const [topN, setTopN]     = React.useState(50);
  const [data, setData]     = React.useState(null);
  const [loading, setLoading] = React.useState(false);

  const handleFetch = () => {
    setLoading(true);
    // Send the league's settings so values reflect ITS teams/roster/scoring,
    // not the server profile defaults (same override shape as /api/suggest).
    fetch('/api/auction', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        budget, top: topN,
        league: league ? {
          numTeams: league.numTeams,
          rosterSlots: league.rosterSlots,
          scoringType: league.scoringType,
          customScoring: league.customScoring,
          importedScoring: league.importedScoring,
        } : undefined,
      }),
    })
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(err => { alert(String(err)); setLoading(false); });
  };

  React.useEffect(() => { handleFetch(); }, []);

  const posColors = {
    QB: T.amberLight, RB: '#dcfce7', WR: '#dbeafe', TE: '#ede9fe', K: '#f3f4f6', DST: '#fce7f3',
  };

  return (
    <Modal title={league ? `Auction Values — ${league.name}` : 'Auction Values'} onClose={onClose} width={560}>
      <div style={{display:'flex', gap:12, marginBottom:16, alignItems:'flex-end'}}>
        <Field label="Budget per Team">
          <Input type="number" value={budget} onChange={e => setBudget(parseInt(e.target.value) || 200)}
            style={{width:100}} />
        </Field>
        <Field label="Show Top">
          <Input type="number" value={topN} onChange={e => setTopN(parseInt(e.target.value) || 50)}
            style={{width:80}} />
        </Field>
        <Btn onClick={handleFetch} disabled={loading} style={{marginBottom:18}}>Refresh</Btn>
      </div>

      {loading && <div style={{textAlign:'center', padding:20, color:T.muted}}>Loading...</div>}

      {data && data.values && (
        <div style={{maxHeight:400, overflowY:'auto'}}>
          <table style={{width:'100%', borderCollapse:'collapse', fontSize:13}}>
            <thead>
              <tr style={{borderBottom:`2px solid ${T.border}`, fontSize:11, fontWeight:700, color:T.muted}}>
                <th style={{textAlign:'left', padding:'6px 8px'}}>#</th>
                <th style={{textAlign:'left', padding:'6px 8px'}}>Player</th>
                <th style={{textAlign:'left', padding:'6px 8px'}}>Pos</th>
                <th style={{textAlign:'left', padding:'6px 8px'}}>Team</th>
                <th style={{textAlign:'right', padding:'6px 8px'}}>Value</th>
              </tr>
            </thead>
            <tbody>
              {data.values.map((v, i) => (
                <tr key={i} style={{borderBottom:`1px solid ${T.borderLight}`}}>
                  <td style={{padding:'5px 8px', color:T.mutedLight, fontSize:12}}>{i+1}</td>
                  <td style={{padding:'5px 8px', fontWeight:600}}>{v.name}</td>
                  <td style={{padding:'5px 8px'}}>
                    <span style={{background:posColors[v.pos]||T.borderLight, borderRadius:4,
                      padding:'1px 6px', fontSize:11, fontWeight:700}}>{v.pos}</span>
                  </td>
                  <td style={{padding:'5px 8px', color:T.muted}}>{v.team}</td>
                  <td style={{padding:'5px 8px', textAlign:'right', fontWeight:700, fontFamily:'DM Mono,monospace',
                    color:v.value >= 20 ? T.green : T.text}}>${v.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
}

// ─── FREE AGENT FINDER ───────────────────────────────────────────────────────
function FreeAgentPosBadge({ pos }) {
  const colors = {
    QB:  { bg:'#fef3c7', fg:'#92400e' },
    RB:  { bg:'#dcfce7', fg:'#14532d' },
    WR:  { bg:'#dbeafe', fg:'#1e3a8a' },
    TE:  { bg:'#ede9fe', fg:'#4c1d95' },
    K:   { bg:'#f3f4f6', fg:'#374151' },
    DST: { bg:'#fce7f3', fg:'#831843' },
  };
  const c = colors[pos] || { bg: T.borderLight, fg: T.muted };
  return (
    <span style={{
      background:c.bg, color:c.fg, borderRadius:T.rxs, padding:'2px 7px',
      fontSize:11, fontWeight:800, display:'inline-block', minWidth:32, textAlign:'center',
    }}>{pos}</span>
  );
}

function FreeAgentFinderModal({ leagues, picks, onClose, initialLeagueId }) {
  const [topN, setTopN] = React.useState(6);
  const [filter, setFilter] = React.useState(initialLeagueId || 'ALL');
  const [horizon, setHorizon] = React.useState('weekly');
  const [week, setWeek] = React.useState(1);
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [refreshingContext, setRefreshingContext] = React.useState(false);
  const [error, setError] = React.useState(null);

  const scan = React.useCallback(() => {
    setLoading(true);
    setError(null);
    fetch('/api/free-agents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ leagues: leagues || [], picks: picks || {}, top: topN, week }),
    })
      .then(r => r.json())
      .then(d => {
        if (d.error) { setError(d.error); setData(null); return; }
        setData(d);
      })
      .catch(err => setError(String(err)))
      .finally(() => setLoading(false));
  }, [leagues, picks, topN, week]);

  React.useEffect(() => { scan(); }, [scan]);

  const refreshUpdates = () => {
    setRefreshingContext(true);
    setError(null);
    fetch('/api/context/refresh', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({week, force:true}),
    }).then(r => r.json()).then(started => {
      if (started.error) throw new Error(started.error);
      const poll = () => fetch(`/api/task/${started.taskId}`).then(r => r.json()).then(task => {
        if (task.status === 'done') { setRefreshingContext(false); scan(); return; }
        if (task.status === 'error') throw new Error(task.error || 'Update refresh failed');
        setTimeout(poll, 1000);
      });
      poll().catch(err => { setRefreshingContext(false); setError(String(err)); });
    }).catch(err => { setRefreshingContext(false); setError(String(err)); });
  };

  const fmt = n => {
    const v = Number(n || 0);
    return `${v >= 0 ? '+' : ''}${v.toFixed(1)}`;
  };

  const leagueRows = (data && data.leagues) || [];
  const visibleLeagues = filter === 'ALL'
    ? leagueRows
    : leagueRows.filter(l => l.id === filter);

  const renderTable = rows => (
    <table style={{width:'100%', borderCollapse:'collapse', fontSize:12.5}}>
      <thead>
        <tr style={{borderBottom:`2px solid ${T.border}`, color:T.muted, fontSize:10, fontWeight:800, letterSpacing:.5}}>
          <th style={{textAlign:'left', padding:'7px 8px'}}>ADD</th>
          <th style={{textAlign:'left', padding:'7px 8px'}}>POS</th>
          <th style={{textAlign:'left', padding:'7px 8px'}}>TEAM</th>
          <th style={{textAlign:'right', padding:'7px 8px'}}>{horizon === 'weekly' ? 'WEEK' : 'ROS'} PTS</th>
          <th style={{textAlign:'right', padding:'7px 8px'}}>SCORE</th>
          <th style={{textAlign:'right', padding:'7px 8px'}}>GAIN</th>
          <th style={{textAlign:'center', padding:'7px 8px'}}>TREND</th>
          <th style={{textAlign:'left', padding:'7px 8px'}}>DROP</th>
          <th style={{textAlign:'left', padding:'7px 8px'}}>WHY</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(row => (
          <tr key={row.id} style={{borderBottom:`1px solid ${T.borderLight}`}}>
            <td style={{padding:'7px 8px', fontWeight:700, color:T.text}}>
              <div>{row.name}</div>
              <div style={{fontSize:10.5, color:T.muted, fontWeight:500}}>
                {row.adp ? `ADP ${row.adp}` : 'No ADP'}{row.byeWeek ? ` · BYE ${row.byeWeek}` : ''}
              </div>
              {row.availability && <div style={{fontSize:10.5, color:T.red, marginTop:2}}>{row.availability}</div>}
            </td>
            <td style={{padding:'7px 8px'}}><FreeAgentPosBadge pos={row.pos} /></td>
            <td style={{padding:'7px 8px', color:T.muted}}>{row.nflTeam}</td>
            <td style={{padding:'7px 8px', textAlign:'right', fontWeight:700, fontFamily:'DM Mono,monospace'}}>
              {Number(row.points || 0).toFixed(1)}
            </td>
            <td style={{padding:'7px 8px', textAlign:'right', fontWeight:800, color:T.primary, fontFamily:'DM Mono,monospace'}}>
              {fmt(row.score)}
            </td>
            <td style={{padding:'7px 8px', textAlign:'right', fontWeight:700, color:row.rosterGain > 0 ? T.green : T.muted,
              fontFamily:'DM Mono,monospace'}}>
              {fmt(row.rosterGain)}
            </td>
            <td style={{padding:'7px 8px', textAlign:'center', color:row.urgency > 0 ? T.green : row.urgency < 0 ? T.red : T.muted,
              fontFamily:'DM Mono,monospace', fontWeight:700}}>
              {row.urgency > 0 ? `+${row.urgency}` : row.urgency || '—'}
            </td>
            <td style={{padding:'7px 8px', color:row.drop ? T.text : T.muted}}>
              {row.drop ? (
                <span>{row.drop.name} <span style={{color:T.muted}}>({row.drop.pos})</span></span>
              ) : 'Open slot'}
            </td>
            <td style={{padding:'7px 8px', color:T.muted, lineHeight:1.35}}>
              <div>{row.reason}</div>
              {(row.signals || []).slice(0,2).map((s,i) => (
                <div key={i} title={`${s.source} · ${s.observed_at}`} style={{fontSize:10, marginTop:2}}>
                  {s.attribution || s.source}: {s.kind.replace('_',' ')} {s.value}
                </div>
              ))}
              {horizon === 'weekly' && <div style={{fontSize:10, marginTop:2}}>{row.weeklyProjectionOrigin}</div>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <Modal title="League-Synced Free Agent Finder" onClose={onClose} width={960}>
      <div style={{display:'inline-flex', border:`1px solid ${T.border}`, borderRadius:T.rsm, overflow:'hidden', marginBottom:14}}>
        {[['weekly','This Week'],['ros','Rest of Season']].map(([value,label]) => (
          <button key={value} onClick={() => setHorizon(value)} style={{
            border:'none', padding:'7px 12px', cursor:'pointer', fontFamily:'inherit', fontSize:12, fontWeight:700,
            background:horizon === value ? T.primary : T.surface,
            color:horizon === value ? '#fff' : T.muted,
          }}>{label}</button>
        ))}
      </div>
      <div style={{display:'flex', alignItems:'flex-end', gap:12, marginBottom:16, flexWrap:'wrap'}}>
        <Field label="League">
          <Select value={filter} onChange={e => setFilter(e.target.value)}
            options={[{value:'ALL', label:'All leagues'}, ...leagueRows.map(l => ({value:l.id, label:l.name}))]}
            style={{width:220}} />
        </Field>
        <Field label="Top per League">
          <Input type="number" value={topN} min={1} max={30}
            onChange={e => setTopN(Math.max(1, Math.min(parseInt(e.target.value) || 1, 30)))}
            style={{width:84}} />
        </Field>
        <Field label="NFL Week">
          <Input type="number" value={week} min={1} max={18}
            onChange={e => setWeek(Math.max(1, Math.min(parseInt(e.target.value) || 1, 18)))}
            style={{width:72}} />
        </Field>
        <Btn onClick={scan} disabled={loading} style={{marginBottom:18}}>Refresh</Btn>
        <Btn variant="ghost" onClick={refreshUpdates} disabled={refreshingContext}
          style={{marginBottom:18}}>{refreshingContext ? 'Updating...' : 'Refresh Updates'}</Btn>
        <div style={{marginBottom:24, marginLeft:'auto', fontSize:12, color:T.muted}}>
          {data ? `${data.scannedLeagues} league${data.scannedLeagues === 1 ? '' : 's'} · Week ${data.week}` : ''}
        </div>
      </div>

      {data && (
        <div style={{fontSize:11, color:data.contextStale ? T.amber : T.muted, margin:'-8px 0 12px'}}>
          Player updates {data.contextAsOf ? `as of ${new Date(data.contextAsOf).toLocaleString()}` : 'have not been refreshed yet'}
          {data.contextStale ? ' · cached data may be stale' : ''}
        </div>
      )}

      {loading && <div style={{textAlign:'center', padding:24, color:T.muted}}>Scanning...</div>}
      {error && <div style={{padding:12, color:T.red, background:T.redLight, borderRadius:T.rsm, marginBottom:12}}>{error}</div>}

      {!loading && data && leagueRows.length === 0 && (
        <div style={{padding:32, textAlign:'center', color:T.muted, border:`1px dashed ${T.border}`, borderRadius:T.rsm}}>
          Add a league first.
        </div>
      )}

      {!loading && visibleLeagues.map(league => (
        <div key={league.id} style={{marginTop:18}}>
          <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:8}}>
            <div>
              <div style={{fontSize:14, fontWeight:800, color:T.text}}>{league.name}</div>
              <div style={{fontSize:11, color:T.muted, marginTop:2}}>
                {league.platform || 'League'} · {league.rostered} rostered · {league.available} available
              </div>
            </div>
          </div>
          {((horizon === 'weekly' ? league.weeklyRecommendations : league.rosRecommendations) || league.recommendations || []).length > 0
            ? renderTable((horizon === 'weekly' ? league.weeklyRecommendations : league.rosRecommendations) || league.recommendations)
            : <div style={{padding:18, color:T.muted, background:T.surfaceAlt, borderRadius:T.rsm}}>No positive upgrades found.</div>
          }
        </div>
      ))}
    </Modal>
  );
}

// ─── FIRST-RUN SETUP GUIDE ───────────────────────────────────────────────────
// Optional onboarding checklist: auto-opens once for new users (tracked via
// localStorage), reopenable from the header. Steps check themselves off from
// live app state so it doubles as a "what's left to set up" review.
function SetupGuide({ playerCount, leagues, picks, onPullData, onAddLeague, onEditLeague, onClose }) {
  const first = leagues[0];
  const hasNames = !!first && (first.teamNames || []).some(Boolean);
  const hasPicks = Object.values(picks || {}).some(arr => (arr || []).length > 0);
  const steps = [
    {
      done: (playerCount || 0) > 0,
      title: 'Player data',
      body: (playerCount || 0) > 0
        ? `${playerCount} players with projections and ADP are loaded. Pull fresh data any time before your draft.`
        : 'No player data found — pull the free consensus sources to load projections and ADP.',
      action: { label: 'Pull Data', onClick: onPullData },
    },
    {
      done: leagues.length > 0,
      title: 'Set up your league',
      body: 'Teams, scoring, roster slots, and draft type (snake or auction). Importing from ESPN, Yahoo, or Sleeper auto-fills everything, including your league-mates’ names.',
      action: first
        ? { label: `Edit “${first.name}”`, onClick: () => onEditLeague(first.id) }
        : { label: '+ Add League', onClick: onAddLeague },
    },
    {
      done: hasNames,
      title: 'Draft order & your team',
      body: 'In the league editor, drag the teams into draft-slot order (ESPN and Yahoo imports arrive in platform order, not draft order) and mark your own team with “Me”. Sleeper imports already know the seating, so they arrive in order with your seat set.',
      action: first ? { label: 'Open editor', onClick: () => onEditLeague(first.id) } : null,
    },
    {
      done: hasPicks,
      title: 'Draft day',
      body: '“Draft →” on a league card opens the draft room: live pick recommendations, a pick ticker, and opponent predictions. In-season, “Free Agents” scans your waiver wire for upgrades.',
      action: null,
    },
  ];
  return (
    <Modal title="Getting Started" onClose={onClose} width={620}>
      <div style={{display:'flex', flexDirection:'column', gap:16}}>
        {steps.map((s, i) => (
          <div key={i} style={{display:'flex', gap:12, alignItems:'flex-start'}}>
            <div style={{
              width:26, height:26, borderRadius:'50%', flexShrink:0, display:'flex',
              alignItems:'center', justifyContent:'center', fontSize:13, fontWeight:800,
              background: s.done ? T.greenLight : T.borderLight,
              color: s.done ? T.green : T.muted,
            }}>{s.done ? '✓' : i + 1}</div>
            <div style={{flex:1, minWidth:0}}>
              <div style={{fontSize:14, fontWeight:700, color:T.text}}>{s.title}</div>
              <div style={{fontSize:12.5, color:T.muted, lineHeight:1.5, marginTop:2}}>{s.body}</div>
            </div>
            {s.action && (
              <Btn variant="ghost" size="sm" onClick={s.action.onClick} style={{flexShrink:0}}>
                {s.action.label}
              </Btn>
            )}
          </div>
        ))}
      </div>
      <div style={{
        display:'flex', justifyContent:'space-between', alignItems:'center',
        marginTop:22, paddingTop:16, borderTop:`1px solid ${T.border}`,
      }}>
        <span style={{fontSize:11.5, color:T.muted}}>Reopen any time via “Setup Guide” in the header.</span>
        <Btn onClick={onClose}>Got it</Btn>
      </div>
    </Modal>
  );
}

// ─── APP UPDATE NOTICE ───────────────────────────────────────────────────────
function UpdateBanner({ update, onDismiss }) {
  if (!update || !update.updateAvailable) return null;
  const openDownload = () => {
    const url = update.downloadUrl || update.releaseUrl;
    if (!url) return;
    if (window.pywebview && window.pywebview.api && window.pywebview.api.open_external_url) {
      window.pywebview.api.open_external_url(url);
    } else {
      window.open(url, '_blank', 'noopener,noreferrer');
    }
  };
  return (
    <div style={{
      margin:'0 0 22px', padding:'13px 15px', borderRadius:T.rsm,
      background:T.primaryLight, border:`1px solid ${T.primary}33`,
      display:'flex', alignItems:'center', gap:12, flexWrap:'wrap',
    }}>
      <div style={{flex:1, minWidth:220}}>
        <div style={{fontSize:13, fontWeight:800, color:T.primary}}>
          Draft Assistant {update.latestVersion} is available
        </div>
        <div style={{fontSize:11.5, color:T.muted, marginTop:2}}>
          Your leagues and player data stay in place when you install the update.
        </div>
      </div>
      <Btn size="sm" onClick={openDownload}>Download update</Btn>
      <button onClick={onDismiss} aria-label="Dismiss update" style={{
        border:'none', background:'none', color:T.muted, fontSize:18,
        cursor:'pointer', padding:'0 3px',
      }}>×</button>
    </div>
  );
}

// ─── HOME SCREEN ─────────────────────────────────────────────────────────────
function HomeScreen({ leagues, picks, onSelectLeague, onAddLeague, onEditLeague, onDeleteLeague, onSyncLeague, playerCount, onRefreshPlayers, updateInfo, onDismissUpdate }) {
  const platformColors = { ESPN:'#cc0000', Yahoo:'#6001d2', Sleeper:'#1e1e1e', 'NFL.com':'#013369', Other: T.muted };
  const [showPull, setShowPull]       = React.useState(false);
  const [auctionFor, setAuctionFor]   = React.useState(null); // league whose $ values to show
  // First-run setup guide: auto-open until dismissed once, reopenable from the header.
  const [showGuide, setShowGuide] = React.useState(() => {
    try { return !localStorage.getItem('fda_setup_seen'); } catch { return false; }
  });
  const closeGuide = () => {
    setShowGuide(false);
    try { localStorage.setItem('fda_setup_seen', '1'); } catch {}
  };
  // null = closed, 'ALL' = every league, or a league id to open scoped to that league
  const [freeAgentsFor, setFreeAgentsFor] = React.useState(null);
  const [syncingId, setSyncingId] = React.useState(null);
  const [syncMsg, setSyncMsg] = React.useState(null);

  const syncLeague = (e, lg) => {
    e.stopPropagation();
    setSyncingId(lg.id);
    setSyncMsg(null);
    onSyncLeague(lg)
      .then(msg => {
        setSyncMsg({ ok: true, text: msg });
        setTimeout(() => setSyncMsg(null), 3500);
      })
      .catch(err => {
        setSyncMsg({ ok: false, text: String(err && err.message ? err.message : err) });
        setTimeout(() => setSyncMsg(null), 6000);
      })
      .finally(() => setSyncingId(null));
  };

  return (
    <div style={{minHeight:'100vh', background:T.bg, display:'flex', flexDirection:'column'}}>
      <div style={{
        background:T.surface, borderBottom:`1px solid ${T.border}`,
        padding:'0 32px', height:60, display:'flex', alignItems:'center', justifyContent:'space-between',
      }}>
        <div style={{display:'flex', alignItems:'center', gap:10}}>
          <div style={{
            width:32, height:32, borderRadius:8, background:T.primary,
            display:'flex', alignItems:'center', justifyContent:'center',
          }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.5">
              <ellipse cx="12" cy="12" rx="10" ry="6" />
              <path d="M2 12h20M12 6c0 0-4 3-4 6s4 6 4 6M12 6c0 0 4 3 4 6s-4 6-4 6" />
            </svg>
          </div>
          <span style={{fontSize:18, fontWeight:700, color:T.text}}>Draft Assistant</span>
          {playerCount != null && (
            <Badge label={`${playerCount} players`} color="gray" />
          )}
        </div>
        <div style={{display:'flex', alignItems:'center', gap:8}}>
          <Btn variant="ghost" size="sm" onClick={() => setShowGuide(true)}>Setup Guide</Btn>
          <Btn variant="green" size="sm" onClick={() => setShowPull(true)}>Pull Data</Btn>
          <Btn variant="ghost" size="sm" onClick={() => setFreeAgentsFor('ALL')}>Free Agents</Btn>
          <Btn onClick={onAddLeague}>+ Add League</Btn>
        </div>
      </div>

      <div style={{flex:1, padding:'40px 32px', maxWidth:960, margin:'0 auto', width:'100%', boxSizing:'border-box'}}>
        <UpdateBanner update={updateInfo} onDismiss={onDismissUpdate} />
        <h2 style={{fontSize:22, fontWeight:700, color:T.text, margin:'0 0 8px'}}>Your Leagues</h2>
        <p style={{fontSize:14, color:T.muted, margin:'0 0 28px'}}>
          Select a league to enter draft mode, or add a new one.
        </p>
        {syncMsg && (
          <div style={{
            margin:'0 0 16px', padding:'9px 12px', borderRadius:T.rsm,
            background: syncMsg.ok ? T.greenLight : T.redLight,
            color: syncMsg.ok ? T.green : T.red, fontSize:12, fontWeight:600,
          }}>
            {syncMsg.text}
          </div>
        )}

        {leagues.length === 0 && (
          <div style={{
            background:T.surface, border:`2px dashed ${T.border}`, borderRadius:T.r,
            padding:'60px 32px', textAlign:'center',
          }}>
            <div style={{fontSize:36, marginBottom:12}}>·</div>
            <div style={{fontSize:16, fontWeight:600, color:T.text, marginBottom:6}}>No leagues yet</div>
            <div style={{fontSize:14, color:T.muted, marginBottom:20}}>Add your first league to get started.</div>
            <Btn onClick={onAddLeague}>+ Add League</Btn>
          </div>
        )}

        <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(280px,1fr))', gap:16}}>
          {leagues.map(lg => {
            const pc = platformColors[lg.platform] || T.muted;
            const totalSlots = Object.values(lg.rosterSlots).reduce((s,v) => s+v, 0);
            const canSync = Boolean(lg.espnLeagueId || lg.yahooLeagueKey || lg.sleeperLeagueId);
            return (
              <div key={lg.id} style={{
                background:T.surface, border:`1px solid ${T.border}`, borderRadius:T.r,
                padding:20, position:'relative', overflow:'hidden',
              }}>
                <div style={{position:'absolute', top:0, left:0, right:0, height:3, background:pc}} />

                <div style={{display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:12, marginTop:4}}>
                  <div>
                    <div style={{fontSize:16, fontWeight:700, color:T.text}}>{lg.name}</div>
                    <div style={{fontSize:12, color:T.muted, marginTop:2}}>{lg.platform}</div>
                  </div>
                  <div style={{display:'flex', gap:6}}>
                    {canSync && (
                      <button onClick={e=>syncLeague(e, lg)} disabled={syncingId === lg.id} style={{
                        background:'none', border:`1px solid ${T.border}`, borderRadius:T.rxs,
                        padding:'4px 8px', cursor: syncingId === lg.id ? 'default' : 'pointer',
                        fontSize:12, color: syncingId === lg.id ? T.mutedLight : T.primary,
                      }}>{syncingId === lg.id ? 'Syncing...' : 'Sync'}</button>
                    )}
                    <button onClick={e=>{e.stopPropagation();onEditLeague(lg.id);}} style={{
                      background:'none', border:`1px solid ${T.border}`, borderRadius:T.rxs,
                      padding:'4px 8px', cursor:'pointer', fontSize:12, color:T.muted,
                    }}>Edit</button>
                    <button onClick={e=>{e.stopPropagation();onDeleteLeague(lg.id);}} style={{
                      background:'none', border:`1px solid ${T.border}`, borderRadius:T.rxs,
                      padding:'4px 8px', cursor:'pointer', fontSize:12, color:T.red,
                    }}>×</button>
                  </div>
                </div>

                <div style={{display:'flex', gap:8, flexWrap:'wrap'}}>
                  <Badge label={SCORING_LABELS[lg.scoringType]} color="blue" />
                  <Badge label={`${lg.numTeams} teams`} color="gray" />
                  {lg.draftType === 'auction'
                    ? <Badge label={`Auction $${lg.auctionBudget || 200}`} color="amber" />
                    : <Badge label={`Pick #${lg.draftPosition}`} color="gray" />}
                  <Badge label={`${totalSlots} slots`} color="gray" />
                </div>

                <div style={{marginTop:16, paddingTop:12, borderTop:`1px solid ${T.borderLight}`}}>
                  <div style={{fontSize:12, color:T.muted, marginBottom:10}}>
                    QB{lg.rosterSlots.QB} · RB{lg.rosterSlots.RB} · WR{lg.rosterSlots.WR} · TE{lg.rosterSlots.TE} · K{lg.rosterSlots.K} · DST{lg.rosterSlots.DST}
                  </div>
                  <div style={{display:'flex', gap:8}}>
                    <Btn variant="ghost" size="sm" onClick={() => setFreeAgentsFor(lg.id)}
                      style={{flex:1, justifyContent:'center', color:T.green, borderColor:T.green}}>
                      Free Agents
                    </Btn>
                    {lg.draftType === 'auction' ? (
                      <Btn size="sm" onClick={() => setAuctionFor(lg)}
                        style={{flex:1, justifyContent:'center'}}>
                        Auction Values →
                      </Btn>
                    ) : (
                      <Btn size="sm" onClick={() => onSelectLeague(lg.id)}
                        style={{flex:1, justifyContent:'center'}}>
                        Draft →
                      </Btn>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {showGuide && <SetupGuide
        playerCount={playerCount} leagues={leagues} picks={picks}
        onPullData={() => setShowPull(true)}
        onAddLeague={onAddLeague}
        onEditLeague={onEditLeague}
        onClose={closeGuide} />}
      {showPull && <PullDataModal league={leagues[0]}
        espnLeagueId={(leagues.find(l => l.espnLeagueId) || {}).espnLeagueId}
        onClose={() => setShowPull(false)} onComplete={onRefreshPlayers} />}
      {freeAgentsFor && <FreeAgentFinderModal leagues={leagues} picks={picks}
        initialLeagueId={freeAgentsFor === 'ALL' ? null : freeAgentsFor}
        onClose={() => setFreeAgentsFor(null)} />}
      {auctionFor && <AuctionModal league={auctionFor} onClose={() => setAuctionFor(null)} />}
    </div>
  );
}

// ─── APP ROOT ─────────────────────────────────────────────────────────────────
function App() {
  const [players, setPlayers] = React.useState(null);
  const [loadError, setLoadError] = React.useState(null);
  const [updateInfo, setUpdateInfo] = React.useState(null);

  const [leagues, setLeagues] = React.useState(() => {
    try { return JSON.parse(localStorage.getItem('fda_leagues') || '[]'); } catch { return []; }
  });
  const [picks, setPicks] = React.useState(() => {
    try { return JSON.parse(localStorage.getItem('fda_picks') || '{}'); } catch { return {}; }
  });
  const [selectedId, setSelectedId] = React.useState(null);
  const [showSetup, setShowSetup] = React.useState(false);
  const [editingId, setEditingId] = React.useState(null);

  const refreshPlayers = React.useCallback(() => {
    return fetch('/api/players')
      .then(r => r.json())
      .then(data => {
        if (!data.error) {
          setPlayers(data);
          setPicks(prev => migratePickIds(prev, data));
        }
      })
      .catch(() => {});
  }, []);

  React.useEffect(() => {
    fetch('/api/players')
      .then(r => r.json())
      .then(data => {
        if (data.error) throw new Error(data.error);
        setPlayers(data);
        setPicks(prev => migratePickIds(prev, data));
      })
      .catch(err => setLoadError(String(err)));

    setLeagues(prev => {
      if (prev.length > 0) return prev;
      fetch('/api/config')
        .then(r => r.json())
        .then(cfg => {
          if (cfg && !cfg.error) {
            const seed = leagueFromBackendConfig(cfg);
            if (seed) setLeagues([seed]);
          }
        })
        .catch(() => {});
      return prev;
    });
  }, []);

  React.useEffect(() => {
    // Update checks never block startup and are only supported by packaged apps.
    fetch('/api/update').then(r => r.json()).then(info => {
      if (!info || !info.updateAvailable) return;
      let skipped = null;
      try { skipped = localStorage.getItem('fda_skipped_update'); } catch {}
      if (skipped !== info.latestVersion) setUpdateInfo(info);
    }).catch(() => {});

    // Render cached context immediately; refresh stale signals in the background.
    fetch('/api/context').then(r => r.json()).then(ctx => {
      if (!ctx || ctx.error || !ctx.stale) return;
      return fetch('/api/context/refresh', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({season:ctx.season, week:ctx.week}),
      }).then(r => r.json()).then(started => {
        if (!started.taskId) return;
        let attempts = 0;
        const poll = () => {
          fetch(`/api/task/${started.taskId}`).then(r => r.json()).then(task => {
            if (task.status === 'done') { refreshPlayers(); return; }
            if (task.status === 'error' || attempts++ >= 90) return;
            setTimeout(poll, 1000);
          }).catch(() => {});
        };
        poll();
      });
    }).catch(() => {});
  }, [refreshPlayers]);

  React.useEffect(() => { localStorage.setItem('fda_leagues', JSON.stringify(leagues)); }, [leagues]);
  React.useEffect(() => { localStorage.setItem('fda_picks',   JSON.stringify(picks));   }, [picks]);

  const saveLeague = lg => {
    setLeagues(prev => {
      const idx = prev.findIndex(l => l.id === lg.id);
      return idx >= 0 ? prev.map(l => l.id === lg.id ? lg : l) : [...prev, lg];
    });
    setShowSetup(false);
    setEditingId(null);
  };

  const deleteLeague = id => {
    if (!window.confirm('Remove this league and all its picks?')) return;
    setLeagues(prev => prev.filter(l => l.id !== id));
    setPicks(prev => { const n={...prev}; delete n[id]; return n; });
    if (selectedId === id) setSelectedId(null);
  };

  const updateLeague = (id, patch) => {
    setLeagues(prev => prev.map(l => l.id === id ? {...l,...patch} : l));
  };

  const addPick = (leagueId, pick) => {
    setPicks(prev => ({ ...prev, [leagueId]: [...(prev[leagueId] || []), pick] }));
  };

  const replacePicks = (leagueId, newPicks) => {
    setPicks(prev => ({ ...prev, [leagueId]: newPicks }));
  };

  const syncLeague = React.useCallback(lg => {
    return fetch('/api/sync-league', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league: lg }),
    })
      .then(r => r.json())
      .then(d => {
        if (d.error) throw new Error(d.error);
        setPicks(prev => ({ ...prev, [lg.id]: d.picks || [] }));
        return `Synced ${d.matched || 0}/${d.rostered || 0} rostered players from ${d.source || lg.platform}.`;
      });
  }, []);

  const undoPick = leagueId => {
    setPicks(prev => ({ ...prev, [leagueId]: (prev[leagueId] || []).slice(0,-1) }));
  };

  const resetPicks = leagueId => {
    if (!window.confirm('Reset all picks for this league?')) return;
    setPicks(prev => ({ ...prev, [leagueId]: [] }));
  };

  const editingLeague = editingId ? leagues.find(l => l.id === editingId) : null;
  const selectedLeague = selectedId ? leagues.find(l => l.id === selectedId) : null;

  if (loadError) {
    return (
      <div style={{padding:40, textAlign:'center', color:T.red, fontSize:14}}>
        Failed to load player data: {loadError}
      </div>
    );
  }

  if (!players) {
    return (
      <div className="loading-screen">
        <div className="loading-spinner"></div>
        <div style={{fontSize:14, color:T.muted}}>Loading player data…</div>
      </div>
    );
  }

  if (selectedLeague) {
    return (
      <DraftScreen
        league={selectedLeague}
        picks={picks[selectedLeague.id] || []}
        allPlayers={players}
        allLeagues={leagues}
        allPicks={picks}
        onBack={() => setSelectedId(null)}
        onAddPick={pick => addPick(selectedLeague.id, pick)}
        onUndoPick={() => undoPick(selectedLeague.id)}
        onResetPicks={() => resetPicks(selectedLeague.id)}
        onReplacePicks={newPicks => replacePicks(selectedLeague.id, newPicks)}
        onUpdateLeague={patch => updateLeague(selectedLeague.id, patch)}
        onRefreshPlayers={refreshPlayers}
      />
    );
  }

  return (
    <>
      <HomeScreen
        leagues={leagues}
        picks={picks}
        onSelectLeague={setSelectedId}
        onAddLeague={() => { setEditingId(null); setShowSetup(true); }}
        onEditLeague={id => { setEditingId(id); setShowSetup(true); }}
        onDeleteLeague={deleteLeague}
        onSyncLeague={syncLeague}
        playerCount={players ? players.length : null}
        onRefreshPlayers={refreshPlayers}
        updateInfo={updateInfo}
        onDismissUpdate={() => {
          if (updateInfo) {
            try { localStorage.setItem('fda_skipped_update', updateInfo.latestVersion); } catch {}
          }
          setUpdateInfo(null);
        }}
      />
      {showSetup && (
        <LeagueSetupModal
          league={editingLeague}
          onSave={saveLeague}
          onClose={() => { setShowSetup(false); setEditingId(null); }}
        />
      )}
    </>
  );
}

Object.assign(window, {
  T, calcProjection, withProjections, withVORP,
  getSnakeTeam, getCurrentRoundPick, getRosterNeeds,
  makeLeague, leagueFromBackendConfig, SCORING_LABELS, POSITIONS,
  Btn, Badge, Modal, Field, Input, Select,
  useTask, PullDataModal, AuctionModal,
  FreeAgentFinderModal,
  LeagueSetupModal, HomeScreen, App,
});
