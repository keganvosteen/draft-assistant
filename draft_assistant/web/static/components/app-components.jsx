// ─── DEFAULT DATA ─────────────────────────────────────────────────────────────
const DEFAULT_SLOTS   = { QB:1, RB:2, WR:2, TE:1, FLEX:1, K:1, DST:1, BN:6 };
// Neutral starting template for a new custom league — NOT any one league's
// settings. Raw stats are league-agnostic; each league's own scoring (entered
// in the editor) is applied to them dynamically, so these are just defaults to
// tweak. New categories default to "off"/common so they only count once set.
const DEFAULT_CUSTOM  = { passTD:4, passYds:25, passInt:-2, sackTaken:0, rushTD:6, rushYds:10, recTD:6, recYds:10, reception:0.5, twoPt:2, fumbleLost:-2, fumble:0, fumRetTD:6 };
const SCORING_LABELS  = { standard:'Standard', ppr:'PPR', 'half-ppr':'Half PPR', custom:'Custom' };
const PLATFORMS       = ['ESPN','Yahoo','Sleeper','NFL.com','Other'];

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

// ─── DRAFT ORDER EDITOR ──────────────────────────────────────────────────────
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
  const bulkPaste = text =>
    onChange({ teamNames: text.split('\n').map(s => s.trim()).slice(0, numTeams) });

  const arrow = disabled => ({
    width:26, height:26, textAlign:'center', padding:0, flexShrink:0,
    border:`1.5px solid ${T.border}`, borderRadius:T.rxs, background:T.surface,
    color: disabled ? T.borderLight : T.muted, cursor: disabled ? 'default' : 'pointer',
    fontSize:12,
  });

  return (
    <div>
      <div style={{display:'flex', justifyContent:'space-between', alignItems:'baseline', marginBottom:10}}>
        <SectionLabel>Draft order · my team</SectionLabel>
        <button type="button" onClick={() => setPasteOpen(o => !o)} style={{
          border:'none', background:'none', color:T.primary, cursor:'pointer',
          fontSize:12, fontWeight:600, padding:0,
        }}>{pasteOpen ? 'Close paste' : 'Paste a list'}</button>
      </div>

      <Note style={{marginBottom:10}}>
        Order the rows to match your draft's seat 1…{numTeams}, then mark your own team with{' '}
        <b style={{color:T.text}}>Me</b>. ESPN and Yahoo imports arrive in platform order, not draft
        order — drag them into place. Sleeper imports already know the seating.
      </Note>

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
                border:`1.5px ${isDropTarget ? 'dashed' : 'solid'} ${isDropTarget || isMe ? T.primary : T.border}`,
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
                style={{cursor:'grab', color:T.mutedLight, fontSize:14, lineHeight:1, padding:'4px 2px', userSelect:'none'}}
              >⠿</span>
              <span style={{width:20, textAlign:'center', fontSize:12, fontWeight:700, color:T.muted}}>{i + 1}</span>
              <Input value={nm} onChange={e => setName(i, e.target.value)} placeholder={`Team ${i + 1}`}
                aria-label={`Team in draft slot ${i + 1}`}
                style={{flex:1, minWidth:0, padding:'6px 10px', fontSize:13}} />
              <button type="button" aria-label={`Move slot ${i + 1} up`} onClick={() => move(i, i - 1)}
                disabled={i === 0} style={arrow(i === 0)}>↑</button>
              <button type="button" aria-label={`Move slot ${i + 1} down`} onClick={() => move(i, i + 1)}
                disabled={i === numTeams - 1} style={arrow(i === numTeams - 1)}>↓</button>
              <button type="button" aria-pressed={isMe} onClick={() => onChange({ draftPosition: i + 1 })} style={{
                padding:'5px 11px', borderRadius:T.rxs, cursor:'pointer',
                fontSize:12, fontWeight:700, whiteSpace:'nowrap', flexShrink:0,
                border:`1.5px solid ${isMe ? T.primary : T.border}`,
                background: isMe ? T.primary : T.surface,
                color: isMe ? '#fff' : T.muted,
              }}>{isMe ? '● Me' : 'Me'}</button>
            </div>
          );
        })}
      </div>

      {pasteOpen && (
        <Textarea
          defaultValue={(teamNames || []).join('\n')}
          onChange={e => bulkPaste(e.target.value)}
          placeholder={'One team name per line — fills the slots above top-to-bottom.'}
          rows={Math.min(numTeams, 6)}
          style={{marginTop:10, fontSize:13}} />
      )}
    </div>
  );
}

