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
function MyTeamPanel({ league, myPlayers, round, hint, onGetHint }) {
  const slots = league.rosterSlots;
  const slotDefs = [];
  for (let i=0;i<(slots.QB||0);i++)   slotDefs.push({label:'QB',  pos:'QB'});
  for (let i=0;i<(slots.RB||0);i++)   slotDefs.push({label:'RB',  pos:'RB'});
  for (let i=0;i<(slots.WR||0);i++)   slotDefs.push({label:'WR',  pos:'WR'});
  for (let i=0;i<(slots.TE||0);i++)   slotDefs.push({label:'TE',  pos:'TE'});
  // Typed flex slots, most restrictive first (a W/T slot fills before a FLEX),
  // each carrying its eligible positions so it never holds an ineligible player.
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
      width:240, flexShrink:0, background:T.surface,
      borderRight:`1px solid ${T.border}`, display:'flex', flexDirection:'column', overflowY:'auto',
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

function OpponentsPanel({ league, oppData, picksMade, onSetTeamMode }) {
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
      width:236, flexShrink:0, background:T.surface,
      borderLeft:`1px solid ${T.border}`, display:'flex', flexDirection:'column', overflowY:'auto',
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
      borderRadius: T.r, padding:'12px 14px', flex:1, minWidth:0,
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

  // Only rank players the engine actually simulated this pick (draftScore set);
  // others have no impact/availPct and would otherwise sort as 0 and show
  // "undefined%" in the cards.
  const rolled = scored.filter(p => p.draftScore != null);
  const sortedByScore = (rolled.length ? rolled : scored).sort((a,b) => b.draftScore - a.draftScore);
  const bestOverall   = sortedByScore[0];

  const needs     = getRosterNeeds(myPlayers, league.rosterSlots);
  const flexElig  = new Set(['RB','WR','TE']);

  // "Need" means an open dedicated starting slot first; only fall back to
  // soft depth caps when every starter is filled. Otherwise a 4th RB keeps
  // masquerading as a need via the flex/bench allowance.
  const posCounts = {};
  myPlayers.forEach(p => { posCounts[p.pos] = (posCounts[p.pos] || 0) + 1; });
  const starterNeeds = ['QB','RB','WR','TE','K','DST'].filter(pos =>
    (posCounts[pos] || 0) < (league.rosterSlots[pos] || 0)
  );
  const needPool = starterNeeds.length > 0 ? starterNeeds : needs;
  const bestByNeed = sortedByScore.find(p =>
    needPool.includes(p.pos) ||
    (starterNeeds.length === 0 && needs.includes('FLEX') && flexElig.has(p.pos))
  ) || bestOverall;

  const isSame = bestOverall.id === bestByNeed.id;

  let scarcityAlert = null;
  needs.forEach(pos => {
    const elites = scored.filter(p => p.pos === pos && p.tier <= 2);
    if (elites.length > 0 && elites.length <= 2) {
      const top = [...elites].sort((a,b) => b.draftScore - a.draftScore)[0];
      if (!scarcityAlert || top.draftScore > scarcityAlert.player.draftScore) {
        scarcityAlert = { player: top, count: elites.length, pos };
      }
    }
  });

  // Position run: opponents picking before my next turn are collectively
  // likely to take 2+ players at a position I still need.
  let runAlert = null;
  if (oppData && oppData.expectedByPos) {
    needs.forEach(pos => {
      const exp = oppData.expectedByPos[pos] || 0;
      if (exp >= 1.6) {
        const top = sortedByScore.find(p => p.pos === pos);
        if (top && (!runAlert || exp > runAlert.exp)) runAlert = { pos, exp, player: top };
      }
    });
  }

  let crossPos = null, crossReason = null;
  if (!isSame && bestOverall.draftScore - bestByNeed.draftScore > 12) {
    const nextAtPos = sortedByScore.filter(p => p.pos === bestOverall.pos && p.id !== bestOverall.id)[0];
    const tierDrop  = nextAtPos ? bestOverall.projPts - nextAtPos.projPts : 999;
    if (tierDrop >= 14 || bestOverall.draftScore - bestByNeed.draftScore > 20) {
      crossPos = bestOverall;
      crossReason = tierDrop >= 14
        ? `${bestOverall.name} is last in their ${bestOverall.pos} tier — next is ${Math.round(tierDrop)} pts lower.`
        : `+${Math.round(bestOverall.draftScore - bestByNeed.draftScore)} Draft Score gap over your top need.`;
    }
  }

  return (
    <div style={{padding:'12px 16px', background:T.surface, borderBottom:`1px solid ${T.border}`}}>
      <div style={{fontSize:10, fontWeight:700, color:T.muted, letterSpacing:.5, marginBottom:8}}>RECOMMENDATIONS</div>
      <div style={{display:'flex', gap:10}}>
        <RecCard icon="▲" label="BEST DRAFT SCORE"
          player={bestOverall}
          reason={isSame ? 'Top score AND fills your positional need.' : `${bestOverall.availPct}% chance still available next pick.`}
          highlight={isSame} />
        {!isSame && (
          <RecCard icon="◎" label="BEST BY NEED"
            player={bestByNeed}
            reason={`Fills ${bestByNeed.pos} need · ${bestByNeed.availPct}% avail at next pick`} />
        )}
        {crossPos && crossPos.id !== bestOverall.id && (
          <RecCard icon="⚡" label="REACH ALERT" player={crossPos} reason={crossReason} highlight />
        )}
        {scarcityAlert && (
          <RecCard icon="⚠" label={`${scarcityAlert.pos} SCARCE`}
            player={scarcityAlert.player}
            reason={`Only ${scarcityAlert.count} elite ${scarcityAlert.pos} left.`} />
        )}
        {runAlert && (
          <RecCard icon="⏳" label={`${runAlert.pos} RUN LIKELY`}
            player={runAlert.player}
            reason={`~${runAlert.exp.toFixed(1)} ${runAlert.pos}s expected to go before your next pick — only ${runAlert.player.availPct}% chance ${runAlert.player.name.split(' ').pop()} survives.`}
            highlight />
        )}
        {!crossPos && !scarcityAlert && !runAlert && !isSame && (
          <div style={{
            flex:1, background:T.surfaceAlt, border:`1.5px dashed ${T.border}`,
            borderRadius:T.r, padding:'12px 14px', display:'flex', alignItems:'center', justifyContent:'center',
          }}>
            <span style={{fontSize:12, color:T.muted}}>No scarcity or cross-position alerts.</span>
          </div>
        )}
      </div>
    </div>
  );
}

// Sort by rollout impact (draftScore), descending. Players the engine did not
// deeply analyze this pick (outside the returned top-N) have draftScore == null
// and fall to the bottom, sub-sorted by VORP so the tail still browses sensibly.
function cmpScore(a, b) {
  const sa = a.draftScore == null ? -Infinity : a.draftScore;
  const sb = b.draftScore == null ? -Infinity : b.draftScore;
  if (sa === sb) return (b.vorp || 0) - (a.vorp || 0);
  return sb - sa;
}

// How many picks until it's my turn (0 = on the clock now). Used to defer the
// expensive rollout to when my pick is near instead of every opponent pick.
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

  const GRID = '30px 1fr 52px 44px 44px 54px 54px 66px 78px';

  return (
    <div style={{flex:1, display:'flex', flexDirection:'column', minHeight:0, overflow:'hidden'}}>
      <div style={{
        padding:'10px 16px', background:T.surface, borderBottom:`1px solid ${T.border}`,
        display:'flex', gap:10, alignItems:'center', flexWrap:'wrap',
      }}>
        <input placeholder="Search player or team…" value={search}
          onChange={e => setSearch(e.target.value)}
          style={{
            flex:1, minWidth:140, padding:'7px 12px', border:`1.5px solid ${T.border}`,
            borderRadius:T.rsm, fontSize:13, fontFamily:'inherit', color:T.text, outline:'none',
          }} />
        <div style={{display:'flex', gap:5}}>
          {['ALL',...window.POSITIONS].map(pos => (
            <button key={pos} onClick={() => setPosFilter(pos)} style={{
              padding:'5px 9px', borderRadius:T.rxs,
              border:`1.5px solid ${posFilter===pos ? T.primary : T.border}`,
              background: posFilter===pos ? T.primaryLight : T.surface,
              color: posFilter===pos ? T.primary : T.muted,
              fontSize:12, fontWeight:600, cursor:'pointer', fontFamily:'inherit',
            }}>{pos}</button>
          ))}
        </div>
        <select value={sortBy} onChange={e=>setSortBy(e.target.value)} style={{
          padding:'6px 10px', border:`1.5px solid ${T.border}`, borderRadius:T.rsm,
          fontSize:13, color:T.text, fontFamily:'inherit', background:T.surface, cursor:'pointer',
        }}>
          {sortOptions.map(o=><option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <button onClick={onToggleDrafted} style={{
          padding:'6px 10px', border:`1.5px solid ${T.border}`, borderRadius:T.rsm,
          background: showDrafted ? T.borderLight : T.surface,
          color:T.muted, fontSize:12, cursor:'pointer', fontFamily:'inherit', fontWeight:600,
        }}>
          {showDrafted ? 'Hide Drafted' : 'Show Drafted'}
        </button>
      </div>

      <div style={{
        display:'grid', gridTemplateColumns:GRID,
        padding:'7px 16px', background:T.surfaceAlt, borderBottom:`1px solid ${T.border}`,
        fontSize:10, fontWeight:700, color:T.muted, letterSpacing:.5, gap:8, alignItems:'center',
      }}>
        <span>#</span>
        <span>PLAYER</span>
        <span>POS</span>
        <span>TEAM</span>
        <span style={{textAlign:'center'}}>BYE</span>
        <span style={{textAlign:'right'}}>PROJ</span>
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

          return (
            <div key={p.id}
              onMouseEnter={() => setHoverId(p.id)}
              onMouseLeave={() => setHoverId(null)}
              title={p.draftScore != null
                ? `Draft Score: ${Math.round(p.draftScore)} | Lineup Gain: ${p.lineupGain} | Scarcity Bonus: ${p.scarcityBonus} | Need ×${p.needMult} | Slot: ${p.slotType || '—'} | Avail: ${p.availPct}%`
                : undefined}
              style={{
                display:'grid', gridTemplateColumns:GRID,
                padding:'8px 16px', gap:8, alignItems:'center',
                borderBottom:`1px solid ${T.borderLight}`,
                background: p.drafted ? T.surfaceAlt : isHov ? '#f5f7ff' : T.surface,
                opacity: p.drafted ? 0.4 : 1,
                transition:'background .1s',
              }}>
              <span style={{fontSize:12, color:T.mutedLight, fontFamily:'DM Mono,monospace'}}>{i+1}</span>

              <div style={{minWidth:0}}>
                <div style={{fontSize:13, fontWeight:600, color:T.text, display:'flex', alignItems:'center', gap:5}}>
                  <span style={{
                    width:7, height:7, borderRadius:'50%', background:tierDot, flexShrink:0,
                  }} title={`Tier ${p.tier}`} />
                  <span style={{overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{p.name}</span>
                </div>
                {isHov && p.draftScore != null && (
                  <div style={{fontSize:10, color:T.muted, marginTop:1}}>
                    <span style={{color:slotColor, fontWeight:700, marginRight:5}}>{(p.slotType||'bench').toUpperCase()}</span>
                    avail {p.availPct}% · need ×{p.needMult}
                    {p.byePen > 0 && <span style={{color:T.amber}}> · bye −{p.byePen}</span>}
                  </div>
                )}
                {(!isHov || p.draftScore == null) && (
                  <div style={{fontSize:10, color:T.mutedLight}}>ADP {p.adp}</div>
                )}
              </div>

              <span><PosBadge pos={p.pos} /></span>
              <span style={{fontSize:12, color:T.muted, fontWeight:500}}>{p.nflTeam}</span>
              <span style={{fontSize:12, fontFamily:'DM Mono,monospace', color:T.muted, textAlign:'center'}}>
                {p.byeWeek || '—'}
              </span>
              <span style={{fontSize:13, fontWeight:600, color:T.text, fontFamily:'DM Mono,monospace', textAlign:'right'}}>
                {Math.round(p.projPts)}
              </span>
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
                    border:'none', borderRadius:T.rxs, padding:'5px 10px',
                    fontSize:12, fontWeight:700, cursor:'pointer', fontFamily:'inherit', transition:'all .15s',
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
  // IR slots aren't drafted, so they don't add a round to the board.
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
function DraftScreen({ league, picks, allPlayers, onBack, onAddPick, onUndoPick, onResetPicks, onReplacePicks, onUpdateLeague, onRefreshPlayers }) {
  const [showDraftBoard, setShowDraftBoard] = React.useState(false);
  const [showDrafted,    setShowDrafted]    = React.useState(false);
  const [showOpponents,  setShowOpponents]  = React.useState(true);
  const [hint,           setHint]           = React.useState('');
  const [showPullModal,  setShowPullModal]  = React.useState(false);
  const [showAuction,    setShowAuction]    = React.useState(false);
  const [saveMsg,        setSaveMsg]        = React.useState(null);

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

  // Opponent roster analysis: predicted positions for every pick between now
  // and my next turn, plus per-player survival odds.
  const oppData = React.useMemo(() => {
    if (!window.OpponentModel) return null;
    return window.OpponentModel.analyze(
      available, picks, league, league.teamModes || {}, playersById
    );
  }, [available, picks, league, playersById]);

  const setTeamMode = (teamNum, mode) => {
    onUpdateLeague({ teamModes: { ...(league.teamModes || {}), [teamNum]: mode } });
  };

  // Recommendation scores come from the Python rest-of-draft rollout engine
  // (POST /api/suggest): it ranks the board by each pick's expected effect on
  // your FINAL roster's total season points, accounting for who survives to your
  // later picks. The rollout is the expensive part, so we DON'T re-run it on
  // every opponent pick — only on the opening board, when your pick is one away
  // (precompute "on deck"), or on a manual Refresh. In between, opponents' picks
  // just update availability (cheap, client-side). This is exact: the rollout
  // reads the current board, so computing it once before your pick equals the
  // last of the per-pick recomputes — minus the wasted work and the wait.
  const untilMyTurn = picksUntilMyTurn(picks.length, league.numTeams, league.draftPosition);

  // More opponents autodrafting => they follow ADP => fewer surprises. Map the
  // count to the engine's opponent ADP-noise (0 auto -> 8.0 chaos, all auto -> 1.0).
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

  // Changing an engine tweak (precision / autodrafters) is an explicit "apply
  // this" action, so force a recompute even when your pick isn't near — instead
  // of waiting for the gate. (adpNoise/sims are read from the live closure.)
  const tweakSig = `${tweaks.sims}|${tweaks.autoDrafters}`;
  const prevTweakSig = React.useRef(tweakSig);
  React.useEffect(() => {
    if (prevTweakSig.current !== tweakSig) {
      prevTweakSig.current = tweakSig;
      handleRefreshRecs();
    }
  }, [tweakSig]);

  // Merge the engine's impact + supporting numbers onto the available board.
  // Players outside the returned top-N get draftScore: null (badge hidden,
  // sorted to the bottom by cmpScore). projPts / vorp stay client-computed.
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

  // Restore picks from the server's draft_state.json (saved here or recorded
  // via the CLI/terminal UI). Team ownership is reconstructed from snake order.
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
      <div style={{
        background:T.surface, borderBottom:`1px solid ${T.border}`,
        padding:'0 20px', height:52, display:'flex', alignItems:'center',
        justifyContent:'space-between', flexShrink:0, gap:12,
      }}>
        <div style={{display:'flex', alignItems:'center', gap:16}}>
          <button onClick={onBack} style={{
            background:'none', border:'none', cursor:'pointer', color:T.muted,
            fontSize:13, fontWeight:600, fontFamily:'inherit', display:'flex', alignItems:'center', gap:4,
          }}>← Leagues</button>
          <div style={{width:1, height:20, background:T.border}} />
          <div>
            <span style={{fontSize:15, fontWeight:700, color:T.text}}>{league.name}</span>
            <span style={{marginLeft:8}}>
              <Badge label={SCORING_LABELS[league.scoringType]} color="blue" />
            </span>
          </div>
        </div>

        <div style={{display:'flex', alignItems:'center', gap:10}}>
          <div style={{
            background: isMyPick ? T.primaryLight : T.surfaceAlt,
            border:`1.5px solid ${isMyPick ? T.primary : T.border}`,
            borderRadius:T.rsm, padding:'4px 12px', textAlign:'center',
          }}>
            <div style={{fontSize:10, fontWeight:700, color:isMyPick?T.primary:T.muted, letterSpacing:.4}}>
              {isMyPick ? 'YOUR PICK' : `TEAM ${currentTeam}`}
            </div>
            <div style={{fontSize:12, fontWeight:700, color:isMyPick?T.primary:T.text}}>
              Round {round} · Pick {pickInRound}/{league.numTeams}
            </div>
          </div>
          <Btn variant="green" size="sm" onClick={() => setShowPullModal(true)}>Pull Data</Btn>
          <Btn variant="ghost" size="sm" onClick={() => setShowAuction(true)}>Auction $</Btn>
          <Btn variant="ghost" size="sm" onClick={handleSave}>
            {saveMsg || 'Save'}
          </Btn>
          <Btn variant="ghost" size="sm" onClick={handleLoad}>Load</Btn>
          <Btn variant="ghost" size="sm" onClick={handleExportLog} disabled={picks.length===0}>Export CSV</Btn>
          <div style={{width:1, height:20, background:T.border}} />
          <Btn variant="ghost" size="sm" onClick={()=>setShowOpponents(v=>!v)}
            style={showOpponents ? {background:T.borderLight} : {}}>Opponents</Btn>
          <Btn variant="ghost" size="sm" onClick={()=>setShowDraftBoard(true)}>Draft Board</Btn>
          <Btn variant="ghost" size="sm" onClick={onUndoPick} disabled={picks.length===0}>Undo</Btn>
          <Btn variant="danger" size="sm" onClick={onResetPicks} disabled={picks.length===0}>Reset</Btn>
        </div>
      </div>

      <div style={{flex:1, display:'flex', minHeight:0}}>
        <MyTeamPanel
          league={league} myPlayers={myPlayers}
          round={round} hint={hint}
          onGetHint={handleGetHint}
        />
        <div style={{flex:1, display:'flex', flexDirection:'column', minWidth:0}}>
          <div style={{
            padding:'3px 16px', fontSize:11, color:T.muted, background:T.surface,
            borderBottom:`1px solid ${T.border}`, display:'flex', gap:8, alignItems:'center',
          }}>
            {suggest.err
              ? <span style={{color:T.danger || '#c0392b'}}>⚠ recommendations: {suggest.err}</span>
              : suggest.loading
                ? <span>⏳ Computing season-points rollout…</span>
                : suggest.stale
                  ? <span>↺ Board held since your last update — recomputes when your pick is near
                      {untilMyTurn > 0 ? ` (${untilMyTurn} pick${untilMyTurn === 1 ? '' : 's'} away)` : ''}.</span>
                  : <span>✓ Rollout engine · {suggest.sims} sims/pick · ranked by season-point impact</span>}
            <button onClick={handleRefreshRecs} title="Recompute recommendations now"
              style={{marginLeft:'auto', background:'none', border:`1px solid ${T.border}`, borderRadius:6,
                padding:'1px 8px', cursor:'pointer', color:T.muted, fontSize:11, fontFamily:'inherit'}}>
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
        {showOpponents && (
          <OpponentsPanel
            league={league} oppData={oppData}
            picksMade={picks.length}
            onSetTeamMode={setTeamMode}
          />
        )}
      </div>

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
    </div>
  );
}

Object.assign(window, {
  PosBadge, VORPBadge, ScoreBadge,
  MyTeamPanel, RecommendationBar, PlayerList, DraftBoardModal, DraftScreen,
  OpponentsPanel,
});
