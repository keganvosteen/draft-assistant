// ─── DRAFT ROOM ───────────────────────────────────────────────────────────────
// Draft day only. The in-season waiver wire is a separate screen reached from
// the league hub — nothing here knows about it.

function VORPBadge({ vorp }) {
  const isPos = vorp > 0;
  const isNeg = vorp < -5;
  const color = isPos ? T.green : isNeg ? T.red : T.muted;
  const bg    = isPos ? T.greenLight : isNeg ? T.redLight : T.borderLight;
  return (
    <span className="da-num" style={{
      background: bg, color, borderRadius: T.rxs, padding: '2px 8px',
      fontSize: 12, fontWeight: 700, display:'inline-block', textAlign:'right', minWidth:48,
    }}>
      {vorp > 0 ? '+' : ''}{vorp}
    </span>
  );
}

// Only rows the engine fully simulated carry a draft score; the rest come back
// with impact null and render as "—" instead of this badge.
//
// Impact is a rest-of-draft differential, so its absolute size shifts hugely
// between round 1 (everything is nearly equivalent) and the late rounds. Fixed
// thresholds made the colour meaningless, so shade against the best impact
// currently on the board instead.
function ScoreBadge({ score, best }) {
  const ratio = best > 0 ? score / best : 0;
  const high = ratio >= 0.9;
  const mid  = ratio >= 0.6;
  const bg   = high ? T.primaryLight : mid ? T.greenLight : T.borderLight;
  const fg   = high ? T.primary : mid ? T.green : T.muted;
  return (
    <span className="da-num" style={{
      background: bg, color: fg, borderRadius: T.rxs, padding: '2px 8px',
      fontSize: 12, fontWeight: 800, display:'inline-block', textAlign:'right', minWidth:54,
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
    return `Round ${round}: continue building the RB/WR core. An elite TE is also a defensible reach now.`;
  }
  if (round <= 7) {
    if (!counts.QB && (slots.QB || 0) > 0) {
      const topQB  = topAvailable.find(p => p.pos === 'QB');
      const qbRank = topQB ? topAvailable.indexOf(topQB) + 1 : 0;
      if (topQB && qbRank <= 3)
        return `Round ${round}: ${topQB.name} is the #${qbRank} score on the board — the QB window is open, take it.`;
      return `Round ${round}: no QB yet — fine for now${topQB ? ` (${topQB.name} ranks #${qbRank})` : ''}, but your open starter slots score higher. Fill those first, grab a QB by round 7–8.`;
    }
    return `Round ${round}: depth time. RB handcuffs and WR3/4 with target share matter; avoid K/DST.`;
  }
  if (round <= 10) {
    if (!counts.TE && (slots.TE || 0) > 0)
      return `Round ${round}: TE streamers are fine, but a startable TE solves a slot. Look at usage trends.`;
    return `Round ${round}: bench upside picks. Rookies, late breakouts, and high target shares.`;
  }
  if (round <= 12) return `Round ${round}: backups and lottery tickets. Avoid K/DST until the last two rounds.`;
  return `Round ${round}: kicker and DST — take the highest-projected ones with favourable byes.`;
}

// ─── MY TEAM PANEL ────────────────────────────────────────────────────────────
function MyTeamPanel({ league, myPlayers, round, hint, onGetHint, fullWidth = false }) {
  const lineup = buildLineup(myPlayers, league.rosterSlots);
  const needs = getRosterNeeds(myPlayers, league.rosterSlots);

  return (
    <aside style={{
      width: fullWidth ? '100%' : 236, flexShrink:0, background:T.surface,
      borderRight: fullWidth ? 'none' : `1px solid ${T.border}`,
      display:'flex', flexDirection:'column', overflowY:'auto',
    }}>
      <div style={{padding:'12px 14px', borderBottom:`1px solid ${T.border}`}}>
        {!fullWidth && <SectionLabel>My team</SectionLabel>}
        <div style={{fontSize:12, color:T.muted, marginTop: fullWidth ? 0 : 2}}>
          {myPlayers.length} of {lineup.length} slots filled
        </div>
      </div>

      <div style={{padding:'6px 12px', flex:1}}>
        {lineup.map(({slot, player}, i) => (
          <div key={i} style={{
            display:'flex', alignItems:'center', gap:8, padding:'5px 2px',
            borderBottom: i < lineup.length - 1 ? `1px solid ${T.borderLight}` : 'none', minHeight:34,
          }}>
            <span style={{
              fontSize:10, fontWeight:800, letterSpacing:.3, width:28, flexShrink:0,
              color: slot.bench ? T.mutedLight : T.muted,
            }}>{slot.label}</span>
            {player ? (
              <div style={{minWidth:0, flex:1}}>
                <div className="da-ellipsis" style={{fontSize:12, fontWeight:600, color:T.text}}>
                  {player.name}
                </div>
                <div style={{fontSize:10, color:T.muted, display:'flex', gap:5}}>
                  <span>{player.pos} · {player.nflTeam}</span>
                  {player.byeWeek && <span style={{color:T.mutedLight}}>BYE {player.byeWeek}</span>}
                </div>
              </div>
            ) : (
              <span style={{fontSize:12, color:T.mutedLight}}>empty</span>
            )}
          </div>
        ))}
      </div>

      {needs.length > 0 && (
        <div style={{padding:'10px 14px', borderTop:`1px solid ${T.border}`}}>
          <SectionLabel style={{marginBottom:6}}>Still need</SectionLabel>
          <div style={{display:'flex', flexWrap:'wrap', gap:4}}>
            {needs.map(pos => <PosBadge key={pos} pos={pos} />)}
          </div>
        </div>
      )}

      <div style={{padding:'11px 14px', borderTop:`1px solid ${T.border}`}}>
        <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:6}}>
          <SectionLabel>Round {round} plan</SectionLabel>
          <button onClick={onGetHint} style={{
            background:'none', border:'none', cursor:'pointer',
            fontSize:11.5, color:T.primary, fontWeight:600, padding:0,
          }}>{hint ? 'Update' : 'Show'}</button>
        </div>
        {hint
          ? <div style={{fontSize:12, color:T.text, lineHeight:1.55}}>{hint}</div>
          : <div style={{fontSize:12, color:T.mutedLight}}>A one-line read on what this round is for.</div>}
      </div>
    </aside>
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
        <button key={m} onClick={() => onChange(m)} aria-pressed={mode === m}
          title={m === 'live' ? 'Drafting live — picks by roster need' : 'Autodrafting — follows ADP'}
          style={{
            border:'none', cursor:'pointer', padding:'2px 7px',
            fontSize:10, fontWeight:700, letterSpacing:.3,
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
      <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', gap:6, marginBottom:3}}>
        <span className="da-ellipsis" style={{fontSize:12, fontWeight:700, color:T.text}}>
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
              <span className="da-num" style={{fontSize:10, fontWeight:700, color:T.muted}}>
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
    <div style={{display:'flex', flexDirection:'column', minHeight:0}}>
      <div style={{padding:'12px 14px', borderBottom:`1px solid ${T.border}`}}>
        {expected.length > 0 ? (
          <div style={{fontSize:11.5, color:T.muted, lineHeight:1.5}}>
            Likely gone before your pick:{' '}
            {expected.map(([pos, n], i) => (
              <span key={pos} style={{fontWeight:700, color:T.text}}>
                {i > 0 && <span style={{fontWeight:400, color:T.muted}}> · </span>}
                ~{n.toFixed(1)} {pos}
              </span>
            ))}
          </div>
        ) : (
          <div style={{fontSize:11.5, color:T.muted}}>
            {oppData.upcoming.length === 0 ? 'No picks before your next turn.' : 'Predictions update each pick.'}
          </div>
        )}
      </div>

      <div style={{padding:10, flex:1}}>
        {oppData.upcoming.length > 0 && (
          <SectionLabel style={{margin:'2px 6px 6px'}}>Picking before you</SectionLabel>
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
            highlight />
        ))}

        {others.length > 0 && <SectionLabel style={{margin:'14px 6px 6px'}}>After your pick</SectionLabel>}
        {others.map(t => (
          <OpponentTeamRow key={t}
            teamNum={t}
            teamName={(league.teamNames || [])[t - 1]}
            mode={modes[t] === 'auto' ? 'auto' : 'live'}
            counts={oppData.rosters[t] ? oppData.rosters[t].reduce((c,p) => { c[p.pos]=(c[p.pos]||0)+1; return c; }, {}) : {}}
            posProbs={null}
            pickLabel={null}
            onSetMode={m => onSetTeamMode(t, m)}
            highlight={false} />
        ))}
      </div>

      <div style={{padding:'10px 14px', borderTop:`1px solid ${T.border}`, fontSize:10.5, color:T.muted, lineHeight:1.55}}>
        <b style={{color:T.text}}>LIVE</b> drafts by roster need. <b style={{color:T.text}}>AUTO</b>{' '}
        follows ADP. Toggling a team changes its availability odds and the position-run alerts.
      </div>
    </div>
  );
}

// ─── PICK TICKER ──────────────────────────────────────────────────────────────
// Horizontal strip of every pick: past picks show the player taken, the
// on-the-clock cell is highlighted, and your seats are tinted. Auto-centres on
// the current pick as the draft advances.
function PickTicker({ league, picks, playersById }) {
  const numTeams = league.numTeams;
  const totalRounds = rosterTotal(league.rosterSlots) || 15;
  const totalPicks = totalRounds * numTeams;
  const currentPick = picks.length + 1;
  const modes = league.teamModes || {};
  const scrollRef = React.useRef(null);
  const currentRef = React.useRef(null);

  React.useEffect(() => {
    const cell = currentRef.current, box = scrollRef.current;
    if (cell && box) {
      box.scrollTo({ left: Math.max(0, cell.offsetLeft - box.clientWidth / 2 + cell.clientWidth / 2), behavior: 'smooth' });
    }
  }, [picks.length]);

  const cells = [];
  for (let n = 1; n <= totalPicks; n++) {
    const rd = Math.ceil(n / numTeams);
    if ((n - 1) % numTeams === 0) cells.push({ type: 'round', round: rd, key: `r${rd}` });
    cells.push({ type: 'pick', n, key: `p${n}` });
  }

  return (
    <div ref={scrollRef} className="da-no-scrollbar" style={{
      display:'flex', overflowX:'auto', background:T.surface,
      borderBottom:`1px solid ${T.border}`, flexShrink:0,
    }}>
      {cells.map(c => {
        if (c.type === 'round') return (
          <div key={c.key} style={{
            flexShrink:0, width:30, display:'flex', flexDirection:'column',
            alignItems:'center', justifyContent:'center', gap:1,
            background:T.surfaceAlt, borderRight:`1px solid ${T.border}`,
          }}>
            <span style={{fontSize:8, fontWeight:800, color:T.mutedLight, letterSpacing:.5}}>RD</span>
            <span style={{fontSize:13, fontWeight:800, color:T.muted}}>{c.round}</span>
          </div>
        );
        const teamNum = getSnakeTeam(c.n, numTeams);
        const isMine = teamNum === league.draftPosition;
        const made = c.n <= picks.length ? picks[c.n - 1] : null;
        const player = made ? playersById[made.playerId] : null;
        const isCurrent = c.n === currentPick;
        const teamName = (league.teamNames || [])[teamNum - 1] || `Team ${teamNum}`;
        const mode = modes[teamNum] === 'auto' ? 'AUTO' : 'LIVE';
        return (
          <div key={c.key} ref={isCurrent ? currentRef : null} style={{
            flexShrink:0, width:112, padding:'5px 8px 6px',
            borderRight:`1px solid ${T.borderLight}`,
            background: isCurrent ? T.primary : isMine ? T.primaryLight : T.surface,
            opacity: made && !isCurrent ? .7 : 1,
          }}>
            <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', gap:4}}>
              <span className="da-num" style={{fontSize:8.5, fontWeight:800,
                color: isCurrent ? 'rgba(255,255,255,.85)' : T.mutedLight}}>{c.n}</span>
              {!made && !isCurrent && !isMine && (
                <span style={{fontSize:8, fontWeight:800, letterSpacing:.3,
                  color: mode === 'AUTO' ? T.amber : T.primary}}>{mode}</span>
              )}
            </div>
            <div className="da-ellipsis" style={{
              fontSize:10.5, fontWeight:700, marginTop:1,
              color: isCurrent ? '#fff' : isMine ? T.primary : T.text,
            }}>{isMine ? 'YOU' : teamName}</div>
            <div className="da-ellipsis" style={{
              fontSize:9.5, marginTop:1, fontWeight: player ? 600 : 500,
              color: isCurrent ? 'rgba(255,255,255,.9)' : player ? T.muted : T.mutedLight,
            }}>
              {isCurrent ? 'On the clock' : player ? `${player.name} · ${player.pos}` : '—'}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── PICKS FEED (newest first) ───────────────────────────────────────────────
function PicksFeedPanel({ league, picks, playersById }) {
  const rows = [...picks].reverse();
  if (rows.length === 0) {
    return (
      <div style={{padding:'28px 16px', fontSize:12.5, color:T.muted, textAlign:'center', lineHeight:1.5}}>
        No picks yet. They stream in here as the draft goes.
      </div>
    );
  }
  return (
    <div style={{flex:1, overflowY:'auto', padding:'6px 10px'}}>
      {rows.map(pk => {
        const p = playersById[pk.playerId];
        const rd = Math.ceil(pk.pickNum / league.numTeams);
        const pip = ((pk.pickNum - 1) % league.numTeams) + 1;
        const mine = pk.teamNum === league.draftPosition;
        const teamName = (league.teamNames || [])[pk.teamNum - 1] || `Team ${pk.teamNum}`;
        return (
          <div key={pk.pickNum} style={{
            display:'flex', gap:8, alignItems:'center', padding:'7px 6px',
            borderBottom:`1px solid ${T.borderLight}`,
            background: mine ? T.primaryLight : 'transparent',
            borderRadius: mine ? T.rxs : 0,
          }}>
            <PosBadge pos={p ? p.pos : '?'} />
            <div style={{minWidth:0, flex:1}}>
              <div className="da-ellipsis" style={{fontSize:12, fontWeight:700, color:T.text}}>
                {p ? p.name : pk.playerId}
                {p && p.nflTeam && <span style={{fontWeight:500, color:T.muted}}> · {p.nflTeam}</span>}
              </div>
              <div className="da-ellipsis" style={{fontSize:10, color:T.muted}}>
                R{rd} P{pip} · #{pk.pickNum} — {mine ? 'You' : teamName}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Right-side panel with Picks / Opponents tabs.
function RightTabbedPanel({ league, picks, playersById, oppData, picksMade, onSetTeamMode, fullWidth = false }) {
  const [tab, setTab] = React.useState('picks');
  const tabBtn = (id, label) => (
    <button key={id} onClick={() => setTab(id)} aria-selected={tab === id} role="tab" style={{
      flex:1, padding:'9px 0', border:'none', cursor:'pointer',
      fontSize:11, fontWeight:800, letterSpacing:.5, textTransform:'uppercase',
      background: tab === id ? T.surface : T.surfaceAlt,
      color: tab === id ? T.primary : T.muted,
      borderBottom: `2px solid ${tab === id ? T.primary : 'transparent'}`,
    }}>{label}</button>
  );
  return (
    <div style={{
      width: fullWidth ? '100%' : 240, flexShrink:0, background:T.surface,
      borderLeft: fullWidth ? 'none' : `1px solid ${T.border}`,
      display:'flex', flexDirection:'column', minHeight:0,
    }}>
      <div role="tablist" style={{display:'flex', borderBottom:`1px solid ${T.border}`, flexShrink:0}}>
        {tabBtn('picks', `Picks${picks.length ? ` (${picks.length})` : ''}`)}
        {tabBtn('opponents', 'Opponents')}
      </div>
      {tab === 'picks'
        ? <PicksFeedPanel league={league} picks={picks} playersById={playersById} />
        : (
          <div style={{flex:1, minHeight:0, overflowY:'auto'}}>
            <OpponentsPanel league={league} oppData={oppData} picksMade={picksMade} onSetTeamMode={onSetTeamMode} />
          </div>
        )}
    </div>
  );
}

// ─── RECOMMENDATIONS ──────────────────────────────────────────────────────────
function RecCard({ label, player, reason, highlight, onDraft, bestImpact }) {
  if (!player) return null;
  const metric = (caption, node) => (
    <span style={{display:'inline-flex', alignItems:'center', gap:4}}>
      <span style={{fontSize:9.5, fontWeight:700, letterSpacing:.4, color:T.mutedLight, textTransform:'uppercase'}}>
        {caption}
      </span>
      {node}
    </span>
  );
  return (
    <div style={{
      background: highlight ? T.primaryLight : T.surfaceAlt,
      border: `1.5px solid ${highlight ? T.primary : T.border}`,
      borderRadius: T.r, padding:'11px 13px', flex:'1 1 210px', minWidth:210,
      display:'flex', flexDirection:'column', gap:5,
    }}>
      <SectionLabel style={{color: highlight ? T.primary : T.muted}}>{label}</SectionLabel>
      <div style={{display:'flex', alignItems:'center', gap:8, minWidth:0}}>
        <PosBadge pos={player.pos} />
        <span className="da-ellipsis" style={{fontSize:14, fontWeight:700, color:T.text}}>{player.name}</span>
        <AvailabilityChip status={player.availability} />
      </div>
      <div style={{display:'flex', alignItems:'center', gap:9, flexWrap:'wrap'}}>
        <span style={{fontSize:11, color:T.muted}}>{player.nflTeam}</span>
        {player.draftScore != null && metric('impact', <ScoreBadge score={player.draftScore} best={bestImpact} />)}
        {metric('vorp', <VORPBadge vorp={player.vorp} />)}
      </div>
      {reason && (
        <div style={{fontSize:11.5, color: highlight ? T.primary : T.muted, lineHeight:1.45}}>{reason}</div>
      )}
      {playerNewsSignals(player.signals).slice(0, 1).map((sig, i) => (
        <div key={i} title={`${sig.source} · ${sig.observed_at}`}
          style={{fontSize:11, color:T.primary, lineHeight:1.4}}>
          {sig.attribution || sig.source}: {String(sig.kind).replace(/_/g, ' ')} {sig.value}
        </div>
      ))}
      <Btn size="sm" variant={highlight ? 'primary' : 'secondary'} onClick={() => onDraft(player)}
        style={{marginTop:2, alignSelf:'flex-start'}}>
        Draft {player.name.split(' ').slice(-1)[0]}
      </Btn>
    </div>
  );
}

function RecommendationBar({ scored, myPlayers, league, oppData, onDraft, stale, untilMyTurn, loading }) {
  const shell = children => (
    <div style={{padding:'10px 14px', background:T.surface, borderBottom:`1px solid ${T.border}`}}>
      {children}
    </div>
  );

  // While it isn't your turn the last rollout's numbers describe a board that no
  // longer exists, so showing them as "recommendations" would be a lie. Say
  // what's actually happening instead.
  if (stale) {
    return shell(
      <div style={{display:'flex', alignItems:'center', gap:10, fontSize:12.5, color:T.muted}}>
        <span style={{
          fontSize:11, fontWeight:800, letterSpacing:.5, color:T.muted,
          background:T.borderLight, borderRadius:99, padding:'3px 10px',
        }}>ON DECK</span>
        {untilMyTurn} pick{untilMyTurn === 1 ? '' : 's'} until you're up — recommendations recompute
        when you're on the clock. The board below still shows projections and VORP.
      </div>
    );
  }

  if (loading) {
    return shell(
      <div style={{display:'flex', alignItems:'center', gap:10, fontSize:12.5, color:T.muted}}>
        <Spinner size={14} />
        Simulating the rest of the draft…
      </div>
    );
  }

  // Only fully-simulated rows can be recommended: an estimated impact isn't
  // measured against the same baseline, so promoting one would compare numbers
  // that don't mean the same thing.
  const rolled = (scored || []).filter(p => p.draftScore != null && p.simulated !== false);
  if (rolled.length === 0) {
    return shell(<div style={{fontSize:12.5, color:T.muted}}>No players available to recommend.</div>);
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

  let atRisk = null;
  rolled.forEach(p => {
    if (p.vorp == null || p.availPct == null) return;
    if (p.vorp > 0 && p.availPct <= 60) {
      if (!atRisk || p.vorp > atRisk.vorp) atRisk = p;
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
  if (runAlert && !dupId(runAlert.player.id)) situational = { kind:'run', ...runAlert };
  else if (atRisk && !dupId(atRisk.id)) situational = { kind:'at-risk', player: atRisk };
  else if (reach && reach.player.id !== bestOverall.id) situational = { kind:'reach', ...reach };

  return shell(
    <>
      <SectionLabel style={{marginBottom:8}}>Recommended right now</SectionLabel>
      <div style={{display:'flex', gap:10, flexWrap:'wrap'}}>
        <RecCard label="Best draft impact" player={bestOverall} onDraft={onDraft} bestImpact={bestOverall.draftScore}
          reason={isSame
            ? 'Highest season-points impact, and it fills an open starting slot.'
            : `${bestOverall.availPct}% chance still there at your next pick.`}
          highlight={isSame} />
        {bestByNeed && !isSame && (
          <RecCard label="Best by need" player={bestByNeed} onDraft={onDraft} bestImpact={bestOverall.draftScore}
            reason={`Top ${bestByNeed.pos} for an open starting slot · ${bestByNeed.availPct}% available next pick.`} />
        )}
        {situational && situational.kind === 'run' && (
          <RecCard label={`${situational.pos} run likely`} player={situational.player} onDraft={onDraft} bestImpact={bestOverall.draftScore}
            reason={`~${situational.exp.toFixed(1)} ${situational.pos}s go before your next pick — only ${situational.player.availPct}% chance this one survives.`}
            highlight />
        )}
        {situational && situational.kind === 'at-risk' && (
          <RecCard label={`${situational.player.pos} value at risk`} player={situational.player} onDraft={onDraft} bestImpact={bestOverall.draftScore}
            reason={`${Math.round(situational.player.vorp)} pts above replacement — only ${situational.player.availPct}% chance they last.`}
            highlight />
        )}
        {situational && situational.kind === 'reach' && (
          <RecCard label="Worth the reach" player={situational.player} onDraft={onDraft} bestImpact={bestOverall.draftScore}
            reason={`+${Math.round(situational.gap)} season-pts over your best need — worth taking now.`}
            highlight />
        )}
      </div>
    </>
  );
}

function cmpScore(a, b) {
  // Fully-simulated rows always rank above estimated ones: their impacts are
  // rest-of-draft expectations and an estimate's isn't on the same scale, so
  // interleaving the two by raw number would mis-order the board.
  const ea = a.simulated === false, eb = b.simulated === false;
  if (ea !== eb) return ea ? 1 : -1;
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

// ─── QUICK PICK ──────────────────────────────────────────────────────────────
function matchQuickPickCandidates(query, players, limit = 5) {
  if (!query || !query.trim()) return [];
  const rawQ = query.trim().toLowerCase();
  const tokens = rawQ.split(/\s+/);

  const POS_SET = new Set(['QB', 'RB', 'WR', 'TE', 'K', 'DST', 'DEF']);
  let queryPos = null;
  const nameTokens = [];

  tokens.forEach(t => {
    const tu = t.toUpperCase();
    if (POS_SET.has(tu)) queryPos = tu === 'DEF' ? 'DST' : tu;
    else nameTokens.push(t.toLowerCase());
  });

  const scored = [];
  players.forEach(p => {
    if (p.drafted) return;
    const pos = (p.pos || '').toUpperCase();
    if (queryPos && pos !== queryPos) return;

    let score = 0;
    const nameLower = (p.name || '').toLowerCase();
    const words = nameLower.split(/\s+/);
    const teamLower = (p.nflTeam || p.team || '').toLowerCase();

    let matchesCount = 0;
    nameTokens.forEach(qt => {
      let tScore = 0;
      if (teamLower && teamLower === qt) tScore = Math.max(tScore, 40);
      if (nameLower.startsWith(qt)) tScore = Math.max(tScore, 85);
      words.forEach(w => {
        if (w === qt) tScore = Math.max(tScore, 90);
        else if (w.startsWith(qt)) tScore = Math.max(tScore, 75);
      });
      if (tScore > 0) { matchesCount++; score += tScore; }
    });

    if (nameTokens.length > 0 && matchesCount < nameTokens.length) return;
    if (nameTokens.length === 0) score = 1;

    scored.push({ player: p, score, adp: p.adp != null ? p.adp : 999 });
  });

  scored.sort((a, b) => b.score - a.score || a.adp - b.adp);
  return scored.slice(0, limit).map(s => s.player);
}

// Typing filters the board below; Enter drafts the highlighted match. The old
// version claimed "Enter to confirm" but only rewrote the search box, which is
// the last thing you want when you're on the clock.
function QuickPickInput({ players, search, setSearch, onDraftPlayer }) {
  const [selectedIndex, setSelectedIndex] = React.useState(0);
  const [isOpen, setIsOpen] = React.useState(false);

  const candidates = React.useMemo(
    () => matchQuickPickCandidates(search, players, 5), [search, players]);

  React.useEffect(() => { setSelectedIndex(0); }, [search]);

  const take = p => { onDraftPlayer(p); setSearch(''); setIsOpen(false); };

  const handleKeyDown = e => {
    if (e.key === 'Escape') { e.preventDefault(); setSearch(''); setIsOpen(false); return; }
    if (!isOpen || candidates.length === 0) {
      if (e.key === 'ArrowDown') setIsOpen(true);
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(i => (i + 1) % candidates.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(i => (i - 1 + candidates.length) % candidates.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (candidates[selectedIndex]) take(candidates[selectedIndex]);
    }
  };

  return (
    <div style={{position:'relative', flex:1, minWidth:200}}>
      <input
        type="text"
        aria-label="Search players — Enter drafts the highlighted match"
        placeholder="Search players (“bij”, “allen qb”, “kc dst”) — Enter drafts"
        value={search}
        onChange={e => { setSearch(e.target.value); setIsOpen(true); }}
        onFocus={() => setIsOpen(true)}
        onBlur={() => setTimeout(() => setIsOpen(false), 120)}
        onKeyDown={handleKeyDown}
        className="da-input"
        style={{
          width:'100%', padding:'7px 30px 7px 11px', border:`1.5px solid ${T.border}`,
          borderRadius:T.rsm, fontSize:13, color:T.text, background:T.surface, outline:'none',
        }}
      />
      {search && (
        <button type="button" onClick={() => { setSearch(''); setIsOpen(false); }} aria-label="Clear search"
          style={{
            position:'absolute', right:6, top:'50%', transform:'translateY(-50%)',
            background:'none', border:'none', cursor:'pointer', color:T.mutedLight,
            fontSize:14, fontWeight:700, padding:'2px 5px', lineHeight:1,
          }}>×</button>
      )}
      {isOpen && candidates.length > 0 && (
        <div className="da-pop" style={{
          position:'absolute', top:'calc(100% + 4px)', left:0, right:0, zIndex:400,
          background:T.surface, border:`1px solid ${T.border}`, borderRadius:T.rsm,
          boxShadow:T.shadowLg, overflow:'hidden',
        }}>
          {candidates.map((p, idx) => {
            const on = idx === selectedIndex;
            return (
              <div key={p.id}
                onMouseDown={e => { e.preventDefault(); take(p); }}
                onMouseEnter={() => setSelectedIndex(idx)}
                style={{
                  padding:'8px 11px', display:'flex', alignItems:'center', justifyContent:'space-between',
                  gap:10, cursor:'pointer', background: on ? T.primaryLight : 'transparent',
                  borderBottom: idx < candidates.length - 1 ? `1px solid ${T.borderLight}` : 'none',
                }}>
                <div style={{display:'flex', alignItems:'center', gap:8, minWidth:0}}>
                  <PosBadge pos={p.pos} />
                  <span className="da-ellipsis" style={{fontWeight:700, fontSize:13, color:T.text}}>{p.name}</span>
                  <span style={{fontSize:11, color:T.muted, flexShrink:0}}>{p.nflTeam || p.team}</span>
                </div>
                <div style={{display:'flex', alignItems:'center', gap:8, flexShrink:0}}>
                  <span className="da-num" style={{fontSize:11, color:T.mutedLight}}>ADP {p.adp || '—'}</span>
                  <span style={{
                    fontSize:10.5, fontWeight:700, color: on ? T.primary : T.mutedLight,
                  }}>{on ? '↵ draft' : 'draft'}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── PLAYER LIST ──────────────────────────────────────────────────────────────
function PlayerList({ players, onDraft, showDrafted, onToggleDrafted }) {
  const [search,    setSearch]    = React.useState('');
  const [posFilter, setPosFilter] = React.useState('ALL');
  const [sortBy,    setSortBy]    = React.useState('draftScore');
  const [hoverId,   setHoverId]   = React.useState(null);
  const { width } = useLayout();

  const isNarrow = width < 650;
  const isMedium = width >= 650 && width < 980;
  const isWide   = width >= 980;

  const filtered = players
    .filter(p => showDrafted || !p.drafted)
    .filter(p => posFilter === 'ALL' || p.pos === posFilter)
    .filter(p => !search ||
      p.name.toLowerCase().includes(search.toLowerCase()) ||
      (p.nflTeam || '').toLowerCase().includes(search.toLowerCase())
    )
    .sort((a,b) => {
      if (sortBy === 'adp')     return (a.adp || 9999) - (b.adp || 9999);
      if (sortBy === 'projPts') return b.projPts - a.projPts;
      if (sortBy === 'vorp')    return (b.vorp || 0) - (a.vorp || 0);
      return cmpScore(a, b);
    });

  const bestImpact = filtered.reduce(
    (best, p) => (p.draftScore != null && p.draftScore > best ? p.draftScore : best), 0);

  const GRID = isWide
    ? '30px 1fr 54px 50px 46px 52px 58px 60px 68px 74px'
    : isMedium
      ? '26px 1fr 50px 58px 60px 68px 70px'
      : '24px 1fr 46px 60px 68px';

  // Clickable column headers replace the old sort dropdown: the header already
  // names the column, so it may as well be the control that sorts by it.
  const SORT_HELP = {
    adp:        'Average draft position across public drafts — where the field is taking this player.',
    projPts:    "Projected season points under this league's scoring.",
    vorp:       'Points above the replacement-level player at this position in this league.',
    draftScore: 'Expected change in your total season points from drafting this player now, from the rest-of-draft simulation.',
  };

  const SortHead = ({ id, label, align = 'right' }) => (
    <button className="da-sort" onClick={() => setSortBy(id)}
      title={SORT_HELP[id]}
      aria-sort={sortBy === id ? 'descending' : 'none'}
      style={{
        justifyContent: align === 'right' ? 'flex-end' : 'flex-start',
        color: sortBy === id ? T.primary : T.muted,
        fontWeight: 800, fontSize: 10, letterSpacing: .6, textTransform: 'uppercase',
      }}>
      {label}{sortBy === id ? ' ↓' : ''}
    </button>
  );

  return (
    <div style={{flex:1, display:'flex', flexDirection:'column', minHeight:0, overflow:'hidden'}}>
      <div style={{
        padding:'8px 14px', background:T.surface, borderBottom:`1px solid ${T.border}`,
        display:'flex', flexDirection:'column', gap:8, flexShrink:0,
      }}>
        <QuickPickInput players={players} search={search} setSearch={setSearch} onDraftPlayer={onDraft} />

        <div className="da-no-scrollbar" style={{display:'flex', gap:4, alignItems:'center', overflowX:'auto'}}>
          {['ALL', ...POSITIONS].map(pos => (
            <button key={pos} onClick={() => setPosFilter(pos)} aria-pressed={posFilter === pos} style={{
              padding:'4px 9px', borderRadius:T.rxs, flexShrink:0, cursor:'pointer',
              border:`1.5px solid ${posFilter===pos ? T.primary : T.border}`,
              background: posFilter===pos ? T.primaryLight : T.surface,
              color: posFilter===pos ? T.primary : T.muted,
              fontSize:11.5, fontWeight:700,
            }}>{pos}</button>
          ))}
          <div style={{width:1, height:16, background:T.border, margin:'0 4px', flexShrink:0}} />
          <button onClick={onToggleDrafted} aria-pressed={showDrafted} style={{
            padding:'4px 9px', borderRadius:T.rxs, flexShrink:0, cursor:'pointer',
            border:`1.5px solid ${T.border}`,
            background: showDrafted ? T.borderLight : T.surface,
            color:T.muted, fontSize:11.5, fontWeight:600,
          }}>
            {showDrafted ? 'Hide drafted' : 'Show drafted'}
          </button>
          <span style={{marginLeft:'auto', fontSize:11.5, color:T.mutedLight, flexShrink:0, paddingLeft:8}}>
            {filtered.length} shown
          </span>
        </div>
      </div>

      <div style={{
        display:'grid', gridTemplateColumns:GRID,
        padding:'7px 14px', background:T.surfaceAlt, borderBottom:`1px solid ${T.border}`,
        fontSize:10, fontWeight:800, color:T.muted, letterSpacing:.6, gap:6, alignItems:'center',
        textTransform:'uppercase',
      }}>
        <span>#</span>
        <span>Player</span>
        <span>Pos</span>
        {isWide && <span>Team</span>}
        {isWide && <span style={{textAlign:'center'}}>Bye</span>}
        {isWide && <SortHead id="adp" label="ADP" />}
        {(isWide || isMedium) && <SortHead id="projPts" label="Proj" />}
        <SortHead id="vorp" label="VORP" />
        <SortHead id="draftScore" label="Impact" />
        <span />
      </div>

      <div style={{flex:1, overflowY:'auto'}}>
        {filtered.length === 0 && (
          <div style={{padding:40, textAlign:'center', color:T.muted, fontSize:13.5}}>
            No players match {search ? `“${search}”` : 'these filters'}.
          </div>
        )}
        {filtered.map((p,i) => {
          const isHov = hoverId === p.id;
          const tierDot = ['','#d97706','#6b7280','#9ca3af','#d1d5db','#e5e7eb'][p.tier] || '#e5e7eb';
          const teamText = p.nflTeam || 'FA';
          const byeText = p.byeWeek ? `Bye ${p.byeWeek}` : null;
          const subDetails = isNarrow
            ? [teamText, byeText, `${Math.round(p.projPts)} pts`, `ADP ${p.adp}`].filter(Boolean).join(' · ')
            : isMedium
              ? [teamText, byeText, `ADP ${p.adp}`].filter(Boolean).join(' · ')
              : (p.tier ? `Tier ${p.tier}` : '');
          // News signals from /api/context: injury, depth chart, snaps, trending adds.
          const updateDetails = playerNewsSignals(p.signals).map(sig =>
            `${sig.attribution || sig.source}: ${sig.kind.replace(/_/g, ' ')} ${sig.value}`
          );
          const rowTitle = [
            p.draftScore != null
              ? `Draft impact ${Math.round(p.draftScore)} · immediate lineup gain ${p.lineupGain} · ${p.availPct}% available at your next pick`
              : null,
            p.availability ? `Availability: ${p.availability}` : null,
            ...updateDetails,
          ].filter(Boolean).join('\n');

          return (
            <div key={p.id}
              onMouseEnter={() => setHoverId(p.id)}
              onMouseLeave={() => setHoverId(null)}
              title={rowTitle || undefined}
              style={{
                display:'grid', gridTemplateColumns:GRID,
                padding:'7px 14px', gap:6, alignItems:'center',
                borderBottom:`1px solid ${T.borderLight}`,
                background: p.drafted ? T.surfaceAlt : isHov ? '#f3f6ff' : T.surface,
                opacity: p.drafted ? .45 : 1,
              }}>
              <span className="da-num" style={{fontSize:11, color:T.mutedLight}}>{i+1}</span>

              <div style={{minWidth:0}}>
                <div style={{fontSize:13, fontWeight:600, color:T.text, display:'flex', alignItems:'center', gap:5}}>
                  <span style={{width:7, height:7, borderRadius:'50%', background:tierDot, flexShrink:0}}
                    title={`Tier ${p.tier}`} />
                  <span className="da-ellipsis">{p.name}</span>
                  {p.availability && <AvailabilityChip status={p.availability} />}
                </div>
                <div className="da-ellipsis" style={{fontSize:10, color:T.mutedLight, marginTop:1}}>
                  {isHov && p.draftScore != null
                    ? <>
                        avail {p.availPct}%
                        {p.byePen > 0 && <span style={{color:T.amber}}> · bye −{p.byePen}</span>}
                        {updateDetails.length > 0 && <span style={{color:T.primary}}> · {updateDetails[0]}</span>}
                      </>
                    : subDetails}
                </div>
              </div>

              <span><PosBadge pos={p.pos} /></span>
              {isWide && <span className="da-ellipsis" style={{fontSize:12, color:T.muted}}>{p.nflTeam}</span>}
              {isWide && (
                <span className="da-num" style={{fontSize:12, color:T.muted, textAlign:'center'}}>
                  {p.byeWeek || '—'}
                </span>
              )}
              {isWide && (
                <span className="da-num" style={{fontSize:12, color:T.mutedLight, textAlign:'right'}}>
                  {p.adp != null ? p.adp : '—'}
                </span>
              )}
              {(isWide || isMedium) && (
                <span className="da-num" style={{fontSize:12, fontWeight:600, color:T.text, textAlign:'right'}}>
                  {Math.round(p.projPts)}
                </span>
              )}
              <span style={{display:'flex', justifyContent:'flex-end'}}>
                <VORPBadge vorp={p.vorp} />
              </span>
              <span style={{display:'flex', justifyContent:'flex-end'}}>
                {p.draftScore != null
                  ? <ScoreBadge score={p.draftScore} best={bestImpact} />
                  : <span style={{fontSize:11, color:T.mutedLight}}>—</span>}
              </span>
              <span style={{display:'flex', justifyContent:'flex-end'}}>
                {p.drafted ? (
                  <span style={{fontSize:11, color:T.mutedLight}}>Taken</span>
                ) : (
                  <button onClick={() => onDraft(p)} aria-label={`Draft ${p.name}`} style={{
                    background: isHov ? T.primary : T.primaryLight,
                    color: isHov ? '#fff' : T.primary,
                    border:'none', borderRadius:T.rxs, padding:'4px 9px',
                    fontSize:11, fontWeight:700, cursor:'pointer', transition:'all .13s',
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
  const rounds     = Math.max(rosterTotal(league.rosterSlots), Math.ceil(picks.length / numTeams));
  const teamNums   = Array.from({length:numTeams},(_,i)=>i+1);
  const roundNums  = Array.from({length:rounds||1},(_,i)=>i+1);

  return (
    <Modal title="Full draft board" onClose={onClose} width={Math.min(numTeams*112+80, 1100)}
      subtitle="Snake order — odd rounds left to right, even rounds right to left. Your seat is tinted.">
      <div style={{overflowX:'auto'}}>
        <table style={{borderCollapse:'collapse', width:'100%', fontSize:11}}>
          <thead>
            <tr>
              <th style={{padding:'6px 10px', textAlign:'left', color:T.mutedLight, fontWeight:800, fontSize:10, letterSpacing:.5}}>RD</th>
              {teamNums.map(t=>(
                <th key={t} className="da-ellipsis" style={{
                  padding:'6px 8px', textAlign:'center', maxWidth:110,
                  color: t===draftPosition ? T.primary : T.muted,
                  fontWeight:800, fontSize:10, letterSpacing:.4,
                  background: t===draftPosition ? T.primaryLight : 'transparent',
                }}>
                  {t===draftPosition ? 'YOU' : ((league.teamNames || [])[t-1] || `T${t}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {roundNums.map(rnd=>(
              <tr key={rnd} style={{background: rnd%2===0 ? T.surfaceAlt : T.surface}}>
                <td className="da-num" style={{padding:'5px 10px', fontWeight:700, color:T.mutedLight, fontSize:11}}>
                  {rnd}
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
                      background: isMe ? 'rgba(58,91,239,.05)' : 'transparent',
                      minWidth:92,
                    }}>
                      {player ? (
                        <div>
                          <div style={{fontWeight:600, color:isMe?T.primary:T.text, fontSize:11, lineHeight:1.3}}>
                            {player.name.split(' ').pop()}
                          </div>
                          <PosBadge pos={player.pos} />
                        </div>
                      ) : (
                        <span style={{color:T.border}}>—</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Modal>
  );
}

// ─── PASTE DRAFT ROOM HISTORY MODAL ───────────────────────────────────────────
function PasteDraftModal({ league, picks, allPlayers, onClose, onBatchDraft }) {
  const [rawText, setRawText] = React.useState('');
  const [parsedItems, setParsedItems] = React.useState([]);
  const [loading, setLoading] = React.useState(false);
  const [err, setErr] = React.useState(null);

  const handleParse = () => {
    if (!rawText.trim()) return;
    setLoading(true);
    setErr(null);

    const playersPayload = (allPlayers || []).map(p => ({
      id: p.id, name: p.name, pos: p.pos, team: p.nflTeam || p.team,
    }));

    fetch('/api/parse-draft-text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: rawText,
        numTeams: league.numTeams,
        startPick: picks.length + 1,
        players: playersPayload,
      }),
    })
      .then(r => r.json())
      .then(d => {
        setLoading(false);
        if (d.error) { setErr(d.error); return; }
        setParsedItems(d.items || []);
      })
      .catch(e => { setLoading(false); setErr(String(e)); });
  };

  const toggleConfirm = idx =>
    setParsedItems(items => items.map((item, i) => i === idx ? { ...item, isConfirmed: !item.isConfirmed } : item));

  const ready = parsedItems.filter(i => i.isConfirmed && i.matchedPlayerId);

  const handleApply = () => {
    if (ready.length === 0) return;
    onBatchDraft(ready);
    onClose();
    toast(`Added ${ready.length} pick${ready.length === 1 ? '' : 's'}.`, 'ok');
  };

  const confidenceBadge = conf => {
    const map = {
      HIGH:      { color:'green', label:'High' },
      MEDIUM:    { color:'amber', label:'Medium' },
      LOW:       { color:'red',   label:'Low' },
      UNMATCHED: { color:'gray',  label:'No match' },
    };
    const c = map[conf] || map.UNMATCHED;
    return <Badge label={c.label} color={c.color} />;
  };

  return (
    <Modal title="Paste draft history" onClose={onClose} width={780}
      subtitle={`Picks are mapped sequentially starting from pick #${picks.length + 1}.`}
      footer={parsedItems.length > 0 ? (
        <>
          <Btn variant="secondary" onClick={onClose}>Cancel</Btn>
          <Btn onClick={handleApply} disabled={ready.length === 0}>
            Add {ready.length} pick{ready.length === 1 ? '' : 's'}
          </Btn>
        </>
      ) : null}>
      <div style={{display:'flex', flexDirection:'column', gap:12}}>
        <div style={{fontSize:12.5, color:T.muted, lineHeight:1.5}}>
          Paste copied text from ESPN, Yahoo, Sleeper, or just a list of player names. Everything is
          previewed before anything is added to your board.
        </div>

        <Textarea rows={5} value={rawText} onChange={e => setRawText(e.target.value)}
          aria-label="Draft room text"
          placeholder="Paste the draft room log here…"
          style={{fontFamily:'var(--mono)', fontSize:12}} />

        <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', gap:10}}>
          <Btn onClick={handleParse} disabled={loading || !rawText.trim()}>
            {loading ? 'Parsing…' : 'Parse and preview'}
          </Btn>
          {err && <span style={{fontSize:12, color:T.red}}>{err}</span>}
        </div>

        {parsedItems.length > 0 && (
          <div style={{borderTop:`1px solid ${T.border}`, paddingTop:12}}>
            <div style={{fontSize:13, fontWeight:700, color:T.text, marginBottom:8}}>
              {ready.length} of {parsedItems.length} picks selected
            </div>
            <div style={{maxHeight:280, overflowY:'auto', border:`1px solid ${T.borderLight}`, borderRadius:T.rsm}}>
              <table className="da-table">
                <thead>
                  <tr>
                    <th style={{width:32}}>Add</th>
                    <th style={{width:44}}>Pick</th>
                    <th style={{width:44}}>Team</th>
                    <th>Matched player</th>
                    <th style={{width:80}}>Match</th>
                    <th>Original text</th>
                  </tr>
                </thead>
                <tbody>
                  {parsedItems.map((item, idx) => (
                    <tr key={idx} style={{background: item.isConfirmed ? 'rgba(58,91,239,.05)' : 'transparent'}}>
                      <td style={{textAlign:'center'}}>
                        <input type="checkbox" checked={!!item.isConfirmed}
                          aria-label={`Include pick ${item.pickNum}`}
                          disabled={!item.matchedPlayerId}
                          onChange={() => toggleConfirm(idx)} />
                      </td>
                      <td className="da-num" style={{fontWeight:700}}>#{item.pickNum}</td>
                      <td style={{color:T.muted}}>T{item.teamNum}</td>
                      <td style={{fontWeight:600, color: item.matchedPlayerId ? T.text : T.mutedLight}}>
                        {item.matchedPlayerName}{' '}
                        {item.matchedPlayerPos && <PosBadge pos={item.matchedPlayerPos} />}
                      </td>
                      <td>{confidenceBadge(item.confidence)}</td>
                      <td className="da-ellipsis" style={{color:T.mutedLight, fontSize:11, maxWidth:200}}>
                        {item.rawText}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}

// ─── ENGINE SETTINGS ─────────────────────────────────────────────────────────
// Was a floating glass panel pinned over the board in a different visual
// language (and with a drag cursor that dragged nothing). It's a normal modal
// now, opened from the draft room's More menu.
function EngineSettingsModal({ league, tweaks, setTweaks, adpNoise, onClose }) {
  return (
    <Modal title="Engine settings" onClose={onClose} width={460}
      subtitle="Changing either value recomputes the recommendations."
      footer={<Btn onClick={onClose}>Done</Btn>}>
      <Field label="Opponents autodrafting"
        hint={`${tweaks.autoDrafters} of ${Math.max(1, league.numTeams - 1)}`}>
        <input type="range" min={0} max={Math.max(1, league.numTeams - 1)} step={1}
          value={tweaks.autoDrafters} style={{width:'100%'}}
          onChange={e => setTweaks('autoDrafters', Number(e.target.value))} />
      </Field>
      <Note style={{marginTop:-6, marginBottom:18}}>
        More autodrafters means opponents stick closer to ADP and the board gets less chaotic.
        Current opponent noise σ ≈ <b style={{color:T.text}}>{adpNoise}</b>.
      </Note>

      <Field label="Precision" hint={`${tweaks.sims} simulations per pick`}>
        <input type="range" min={16} max={96} step={8}
          value={tweaks.sims} style={{width:'100%'}}
          onChange={e => setTweaks('sims', Number(e.target.value))} />
      </Field>
      <Note style={{marginTop:-6}}>
        Higher precision gives steadier numbers between picks, at a little more time per
        recommendation.
      </Note>
    </Modal>
  );
}

// ─── DRAFT SCREEN ─────────────────────────────────────────────────────────────
function DraftScreen({ league, picks, allPlayers, onBack, onAddPick, onUndoPick,
                       onResetPicks, onReplacePicks, onUpdateLeague, onRefreshPlayers }) {
  const [showDraftBoard,   setShowDraftBoard]   = React.useState(false);
  const [showDrafted,      setShowDrafted]      = React.useState(false);
  const [showSidePanel,    setShowSidePanel]    = React.useState(true);
  const [showMyTeamDrawer, setShowMyTeamDrawer] = React.useState(false);
  const [showOppDrawer,    setShowOppDrawer]    = React.useState(false);
  const [showPasteModal,   setShowPasteModal]   = React.useState(false);
  const [showPullModal,    setShowPullModal]    = React.useState(false);
  const [showAuction,      setShowAuction]      = React.useState(false);
  const [showEngine,       setShowEngine]       = React.useState(false);
  const [hint,             setHint]             = React.useState('');

  const { isMobile, isTablet, isDesktop } = useLayout();

  const tweakDefaults = typeof TWEAK_DEFAULTS !== 'undefined' ? TWEAK_DEFAULTS : { sims: 24, autoDrafters: 0 };
  const [tweaks, setTweaks] = useTweaks(tweakDefaults);

  const draftedIds = React.useMemo(() => new Set(picks.map(p=>p.playerId)), [picks]);
  const { round, pickInRound } = getCurrentRoundPick(picks.length, league.numTeams);
  const currentTeam = getSnakeTeam(picks.length + 1, league.numTeams);
  const isMyPick    = currentTeam === league.draftPosition;

  const playersWithProj = React.useMemo(() => withProjections(allPlayers, league), [allPlayers, league]);
  const playersWithVORP = React.useMemo(() => withVORP(playersWithProj, league), [playersWithProj, league]);

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
    return window.OpponentModel.analyze(available, picks, league, league.teamModes || {}, playersById);
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
  const handleRefreshRecs = () => setRefreshNonce(n => n + 1);

  React.useEffect(() => {
    // A recommendation means "draft this player now", so only compute it on the
    // user's actual turn. Computing one pick early let the rollout reserve
    // candidates through an opponent selection and overstated availability.
    if (untilMyTurn !== 0) {
      setSuggest(s => ({ ...s, loading: false, stale: true }));
      return undefined;
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
        importedScoring: league.importedScoring,
        draftType: league.draftType,
        adpNoise,
        sims: (tweaks && tweaks.sims) || undefined,
      },
    };
    const ctrl = new AbortController();
    // `stale` has to clear here as well: RecommendationBar tests it before
    // `loading`, so leaving it set makes the bar read "ON DECK — 0 picks until
    // you're up" for the whole rollout instead of showing the spinner.
    setSuggest(s => ({ ...s, loading: true, err: null, stale: false }));
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
      league.scoringType, league.customScoring, refreshNonce]); // eslint-disable-line react-hooks/exhaustive-deps

  const tweakSig = `${tweaks.sims}|${tweaks.autoDrafters}`;
  const prevTweakSig = React.useRef(tweakSig);
  React.useEffect(() => {
    if (prevTweakSig.current !== tweakSig) {
      prevTweakSig.current = tweakSig;
      handleRefreshRecs();
    }
  }, [tweakSig]); // eslint-disable-line react-hooks/exhaustive-deps

  const scored = React.useMemo(() => {
    const rows = suggest.rows;
    return available.map(p => {
      const r = rows[p.id];
      if (!r) return { ...p, draftScore: null };
      return {
        ...p,
        // impact is null for rows the engine didn't fully simulate — they keep
        // their board position and projections but show no draft score.
        draftScore: r.impact == null ? null : r.impact,
        impact: r.impact,
        simulated: r.simulated !== false,
        projRoster: r.projRoster,
        goneRisk: r.goneRisk,
        availPct: Math.max(0, Math.round(100 * (1 - (r.goneRisk || 0)))),
        lineupGain: r.immediateGain,
        byePen: r.byePenalty || 0,
        // News context from /api/context, joined server-side onto each row.
        availability: r.availability || p.availability,
        confidence: r.confidence,
        signals: r.signals && r.signals.length ? r.signals : p.signals,
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

  // A snapshot on disk, shared by every league on this machine — one slot, not
  // per-league storage. Picks themselves autosave in the browser; this exists
  // to move a draft between profiles or recover after clearing site data.
  const handleSaveSnapshot = () => {
    const pickData = picks.map(pk => pk.playerId);
    const myPickData = picks.filter(pk => pk.teamNum === league.draftPosition).map(pk => pk.playerId);
    fetch('/api/save-draft', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ picks: pickData, my_picks: myPickData }),
    })
      .then(r => r.json())
      .then(d => toast(d.ok ? 'Snapshot saved to disk.' : (d.error || 'Save failed'), d.ok ? 'ok' : 'error'))
      .catch(() => toast('Save failed.', 'error'));
  };

  const handleRestoreSnapshot = () => {
    const run = () => fetch('/api/load-draft')
      .then(r => r.json())
      .then(d => {
        if (d.error) { toast(d.error, 'error'); return; }
        const keys = Array.isArray(d.picks) ? d.picks : [];
        const known = new Set(allPlayers.map(p => p.id));
        const loaded = keys
          .filter(k => known.has(k))
          .map((k, i) => ({ pickNum: i + 1, teamNum: getSnakeTeam(i + 1, league.numTeams), playerId: k }));
        onReplacePicks(loaded);
        const skipped = keys.length - loaded.length;
        toast(skipped > 0
          ? `Restored ${loaded.length} picks (${skipped} unknown players skipped).`
          : `Restored ${loaded.length} picks.`, 'ok');
      })
      .catch(() => toast('Restore failed.', 'error'));

    if (picks.length === 0) { run(); return; }
    confirmDialog({
      title: 'Replace the current picks?',
      body: `The ${picks.length} picks on this board are replaced by the snapshot saved on disk. The snapshot is shared by every league on this machine, so make sure it belongs to this draft.`,
      confirmLabel: 'Replace picks', tone: 'danger',
    }).then(ok => { if (ok) run(); });
  };

  const handleBatchDraft = confirmedItems => {
    let count = picks.length;
    confirmedItems.forEach(item => {
      count++;
      const team = getSnakeTeam(count, league.numTeams);
      onAddPick({ pickNum: count, teamNum: team, playerId: item.matchedPlayerId });
    });
  };

  // ── Sleeper live draft sync ────────────────────────────────────────────
  // Sleeper hands back real pick numbers and seats, so the board can simply
  // mirror the draft while it happens instead of being typed in.
  const canLiveSync = Boolean(league.sleeperDraftId || league.sleeperLeagueId);
  const [live, setLive] = React.useState({ on:false, busy:false, ok:null, msg:null, status:'', unmatched:0 });
  const liveRef = React.useRef({ inFlight:false });
  // The apply guard compares Sleeper against the board as it stands *now*, not
  // against the last payload we applied. Caching the payload signature instead
  // meant an Undo (or any local edit) could never be re-synced: Sleeper would
  // report the same picks, the signature would match, and the board stayed
  // desynced until Sleeper's own pick count moved.
  const picksRef = React.useRef(picks);
  picksRef.current = picks;
  const picksSig = list => (list || []).map(pk => `${pk.pickNum}:${pk.playerId || ''}`).join(',');

  const syncSleeperDraft = ({ manual = false } = {}) => {
    if (liveRef.current.inFlight) return;
    liveRef.current.inFlight = true;
    if (manual) setLive(s => ({ ...s, busy:true, msg:null }));
    fetch('/api/sleeper/draft', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ league }),
    })
      .then(r => r.json())
      .then(d => {
        if (d.error) { setLive(s => ({ ...s, busy:false, ok:false, msg:d.error })); return; }
        const synced = d.picks || [];
        // Only push when Sleeper and the board actually differ — replacing
        // picks re-runs the rollout, which is the expensive part.
        if (picksSig(synced) !== picksSig(picksRef.current)) {
          onReplacePicks(synced);
        }
        const unknown = (d.unmatched || []).length;
        setLive(s => ({
          ...s, busy:false, ok:true, status:d.status || '', unmatched:unknown,
          // A finished draft has nothing left to poll for.
          on: d.status === 'complete' ? false : s.on,
          msg: `${synced.length} pick${synced.length === 1 ? '' : 's'}`
            + (unknown ? ` · ${unknown} not on board` : '')
            + (d.status === 'complete' ? ' · draft complete' : ''),
        }));
      })
      .catch(() => setLive(s => ({ ...s, busy:false, ok:false, msg:'Sync failed' })))
      .finally(() => { liveRef.current.inFlight = false; });
  };

  // Keep the poller pointed at a fresh closure without restarting the interval
  // on every render (league/picks change constantly mid-draft).
  const syncRef = React.useRef(syncSleeperDraft);
  syncRef.current = syncSleeperDraft;
  React.useEffect(() => {
    if (!live.on) return undefined;
    syncRef.current();
    const timer = setInterval(() => syncRef.current(), 5000);
    return () => clearInterval(timer);
  }, [live.on]);

  const toggleLive = () => {
    if (live.on) { setLive(s => ({ ...s, on:false, msg:null })); return; }
    const start = () => setLive(s => ({ ...s, on:true, msg:'Connecting…' }));
    if (picks.length === 0) { start(); return; }
    confirmDialog({
      title: 'Follow the Sleeper draft live?',
      body: 'Sleeper becomes the source of truth: the picks on this board are replaced by whatever Sleeper reports, and keep updating every 5 seconds.',
      confirmLabel: 'Go live',
    }).then(ok => { if (ok) start(); });
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
    toast('Draft log exported.', 'ok');
  };

  // Everything that isn't "who do I take right now" lives behind one menu. The
  // header used to carry fourteen buttons at desktop width and a second,
  // divergent menu below it.
  const menuItems = [
    isMobile && { type:'label', label:'Panels' },
    isMobile && { label: `My team (${myPlayers.length})`, onClick: () => setShowMyTeamDrawer(true) },
    isMobile && { label: 'Picks & opponents', onClick: () => setShowOppDrawer(true) },
    isMobile && { type:'sep' },
    { type:'label', label:'Live draft' },
    canLiveSync && { label: live.on ? 'Stop following Sleeper' : 'Follow Sleeper live',
      hint: live.on ? 'on' : null, onClick: toggleLive },
    canLiveSync && !live.on && { label: 'Sync picks once', onClick: () => syncSleeperDraft({ manual:true }) },
    { label: 'Paste draft history', onClick: () => setShowPasteModal(true) },
    { type:'sep' },
    { type:'label', label:'View' },
    { label: 'Full draft board', onClick: () => setShowDraftBoard(true) },
    isDesktop && { label: showSidePanel ? 'Hide picks & opponents' : 'Show picks & opponents',
      onClick: () => setShowSidePanel(v => !v) },
    league.draftType === 'auction' && { label: 'Auction values', onClick: () => setShowAuction(true) },
    { type:'sep' },
    { type:'label', label:'Data' },
    { label: 'Engine settings', hint: `${tweaks.sims} sims`, onClick: () => setShowEngine(true) },
    { label: 'Pull player data', onClick: () => setShowPullModal(true) },
    { label: 'Export draft log (CSV)', disabled: picks.length === 0, onClick: handleExportLog },
    { label: 'Save snapshot to disk', onClick: handleSaveSnapshot },
    { label: 'Restore snapshot', onClick: handleRestoreSnapshot },
    { type:'sep' },
    { label: 'Clear all picks', tone:'danger', disabled: picks.length === 0, onClick: onResetPicks },
  ].filter(Boolean);

  return (
    <div style={{height:'100vh', display:'flex', flexDirection:'column', background:T.bg, overflow:'hidden'}}>
      <AppBar onBack={onBack} backLabel={isMobile ? '' : league.name} title="Draft room" compact
        badges={!isMobile ? <Badge label={SCORING_LABELS[league.scoringType]} color="blue" /> : null}>
        <div style={{
          background: isMyPick ? T.primary : T.surfaceAlt,
          border:`1.5px solid ${isMyPick ? T.primary : T.border}`,
          borderRadius:T.rsm, padding:'3px 10px', textAlign:'center', flexShrink:0,
        }}>
          <div style={{fontSize:9, fontWeight:800, letterSpacing:.5,
            color: isMyPick ? 'rgba(255,255,255,.85)' : T.muted}}>
            {isMyPick ? 'YOUR PICK' : `TEAM ${currentTeam}`}
          </div>
          <div className="da-num" style={{fontSize:11.5, fontWeight:700, color: isMyPick ? '#fff' : T.text}}>
            R{round} · {pickInRound}/{league.numTeams}
          </div>
        </div>

        {isTablet && (
          <>
            <Btn variant="secondary" size="sm" onClick={() => setShowMyTeamDrawer(true)}>
              Team ({myPlayers.length})
            </Btn>
            <Btn variant="secondary" size="sm" onClick={() => setShowOppDrawer(true)}>Picks</Btn>
          </>
        )}
        <Btn variant="secondary" size="sm" onClick={onUndoPick} disabled={picks.length === 0}>Undo</Btn>
        <Menu label="More" items={menuItems} />
      </AppBar>

      {!isMobile && <PickTicker league={league} picks={picks} playersById={playersById} />}

      <div style={{flex:1, display:'flex', minHeight:0}}>
        {isDesktop && (
          <MyTeamPanel league={league} myPlayers={myPlayers} round={round} hint={hint} onGetHint={handleGetHint} />
        )}

        <div style={{flex:1, display:'flex', flexDirection:'column', minWidth:0}}>
          <div style={{
            padding:'4px 12px', fontSize:11, color:T.muted, background:T.surface,
            borderBottom:`1px solid ${T.border}`, display:'flex', gap:8, alignItems:'center',
          }}>
            {suggest.err
              ? <span style={{color:T.red}}>Recommendations failed: {suggest.err}</span>
              : suggest.loading
                ? <span>Computing rollout…</span>
                : suggest.stale
                  ? <span>Board held — recomputes when your pick is up</span>
                  : <span>Rollout engine · {suggest.sims} sims per pick</span>}
            {canLiveSync && (live.on || live.msg) && (
              <span style={{
                paddingLeft:8, borderLeft:`1px solid ${T.border}`,
                color: live.ok === false ? T.red : live.on ? T.green : T.muted,
              }}>
                {live.on ? '● ' : ''}Sleeper: {live.msg || 'connecting…'}
              </span>
            )}
            <button onClick={handleRefreshRecs} title="Recompute recommendations now"
              style={{marginLeft:'auto', background:'none', border:`1px solid ${T.border}`, borderRadius:T.rxs,
                padding:'1px 7px', cursor:'pointer', color:T.muted, fontSize:10.5}}>
              Refresh
            </button>
          </div>

          <RecommendationBar scored={scored} myPlayers={myPlayers} league={league} oppData={oppData}
            onDraft={handleDraft} stale={suggest.stale && !suggest.err}
            untilMyTurn={untilMyTurn} loading={suggest.loading} />

          <PlayerList players={enriched} onDraft={handleDraft}
            showDrafted={showDrafted} onToggleDrafted={() => setShowDrafted(v => !v)} />
        </div>

        {isDesktop && showSidePanel && (
          <RightTabbedPanel league={league} picks={picks} playersById={playersById}
            oppData={oppData} picksMade={picks.length} onSetTeamMode={setTeamMode} />
        )}
      </div>

      {showMyTeamDrawer && (
        <Drawer title="My team" onClose={() => setShowMyTeamDrawer(false)}>
          <MyTeamPanel league={league} myPlayers={myPlayers} round={round}
            hint={hint} onGetHint={handleGetHint} fullWidth />
        </Drawer>
      )}

      {showOppDrawer && (
        <Drawer title="Picks & opponents" onClose={() => setShowOppDrawer(false)}>
          <RightTabbedPanel league={league} picks={picks} playersById={playersById}
            oppData={oppData} picksMade={picks.length} onSetTeamMode={setTeamMode} fullWidth />
        </Drawer>
      )}

      {showEngine && (
        <EngineSettingsModal league={league} tweaks={tweaks} setTweaks={setTweaks}
          adpNoise={adpNoise} onClose={() => setShowEngine(false)} />
      )}
      {showDraftBoard && (
        <DraftBoardModal league={league} picks={picks} allPlayers={enriched}
          onClose={() => setShowDraftBoard(false)} />
      )}
      {showPasteModal && (
        <PasteDraftModal league={league} picks={picks} allPlayers={enriched}
          onClose={() => setShowPasteModal(false)} onBatchDraft={handleBatchDraft} />
      )}
      {showPullModal && (
        <PullDataModal league={league} espnLeagueId={league.espnLeagueId}
          onClose={() => setShowPullModal(false)}
          onComplete={() => onRefreshPlayers && onRefreshPlayers()} />
      )}
      {showAuction && <AuctionModal league={league} onClose={() => setShowAuction(false)} />}
    </div>
  );
}

Object.assign(window, {
  VORPBadge, ScoreBadge, MyTeamPanel, RecommendationBar, PlayerList,
  DraftBoardModal, PasteDraftModal, EngineSettingsModal, DraftScreen, OpponentsPanel,
  PickTicker, RightTabbedPanel, matchQuickPickCandidates,
});