// ─── LEAGUE IMPORT PANELS ────────────────────────────────────────────────────
// One platform at a time. All three used to be stacked open at once, which made
// the setup modal a wall of credentials for services you weren't using.
function ImportPanel({ form, setForm }) {
  const [provider, setProvider] = React.useState(
    form.sleeperLeagueId ? 'sleeper' : form.yahooLeagueKey ? 'yahoo' : 'espn');

  // ── ESPN (public leagues only — nothing to authorize) ──
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
          text: `Imported “${d.name}” — ${d.numTeams} teams, ${(d.teamNames || []).length} names, ${d.scoringType}` });
      })
      .catch(() => setImportMsg({ ok: false, text: 'Import failed — is the league public?' }))
      .finally(() => setImporting(false));
  };

  // ── Sleeper (public API — a username or a league id is all it takes) ──
  const [sl, setSl] = React.useState({
    username: '', leagueId: form.sleeperLeagueId || '', leagues: null, busy: false, msg: null,
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
        text: `Imported “${d.name}” — ${d.numTeams} teams${seat}, ${d.scoringType}${d.sleeperDraftId ? ' · draft linked' : ''}` } });
    });
  };

  // ── Yahoo OAuth (multi-step: credentials → authorize → pick league) ──
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
    if (!useStored && (!yh.clientId.trim() || !yh.clientSecret.trim())) {
      yhSet({ msg: { ok: false, text: 'Enter Client ID and Secret' } }); return;
    }
    const body = useStored
      ? { redirectUri: yh.redirectUri.trim() }
      : { clientId: yh.clientId.trim(), clientSecret: yh.clientSecret.trim(), redirectUri: yh.redirectUri.trim() };
    yhPost('/api/yahoo/connect', body, d => {
      yhSet({ authUrl: d.authUrl, msg: { ok: true, text: 'Authorize in the opened tab, then paste the code below.' } });
      window.open(d.authUrl, '_blank');
    });
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
      yhSet({ msg: { ok: true, text: `Imported “${d.name}” — ${d.numTeams} teams, ${(d.teamNames || []).length} names, ${d.scoringType}` } });
    });
  };

  const status = msg => msg && (
    <Note tone={msg.ok ? 'ok' : 'error'} style={{marginTop:10}}>{msg.text}</Note>
  );

  return (
    <div>
      <Note tone="info" style={{marginBottom:16}}>
        Importing fills in teams, roster slots, scoring, and your league-mates' names, so you can
        skip the rest of this form. Setting a league up by hand works too — use the tabs above.
      </Note>

      <Field label="Where is your league?">
        <SegmentedControl name="provider" value={provider} onChange={setProvider} options={[
          { value: 'espn',    label: 'ESPN',    hint: 'Public leagues' },
          { value: 'sleeper', label: 'Sleeper', hint: 'No login' },
          { value: 'yahoo',   label: 'Yahoo',   hint: 'OAuth' },
        ]} />
      </Field>

      {provider === 'espn' && (
        <div>
          <div style={{display:'flex', gap:8, alignItems:'center'}}>
            <Input value={espnId} onChange={e=>setEspnId(e.target.value)}
              aria-label="ESPN league ID"
              placeholder="ESPN League ID (e.g. 75034031)" style={{flex:1}} />
            <Btn onClick={importEspn} disabled={importing || !espnId.trim()}>
              {importing ? 'Importing…' : 'Import'}
            </Btn>
          </div>
          {status(importMsg)}
          <div style={{marginTop:8, fontSize:11.5, color:T.muted, lineHeight:1.5}}>
            Find the ID in your ESPN league URL: <code>…/leagues/<b>THIS</b></code>. Private leagues
            can't be read without credentials — set those up by hand on the other tabs.
          </div>
        </div>
      )}

      {provider === 'sleeper' && (
        <div>
          <div style={{display:'flex', gap:8, alignItems:'center'}}>
            <Input value={sl.username} onChange={e=>slSet({username:e.target.value})}
              aria-label="Sleeper username" placeholder="Sleeper username" style={{flex:1}} />
            <Btn variant="secondary" onClick={sleeperFindLeagues} disabled={sl.busy || !sl.username.trim()}>
              {sl.busy ? '…' : 'Find leagues'}
            </Btn>
          </div>
          <div style={{display:'flex', gap:8, alignItems:'center', marginTop:8}}>
            <div style={{flex:1}}>
              {sl.leagues && sl.leagues.length ? (
                <Select value={sl.leagueId} onChange={e=>slSet({leagueId:e.target.value})}
                  aria-label="Sleeper league"
                  options={sl.leagues.map(l=>({value:l.leagueId, label:`${l.name} (${l.season}, ${l.totalRosters} teams)`}))} />
              ) : (
                <Input value={sl.leagueId} onChange={e=>slSet({leagueId:e.target.value})}
                  aria-label="Sleeper league ID" placeholder="…or paste a Sleeper League ID" />
              )}
            </div>
            <Btn onClick={sleeperImport} disabled={sl.busy || !(sl.leagueId||'').trim()}>Import</Btn>
          </div>
          {status(sl.msg)}
          <div style={{marginTop:8, fontSize:11.5, color:T.muted, lineHeight:1.5}}>
            The most complete import: names arrive already in <b>draft-slot order</b> with your own
            seat set, and the draft is linked so the board can follow picks live.
          </div>
        </div>
      )}

      {provider === 'yahoo' && (
        <div>
          {!yh.leagues ? (
            <>
              {yh.credsSaved && !yh.showCredForm ? (
                <div style={{fontSize:12.5, color:T.text, marginBottom:8}}>
                  ✓ Yahoo credentials saved on this machine.{' '}
                  <button onClick={()=>yhSet({showCredForm:true})} style={{
                    background:'none', border:'none', padding:0, color:T.primary,
                    cursor:'pointer', textDecoration:'underline', fontSize:12.5,
                  }}>Use different credentials</button>
                </div>
              ) : (
                <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8}}>
                  <Input value={yh.clientId} onChange={e=>yhSet({clientId:e.target.value})}
                    aria-label="Yahoo client ID" placeholder="Client ID (Consumer Key)" />
                  <Input value={yh.clientSecret} onChange={e=>yhSet({clientSecret:e.target.value})}
                    aria-label="Yahoo client secret" placeholder="Client Secret" type="password" />
                </div>
              )}
              <div style={{display:'flex', gap:8, marginTop:8, alignItems:'center'}}>
                <Input value={yh.redirectUri} onChange={e=>yhSet({redirectUri:e.target.value})}
                  aria-label="Redirect URI" placeholder="Redirect URI" style={{flex:1}} />
                <Btn variant="secondary" onClick={yahooConnect} disabled={yh.busy}>
                  {yh.busy ? '…' : 'Get authorize link'}
                </Btn>
              </div>
              {yh.authUrl && (
                <div style={{marginTop:10}}>
                  <a href={yh.authUrl} target="_blank" rel="noreferrer"
                    style={{fontSize:12.5, color:T.primary, fontWeight:600}}>
                    Open Yahoo authorize page ↗
                  </a>
                  <div style={{display:'flex', gap:8, marginTop:8, alignItems:'center'}}>
                    <Input value={yh.code} onChange={e=>yhSet({code:e.target.value})}
                      aria-label="Yahoo authorization code"
                      placeholder="Paste authorization code" style={{flex:1}} />
                    <Btn onClick={yahooExchange} disabled={yh.busy}>Connect</Btn>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div style={{display:'flex', gap:8, alignItems:'center'}}>
              <div style={{flex:1}}>
                <Select value={yh.leagueKey} onChange={e=>yhSet({leagueKey:e.target.value})}
                  aria-label="Yahoo league"
                  options={yh.leagues.map(l=>({value:l.league_key, label:`${l.name}${l.season?` (${l.season})`:''}`}))} />
              </div>
              <Btn onClick={yahooImport} disabled={yh.busy || !yh.leagueKey}>Import</Btn>
            </div>
          )}
          {status(yh.msg)}
          <div style={{marginTop:8, fontSize:11.5, color:T.muted, lineHeight:1.5}}>
            Register a free app at developer.yahoo.com (Installed App · Fantasy → Read · redirect{' '}
            <b>https://localhost/</b>). After authorizing, copy the <b>code</b> from the address bar.
            Yahoo has no projections, so those stay from the consensus. Your secret is stored only
            on this machine.
          </div>
        </div>
      )}
    </div>
  );
}

