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
    if (!counts.QB && (slots.QB || 0) > 0)
      return `Round ${round}: window is opening for top QBs. ${top && top.pos==='QB' ? top.name + ' is excellent value. ' : ''}Don't wait too late on a 1-QB tier dropoff.`;
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
  for (let i=0;i<(slots.FLEX||0);i++) slotDefs.push({label:'FLX', pos:'FLEX'});
  for (let i=0;i<(slots.K||0);i++)    slotDefs.push({label:'K',   pos:'K'});
  for (let i=0;i<(slots.DST||0);i++)  slotDefs.push({label:'DST', pos:'DST'});
  for (let i=0;i<(slots.BN||0);i++)   slotDefs.push({label:'BN',  pos:null});

  const filled = [];
  const remaining = [...myPlayers];
  const flexElig  = new Set(['RB','WR','TE']);

  slotDefs.forEach(slot => {
    if (!slot.pos) { filled.push({slot, player: remaining.shift()||null}); return; }
    if (slot.pos === 'FLEX') {
      const idx = remaining.findIndex(p => flexElig.has(p.pos));
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

function RecommendationBar({ scored, myPlayers, league }) {
  if (!scored || scored.length === 0) {
    return (
      <div style={{padding:'12px 16px', background:T.surface, borderBottom:`1px solid ${T.border}`}}>
        <div style={{fontSize:12, color:T.muted}}>No players available.</div>
      </div>
    );
  }

  const sortedByScore = [...scored].sort((a,b) => b.draftScore - a.draftScore);
  const bestOverall   = sortedByScore[0];

  const needs     = getRosterNeeds(myPlayers, league.rosterSlots);
  const flexElig  = new Set(['RB','WR','TE']);
  const bestByNeed = sortedByScore.find(p =>
    needs.includes(p.pos) || (needs.includes('FLEX') && flexElig.has(p.pos))
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
        {!crossPos && !scarcityAlert && !isSame && (
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
      return b.draftScore - a.draftScore;
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
  const totalSlots = Object.values(league.rosterSlots).reduce((s,v)=>s+v,0);
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
function DraftScreen({ league, picks, allPlayers, onBack, onAddPick, onUndoPick, onResetPicks, onUpdateLeague }) {
  const [showDraftBoard, setShowDraftBoard] = React.useState(false);
  const [showDrafted,    setShowDrafted]    = React.useState(false);
  const [hint,           setHint]           = React.useState('');

  const tweakDefaults = typeof TWEAK_DEFAULTS !== 'undefined' ? TWEAK_DEFAULTS : {
    scarcityWeight:0.60, nextPickWeight:0.25, vorWeight:0.20,
    adpSigma:18, byePenalty:1.0, benchRBWR:0.18, benchTE:0.12, benchQB:0.08,
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

  const scored = React.useMemo(() => {
    if (typeof window.computeDraftScores !== 'function') return available;
    return window.computeDraftScores(available, myPlayers, league, picks.length, tweaks);
  }, [available, myPlayers, league, picks.length, tweaks]);

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
    const sortedScored = [...scored].sort((a,b) => b.draftScore - a.draftScore);
    setHint(generateRoundHint(round, myPlayers, sortedScored, league));
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
          <RecommendationBar scored={scored} myPlayers={myPlayers} league={league} />
          <PlayerList
            players={enriched}
            onDraft={handleDraft}
            showDrafted={showDrafted}
            onToggleDrafted={()=>setShowDrafted(v=>!v)}
          />
        </div>
      </div>

      <TweaksPanel title="Draft Tweaks">
        <TweakSection title="DRAFT SCORE">
          <TweakSlider id="scarcityWeight" label="Scarcity Weight" min={0} max={1} step={0.05} tweaks={tweaks} setTweaks={setTweaks} />
          <TweakSlider id="adpSigma" label="ADP Noise σ" min={5} max={35} step={1} tweaks={tweaks} setTweaks={setTweaks} />
        </TweakSection>
        <TweakSection title="BYE PENALTY">
          <TweakSlider id="byePenalty" label="Per shared bye" min={0} max={6} step={0.5} tweaks={tweaks} setTweaks={setTweaks} />
        </TweakSection>
        <TweakSection title="BENCH DISCOUNTS">
          <TweakSlider id="benchRBWR" label="RB / WR" min={0} max={0.35} step={0.01} tweaks={tweaks} setTweaks={setTweaks} />
          <TweakSlider id="benchTE" label="TE" min={0} max={0.25} step={0.01} tweaks={tweaks} setTweaks={setTweaks} />
          <TweakSlider id="benchQB" label="QB" min={0} max={0.2} step={0.01} tweaks={tweaks} setTweaks={setTweaks} />
        </TweakSection>
      </TweaksPanel>

      {showDraftBoard && (
        <DraftBoardModal
          league={league} picks={picks} allPlayers={enriched}
          onClose={()=>setShowDraftBoard(false)}
        />
      )}
    </div>
  );
}

Object.assign(window, {
  PosBadge, VORPBadge, ScoreBadge,
  MyTeamPanel, RecommendationBar, PlayerList, DraftBoardModal, DraftScreen,
});
