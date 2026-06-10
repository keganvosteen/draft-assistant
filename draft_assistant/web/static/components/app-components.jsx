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

// ─── UTILITIES ────────────────────────────────────────────────────────────────
function calcProjection(player, scoringType, customRec) {
  if (scoringType === 'standard') return player.stdPts;
  if (scoringType === 'ppr')      return player.stdPts + player.recPts;
  if (scoringType === 'half-ppr') return Math.round(player.stdPts + player.recPts * 0.5);
  if (scoringType === 'custom')   return Math.round(player.stdPts + player.recPts * (customRec || 0));
  return player.stdPts;
}

function withProjections(players, league) {
  const recMult = league.scoringType === 'custom' ? (league.customScoring && league.customScoring.reception || 0) : 1;
  return players.map(p => ({ ...p, projPts: calcProjection(p, league.scoringType, recMult) }));
}

function withVORP(players, league) {
  const { numTeams, rosterSlots } = league;
  const flex = rosterSlots.FLEX || 0;
  const repRank = {
    QB:  Math.floor(numTeams * (rosterSlots.QB  || 1) + 1),
    RB:  Math.floor(numTeams * ((rosterSlots.RB  || 2) + flex * 0.5) + 1),
    WR:  Math.floor(numTeams * ((rosterSlots.WR  || 2) + flex * 0.5) + 1),
    TE:  Math.floor(numTeams * (rosterSlots.TE  || 1) + 1),
    K:   Math.floor(numTeams * (rosterSlots.K   || 1) + 1),
    DST: Math.floor(numTeams * (rosterSlots.DST || 1) + 1),
  };
  const byPos = {};
  players.forEach(p => { (byPos[p.pos] = byPos[p.pos] || []).push(p); });
  const repPts = {};
  Object.entries(byPos).forEach(([pos, arr]) => {
    const sorted = [...arr].sort((a, b) => b.projPts - a.projPts);
    const idx = Math.min((repRank[pos] || 1) - 1, sorted.length - 1);
    repPts[pos] = sorted[idx] ? sorted[idx].projPts : 0;
  });
  return players.map(p => ({ ...p, vorp: Math.round(p.projPts - (repPts[p.pos] || 0)) }));
}

function getSnakeTeam(pickNum, numTeams) {
  const round = Math.ceil(pickNum / numTeams);
  const pos   = pickNum - (round - 1) * numTeams;
  return round % 2 === 1 ? pos : numTeams - pos + 1;
}

function getCurrentRoundPick(totalPicks, numTeams) {
  const round = Math.ceil((totalPicks + 1) / numTeams);
  const pickInRound = ((totalPicks) % numTeams) + 1;
  return { round, pickInRound };
}

function getRosterNeeds(myPlayers, rosterSlots) {
  const counts = {};
  myPlayers.forEach(p => { counts[p.pos] = (counts[p.pos] || 0) + 1; });
  const flex = rosterSlots.FLEX || 0;
  const maxByPos = {
    QB:  rosterSlots.QB  || 1,
    RB:  (rosterSlots.RB  || 2) + Math.ceil(flex * 0.6),
    WR:  (rosterSlots.WR  || 2) + Math.ceil(flex * 0.6),
    TE:  (rosterSlots.TE  || 1) + Math.floor(flex * 0.2),
    K:   rosterSlots.K   || 1,
    DST: rosterSlots.DST || 1,
  };
  return Object.entries(maxByPos)
    .filter(([pos, max]) => (counts[pos] || 0) < max)
    .map(([pos]) => pos);
}

// ─── DEFAULT DATA ─────────────────────────────────────────────────────────────
const DEFAULT_SLOTS   = { QB:1, RB:2, WR:2, TE:1, FLEX:1, K:1, DST:1, BN:6 };
const DEFAULT_CUSTOM  = { passTD:4, passYds:25, passInt:-2, rushTD:6, rushYds:10, recTD:6, recYds:10, reception:0.5 };
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
    scoringType: 'ppr',
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
    rosterSlots: { ...DEFAULT_SLOTS, ...roster },
  });
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