// ─── LEAGUE SETUP MODAL ──────────────────────────────────────────────────────
// Four tabs instead of one long scroll: import, the handful of settings that
// actually change rankings, roster slots, and the draft seating.
function LeagueSetupModal({ league, onSave, onClose }) {
  const [form, setForm] = React.useState(league
    ? {...league, rosterSlots:{...league.rosterSlots}, customScoring:{...DEFAULT_CUSTOM, ...league.customScoring}}
    : makeLeague());
  const [tab, setTab] = React.useState(league ? 'basics' : 'import');
  const set = (k, v) => setForm(f => ({...f, [k]: v}));
  const setSlot = (k, v) => setForm(f => ({...f, rosterSlots:{...f.rosterSlots, [k]: parseInt(v)||0}}));
  const setCustom = (k, v) => setForm(f => ({...f, customScoring:{...f.customScoring, [k]: parseFloat(v)||0}}));

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
  const totalSlots = rosterTotal(form.rosterSlots);

  const TABS = [
    { id:'import', label:'Import' },
    { id:'basics', label:'Basics' },
    { id:'roster', label:'Roster & scoring' },
    { id:'order',  label:'Draft order' },
  ];

  return (
    <Modal
      title={league ? `Edit ${league.name}` : 'Add a league'}
      subtitle="Everything here feeds the projections and the draft board."
      onClose={onClose} width={640}
      footer={
        <>
          <Btn variant="secondary" onClick={onClose}>Cancel</Btn>
          <Btn onClick={() => onSave(form)}>{league ? 'Save changes' : 'Add league'}</Btn>
        </>
      }>
      <div className="da-no-scrollbar" role="tablist" style={{
        display:'flex', gap:4, marginBottom:20, borderBottom:`1px solid ${T.border}`,
        overflowX:'auto',
      }}>
        {TABS.map(t => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
            style={{
              background:'none', border:'none', cursor:'pointer', padding:'8px 12px',
              fontSize:13, fontWeight: tab === t.id ? 700 : 600, whiteSpace:'nowrap',
              color: tab === t.id ? T.primary : T.muted,
              borderBottom:`2px solid ${tab === t.id ? T.primary : 'transparent'}`,
              marginBottom:-1,
            }}>{t.label}</button>
        ))}
      </div>

      {tab === 'import' && <ImportPanel form={form} setForm={setForm} />}

      {tab === 'basics' && (
        <div>
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:14}}>
            <Field label="League name">
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
            <Field label="My team" hint="draft slot">
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

          <Field label="Draft type">
            <SegmentedControl name="draftType" value={form.draftType || 'snake'}
              onChange={v => set('draftType', v)}
              options={[{value:'snake', label:'Snake'}, {value:'auction', label:'Auction'}]} />
          </Field>
          {(form.draftType||'snake') === 'auction' && (
            <Field label="Auction budget per team">
              <Input type="number" value={form.auctionBudget || 200} min={1}
                onChange={e=>set('auctionBudget', Math.max(1, parseInt(e.target.value)||200))}
                style={{width:140}} />
            </Field>
          )}
        </div>
      )}

      {tab === 'roster' && (
        <div>
          <Field label="Scoring format">
            <SegmentedControl name="scoring" value={form.scoringType}
              onChange={v => set('scoringType', v)}
              options={Object.entries(SCORING_LABELS).map(([v,l]) => ({value:v, label:l}))} />
          </Field>

          {form.scoringType === 'custom' && (
            <div style={{marginTop:4, marginBottom:20, padding:16, background:T.surfaceAlt, borderRadius:T.r, border:`1px solid ${T.border}`}}>
              <SectionLabel style={{marginBottom:12}}>Custom scoring</SectionLabel>
              <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(128px,1fr))', gap:12}}>
                {[
                  {k:'passTD', l:'Pass TD'},
                  {k:'passYds', l:'Yds / pass pt', hint:'yds per 1 pt'},
                  {k:'passInt', l:'Interception'},
                  {k:'sackTaken', l:'Sack taken', hint:'per QB sack'},
                  {k:'rushTD', l:'Rush TD'},
                  {k:'rushYds', l:'Yds / rush pt', hint:'yds per 1 pt'},
                  {k:'recTD', l:'Rec TD'},
                  {k:'recYds', l:'Yds / rec pt', hint:'yds per 1 pt'},
                  {k:'reception', l:'Per reception', step:0.05, hint:'e.g. 0.25'},
                  {k:'twoPt', l:'2-pt conversion'},
                  {k:'fumbleLost', l:'Fumble lost'},
                  {k:'fumble', l:'Any fumble'},
                  {k:'fumRetTD', l:'Off. fum. ret. TD'},
                ].map(({k,l,hint,step}) => (
                  <Field key={k} label={l} hint={hint} style={{marginBottom:0}}>
                    <Input type="number" value={form.customScoring[k]}
                      onChange={e=>setCustom(k,e.target.value)} step={step||0.5} />
                  </Field>
                ))}
              </div>
            </div>
          )}

          <div style={{display:'flex', alignItems:'baseline', justifyContent:'space-between', margin:'22px 0 12px'}}>
            <SectionLabel>Roster slots</SectionLabel>
            <span style={{fontSize:12, color:T.muted}}>{totalSlots} total · {totalSlots} rounds</span>
          </div>
          <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(128px,1fr))', gap:12}}>
            {slotFields.map(({k,label}) => (
              <Field key={k} label={label} style={{marginBottom:0}}>
                <Input type="number" value={form.rosterSlots[k]||0}
                  onChange={e=>setSlot(k,e.target.value)} min={0} max={10} />
              </Field>
            ))}
          </div>
          <Note style={{marginTop:18}}>
            Projections are stored as raw stats, so changing scoring here re-ranks the whole board
            immediately — no re-pull needed.
          </Note>
        </div>
      )}

      {tab === 'order' && (
        <DraftOrderEditor
          numTeams={form.numTeams}
          teamNames={form.teamNames}
          draftPosition={form.draftPosition}
          onChange={patch => setForm(f => ({ ...f, ...patch }))} />
      )}
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
  const [advanced, setAdvanced] = React.useState(false);
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
        if (data.error) { toast(data.error, 'error', 6000); return; }
        task.start(data.taskId);
      })
      .catch(err => toast(String(err), 'error', 6000));
  };

  const handleDone = () => {
    const n = task.result && task.result.players;
    task.reset();
    onComplete();
    onClose();
    if (n) toast(`${n} players loaded.`, 'ok');
  };

  const busy = task.status === 'running';

  return (
    <Modal title="Pull player data" onClose={onClose} width={540} dismissible={!busy}
      subtitle={busy ? null : 'Projections, ADP, and recent stats from the free consensus sources.'}
      footer={task.status ? null : (
        <>
          <Btn variant="secondary" onClick={onClose}>Cancel</Btn>
          <Btn onClick={handlePull}>Pull data</Btn>
        </>
      )}>
      {busy && (
        <div className="loading-screen" style={{height:200}}>
          <Spinner />
          <div style={{textAlign:'center'}}>
            <div style={{fontSize:14, fontWeight:600, color:T.text}}>Pulling data…</div>
            <div style={{fontSize:12.5, color:T.muted, marginTop:4}}>Usually 30–60 seconds. You can leave this open.</div>
          </div>
        </div>
      )}

      {task.status === 'done' && (
        <div style={{textAlign:'center', padding:'12px 0'}}>
          <div style={{fontSize:15.5, fontWeight:700, color:T.text, marginBottom:6}}>
            {task.result?.players} players loaded
          </div>
          <div style={{fontSize:12.5, color:T.muted}}>
            {task.result?.consensusPlayers > 0 && `${task.result.consensusPlayers} with consensus projections`}
            {task.result?.historySeasons?.length > 0 && ` · history ${task.result.historySeasons.join(', ')}`}
          </div>

          {task.result?.warnings?.length > 0 && (
            <Note tone="warn" style={{textAlign:'left', marginTop:16}}>
              <b>Single-source projections</b>
              {task.result.warnings.map((w, i) => <div key={i} style={{marginTop:3}}>{w}</div>)}
            </Note>
          )}

          {task.result?.reports && (
            <div style={{textAlign:'left', marginTop:16, background:T.surfaceAlt,
              borderRadius:T.rsm, padding:'10px 14px', fontSize:12.5}}>
              {task.result.reports.map((r, i) => (
                <div key={i} style={{display:'flex', justifyContent:'space-between', padding:'3px 0',
                  color: r.ok ? T.text : T.mutedLight}}>
                  <span>{r.source}</span>
                  <span className="da-num">{r.ok ? `${r.records} records` : 'skipped'}</span>
                </div>
              ))}
            </div>
          )}
          <Btn onClick={handleDone} style={{marginTop:18}}>Done</Btn>
        </div>
      )}

      {task.status === 'error' && (
        <div style={{textAlign:'center', padding:'12px 0'}}>
          <div style={{fontSize:14, fontWeight:700, color:T.red, marginBottom:8}}>Pull failed</div>
          <div style={{fontSize:12.5, color:T.muted, marginBottom:18, wordBreak:'break-word'}}>{task.error}</div>
          <div style={{display:'flex', gap:8, justifyContent:'center'}}>
            <Btn onClick={() => task.reset()}>Try again</Btn>
            <Btn variant="secondary" onClick={onClose}>Close</Btn>
          </div>
        </div>
      )}

      {!task.status && (
        <>
          <Field label="Source">
            <SegmentedControl name="pullMode" value={mode} onChange={setMode} options={[
              { value:'free', label:'Free sources', hint:'No extra packages' },
              { value:'full', label:'Full collect', hint:'Adds nfl_data_py' },
            ]} />
          </Field>

          <Note style={{marginBottom:16}}>
            Full collect is a superset: it pulls the same free sources, then enriches them. ADP is
            matched to this league automatically — <b style={{color:T.text}}>
            {adpFormat === 'ppr' ? 'PPR' : adpFormat === 'half-ppr' ? 'Half PPR' : 'Standard'}, {Math.min(teams,14)} teams</b>.
          </Note>

          <button onClick={() => setAdvanced(a => !a)} style={{
            background:'none', border:'none', padding:0, cursor:'pointer',
            color:T.primary, fontSize:12.5, fontWeight:600,
          }}>{advanced ? 'Hide' : 'Show'} season options</button>

          {advanced && (
            <div style={{marginTop:14}}>
              <div style={{display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:12}}>
                <Field label="Projections" hint="season">
                  <Input type="number" value={season} onChange={e => setSeason(parseInt(e.target.value) || currentYear)} />
                </Field>
                <Field label="Stats" hint="most recent">
                  <Input type="number" value={statsSeason} onChange={e => setStats(parseInt(e.target.value) || currentYear-1)} />
                </Field>
                <Field label="History" hint="years">
                  <Input type="number" value={history} min={1} max={5}
                    onChange={e => setHistory(parseInt(e.target.value) || 3)} />
                </Field>
              </div>
              <Checkbox checked={skipFf} onChange={e => setSkipFf(e.target.checked)}
                label="Skip FFToday scraping"
                hint="FFToday is the only source pulled by scraping pages, so it's the slowest and most fragile step. Skipping makes the pull quicker; leaving it on adds another projection source. Either way the pull completes if it fails." />
            </div>
          )}
        </>
      )}
    </Modal>
  );
}

