// ─── WINDOW SIZE HOOK ────────────────────────────────────────────────────────
function useWindowWidth() {
  const [width, setWidth] = React.useState(
    typeof window !== 'undefined' ? window.innerWidth : 1200
  );
  React.useEffect(() => {
    const handleResize = () => setWidth(window.innerWidth);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);
  return width;
}

// ─── DRAWER OVERLAY ──────────────────────────────────────────────────────────
function Drawer({ title, onClose, children }) {
  return (
    <div style={{
      position:'fixed', inset:0, background:'rgba(0,0,0,.45)', zIndex:990,
      display:'flex', justifyContent:'flex-end',
    }} onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={{
        background: T.surface, width:'100%', maxWidth:360, height:'100%',
        display:'flex', flexDirection:'column', boxShadow:'-4px 0 24px rgba(0,0,0,.2)',
        overflow:'hidden',
      }}>
        <div style={{
          padding:'14px 16px', borderBottom:`1px solid ${T.border}`,
          display:'flex', alignItems:'center', justifyContent:'space-between', flexShrink:0,
        }}>
          <span style={{fontSize:14, fontWeight:700, color:T.text}}>{title}</span>
          <button onClick={onClose} style={{
            background:'none', border:'none', fontSize:20, cursor:'pointer', color:T.muted, padding:'0 4px',
          }}>×</button>
        </div>
        <div style={{flex:1, overflowY:'auto', display:'flex', flexDirection:'column'}}>
          {children}
        </div>
      </div>
    </div>
  );
}

// ─── POSITION COLORS ─────────────────────────────────────────────────────────
const POS_COLORS = {
  QB:  { bg:'#fef3c7', fg:'#92400e' },
  RB:  { bg:'#dcfce7', fg:'#14532d' },
  WR:  { bg:'#dbeafe', fg:'#1e3a8a' },
  TE:  { bg:'#ede9fe', fg:'#4c1d95' },
  K:   { bg:'#f3f4f6', fg:'#374151' },
  DST: { bg:'#fce7f3', fg:'#831843' },
};

function PosBadge({ pos }) {
  const c = POS_COLORS[pos] || { bg: T.borderLight, fg: T.muted };
  return (
    <span style={{
      background: c.bg, color: c.fg, borderRadius: 4, padding: '2px 7px',
      fontSize: 11, fontWeight: 800, letterSpacing: .4, display:'inline-block',
      minWidth: 32, textAlign:'center',
    }}>{pos}</span>
  );
}

function VORPBadge({ vorp }) {
  const isPos = vorp > 0;
  const isNeg = vorp < -5;
  const color = isPos ? T.green : isNeg ? T.red : T.muted;
  const bg    = isPos ? T.greenLight : isNeg ? T.redLight : T.borderLight;
  return (
    <span style={{
      background: bg, color, borderRadius: 4, padding: '2px 8px',
      fontSize: 12, fontWeight: 700, fontFamily: 'DM Mono, monospace',
      display:'inline-block', textAlign:'right', minWidth:48,
    }}>
      {vorp > 0 ? '+' : ''}{vorp}
    </span>
  );
}

function ScoreBadge({ score }) {
  const high = score >= 250;
  const mid  = score >= 180;
  const bg   = high ? '#eef1fd' : mid ? T.greenLight : T.borderLight;
  const fg   = high ? T.primary : mid ? T.green : T.muted;
  return (
    <span style={{
      background: bg, color: fg, borderRadius: 4, padding: '2px 8px',
      fontSize: 12, fontWeight: 800, fontFamily: 'DM Mono, monospace',
      display:'inline-block', textAlign:'right', minWidth:54,
    }}>
      {Math.round(score)}
    </span>
  );
}

// Local round-strategy hint generator (no external API call needed)
function generateRoundHint(round, myPlayers, topAvailable, league) {
  const slots = league.rosterSlots;
  const counts = {};
  myPlayers.forEach(p => { counts[p.pos] = (counts[p.pos] || 0) + 1; });
  const top = topAvailable[0];

  if (round <= 2) {
    if (top && (top.pos === 'RB' || top.pos === 'WR'))
      return `Round ${round}: lock in elite ${top.pos} value. ${top.name} has the highest VORP — don't pass.`;
    return `Round ${round}: prioritize the highest VORP available. RB/WR depth tier is what wins leagues.`;
  }
  if (round <= 4) {
    const rb = counts.RB || 0, wr = counts.WR || 0;
    if (rb < 1) return `Round ${round}: you have 0 RBs. RB scarcity is real — strongly consider locking one.`;
    if (wr < 1) return `Round ${round}: you have 0 WRs. Grab a WR1 before the tier breaks.`;
    return `Round ${round}: continue building RB/WR core. Elite TE (Kelce-tier) is also a defensible reach now.`;
  }
  if (round <= 7) {
    if (!counts.QB && (slots.QB || 0) > 0) {
      const topQB  = topAvailable.find(p => p.pos === 'QB');
      const qbRank = topQB ? topAvailable.indexOf(topQB) + 1 : 0;
      if (topQB && qbRank <= 3)
        return `Round ${round}: ${topQB.name} is the #${qbRank} score on the board — QB window is open, take it.`;
      return `Round ${round}: no QB yet — okay for now${topQB ? ` (${topQB.name} ranks #${qbRank})` : ''}, but your open starter slots score higher. Fill those first, grab a QB by round 7-8.`;
    }
    return `Round ${round}: depth time. RB handcuffs and WR3/4 with target share matter; avoid kicker/DST.`;
  }
  if (round <= 10) {
    if (!counts.TE && (slots.TE || 0) > 0)
      return `Round ${round}: TE streamers are fine but a startable TE solves a slot. Look at usage trends.`;
    return `Round ${round}: bench upside picks. Rookies, late breakouts, and high-target shares.`;
  }
  if (round <= 12) return `Round ${round}: backups & lottery tickets. Avoid drafting K/DST until last 2 rounds.`;
  return `Round ${round}: kicker + DST — pick the highest-projected ones with favorable byes.`;
}

// ─── MY TEAM PANEL ────────────────────────────────────────────────────────────
function MyTeamPanel({ league, myPlayers, round, hint, onGetHint, fullWidth=false }) {
  const slots = league.rosterSlots;
  const slotDefs = [];
  for (let i=0;i<(slots.QB||0);i++)   slotDefs.push({label:'QB',  pos:'QB'});
  for (let i=0;i<(slots.RB||0);i++)   slotDefs.push({label:'RB',  pos:'RB'});
  for (let i=0;i<(slots.WR||0);i++)   slotDefs.push({label:'WR',  pos:'WR'});
  for (let i=0;i<(slots.TE||0);i++)   slotDefs.push({label:'TE',  pos:'TE'});
  const flexMap = (typeof FLEX_TYPES_JS !== 'undefined') ? FLEX_TYPES_JS
    : { FLEX: { label:'FLX', elig:['RB','WR','TE'] } };
  Object.keys(flexMap)
    .filter(fk => (slots[fk]||0) > 0)
    .sort((a,b) => flexMap[a].elig.length - flexMap[b].elig.length)
    .forEach(fk => {
      for (let i=0;i<(slots[fk]||0);i++)
        slotDefs.push({label:flexMap[fk].label, pos:'FLEX', elig:flexMap[fk].elig});
    });
  for (let i=0;i<(slots.K||0);i++)    slotDefs.push({label:'K',   pos:'K'});
  for (let i=0;i<(slots.DST||0);i++)  slotDefs.push({label:'DST', pos:'DST'});
  for (let i=0;i<(slots.BN||0);i++)   slotDefs.push({label:'BN',  pos:null});

  const filled = [];
  const remaining = [...myPlayers];

  slotDefs.forEach(slot => {
    if (!slot.pos) { filled.push({slot, player: remaining.shift()||null}); return; }
    if (slot.pos === 'FLEX') {
      const elig = new Set(slot.elig || ['RB','WR','TE']);
      const idx = remaining.findIndex(p => elig.has(p.pos));
      filled.push({slot, player: idx>=0 ? remaining.splice(idx,1)[0] : null});
      return;
    }
    const idx = remaining.findIndex(p => p.pos === slot.pos);
    filled.push({slot, player: idx>=0 ? remaining.splice(idx,1)[0] : null});
  });

  const needs = getRosterNeeds(myPlayers, slots);

  return (
    <div style={{
      width: fullWidth ? '100%' : 240, flexShrink:0, background:T.surface,
      borderRight: fullWidth ? 'none' : `1px solid ${T.border}`, display:'flex', flexDirection:'column', overflowY:'auto', flex:1,
    }}>
      <div style={{padding:'14px 16px', borderBottom:`1px solid ${T.border}`}}>
        <div style={{fontSize:11, fontWeight:700, color:T.muted, letterSpacing:.5}}>MY TEAM</div>
        <div style={{fontSize:12, color:T.muted, marginTop:2}}>
          {myPlayers.length} / {slotDefs.length} picked
        </div>
      </div>

      <div style={{padding:'8px 12px', flex:1}}>
        {filled.map(({slot, player}, i) => (
          <div key={i} style={{
            display:'flex', alignItems:'center', gap:8, padding:'5px 4px',
            borderBottom: i<filled.length-1 ? `1px solid ${T.borderLight}` : 'none', minHeight:34,
          }}>
            <span style={{fontSize:10, fontWeight:700, color:T.muted, width:28, flexShrink:0}}>{slot.label}</span>
            {player ? (
              <div style={{minWidth:0, flex:1}}>
                <div style={{fontSize:12, fontWeight:600, color:T.text, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}}>
                  {player.name}
                </div>
                <div style={{fontSize:10, color:T.muted, display:'flex', gap:5}}>
                  <span>{player.nflTeam}</span>
                  {player.byeWeek && <span style={{color:T.mutedLight}}>BYE {player.byeWeek}</span>}
                </div>
              </div>
            ) : (
              <span style={{fontSize:12, color:T.borderLight}}>—</span>
            )}
          </div>
        ))}
      </div>

      {needs.length > 0 && (
        <div style={{padding:'10px 12px', borderTop:`1px solid ${T.border}`}}>
          <div style={{fontSize:10, fontWeight:700, color:T.muted, letterSpacing:.5, marginBottom:6}}>NEEDS</div>
          <div style={{display:'flex', flexWrap:'wrap', gap:4}}>
            {needs.map(pos => <PosBadge key={pos} pos={pos} />)}
          </div>
        </div>
      )}

      <div style={{padding:'12px', borderTop:`1px solid ${T.border}`}}>
        <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:6}}>
          <div style={{fontSize:10, fontWeight:700, color:T.muted, letterSpacing:.5}}>ROUND {round} HINT</div>
          <button onClick={onGetHint} style={{
            background:'none', border:'none', cursor:'pointer',
            fontSize:11, color:T.primary, fontWeight:600, padding:0, fontFamily:'inherit',
          }}>Refresh</button>
        </div>
        {hint
          ? <div style={{fontSize:12, color:T.text, lineHeight:1.55}}>{hint}</div>
          : <div style={{fontSize:12, color:T.muted, fontStyle:'italic'}}>Click Refresh for a strategy tip.</div>
        }
      </div>
    </div>
  );
}