// ─── LEAGUE SETUP MODAL ──────────────────────────────────────────────────────
function LeagueSetupModal({ league, onSave, onClose }) {
  const [form, setForm] = React.useState(league
    ? {...league, rosterSlots:{...league.rosterSlots}, customScoring:{...league.customScoring}}
    : makeLeague());
  const set = (k, v) => setForm(f => ({...f, [k]: v}));
  const setSlot = (k, v) => setForm(f => ({...f, rosterSlots:{...f.rosterSlots, [k]: parseInt(v)||0}}));
  const setCustom = (k, v) => setForm(f => ({...f, customScoring:{...f.customScoring, [k]: parseFloat(v)||0}}));

  const slotFields = [
    {k:'QB',label:'QB'},{k:'RB',label:'RB'},{k:'WR',label:'WR'},
    {k:'TE',label:'TE'},{k:'FLEX',label:'FLEX (RB/WR/TE)'},{k:'K',label:'K'},
    {k:'DST',label:'DST'},{k:'BN',label:'Bench'},
  ];

  return (
    <Modal title={league ? 'Edit League' : 'Add New League'} onClose={onClose} width={600}>
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
            options={[8,10,12,14].map(n=>({value:n,label:`${n} teams`}))} />
        </Field>
        <Field label="My Draft Position">
          <Input type="number" value={form.draftPosition}
            onChange={e=>set('draftPosition',parseInt(e.target.value)||1)}
            min={1} max={form.numTeams} />
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

      {form.scoringType === 'custom' && (
        <div style={{marginTop:16, padding:16, background:T.surfaceAlt, borderRadius:T.r, border:`1px solid ${T.border}`}}>
          <div style={{fontSize:12, fontWeight:700, color:T.muted, marginBottom:12, letterSpacing:.5}}>CUSTOM SCORING</div>
          <div style={{display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:12}}>
            {[
              {k:'passTD', l:'Pass TD'},
              {k:'passYds', l:'Yds/Pass Pt', hint:'yds per 1 pt'},
              {k:'passInt', l:'Interception'},
              {k:'reception', l:'Reception (PPR)'},
              {k:'rushTD', l:'Rush TD'},
              {k:'rushYds', l:'Yds/Rush Pt'},
              {k:'recTD', l:'Rec TD'},
              {k:'recYds', l:'Yds/Rec Pt'},
            ].map(({k,l,hint}) => (
              <Field key={k} label={l} hint={hint}>
                <Input type="number" value={form.customScoring[k]}
                  onChange={e=>setCustom(k,e.target.value)} step="0.5" />
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
function PullDataModal({ league, onClose, onComplete }) {
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
    const body = mode === 'free'
      ? { season, statsSeason, teams, adpFormat, skipFftoday: skipFf }
      : { season, teams, scoring: adpFormat, history };
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
                {v:'full', l:'Full Collect', hint:'Requires nfl_data_py'},
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
            {mode === 'free' && (
              <Field label="Stats Season">
                <Input type="number" value={statsSeason} onChange={e => setStats(parseInt(e.target.value) || currentYear-1)} />
              </Field>
            )}
            {mode === 'full' && (
              <Field label="History Seasons" hint="years of stats">
                <Input type="number" value={history} onChange={e => setHistory(parseInt(e.target.value) || 3)}
                  min={1} max={5} />
              </Field>
            )}
          </div>

          {mode === 'free' && (
            <label style={{display:'flex', alignItems:'center', gap:8, fontSize:13, color:T.text, marginTop:8, cursor:'pointer'}}>
              <input type="checkbox" checked={skipFf} onChange={e => setSkipFf(e.target.checked)} />
              Skip FFToday scraping
            </label>
          )}

          <div style={{
            marginTop:16, padding:'10px 14px', background:T.surfaceAlt,
            border:`1px solid ${T.border}`, borderRadius:T.rsm, fontSize:12, color:T.muted, lineHeight:1.5,
          }}>
            Projections are pulled as raw stats — your league's scoring is applied
            automatically and updates in real time when you change league settings.
            ADP board matched to your league: <b style={{color:T.text}}>
            {adpFormat === 'ppr' ? 'PPR' : adpFormat === 'half-ppr' ? 'Half PPR' : 'Standard'} · {teams} teams</b>
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
function AuctionModal({ onClose }) {
  const [budget, setBudget] = React.useState(200);
  const [topN, setTopN]     = React.useState(50);
  const [data, setData]     = React.useState(null);
  const [loading, setLoading] = React.useState(false);

  const handleFetch = () => {
    setLoading(true);
    fetch('/api/auction', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ budget, top: topN }),
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
    <Modal title="Auction Values" onClose={onClose} width={560}>
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

// ─── HOME SCREEN ─────────────────────────────────────────────────────────────
function HomeScreen({ leagues, onSelectLeague, onAddLeague, onEditLeague, onDeleteLeague, playerCount, onRefreshPlayers }) {
  const platformColors = { ESPN:'#cc0000', Yahoo:'#6001d2', Sleeper:'#1e1e1e', 'NFL.com':'#013369', Other: T.muted };
  const [showPull, setShowPull]       = React.useState(false);
  const [showAuction, setShowAuction] = React.useState(false);

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
          <Btn variant="green" size="sm" onClick={() => setShowPull(true)}>Pull Data</Btn>
          <Btn variant="ghost" size="sm" onClick={() => setShowAuction(true)}>Auction $</Btn>
          <Btn onClick={onAddLeague}>+ Add League</Btn>
        </div>
      </div>

      <div style={{flex:1, padding:'40px 32px', maxWidth:960, margin:'0 auto', width:'100%', boxSizing:'border-box'}}>
        <h2 style={{fontSize:22, fontWeight:700, color:T.text, margin:'0 0 8px'}}>Your Leagues</h2>
        <p style={{fontSize:14, color:T.muted, margin:'0 0 28px'}}>
          Select a league to enter draft mode, or add a new one.
        </p>

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
            return (
              <div key={lg.id} style={{
                background:T.surface, border:`1px solid ${T.border}`, borderRadius:T.r,
                padding:20, cursor:'pointer', transition:'box-shadow .15s, transform .15s',
                position:'relative', overflow:'hidden',
              }}
                onClick={() => onSelectLeague(lg.id)}
                onMouseEnter={e => { e.currentTarget.style.boxShadow='0 4px 20px rgba(0,0,0,.1)'; e.currentTarget.style.transform='translateY(-2px)'; }}
                onMouseLeave={e => { e.currentTarget.style.boxShadow='none'; e.currentTarget.style.transform='none'; }}
              >
                <div style={{position:'absolute', top:0, left:0, right:0, height:3, background:pc}} />

                <div style={{display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:12, marginTop:4}}>
                  <div>
                    <div style={{fontSize:16, fontWeight:700, color:T.text}}>{lg.name}</div>
                    <div style={{fontSize:12, color:T.muted, marginTop:2}}>{lg.platform}</div>
                  </div>
                  <div style={{display:'flex', gap:6}}>
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
                  <Badge label={`Pick #${lg.draftPosition}`} color="gray" />
                  <Badge label={`${totalSlots} slots`} color="gray" />
                </div>

                <div style={{
                  marginTop:16, paddingTop:12, borderTop:`1px solid ${T.borderLight}`,
                  display:'flex', alignItems:'center', justifyContent:'space-between',
                }}>
                  <span style={{fontSize:12, color:T.muted}}>
                    QB{lg.rosterSlots.QB} · RB{lg.rosterSlots.RB} · WR{lg.rosterSlots.WR} · TE{lg.rosterSlots.TE} · K{lg.rosterSlots.K} · DST{lg.rosterSlots.DST}
                  </span>
                  <span style={{fontSize:12, fontWeight:600, color:T.primary}}>Draft →</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {showPull && <PullDataModal league={leagues[0]} onClose={() => setShowPull(false)} onComplete={onRefreshPlayers} />}
      {showAuction && <AuctionModal onClose={() => setShowAuction(false)} />}
    </div>
  );
}

// ─── APP ROOT ─────────────────────────────────────────────────────────────────
function App() {
  const [players, setPlayers] = React.useState(null);
  const [loadError, setLoadError] = React.useState(null);

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
      .then(data => { if (!data.error) setPlayers(data); })
      .catch(() => {});
  }, []);

  React.useEffect(() => {
    fetch('/api/players')
      .then(r => r.json())
      .then(data => {
        if (data.error) throw new Error(data.error);
        setPlayers(data);
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
        onBack={() => setSelectedId(null)}
        onAddPick={pick => addPick(selectedLeague.id, pick)}
        onUndoPick={() => undoPick(selectedLeague.id)}
        onResetPicks={() => resetPicks(selectedLeague.id)}
        onUpdateLeague={patch => updateLeague(selectedLeague.id, patch)}
        onRefreshPlayers={refreshPlayers}
      />
    );
  }

  return (
    <>
      <HomeScreen
        leagues={leagues}
        onSelectLeague={setSelectedId}
        onAddLeague={() => { setEditingId(null); setShowSetup(true); }}
        onEditLeague={id => { setEditingId(id); setShowSetup(true); }}
        onDeleteLeague={deleteLeague}
        playerCount={players ? players.length : null}
        onRefreshPlayers={refreshPlayers}
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
  LeagueSetupModal, HomeScreen, App,
});