// ─── AUCTION MODAL ───────────────────────────────────────────────────────────
function AuctionModal({ league, onClose }) {
  const [budget, setBudget]   = React.useState((league && league.auctionBudget) || 200);
  const [topN, setTopN]       = React.useState(50);
  const [data, setData]       = React.useState(null);
  const [loading, setLoading] = React.useState(false);

  const handleFetch = React.useCallback(() => {
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
      .catch(err => { toast(String(err), 'error'); setLoading(false); });
  }, [budget, topN, league]);

  React.useEffect(() => { handleFetch(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Modal title="Auction values" onClose={onClose} width={580}
      subtitle={league ? `${league.name} · ${league.numTeams} teams · ${SCORING_LABELS[league.scoringType]}` : null}>
      <div style={{display:'flex', gap:12, marginBottom:16, alignItems:'flex-end', flexWrap:'wrap'}}>
        <Field label="Budget per team" style={{marginBottom:0}}>
          <Input type="number" value={budget} onChange={e => setBudget(parseInt(e.target.value) || 200)}
            style={{width:110}} />
        </Field>
        <Field label="Show top" style={{marginBottom:0}}>
          <Input type="number" value={topN} onChange={e => setTopN(parseInt(e.target.value) || 50)}
            style={{width:90}} />
        </Field>
        <Btn variant="secondary" onClick={handleFetch} disabled={loading}>
          {loading ? 'Loading…' : 'Recalculate'}
        </Btn>
      </div>

      {loading && !data && (
        <div className="loading-screen" style={{height:180}}><Spinner /><span>Valuing the pool…</span></div>
      )}

      {data && data.values && (
        <table className="da-table">
          <thead>
            <tr>
              <th style={{width:30}}>#</th>
              <th>Player</th>
              <th style={{width:52}}>Pos</th>
              <th style={{width:60}}>Team</th>
              <th style={{textAlign:'right', width:70}}>Value</th>
            </tr>
          </thead>
          <tbody>
            {data.values.map((v, i) => (
              <tr key={i}>
                <td className="da-num" style={{color:T.mutedLight, fontSize:12}}>{i+1}</td>
                <td style={{fontWeight:600}}>{v.name}</td>
                <td><PosBadge pos={v.pos} /></td>
                <td style={{color:T.muted}}>{v.team}</td>
                <td className="da-num" style={{textAlign:'right', fontWeight:700,
                  color: v.value >= 20 ? T.green : T.text}}>${v.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
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
      title: 'Load player data',
      body: (playerCount || 0) > 0
        ? `${playerCount} players with projections and ADP are loaded. Pull again any time before your draft.`
        : 'Nothing is loaded yet — pull the free consensus sources to get projections and ADP.',
      action: { label: 'Pull data', onClick: onPullData },
    },
    {
      done: leagues.length > 0,
      title: 'Add your league',
      body: 'Teams, scoring, roster slots, and draft type. Importing from ESPN, Yahoo, or Sleeper fills all of it in, league-mates included.',
      action: first
        ? { label: 'Edit league', onClick: () => onEditLeague(first.id) }
        : { label: 'Add league', onClick: onAddLeague },
    },
    {
      done: hasNames,
      title: 'Set the draft order',
      body: 'Drag the teams into seat order and mark your own with “Me”. Sleeper imports arrive already seated; ESPN and Yahoo do not.',
      action: first ? { label: 'Draft order', onClick: () => onEditLeague(first.id) } : null,
    },
    {
      done: hasPicks,
      title: 'Record your first pick',
      body: 'Open a league to reach its hub, where the draft room and the in-season waiver wire sit side by side. This step ticks itself off once picks start landing on a board.',
      action: null,
    },
  ];
  return (
    <Modal title="Getting started" onClose={onClose} width={580}
      footer={<Btn onClick={onClose}>Got it</Btn>}>
      <div style={{display:'flex', flexDirection:'column', gap:16}}>
        {steps.map((s, i) => (
          <div key={i} style={{display:'flex', gap:12, alignItems:'flex-start'}}>
            <div style={{
              width:24, height:24, borderRadius:'50%', flexShrink:0, display:'flex',
              alignItems:'center', justifyContent:'center', fontSize:12, fontWeight:800,
              background: s.done ? T.greenLight : T.borderLight,
              color: s.done ? T.green : T.muted,
            }}>{s.done ? '✓' : i + 1}</div>
            <div style={{flex:1, minWidth:0}}>
              <div style={{fontSize:13.5, fontWeight:700, color:T.text}}>{s.title}</div>
              <div style={{fontSize:12.5, color:T.muted, lineHeight:1.55, marginTop:2}}>{s.body}</div>
            </div>
            {s.action && (
              <Btn variant="secondary" size="sm" onClick={s.action.onClick} style={{flexShrink:0}}>
                {s.action.label}
              </Btn>
            )}
          </div>
        ))}
      </div>
      <div style={{marginTop:20, paddingTop:14, borderTop:`1px solid ${T.borderLight}`, fontSize:11.5, color:T.mutedLight}}>
        Reopen any time from “Setup guide” in the header.
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
function LeagueCard({ league, picks, onOpen, onEdit }) {
  const accent = PLATFORM_COLORS[league.platform] || T.muted;
  const totalSlots = rosterTotal(league.rosterSlots);
  const myPicks = picks.filter(p => p.teamNum === league.draftPosition).length;

  return (
    <div className="da-card" style={{position:'relative', overflow:'hidden', display:'flex', flexDirection:'column'}}>
      <div style={{position:'absolute', top:0, left:0, right:0, height:3, background:accent}} />
      <button onClick={onOpen} className="da-card-link" aria-label={`Open ${league.name}`} style={{
        border:'none', background:'none', boxShadow:'none', padding:'20px 20px 16px', flex:1,
        borderRadius:0,
      }}>
        <div style={{fontSize:16, fontWeight:700, color:T.text, marginBottom:2}}>{league.name}</div>
        <div style={{fontSize:12, color:T.muted, marginBottom:14}}>
          {league.platform} · {league.numTeams} teams
        </div>
        <div style={{display:'flex', gap:6, flexWrap:'wrap', marginBottom:14}}>
          <Badge label={SCORING_LABELS[league.scoringType]} color="blue" />
          {league.draftType === 'auction'
            ? <Badge label={`Auction $${league.auctionBudget || 200}`} color="amber" />
            : <Badge label={`Pick #${league.draftPosition}`} />}
          <Badge label={`${totalSlots} slots`} />
        </div>
        <div style={{fontSize:12, color:T.muted}}>
          {picks.length > 0
            ? `${picks.length} picks recorded · ${myPicks} on your roster`
            : 'No picks yet'}
        </div>
      </button>
      <div style={{
        display:'flex', alignItems:'center', justifyContent:'space-between',
        padding:'10px 16px', borderTop:`1px solid ${T.borderLight}`, background:T.surfaceAlt,
      }}>
        <Btn variant="subtle" size="sm" onClick={onEdit}>Settings</Btn>
        <Btn size="sm" onClick={onOpen}>Open league →</Btn>
      </div>
    </div>
  );
}

function HomeScreen({ leagues, picks, onOpenLeague, onAddLeague, onEditLeague, playerCount,
                      onRefreshPlayers, updateInfo, onDismissUpdate }) {
  const [showPull, setShowPull] = React.useState(false);
  // First-run setup guide: auto-open until dismissed once, reopenable from the header.
  const [showGuide, setShowGuide] = React.useState(() => {
    try { return !localStorage.getItem('fda_setup_seen'); } catch { return false; }
  });
  const closeGuide = () => {
    setShowGuide(false);
    try { localStorage.setItem('fda_setup_seen', '1'); } catch {}
  };
  const { isMobile } = useLayout();

  return (
    <div style={{minHeight:'100vh', background:T.bg, display:'flex', flexDirection:'column'}}>
      <AppBar
        title={
          <span style={{display:'inline-flex', alignItems:'center', gap:10}}>
            <span style={{
              width:28, height:28, borderRadius:8, background:T.primary,
              display:'inline-flex', alignItems:'center', justifyContent:'center',
            }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.5" aria-hidden="true">
                <ellipse cx="12" cy="12" rx="10" ry="6" />
                <path d="M2 12h20M12 6c0 0-4 3-4 6s4 6 4 6M12 6c0 0 4 3 4 6s-4 6-4 6" />
              </svg>
            </span>
            Draft Assistant
          </span>
        }
        badges={playerCount != null
          ? <Badge label={`${playerCount} players`} color={playerCount ? 'gray' : 'amber'} />
          : null}>
        <Btn variant="subtle" size="sm" onClick={() => setShowGuide(true)}>Setup guide</Btn>
        <Btn variant="secondary" size="sm" onClick={() => setShowPull(true)}>Pull data</Btn>
        <Btn onClick={onAddLeague}>Add league</Btn>
      </AppBar>

      <div style={{flex:1, padding: isMobile ? '24px 16px' : '36px 24px', maxWidth:960, margin:'0 auto', width:'100%'}}>
        <UpdateBanner update={updateInfo} onDismiss={onDismissUpdate} />
        <h2 style={{fontSize:21, fontWeight:700, color:T.text, margin:'0 0 4px'}}>Your leagues</h2>
        <p style={{fontSize:13.5, color:T.muted, margin:'0 0 24px'}}>
          Open a league to reach its draft room and waiver wire.
        </p>

        {(playerCount || 0) === 0 && leagues.length > 0 && (
          <Note tone="warn" style={{marginBottom:20}}>
            No player data loaded — rankings will be empty until you{' '}
            <button onClick={() => setShowPull(true)} style={{
              background:'none', border:'none', padding:0, color:T.primary,
              fontWeight:700, cursor:'pointer', textDecoration:'underline',
            }}>pull player data</button>.
          </Note>
        )}

        {leagues.length === 0 ? (
          <EmptyState
            title="No leagues yet"
            body="Add your league to get a draft board tuned to its scoring and roster — or import it from ESPN, Yahoo, or Sleeper and skip the typing."
            action={<Btn size="lg" onClick={onAddLeague}>Add your first league</Btn>} />
        ) : (
          <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(288px,1fr))', gap:16}}>
            {leagues.map(lg => (
              <LeagueCard key={lg.id} league={lg} picks={picks[lg.id] || []}
                onOpen={() => onOpenLeague(lg.id)}
                onEdit={() => onEditLeague(lg.id)} />
            ))}
          </div>
        )}
      </div>

      {showGuide && <SetupGuide
        playerCount={playerCount} leagues={leagues} picks={picks}
        onPullData={() => { closeGuide(); setShowPull(true); }}
        onAddLeague={() => { closeGuide(); onAddLeague(); }}
        onEditLeague={id => { closeGuide(); onEditLeague(id); }}
        onClose={closeGuide} />}
      {showPull && <PullDataModal league={leagues[0]}
        espnLeagueId={(leagues.find(l => l.espnLeagueId) || {}).espnLeagueId}
        onClose={() => setShowPull(false)} onComplete={onRefreshPlayers} />}
    </div>
  );
}

// ─── APP ROOT ─────────────────────────────────────────────────────────────────
// Navigation is a flat route: leagues → one league's hub → draft room or waiver
// wire. The draft and the waiver wire never contain each other; the hub is the
// only place both are reachable from.
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
  // { screen: 'home' | 'league' | 'draft' | 'waivers', leagueId }
  const [route, setRoute] = React.useState({ screen: 'home', leagueId: null });
  const [showSetup, setShowSetup] = React.useState(false);
  const [editingId, setEditingId] = React.useState(null);
  const [showPull, setShowPull] = React.useState(false);

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
    toast(`${lg.name} saved.`, 'ok');
  };

  const deleteLeague = id => {
    setLeagues(prev => prev.filter(l => l.id !== id));
    setPicks(prev => { const n = {...prev}; delete n[id]; return n; });
  };

  const updateLeague = (id, patch) => {
    setLeagues(prev => prev.map(l => l.id === id ? {...l, ...patch} : l));
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
        return `Synced ${d.matched || 0} of ${d.rostered || 0} rostered players from ${d.source || lg.platform}.`;
      });
  }, []);

  const undoPick = leagueId => {
    setPicks(prev => ({ ...prev, [leagueId]: (prev[leagueId] || []).slice(0, -1) }));
  };

  const resetPicks = leagueId => {
    confirmDialog({
      title: 'Clear every pick?',
      body: 'All picks recorded for this league are removed. The league itself and your player data stay.',
      confirmLabel: 'Clear picks', tone: 'danger',
    }).then(ok => {
      if (!ok) return;
      setPicks(prev => ({ ...prev, [leagueId]: [] }));
      toast('Picks cleared.', 'ok');
    });
  };

  const editingLeague = editingId ? leagues.find(l => l.id === editingId) : null;
  const routeLeague = route.leagueId ? leagues.find(l => l.id === route.leagueId) : null;
  const goHome = () => setRoute({ screen: 'home', leagueId: null });
  const openEditor = id => { setEditingId(id); setShowSetup(true); };

  if (loadError) {
    return (
      <div style={{padding:40, textAlign:'center'}}>
        <div style={{color:T.red, fontSize:14, fontWeight:600, marginBottom:8}}>
          Couldn't load player data
        </div>
        <div style={{color:T.muted, fontSize:13}}>{loadError}</div>
      </div>
    );
  }

  if (!players) {
    return (
      <div className="loading-screen">
        <Spinner />
        <span>Loading player data…</span>
      </div>
    );
  }

  // A league can be deleted while its screens are open; fall back to home.
  const screen = routeLeague ? route.screen : 'home';

  let body;
  if (screen === 'draft') {
    body = (
      <DraftScreen
        league={routeLeague}
        picks={picks[routeLeague.id] || []}
        allPlayers={players}
        onBack={() => setRoute({ screen: 'league', leagueId: routeLeague.id })}
        onAddPick={pick => addPick(routeLeague.id, pick)}
        onUndoPick={() => undoPick(routeLeague.id)}
        onResetPicks={() => resetPicks(routeLeague.id)}
        onReplacePicks={newPicks => replacePicks(routeLeague.id, newPicks)}
        onUpdateLeague={patch => updateLeague(routeLeague.id, patch)}
        onRefreshPlayers={refreshPlayers}
      />
    );
  } else if (screen === 'waivers') {
    body = (
      <WaiverScreen
        league={routeLeague}
        picks={picks[routeLeague.id] || []}
        allPlayers={players}
        onBack={() => setRoute({ screen: 'league', leagueId: routeLeague.id })}
        onSyncLeague={syncLeague}
        onEditLeague={openEditor}
      />
    );
  } else if (screen === 'league') {
    body = (
      <LeagueHub
        league={routeLeague}
        picks={picks[routeLeague.id] || []}
        playerCount={players.length}
        onBack={goHome}
        onOpenDraft={() => setRoute({ screen: 'draft', leagueId: routeLeague.id })}
        onOpenWaivers={() => setRoute({ screen: 'waivers', leagueId: routeLeague.id })}
        onEditLeague={openEditor}
        onDeleteLeague={deleteLeague}
        onSyncLeague={syncLeague}
        onPullData={() => setShowPull(true)}
      />
    );
  } else {
    body = (
      <HomeScreen
        leagues={leagues}
        picks={picks}
        onOpenLeague={id => setRoute({ screen: 'league', leagueId: id })}
        onAddLeague={() => { setEditingId(null); setShowSetup(true); }}
        onEditLeague={openEditor}
        playerCount={players.length}
        onRefreshPlayers={refreshPlayers}
        updateInfo={updateInfo}
        onDismissUpdate={() => {
          if (updateInfo) {
            try { localStorage.setItem('fda_skipped_update', updateInfo.latestVersion); } catch {}
          }
          setUpdateInfo(null);
        }}
      />
    );
  }

  return (
    <>
      {body}
      {showSetup && (
        <LeagueSetupModal
          league={editingLeague}
          onSave={saveLeague}
          onClose={() => { setShowSetup(false); setEditingId(null); }}
        />
      )}
      {showPull && (
        <PullDataModal
          league={routeLeague || leagues[0]}
          espnLeagueId={(routeLeague || {}).espnLeagueId
            || (leagues.find(l => l.espnLeagueId) || {}).espnLeagueId}
          onClose={() => setShowPull(false)}
          onComplete={refreshPlayers}
        />
      )}
      <Toaster />
      <ConfirmHost />
    </>
  );
}

Object.assign(window, {
  calcProjection, withProjections, withVORP,
  getSnakeTeam, getCurrentRoundPick, getRosterNeeds,
  makeLeague, leagueFromBackendConfig, SCORING_LABELS,
  useTask, PullDataModal, AuctionModal,
  DraftOrderEditor, LeagueSetupModal, HomeScreen, SetupGuide, App,
});