// ─── OPPONENTS PANEL ─────────────────────────────────────────────────────────
function rosterCountString(counts) {
  return ['QB','RB','WR','TE','K','DST']
    .filter(pos => counts[pos])
    .map(pos => `${counts[pos]}${pos}`)
    .join(' · ') || 'empty';
}

function ModeToggle({ mode, onChange }) {
  return (
    <div style={{display:'inline-flex', border:`1px solid ${T.border}`, borderRadius:T.rxs, overflow:'hidden'}}>
      {['live','auto'].map(m => (
        <button key={m} onClick={() => onChange(m)} title={m === 'live' ? 'Drafting live — picks by need' : 'Autodrafting — follows ADP'}
          style={{
            border:'none', cursor:'pointer', fontFamily:'inherit',
            padding:'2px 7px', fontSize:10, fontWeight:700, letterSpacing:.3,
            background: mode === m ? (m === 'auto' ? T.amberLight : T.primaryLight) : T.surface,
            color:      mode === m ? (m === 'auto' ? T.amber : T.primary) : T.mutedLight,
          }}>
          {m === 'auto' ? 'AUTO' : 'LIVE'}
        </button>
      ))}
    </div>
  );
}

function OpponentTeamRow({ teamNum, teamName, mode, counts, posProbs, pickLabel, onSetMode, highlight }) {
  const topPos = posProbs
    ? Object.entries(posProbs).sort((a,b) => b[1]-a[1]).filter(([,p]) => p >= 0.08).slice(0,3)
    : null;
  return (
    <div style={{
      padding:'8px 10px', borderRadius:T.rsm, marginBottom:6,
      background: highlight ? T.surfaceAlt : 'transparent',
      border: `1px solid ${highlight ? T.border : 'transparent'}`,
    }}>
      <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:3}}>
        <span style={{fontSize:12, fontWeight:700, color:T.text}}>
          {teamName || `Team ${teamNum}`}
          {pickLabel && <span style={{fontWeight:600, color:T.muted, marginLeft:6, fontSize:10}}>{pickLabel}</span>}
        </span>
        <ModeToggle mode={mode} onChange={onSetMode} />
      </div>
      <div style={{fontSize:10, color:T.muted, marginBottom: topPos ? 5 : 0}}>{rosterCountString(counts)}</div>
      {topPos && (
        <div style={{display:'flex', gap:4, flexWrap:'wrap'}}>
          {topPos.map(([pos, p]) => (
            <span key={pos} style={{display:'inline-flex', alignItems:'center', gap:3}}>
              <PosBadge pos={pos} />
              <span style={{fontSize:10, fontWeight:700, color:T.muted, fontFamily:'DM Mono,monospace'}}>
                {Math.round(p*100)}%
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function OpponentsPanel({ league, oppData, picksMade, onSetTeamMode, fullWidth=false }) {
  if (!oppData) return null;
  const modes = league.teamModes || {};
  const upcomingTeams = new Set(oppData.upcoming.map(u => u.teamNum));

  const others = [];
  for (let t = 1; t <= league.numTeams; t++) {
    if (t === league.draftPosition || upcomingTeams.has(t)) continue;
    others.push(t);
  }

  const expected = Object.entries(oppData.expectedByPos)
    .filter(([,n]) => n >= 0.5)
    .sort((a,b) => b[1]-a[1])
    .slice(0,4);

  return (
    <div style={{
      width: fullWidth ? '100%' : 236, flexShrink:0, background:T.surface,
      borderLeft: fullWidth ? 'none' : `1px solid ${T.border}`, display:'flex', flexDirection:'column', overflowY:'auto', flex:1,
    }}>
      <div style={{padding:'14px 16px', borderBottom:`1px solid ${T.border}`}}>
        <div style={{fontSize:11, fontWeight:700, color:T.muted, letterSpacing:.5}}>OPPONENTS</div>
        {expected.length > 0 ? (
          <div style={{fontSize:11, color:T.muted, marginTop:4, lineHeight:1.5}}>
            Likely gone before your pick:{' '}
            {expected.map(([pos, n], i) => (
              <span key={pos} style={{fontWeight:700, color:T.text}}>
                {i > 0 && <span style={{fontWeight:400, color:T.muted}}> · </span>}
                ~{n.toFixed(1)} {pos}
              </span>
            ))}
          </div>
        ) : (
          <div style={{fontSize:11, color:T.muted, marginTop:4}}>
            {oppData.upcoming.length === 0 ? 'No picks before your next turn.' : 'Predictions update each pick.'}
          </div>
        )}
      </div>

      <div style={{padding:'10px 10px', flex:1}}>
        {oppData.upcoming.length > 0 && (
          <div style={{fontSize:10, fontWeight:700, color:T.muted, letterSpacing:.5, margin:'2px 6px 6px'}}>
            PICKING BEFORE YOU
          </div>
        )}
        {oppData.upcoming.map(u => (
          <OpponentTeamRow key={u.teamNum}
            teamNum={u.teamNum}
            teamName={(league.teamNames || [])[u.teamNum - 1]}
            mode={modes[u.teamNum] === 'auto' ? 'auto' : 'live'}
            counts={u.rosterCounts}
            posProbs={u.posProbs}
            pickLabel={`pick ${u.pickNum - picksMade > 1 ? `in ${u.pickNum - picksMade}` : 'next'}`}
            onSetMode={m => onSetTeamMode(u.teamNum, m)}
            highlight
          />
        ))}

        {others.length > 0 && (
          <div style={{fontSize:10, fontWeight:700, color:T.muted, letterSpacing:.5, margin:'12px 6px 6px'}}>
            AFTER YOUR PICK
          </div>
        )}
        {others.map(t => (
          <OpponentTeamRow key={t}
            teamNum={t}
            teamName={(league.teamNames || [])[t - 1]}
            mode={modes[t] === 'auto' ? 'auto' : 'live'}
            counts={oppData.rosters[t] ? oppData.rosters[t].reduce((c,p) => { c[p.pos]=(c[p.pos]||0)+1; return c; }, {}) : {}}
            posProbs={null}
            pickLabel={null}
            onSetMode={m => onSetTeamMode(t, m)}
            highlight={false}
          />
        ))}
      </div>

      <div style={{padding:'10px 16px', borderTop:`1px solid ${T.border}`, fontSize:10, color:T.muted, lineHeight:1.5}}>
        <b style={{color:T.text}}>LIVE</b> = drafts by roster need.{' '}
        <b style={{color:T.text}}>AUTO</b> = autodraft, follows ADP. Toggle per team — it changes
        availability odds and the position-run alerts.
      </div>
    </div>
  );
}

// ─── RECOMMENDATION BAR ───────────────────────────────────────────────────────
function RecCard({ icon, label, player, reason, highlight }) {
  if (!player) return null;
  return (
    <div style={{
      background: highlight ? T.primaryLight : T.surfaceAlt,
      border: `1.5px solid ${highlight ? T.primary : T.border}`,
      borderRadius: T.r, padding:'12px 14px', flex:'1 1 200px', minWidth:200,
    }}>
      <div style={{fontSize:10, fontWeight:700, color: highlight ? T.primary : T.muted, letterSpacing:.5, marginBottom:6}}>
        {icon} {label}
      </div>
      <div style={{display:'flex', alignItems:'center', gap:8, marginBottom:4}}>
        <PosBadge pos={player.pos} />
        <span style={{fontSize:14, fontWeight:700, color:T.text, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}}>
          {player.name}
        </span>
      </div>
      <div style={{display:'flex', alignItems:'center', gap:6, marginBottom:6, flexWrap:'wrap'}}>
        <span style={{fontSize:11, color:T.muted}}>{player.nflTeam}</span>
        {player.tier && <span style={{fontSize:11, color:T.muted}}>T{player.tier}</span>}
        {player.draftScore != null && <ScoreBadge score={player.draftScore} />}
        <VORPBadge vorp={player.vorp} />
      </div>
      {reason && (
        <div style={{fontSize:11, color: highlight ? T.primary : T.muted, lineHeight:1.4}}>
          {reason}
        </div>
      )}
    </div>
  );
}

function RecommendationBar({ scored, myPlayers, league, oppData }) {
  if (!scored || scored.length === 0) {
    return (
      <div style={{padding:'12px 16px', background:T.surface, borderBottom:`1px solid ${T.border}`}}>
        <div style={{fontSize:12, color:T.muted}}>No players available.</div>
      </div>
    );
  }

  const rolled = scored.filter(p => p.draftScore != null);
  if (rolled.length === 0) {
    return (
      <div style={{padding:'12px 16px', background:T.surface, borderBottom:`1px solid ${T.border}`}}>
        <div style={{fontSize:12, color:T.muted}}>Waiting for the engine…</div>
      </div>
    );
  }
  const sortedByScore = [...rolled].sort((a,b) => b.draftScore - a.draftScore);
  const bestOverall   = sortedByScore[0];

  const needs     = getRosterNeeds(myPlayers, league.rosterSlots);
  const flexElig  = new Set(['RB','WR','TE']);
  const posCounts = {};
  myPlayers.forEach(p => { posCounts[p.pos] = (posCounts[p.pos] || 0) + 1; });
  const starterNeeds = ['QB','RB','WR','TE','K','DST'].filter(pos =>
    (posCounts[pos] || 0) < (league.rosterSlots[pos] || 0)
  );
  const fillsNeed = p => starterNeeds.includes(p.pos) ||
    (starterNeeds.length === 0 && needs.includes('FLEX') && flexElig.has(p.pos));

  const NEED_EPS = 0.5;
  const bestByNeed = sortedByScore.find(p => p.draftScore > NEED_EPS && fillsNeed(p)) || null;
  const isSame = bestByNeed && bestOverall.id === bestByNeed.id;

  let scarce = null;
  rolled.forEach(p => {
    if (p.scarcityBonus == null || p.availPct == null) return;
    if (p.scarcityBonus >= 4 && p.availPct <= 60) {
      if (!scarce || p.scarcityBonus > scarce.scarcityBonus) scarce = p;
    }
  });

  let runAlert = null;
  if (oppData && oppData.expectedByPos) {
    needs.forEach(pos => {
      const exp = oppData.expectedByPos[pos] || 0;
      if (exp >= 1.6) {
        const top = sortedByScore.find(p => p.pos === pos && p.draftScore > NEED_EPS);
        if (top && (!runAlert || exp > runAlert.exp)) runAlert = { pos, exp, player: top };
      }
    });
  }

  let reach = null;
  if (bestByNeed && !isSame) {
    const gap = bestOverall.draftScore - bestByNeed.draftScore;
    if (gap >= 12) reach = { player: bestOverall, gap };
  }

  const dupId = id => id === bestOverall.id || (bestByNeed && id === bestByNeed.id);
  let situational = null;
  if (runAlert && !dupId(runAlert.player.id)) {
    situational = { kind:'run', ...runAlert };
  } else if (scarce && !dupId(scarce.id)) {
    situational = { kind:'scarce', player: scarce };
  } else if (reach && reach.player.id !== bestOverall.id) {
    situational = { kind:'reach', ...reach };
  }

  return (
    <div style={{padding:'12px 16px', background:T.surface, borderBottom:`1px solid ${T.border}`}}>
      <div style={{fontSize:10, fontWeight:700, color:T.muted, letterSpacing:.5, marginBottom:8}}>RECOMMENDATIONS</div>
      <div style={{display:'flex', gap:10, flexWrap:'wrap'}}>
        <RecCard icon="▲" label="BEST DRAFT SCORE"
          player={bestOverall}
          reason={isSame
            ? 'Top season-points impact AND fills an open starting slot.'
            : `${bestOverall.availPct}% chance still there at your next pick.`}
          highlight={isSame} />
        {bestByNeed && !isSame && (
          <RecCard icon="◎" label="BEST BY NEED"
            player={bestByNeed}
            reason={`Top ${bestByNeed.pos} for an open starting slot · ${bestByNeed.availPct}% avail next pick`} />
        )}
        {situational && situational.kind === 'run' && (
          <RecCard icon="⏳" label={`${situational.pos} RUN LIKELY`}
            player={situational.player}
            reason={`~${situational.exp.toFixed(1)} ${situational.pos}s likely gone before your next pick — only ${situational.player.availPct}% chance ${situational.player.name.split(' ').pop()} survives.`}
            highlight />
        )}
        {situational && situational.kind === 'scarce' && (
          <RecCard icon="⚠" label={`${situational.player.pos} SCARCE`}
            player={situational.player}
            reason={`+${Math.round(situational.player.scarcityBonus)} pts of this pick's value is scarcity — only ${situational.player.availPct}% chance they last.`}
            highlight />
        )}
        {situational && situational.kind === 'reach' && (
          <RecCard icon="⚡" label="WORTH THE REACH"
            player={situational.player}
            reason={`+${Math.round(situational.gap)} season-pts impact over your best need — worth taking now.`}
            highlight />
        )}
        {!situational && !isSame && (
          <div style={{
            flex:'1 1 200px', minWidth:200, background:T.surfaceAlt, border:`1.5px dashed ${T.border}`,
            borderRadius:T.r, padding:'12px 14px', display:'flex', alignItems:'center', justifyContent:'center',
          }}>
            <span style={{fontSize:12, color:T.muted}}>No run, scarcity, or reach alerts.</span>
          </div>
        )}
      </div>
    </div>
  );
}

function cmpScore(a, b) {
  const sa = a.draftScore == null ? -Infinity : a.draftScore;
  const sb = b.draftScore == null ? -Infinity : b.draftScore;
  if (sa === sb) return (b.vorp || 0) - (a.vorp || 0);
  return sb - sa;
}

function picksUntilMyTurn(picksMade, numTeams, draftPosition) {
  for (let i = 0; i <= numTeams * 2 + 2; i++) {
    if (getSnakeTeam(picksMade + 1 + i, numTeams) === draftPosition) return i;
  }
  return numTeams;
}

// ─── PLAYER LIST ──────────────────────────────────────────────────────────────
function PlayerList({ players, onDraft, showDrafted, onToggleDrafted }) {
  const [search,    setSearch]    = React.useState('');
  const [posFilter, setPosFilter] = React.useState('ALL');
  const [sortBy,    setSortBy]    = React.useState('draftScore');
  const [hoverId,   setHoverId]   = React.useState(null);
  const width = useWindowWidth();

  const isNarrow = width < 650;
  const isMedium = width >= 650 && width < 960;
  const isWide   = width >= 960;

  const sortOptions = [
    {value:'draftScore', label:'Draft Score'},
    {value:'vorp',       label:'VORP'},
    {value:'projPts',    label:'Proj Pts'},
    {value:'adp',        label:'ADP'},
  ];

  const filtered = players
    .filter(p => showDrafted || !p.drafted)
    .filter(p => posFilter === 'ALL' || p.pos === posFilter)
    .filter(p => !search ||
      p.name.toLowerCase().includes(search.toLowerCase()) ||
      p.nflTeam.toLowerCase().includes(search.toLowerCase())
    )
    .sort((a,b) => {
      if (sortBy === 'adp')      return a.adp - b.adp;
      if (sortBy === 'projPts')  return b.projPts - a.projPts;
      if (sortBy === 'vorp')     return b.vorp - a.vorp;
      return cmpScore(a, b);
    });

  const GRID = isWide
    ? '30px 1fr 52px 48px 44px 54px 54px 64px 74px'
    : isMedium
      ? '26px 1fr 48px 54px 54px 62px 70px'
      : '24px 1fr 44px 52px 58px 66px';

  return (
    <div style={{flex:1, display:'flex', flexDirection:'column', minHeight:0, overflow:'hidden'}}>
      <div style={{
        padding:'8px 14px', background:T.surface, borderBottom:`1px solid ${T.border}`,
        display:'flex', flexDirection:'column', gap:8, flexShrink:0,
      }}>
        <div style={{display:'flex', gap:8, alignItems:'center'}}>
          <input placeholder="Search player or team…" value={search}
            onChange={e => setSearch(e.target.value)}
            style={{
              flex:1, minWidth:120, padding:'6px 10px', border:`1.5px solid ${T.border}`,
              borderRadius:T.rsm, fontSize:13, fontFamily:'inherit', color:T.text, outline:'none',
            }} />
          <div style={{display:'flex', alignItems:'center', gap:4, flexShrink:0}}>
            <span style={{fontSize:11, fontWeight:700, color:T.muted, letterSpacing:.3}}>Sort:</span>
            <select value={sortBy} onChange={e=>setSortBy(e.target.value)} style={{
              padding:'6px 8px', border:`1.5px solid ${T.primary}`, borderRadius:T.rsm,
              fontSize:12, fontWeight:700, color:T.primary, fontFamily:'inherit', background:T.primaryLight, cursor:'pointer',
            }}>
              {sortOptions.map(o=><option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
        </div>

        <div style={{
          display:'flex', gap:4, alignItems:'center', overflowX:'auto',
          whiteSpace:'nowrap', paddingBottom:2, msOverflowStyle:'none', scrollbarWidth:'none',
        }}>
          {['ALL',...window.POSITIONS].map(pos => (
            <button key={pos} onClick={() => setPosFilter(pos)} style={{
              padding:'4px 8px', borderRadius:T.rxs, flexShrink:0,
              border:`1.5px solid ${posFilter===pos ? T.primary : T.border}`,
              background: posFilter===pos ? T.primaryLight : T.surface,
              color: posFilter===pos ? T.primary : T.muted,
              fontSize:11, fontWeight:600, cursor:'pointer', fontFamily:'inherit',
            }}>{pos}</button>
          ))}
          <div style={{width:1, height:16, background:T.border, margin:'0 4px', flexShrink:0}} />
          <button onClick={onToggleDrafted} style={{
            padding:'4px 8px', borderRadius:T.rxs, flexShrink:0,
            border:`1.5px solid ${T.border}`,
            background: showDrafted ? T.borderLight : T.surface,
            color:T.muted, fontSize:11, cursor:'pointer', fontFamily:'inherit', fontWeight:600,
          }}>
            {showDrafted ? 'Hide Drafted' : 'Show Drafted'}
          </button>
        </div>
      </div>

      <div style={{
        display:'grid', gridTemplateColumns:GRID,
        padding:'7px 14px', background:T.surfaceAlt, borderBottom:`1px solid ${T.border}`,
        fontSize:10, fontWeight:700, color:T.muted, letterSpacing:.5, gap:6, alignItems:'center',
      }}>
        <span>#</span>
        <span>PLAYER</span>
        <span>POS</span>
        {isWide && <span>TEAM</span>}
        {isWide && <span style={{textAlign:'center'}}>BYE</span>}
        {(isWide || isMedium) && <span style={{textAlign:'right'}}>PROJ</span>}
        <span style={{textAlign:'right'}}>VORP</span>
        <span style={{textAlign:'right', color:T.primary}}>SCORE ↓</span>
        <span></span>
      </div>

      <div style={{flex:1, overflowY:'auto'}}>
        {filtered.length === 0 && (
          <div style={{padding:40, textAlign:'center', color:T.muted, fontSize:14}}>
            No players match your filters.
          </div>
        )}
        {filtered.map((p,i) => {
          const isHov = hoverId === p.id;
          const tierDot = ['','#d97706','#6b7280','#9ca3af','#d1d5db','#e5e7eb'][p.tier] || '#e5e7eb';
          const slotColor = p.slotType === 'starter' ? T.green : p.slotType === 'flex' ? T.blue : T.muted;

          const teamText = p.nflTeam || 'FA';
          const byeText = p.byeWeek ? `Bye ${p.byeWeek}` : null;
          const projText = `${Math.round(p.projPts)} pts`;
          const subDetails = isNarrow
            ? [teamText, byeText, projText, `ADP ${p.adp}`].filter(Boolean).join(' · ')
            : isMedium
              ? [teamText, byeText, `ADP ${p.adp}`].filter(Boolean).join(' · ')
              : `ADP ${p.adp}`;

          return (
            <div key={p.id}
              onMouseEnter={() => setHoverId(p.id)}
              onMouseLeave={() => setHoverId(null)}
              title={p.draftScore != null
                ? `Draft Score: ${Math.round(p.draftScore)} | Lineup Gain: ${p.lineupGain} | Scarcity Bonus: ${p.scarcityBonus} | Need ×${p.needMult} | Slot: ${p.slotType || '—'} | Avail: ${p.availPct}%`
                : undefined}
              style={{
                display:'grid', gridTemplateColumns:GRID,
                padding:'7px 14px', gap:6, alignItems:'center',
                borderBottom:`1px solid ${T.borderLight}`,
                background: p.drafted ? T.surfaceAlt : isHov ? '#f5f7ff' : T.surface,
                opacity: p.drafted ? 0.4 : 1,
                transition:'background .1s',
              }}>
              <span style={{fontSize:11, color:T.mutedLight, fontFamily:'DM Mono,monospace'}}>{i+1}</span>

              <div style={{minWidth:0}}>
                <div style={{fontSize:13, fontWeight:600, color:T.text, display:'flex', alignItems:'center', gap:5}}>
                  <span style={{
                    width:7, height:7, borderRadius:'50%', background:tierDot, flexShrink:0,
                  }} title={`Tier ${p.tier}`} />
                  <span style={{overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{p.name}</span>
                </div>
                {isHov && p.draftScore != null ? (
                  <div style={{fontSize:10, color:T.muted, marginTop:1, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}}>
                    <span style={{color:slotColor, fontWeight:700, marginRight:4}}>{(p.slotType||'bench').toUpperCase()}</span>
                    avail {p.availPct}%
                    {p.byePen > 0 && <span style={{color:T.amber}}> · bye −{p.byePen}</span>}
                  </div>
                ) : (
                  <div style={{fontSize:10, color:T.mutedLight, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}}>
                    {subDetails}
                  </div>
                )}
              </div>

              <span><PosBadge pos={p.pos} /></span>
              {isWide && <span style={{fontSize:12, color:T.muted, fontWeight:500, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{p.nflTeam}</span>}
              {isWide && (
                <span style={{fontSize:12, fontFamily:'DM Mono,monospace', color:T.muted, textAlign:'center'}}>
                  {p.byeWeek || '—'}
                </span>
              )}
              {(isWide || isMedium) && (
                <span style={{fontSize:12, fontWeight:600, color:T.text, fontFamily:'DM Mono,monospace', textAlign:'right'}}>
                  {Math.round(p.projPts)}
                </span>
              )}
              <span style={{display:'flex', justifyContent:'flex-end'}}>
                <VORPBadge vorp={p.vorp} />
              </span>
              <span style={{display:'flex', justifyContent:'flex-end'}}>
                {p.draftScore != null
                  ? <ScoreBadge score={p.draftScore} />
                  : <span style={{fontSize:11, color:T.muted}}>—</span>
                }
              </span>
              <span style={{display:'flex', justifyContent:'flex-end'}}>
                {p.drafted ? (
                  <span style={{fontSize:11, color:T.muted}}>Drafted</span>
                ) : (
                  <button onClick={() => onDraft(p)} style={{
                    background: isHov ? T.primary : T.primaryLight,
                    color: isHov ? '#fff' : T.primary,
                    border:'none', borderRadius:T.rxs, padding:'4px 8px',
                    fontSize:11, fontWeight:700, cursor:'pointer', fontFamily:'inherit', transition:'all .15s',
                  }}>Draft</button>
                )}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── DRAFT BOARD MODAL ────────────────────────────────────────────────────────
function DraftBoardModal({ league, picks, allPlayers, onClose }) {
  const { numTeams, draftPosition } = league;
  const playerById = Object.fromEntries(allPlayers.map(p=>[p.id,p]));
  const totalSlots = Object.entries(league.rosterSlots)
    .reduce((s,[k,v]) => k === 'IR' ? s : s + v, 0);
  const rounds     = Math.max(totalSlots, Math.ceil(picks.length / numTeams));
  const teamNums   = Array.from({length:numTeams},(_,i)=>i+1);
  const roundNums  = Array.from({length:rounds||1},(_,i)=>i+1);

  return (
    <Modal title="Full Draft Board" onClose={onClose} width={Math.min(numTeams*110+80,1100)}>
      <div style={{overflowX:'auto'}}>
        <table style={{borderCollapse:'collapse', width:'100%', fontSize:11}}>
          <thead>
            <tr>
              <th style={{padding:'6px 10px', textAlign:'left', color:T.muted, fontWeight:700, fontSize:10, letterSpacing:.4}}>RND</th>
              {teamNums.map(t=>(
                <th key={t} style={{
                  padding:'6px 8px', textAlign:'center',
                  color: t===draftPosition ? T.primary : T.muted,
                  fontWeight:700, fontSize:10, letterSpacing:.4,
                  background: t===draftPosition ? T.primaryLight : 'transparent',
                }}>
                  {t===draftPosition ? `YOU (${t})` : `T${t}`}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {roundNums.map(rnd=>(
              <tr key={rnd} style={{background: rnd%2===0 ? T.surfaceAlt : T.surface}}>
                <td style={{padding:'5px 10px', fontWeight:700, color:T.muted, fontSize:11, fontFamily:'DM Mono,monospace'}}>
                  R{rnd}
                </td>
                {teamNums.map(t=>{
                  const snakeTeam = rnd%2===1 ? t : numTeams-t+1;
                  const pickIdx   = (rnd-1)*numTeams + snakeTeam - 1;
                  const pick      = picks[pickIdx];
                  const player    = pick ? playerById[pick.playerId] : null;
                  const isMe      = t===draftPosition;
                  return (
                    <td key={t} style={{
                      padding:'5px 8px', textAlign:'center', verticalAlign:'middle',
                      border:`1px solid ${T.borderLight}`,
                      background: isMe ? 'rgba(58,91,239,.04)' : 'transparent',
                      minWidth:90,
                    }}>
                      {player ? (
                        <div>
                          <div style={{fontWeight:600, color:isMe?T.primary:T.text, fontSize:11, lineHeight:1.3}}>
                            {player.name.split(' ').pop()}
                          </div>
                          <PosBadge pos={player.pos} />
                        </div>
                      ) : (
                        <span style={{color:T.borderLight, fontSize:16}}>·</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{marginTop:16, fontSize:12, color:T.muted}}>
        Your picks are highlighted. Snake draft — odd rounds left→right, even rounds right→left.
      </div>
    </Modal>
  );
}

// ─── DRAFT SCREEN ─────────────────────────────────────────────────────────────
function DraftScreen({ league, picks, allPlayers, allLeagues, allPicks, onBack, onAddPick, onUndoPick, onResetPicks, onReplacePicks, onUpdateLeague, onRefreshPlayers }) {
  const [showDraftBoard, setShowDraftBoard] = React.useState(false);
  const [showDrafted,    setShowDrafted]    = React.useState(false);
  const [showOpponents,  setShowOpponents]  = React.useState(true);
  const [showMyTeamDrawer, setShowMyTeamDrawer]   = React.useState(false);
  const [showOppDrawer,    setShowOppDrawer]      = React.useState(false);
  const [showActionsMenu,  setShowActionsMenu]    = React.useState(false);
  const [hint,           setHint]           = React.useState('');
  const [showPullModal,  setShowPullModal]  = React.useState(false);
  const [showAuction,    setShowAuction]    = React.useState(false);
  const [showFreeAgents, setShowFreeAgents] = React.useState(false);
  const [saveMsg,        setSaveMsg]        = React.useState(null);

  const width = useWindowWidth();
  const isDesktop = width >= 1140;
  const isTablet  = width >= 850 && width < 1140;
  const isMobile  = width < 850;
  const isHeaderCompact = width < 960;

  const tweakDefaults = typeof TWEAK_DEFAULTS !== 'undefined' ? TWEAK_DEFAULTS : {
    sims: 24, autoDrafters: 0,
  };
  const [tweaks, setTweaks] = useTweaks(tweakDefaults);

  const draftedIds = React.useMemo(() => new Set(picks.map(p=>p.playerId)), [picks]);
  const { round, pickInRound } = getCurrentRoundPick(picks.length, league.numTeams);
  const currentTeam = getSnakeTeam(picks.length + 1, league.numTeams);
  const isMyPick    = currentTeam === league.draftPosition;

  const playersWithProj = React.useMemo(
    () => withProjections(allPlayers, league),
    [allPlayers, league]
  );
  const playersWithVORP = React.useMemo(
    () => withVORP(playersWithProj, league),
    [playersWithProj, league]
  );

  const myPlayers = React.useMemo(() =>
    picks
      .filter(pk => pk.teamNum === league.draftPosition)
      .map(pk => playersWithVORP.find(p => p.id === pk.playerId))
      .filter(Boolean),
    [picks, league.draftPosition, playersWithVORP]
  );

  const available = React.useMemo(
    () => playersWithVORP.filter(p => !draftedIds.has(p.id)),
    [playersWithVORP, draftedIds]
  );

  const playersById = React.useMemo(
    () => Object.fromEntries(playersWithVORP.map(p => [p.id, p])),
    [playersWithVORP]
  );

  const oppData = React.useMemo(() => {
    if (!window.OpponentModel) return null;
    return window.OpponentModel.analyze(
      available, picks, league, league.teamModes || {}, playersById
    );
  }, [available, picks, league, playersById]);

  const setTeamMode = (teamNum, mode) => {
    onUpdateLeague({ teamModes: { ...(league.teamModes || {}), [teamNum]: mode } });
  };

  const untilMyTurn = picksUntilMyTurn(picks.length, league.numTeams, league.draftPosition);
  const opponentCount = Math.max(1, league.numTeams - 1);
  const autoFrac = Math.min(1, Math.max(0, (tweaks.autoDrafters || 0) / opponentCount));
  const adpNoise = +(1 + (8 - 1) * (1 - autoFrac)).toFixed(1);

  const [suggest, setSuggest] = React.useState({ rows: {}, loading: false, sims: 0, err: null, stale: false });
  const [refreshNonce, setRefreshNonce] = React.useState(0);
  const forceRef = React.useRef(false);
  const handleRefreshRecs = () => { forceRef.current = true; setRefreshNonce(n => n + 1); };

  React.useEffect(() => {
    const force = forceRef.current;
    forceRef.current = false;
    const shouldCompute = force || picks.length === 0 || untilMyTurn <= 1;
    if (!shouldCompute) {
      setSuggest(s => ({ ...s, loading: false, stale: true }));
      return;
    }
    const pickKeys = picks.map(pk => pk.playerId);
    const myKeys = picks
      .filter(pk => pk.teamNum === league.draftPosition)
      .map(pk => pk.playerId);
    const body = {
      picks: pickKeys,
      my_picks: myKeys,
      top: 30,
      league: {
        numTeams: league.numTeams,
        draftPosition: league.draftPosition,
        rosterSlots: league.rosterSlots,
        scoringType: league.scoringType,
        customScoring: league.customScoring,
        adpNoise,
        sims: (tweaks && tweaks.sims) || undefined,
      },
    };
    const ctrl = new AbortController();
    setSuggest(s => ({ ...s, loading: true, err: null }));
    const timer = setTimeout(() => {
      fetch('/api/suggest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: ctrl.signal,
      })
        .then(r => r.json())
        .then(d => {
          if (d.error) { setSuggest({ rows: {}, loading: false, sims: 0, err: d.error, stale: false }); return; }
          const rows = {};
          (d.suggestions || []).forEach(row => { rows[row.id] = row; });
          setSuggest({ rows, loading: false, sims: d.sims || 0, err: null, stale: false });
        })
        .catch(e => {
          if (e.name !== 'AbortError') setSuggest({ rows: {}, loading: false, sims: 0, err: String(e), stale: false });
        });
    }, 120);
    return () => { ctrl.abort(); clearTimeout(timer); };
  }, [picks, untilMyTurn, league.numTeams, league.draftPosition, league.rosterSlots,
      league.scoringType, league.customScoring, refreshNonce]);

  const tweakSig = `${tweaks.sims}|${tweaks.autoDrafters}`;
  const prevTweakSig = React.useRef(tweakSig);
  React.useEffect(() => {
    if (prevTweakSig.current !== tweakSig) {
      prevTweakSig.current = tweakSig;
      handleRefreshRecs();
    }
  }, [tweakSig]);

  const scored = React.useMemo(() => {
    const rows = suggest.rows;
    return available.map(p => {
      const r = rows[p.id];
      if (!r) return { ...p, draftScore: null };
      return {
        ...p,
        draftScore: r.impact,
        impact: r.impact,
        projRoster: r.projRoster,
        goneRisk: r.goneRisk,
        availPct: Math.max(0, Math.round(100 * (1 - (r.goneRisk || 0)))),
        lineupGain: r.immediateGain,
        scarcityBonus: +(r.impact - r.immediateGain).toFixed(1),
        needMult: 1,
        slotType: '',
      };
    });
  }, [available, suggest]);

  const enriched = React.useMemo(() => {
    const scoredMap = Object.fromEntries(scored.map(p=>[p.id,p]));
    return playersWithVORP.map(p => ({
      ...(scoredMap[p.id] || p),
      drafted: draftedIds.has(p.id),
    }));
  }, [scored, playersWithVORP, draftedIds]);

  const handleDraft = p => {
    const pickNum = picks.length + 1;
    const team    = getSnakeTeam(pickNum, league.numTeams);
    onAddPick({ pickNum, teamNum: team, playerId: p.id });
  };

  const handleGetHint = () => {
    const sortedScored = [...scored].sort(cmpScore);
    setHint(generateRoundHint(round, myPlayers, sortedScored, league));
  };

  const handleSave = () => {
    const pickData = picks.map(pk => pk.playerId);
    const myPickData = picks.filter(pk => pk.teamNum === league.draftPosition).map(pk => pk.playerId);
    fetch('/api/save-draft', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ picks: pickData, my_picks: myPickData }),
    })
      .then(r => r.json())
      .then(d => {
        setSaveMsg(d.ok ? 'Saved!' : (d.error || 'Error'));
        setTimeout(() => setSaveMsg(null), 2000);
      })
      .catch(() => { setSaveMsg('Save failed'); setTimeout(() => setSaveMsg(null), 2000); });
  };

  const handleLoad = () => {
    if (picks.length > 0 &&
        !window.confirm('Replace the current picks with the saved draft state?')) return;
    fetch('/api/load-draft')
      .then(r => r.json())
      .then(d => {
        if (d.error) { setSaveMsg(d.error); setTimeout(() => setSaveMsg(null), 2500); return; }
        const keys = Array.isArray(d.picks) ? d.picks : [];
        const known = new Set(allPlayers.map(p => p.id));
        const loaded = keys
          .filter(k => known.has(k))
          .map((k, i) => ({
            pickNum: i + 1,
            teamNum: getSnakeTeam(i + 1, league.numTeams),
            playerId: k,
          }));
        onReplacePicks(loaded);
        const skipped = keys.length - loaded.length;
        setSaveMsg(skipped > 0 ? `Loaded ${loaded.length} (${skipped} unknown)` : `Loaded ${loaded.length}`);
        setTimeout(() => setSaveMsg(null), 2500);
      })
      .catch(() => { setSaveMsg('Load failed'); setTimeout(() => setSaveMsg(null), 2500); });
  };

  const handleExportLog = () => {
    const playerMap = {};
    allPlayers.forEach(p => { playerMap[p.id] = { name: p.name, pos: p.pos }; });
    const blob = new Blob([
      'pick,round,pick_in_round,team,player,position\n' +
      picks.map((pk, i) => {
        const n = i + 1;
        const rd = Math.ceil(n / league.numTeams);
        const pip = ((n - 1) % league.numTeams) + 1;
        const pl = playerMap[pk.playerId] || {};
        return `${n},${rd},${pip},${pk.teamNum},${(pl.name||pk.playerId).replace(/,/g,' ')},${pl.pos||''}`;
      }).join('\n')
    ], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `draft_log_${league.name.replace(/\s+/g, '_')}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div style={{height:'100vh', display:'flex', flexDirection:'column', background:T.bg, overflow:'hidden'}}>
      {/* Header Bar */}
      <div style={{
        background:T.surface, borderBottom:`1px solid ${T.border}`,
        padding:'0 14px', height:52, display:'flex', alignItems:'center',
        justifyContent:'space-between', flexShrink:0, gap:8,
      }}>
        <div style={{display:'flex', alignItems:'center', gap:10, minWidth:0}}>
          <button onClick={onBack} style={{
            background:'none', border:'none', cursor:'pointer', color:T.muted,
            fontSize:12, fontWeight:600, fontFamily:'inherit', display:'flex', alignItems:'center', gap:3, flexShrink:0,
          }}>← Leagues</button>
          <div style={{width:1, height:18, background:T.border, flexShrink:0}} />
          <div style={{minWidth:0, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>
            <span style={{fontSize:14, fontWeight:700, color:T.text}}>{league.name}</span>
            {!isMobile && (
              <span style={{marginLeft:6}}>
                <Badge label={SCORING_LABELS[league.scoringType]} color="blue" />
              </span>
            )}
          </div>
        </div>

        <div style={{display:'flex', alignItems:'center', gap:6, flexShrink:0}}>
          <div style={{
            background: isMyPick ? T.primaryLight : T.surfaceAlt,
            border:`1.5px solid ${isMyPick ? T.primary : T.border}`,
            borderRadius:T.rsm, padding:'3px 8px', textAlign:'center', flexShrink:0,
          }}>
            <div style={{fontSize:9, fontWeight:700, color:isMyPick?T.primary:T.muted, letterSpacing:.3}}>
              {isMyPick ? 'YOUR PICK' : `TEAM ${currentTeam}`}
            </div>
            <div style={{fontSize:11, fontWeight:700, color:isMyPick?T.primary:T.text}}>
              R{round} · Pick {pickInRound}/{league.numTeams}
            </div>
          </div>

          {/* Strategic Mobile/Tablet Drawer Toggle Buttons */}
          {(isMobile || isTablet) && (
            <button onClick={() => setShowMyTeamDrawer(true)} style={{
              background: T.surfaceAlt, border:`1px solid ${T.border}`, borderRadius:T.rsm,
              padding:'4px 8px', fontSize:11, fontWeight:700, color:T.text, cursor:'pointer', fontFamily:'inherit',
            }}>
              🛡️ Team ({myPlayers.length})
            </button>
          )}

          {isMobile && (
            <button onClick={() => setShowOppDrawer(true)} style={{
              background: T.surfaceAlt, border:`1px solid ${T.border}`, borderRadius:T.rsm,
              padding:'4px 8px', fontSize:11, fontWeight:700, color:T.text, cursor:'pointer', fontFamily:'inherit',
            }}>
              👥 Opponents
            </button>
          )}

          {!isHeaderCompact ? (
            <>
              <Btn variant="green" size="sm" onClick={() => setShowPullModal(true)}>Pull Data</Btn>
              <Btn variant="ghost" size="sm" onClick={() => setShowFreeAgents(true)}>Free Agents</Btn>
              <Btn variant="ghost" size="sm" onClick={() => setShowAuction(true)}>Auction $</Btn>
              <Btn variant="ghost" size="sm" onClick={handleSave}>{saveMsg || 'Save'}</Btn>
              <Btn variant="ghost" size="sm" onClick={handleLoad}>Load</Btn>
              <Btn variant="ghost" size="sm" onClick={handleExportLog} disabled={picks.length===0}>Export</Btn>
              <div style={{width:1, height:18, background:T.border}} />
              {isDesktop && (
                <Btn variant="ghost" size="sm" onClick={()=>setShowOpponents(v=>!v)}
                  style={showOpponents ? {background:T.borderLight} : {}}>Opponents</Btn>
              )}
              <Btn variant="ghost" size="sm" onClick={()=>setShowDraftBoard(true)}>Board</Btn>
            </>
          ) : (
            <div style={{position:'relative'}}>
              <button onClick={() => setShowActionsMenu(v => !v)} style={{
                background: T.surfaceAlt, border:`1px solid ${T.border}`, borderRadius:T.rsm,
                padding:'4px 8px', fontSize:11, fontWeight:700, color:T.text, cursor:'pointer', fontFamily:'inherit',
              }}>
                Actions ▾
              </button>
              {showActionsMenu && (
                <div style={{
                  position:'absolute', right:0, top:32, zIndex:100, background:T.surface,
                  border:`1px solid ${T.border}`, borderRadius:T.rsm, boxShadow:'0 8px 24px rgba(0,0,0,.15)',
                  padding:6, display:'flex', flexDirection:'column', gap:4, minWidth:140,
                }} onClick={() => setShowActionsMenu(false)}>
                  <button onClick={() => setShowPullModal(true)} style={{textAlign:'left', padding:'6px 10px', background:'none', border:'none', cursor:'pointer', fontSize:12, color:T.text}}>Pull Data</button>
                  <button onClick={() => setShowFreeAgents(true)} style={{textAlign:'left', padding:'6px 10px', background:'none', border:'none', cursor:'pointer', fontSize:12, color:T.text}}>Free Agents</button>
                  <button onClick={() => setShowAuction(true)} style={{textAlign:'left', padding:'6px 10px', background:'none', border:'none', cursor:'pointer', fontSize:12, color:T.text}}>Auction $</button>
                  <button onClick={handleSave} style={{textAlign:'left', padding:'6px 10px', background:'none', border:'none', cursor:'pointer', fontSize:12, color:T.text}}>{saveMsg || 'Save Draft'}</button>
                  <button onClick={handleLoad} style={{textAlign:'left', padding:'6px 10px', background:'none', border:'none', cursor:'pointer', fontSize:12, color:T.text}}>Load Draft</button>
                  <button onClick={handleExportLog} disabled={picks.length===0} style={{textAlign:'left', padding:'6px 10px', background:'none', border:'none', cursor:'pointer', fontSize:12, color:T.text}}>Export CSV</button>
                  <button onClick={()=>setShowDraftBoard(true)} style={{textAlign:'left', padding:'6px 10px', background:'none', border:'none', cursor:'pointer', fontSize:12, color:T.text}}>Full Draft Board</button>
                </div>
              )}
            </div>
          )}

          <Btn variant="ghost" size="sm" onClick={onUndoPick} disabled={picks.length===0}>Undo</Btn>
          <Btn variant="danger" size="sm" onClick={onResetPicks} disabled={picks.length===0}>Reset</Btn>
        </div>
      </div>

      {/* Main Content Area */}
      <div style={{flex:1, display:'flex', minHeight:0}}>
        {/* Left Panel: My Team (visible inline on Desktop/Tablet, drawer on Mobile) */}
        {!isMobile && (
          <MyTeamPanel
            league={league} myPlayers={myPlayers}
            round={round} hint={hint}
            onGetHint={handleGetHint}
          />
        )}

        {/* Center: Main Draft Board & Recommendations */}
        <div style={{flex:1, display:'flex', flexDirection:'column', minWidth:0}}>
          <div style={{
            padding:'3px 12px', fontSize:11, color:T.muted, background:T.surface,
            borderBottom:`1px solid ${T.border}`, display:'flex', gap:6, alignItems:'center',
          }}>
            {suggest.err
              ? <span style={{color:T.danger || '#c0392b'}}>⚠ recommendations: {suggest.err}</span>
              : suggest.loading
                ? <span>⏳ Computing rollout…</span>
                : suggest.stale
                  ? <span>↺ Board held — recomputes when pick is near ({untilMyTurn} away)</span>
                  : <span>✓ Rollout engine · {suggest.sims} sims/pick</span>}
            <button onClick={handleRefreshRecs} title="Recompute recommendations now"
              style={{marginLeft:'auto', background:'none', border:`1px solid ${T.border}`, borderRadius:6,
                padding:'1px 6px', cursor:'pointer', color:T.muted, fontSize:10, fontFamily:'inherit'}}>
              ↻ Refresh
            </button>
          </div>

          <RecommendationBar scored={scored} myPlayers={myPlayers} league={league} oppData={oppData} />
          <PlayerList
            players={enriched}
            onDraft={handleDraft}
            showDrafted={showDrafted}
            onToggleDrafted={()=>setShowDrafted(v=>!v)}
          />
        </div>

        {/* Right Panel: Opponents (visible inline on Desktop only when enabled) */}
        {isDesktop && showOpponents && (
          <OpponentsPanel
            league={league} oppData={oppData}
            picksMade={picks.length}
            onSetTeamMode={setTeamMode}
          />
        )}
      </div>

      {/* Mobile/Tablet Drawers */}
      {showMyTeamDrawer && (
        <Drawer title="My Team Roster & Strategy" onClose={() => setShowMyTeamDrawer(false)}>
          <MyTeamPanel
            league={league} myPlayers={myPlayers}
            round={round} hint={hint}
            onGetHint={handleGetHint}
            fullWidth
          />
        </Drawer>
      )}

      {showOppDrawer && (
        <Drawer title="Opponent Analysis & Autodraft" onClose={() => setShowOppDrawer(false)}>
          <OpponentsPanel
            league={league} oppData={oppData}
            picksMade={picks.length}
            onSetTeamMode={setTeamMode}
            fullWidth
          />
        </Drawer>
      )}

      <TweaksPanel title="Draft Tweaks">
        <TweakSection title="ENGINE">
          <TweakSlider id="autoDrafters" label="Opponents autodrafting"
            min={0} max={Math.max(1, league.numTeams - 1)} step={1}
            tweaks={tweaks} setTweaks={setTweaks} />
          <TweakSlider id="sims" label="Precision (sims/pick)"
            min={16} max={96} step={8} tweaks={tweaks} setTweaks={setTweaks} />
          <div style={{fontSize:10.5, color:'rgba(41,38,27,.6)', lineHeight:1.45, marginTop:2}}>
            More autodrafters → opponents stick to ADP → less board chaos
            (opponent noise σ ≈ {adpNoise}). Higher precision = steadier numbers,
            a little slower per pick.
          </div>
        </TweakSection>
      </TweaksPanel>

      {showDraftBoard && (
        <DraftBoardModal
          league={league} picks={picks} allPlayers={enriched}
          onClose={()=>setShowDraftBoard(false)}
        />
      )}
      {showPullModal && (
        <PullDataModal
          league={league}
          espnLeagueId={league.espnLeagueId}
          onClose={() => setShowPullModal(false)}
          onComplete={() => onRefreshPlayers && onRefreshPlayers()}
        />
      )}
      {showAuction && (
        <AuctionModal onClose={() => setShowAuction(false)} />
      )}
      {showFreeAgents && (
        <FreeAgentFinderModal
          leagues={allLeagues || [league]}
          picks={allPicks || { [league.id]: picks }}
          onClose={() => setShowFreeAgents(false)}
        />
      )}
    </div>
  );
}

Object.assign(window, {
  PosBadge, VORPBadge, ScoreBadge,
  MyTeamPanel, RecommendationBar, PlayerList, DraftBoardModal, DraftScreen,
  OpponentsPanel,
});
