// ─── WAIVER WIRE ──────────────────────────────────────────────────────────────
// The in-season half of the app, scoped to one league and completely separate
// from the draft room. It answers one question — who should I add, and who do
// I drop for them — using the same scoring and roster optimizer the draft
// engine uses, applied to the roster you actually own today.

// The roster the recommendations are measured against, laid out in lineup
// order so an "add" that only improves the bench reads differently from one
// that changes a starter.
function WaiverRosterPanel({ league, myPlayers, fullWidth = false }) {
  const lineup = buildLineup(myPlayers, league.rosterSlots);
  const needs = getRosterNeeds(myPlayers, league.rosterSlots);
  const starters = lineup.filter(r => !r.slot.bench);
  const bench = lineup.filter(r => r.slot.bench);

  const row = ({ slot, player }, i, dim) => (
    <div key={i} style={{
      display: 'flex', alignItems: 'center', gap: 9, padding: '6px 4px',
      borderBottom: `1px solid ${T.borderLight}`, minHeight: 36,
    }}>
      <span style={{
        fontSize: 10, fontWeight: 800, color: dim ? T.mutedLight : T.muted,
        width: 30, flexShrink: 0, letterSpacing: .3,
      }}>{slot.label}</span>
      {player ? (
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="da-ellipsis" style={{ fontSize: 12.5, fontWeight: 600, color: T.text }}>
            {player.name}
          </div>
          <div style={{ fontSize: 10.5, color: T.muted, display: 'flex', gap: 6 }}>
            <span>{player.pos} · {player.nflTeam || 'FA'}</span>
            {player.byeWeek ? <span style={{ color: T.mutedLight }}>BYE {player.byeWeek}</span> : null}
          </div>
        </div>
      ) : (
        <span style={{ fontSize: 12, color: T.mutedLight }}>empty</span>
      )}
      {player && player.projPts != null && (
        <span className="da-num" style={{ fontSize: 12, color: T.muted, flexShrink: 0 }}>
          {Math.round(player.projPts)}
        </span>
      )}
    </div>
  );

  return (
    <aside style={{
      width: fullWidth ? '100%' : 250, flexShrink: 0, background: T.surface,
      borderRight: fullWidth ? 'none' : `1px solid ${T.border}`,
      display: 'flex', flexDirection: 'column', overflowY: 'auto',
    }}>
      <div style={{ padding: '13px 14px', borderBottom: `1px solid ${T.border}` }}>
        {!fullWidth && <SectionLabel>My roster</SectionLabel>}
        <div style={{ fontSize: 12, color: T.muted, marginTop: fullWidth ? 0 : 3 }}>
          {myPlayers.length} of {lineup.length} slots filled
        </div>
      </div>
      <div style={{ padding: '4px 12px 10px', flex: 1 }}>
        <SectionLabel style={{ margin: '10px 0 2px' }}>Starters</SectionLabel>
        {starters.map((r, i) => row(r, i, false))}
        {bench.length > 0 && <SectionLabel style={{ margin: '14px 0 2px' }}>Bench</SectionLabel>}
        {bench.map((r, i) => row(r, `b${i}`, true))}
      </div>
      {needs.length > 0 && (
        <div style={{ padding: '10px 14px', borderTop: `1px solid ${T.border}` }}>
          <SectionLabel style={{ marginBottom: 6 }}>Thin at</SectionLabel>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {needs.map(pos => <PosBadge key={pos} pos={pos} />)}
          </div>
        </div>
      )}
    </aside>
  );
}

function signed(n, digits = 1) {
  const v = Number(n || 0);
  return `${v > 0 ? '+' : ''}${v.toFixed(digits)}`;
}

function WaiverScreen({ league, picks, allPlayers, onBack, onSyncLeague, onEditLeague }) {
  const [topN, setTopN]           = React.useState(15);
  const [posFilter, setPosFilter] = React.useState('ALL');
  const [data, setData]           = React.useState(null);
  const [loading, setLoading]     = React.useState(false);
  const [error, setError]         = React.useState(null);
  const [syncing, setSyncing]     = React.useState(false);
  const [showRoster, setShowRoster] = React.useState(false);
  const { isMobile } = useLayout();

  const linkedTo = league.sleeperLeagueId ? 'Sleeper'
    : league.espnLeagueId ? 'ESPN'
      : league.yahooLeagueKey ? 'Yahoo' : null;

  const playersWithProj = React.useMemo(
    () => withProjections(allPlayers, league), [allPlayers, league]);
  const myPlayers = React.useMemo(() => picks
    .filter(pk => pk.teamNum === league.draftPosition)
    .map(pk => playersWithProj.find(p => p.id === pk.playerId))
    .filter(Boolean), [picks, league.draftPosition, playersWithProj]);

  // Ask for the full window (the API caps at 30) and filter by position in the
  // browser, so switching position tabs is instant instead of a round trip.
  const scan = React.useCallback(() => {
    setLoading(true);
    setError(null);
    fetch('/api/free-agents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ leagues: [league], picks: { [league.id]: picks }, top: 30 }),
    })
      .then(r => r.json())
      .then(d => {
        if (d.error) { setError(d.error); setData(null); return; }
        setData((d.leagues || [])[0] || null);
      })
      .catch(err => setError(String(err)))
      .finally(() => setLoading(false));
  }, [league, picks]);

  React.useEffect(() => { scan(); }, [scan]);

  const sync = () => {
    setSyncing(true);
    onSyncLeague(league)
      .then(msg => toast(msg, 'ok'))
      .catch(err => toast(String(err && err.message ? err.message : err), 'error', 6000))
      .finally(() => setSyncing(false));
  };

  const allRows = (data && data.recommendations) || [];
  const rows = (posFilter === 'ALL' ? allRows : allRows.filter(r => r.pos === posFilter)).slice(0, topN);
  const counts = allRows.reduce((acc, r) => { acc[r.pos] = (acc[r.pos] || 0) + 1; return acc; }, {});

  const rosterPanel = <WaiverRosterPanel league={league} myPlayers={myPlayers} fullWidth={isMobile} />;

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: T.bg, overflow: 'hidden' }}>
      <AppBar
        onBack={onBack} backLabel={league.name}
        title="Waiver wire"
        subtitle={data ? `${data.available} available · ${myPlayers.length} on your roster` : 'Scanning the pool…'}
        compact>
        {isMobile && (
          <Btn variant="secondary" size="sm" onClick={() => setShowRoster(true)}>
            Roster ({myPlayers.length})
          </Btn>
        )}
        {linkedTo && (
          <Btn variant="secondary" size="sm" onClick={sync} disabled={syncing}>
            {syncing ? 'Syncing…' : `Sync from ${linkedTo}`}
          </Btn>
        )}
        <Btn variant="secondary" size="sm" onClick={scan} disabled={loading}>
          {loading ? 'Scanning…' : 'Refresh'}
        </Btn>
      </AppBar>

      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        {!isMobile && rosterPanel}

        <main style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <div style={{
            padding: '9px 14px', background: T.surface, borderBottom: `1px solid ${T.border}`,
            display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', flexShrink: 0,
          }}>
            <div className="da-no-scrollbar" style={{ display: 'flex', gap: 4, overflowX: 'auto', flex: 1, minWidth: 0 }}>
              {['ALL', ...POSITIONS].map(pos => {
                const on = posFilter === pos;
                const n = pos === 'ALL' ? allRows.length : (counts[pos] || 0);
                return (
                  <button key={pos} onClick={() => setPosFilter(pos)} disabled={n === 0 && pos !== 'ALL'}
                    style={{
                      padding: '4px 10px', borderRadius: T.rxs, flexShrink: 0, cursor: n || pos === 'ALL' ? 'pointer' : 'default',
                      border: `1.5px solid ${on ? T.primary : T.border}`,
                      background: on ? T.primaryLight : T.surface,
                      color: n === 0 && pos !== 'ALL' ? T.mutedLight : on ? T.primary : T.muted,
                      fontSize: 11.5, fontWeight: 700,
                    }}>{pos}{n > 0 ? ` ${n}` : ''}</button>
                );
              })}
            </div>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: T.muted, flexShrink: 0 }}>
              Show
              <Select value={topN} onChange={e => setTopN(parseInt(e.target.value, 10))}
                options={[5, 10, 15, 30].map(n => ({ value: n, label: `top ${n}` }))}
                style={{ width: 96, padding: '5px 8px', fontSize: 12 }} />
            </label>
          </div>

          <div style={{ flex: 1, overflowY: 'auto', padding: isMobile ? 12 : 18 }}>
            {error && <Note tone="error" style={{ marginBottom: 14 }}>{error}</Note>}

            {loading && !data && (
              <div className="loading-screen" style={{ height: 260 }}>
                <Spinner />
                <span>Ranking the free-agent pool…</span>
              </div>
            )}

            {!loading && myPlayers.length === 0 && (
              <EmptyState
                title="No roster loaded for this league"
                body={linkedTo
                  ? `Waiver picks are ranked against the players you already own. Pull your roster from ${linkedTo} and the board fills in.`
                  : 'Waiver picks are ranked against the players you already own. Link this league to ESPN, Yahoo, or Sleeper in league settings, or draft in the draft room, so the app knows your roster.'}
                action={linkedTo
                  ? <Btn onClick={sync} disabled={syncing}>{syncing ? 'Syncing…' : `Sync from ${linkedTo}`}</Btn>
                  : <Btn onClick={() => onEditLeague(league.id)}>Open league settings</Btn>} />
            )}

            {!loading && myPlayers.length > 0 && rows.length === 0 && (
              <EmptyState
                title="No upgrades available"
                body={posFilter === 'ALL'
                  ? 'Every free agent projects below what you already start. Check back after injuries or a bye week shakes the pool up.'
                  : `No ${posFilter} on the wire beats what you have. Try another position.`}
                action={posFilter === 'ALL' ? null : <Btn variant="secondary" onClick={() => setPosFilter('ALL')}>Show all positions</Btn>} />
            )}

            {myPlayers.length > 0 && rows.length > 0 && (
              <div className="da-card" style={{ overflow: 'hidden' }}>
                <div style={{ overflowX: 'auto' }}>
                  <table className="da-table">
                    <thead>
                      <tr>
                        <th style={{ width: 32 }}>#</th>
                        <th>Add</th>
                        <th style={{ width: 52 }}>Pos</th>
                        <th style={{ textAlign: 'right', width: 96 }} title="Points this add gains your starting lineup over a full season">
                          Starters
                        </th>
                        <th style={{ textAlign: 'right', width: 96 }} title="Points this add gains your whole roster, starters and bench">
                          Roster
                        </th>
                        <th style={{ width: 150 }}>Drop</th>
                        {!isMobile && <th>Why</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row, i) => (
                        <tr key={row.id}>
                          <td className="da-num" style={{ color: T.mutedLight, fontSize: 12 }}>{i + 1}</td>
                          <td>
                            <div style={{ fontWeight: 700, color: T.text }}>{row.name}</div>
                            <div style={{ fontSize: 11, color: T.muted, marginTop: 1 }}>
                              {row.nflTeam}
                              {row.byeWeek ? ` · BYE ${row.byeWeek}` : ''}
                              {row.adp ? ` · ADP ${row.adp}` : ''}
                            </div>
                            {isMobile && (
                              <div style={{ fontSize: 11, color: T.muted, marginTop: 4, lineHeight: 1.4 }}>{row.reason}</div>
                            )}
                          </td>
                          <td><PosBadge pos={row.pos} /></td>
                          <td className="da-num" style={{
                            textAlign: 'right', fontWeight: 800,
                            color: row.starterGain > 0 ? T.green : T.mutedLight,
                          }}>{signed(row.starterGain)}</td>
                          <td className="da-num" style={{
                            textAlign: 'right', fontWeight: 700,
                            color: row.rosterGain > 0 ? T.text : T.mutedLight,
                          }}>{signed(row.rosterGain)}</td>
                          <td style={{ color: row.drop ? T.text : T.muted, fontSize: 12.5 }}>
                            {row.drop
                              ? <span>{row.drop.name} <span style={{ color: T.muted }}>({row.drop.pos})</span></span>
                              : <span style={{ color: T.green }}>Open slot</span>}
                          </td>
                          {!isMobile && (
                            <td style={{ color: T.muted, fontSize: 12, lineHeight: 1.45 }}>{row.reason}</td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {myPlayers.length > 0 && rows.length > 0 && (
              <Note style={{ marginTop: 14 }}>
                <b style={{ color: T.text }}>Starters</b> is the season-point swing to your starting
                lineup — the number that decides most weeks. <b style={{ color: T.text }}>Roster</b>{' '}
                counts bench depth too, so a high roster gain with a flat starter gain is insurance,
                not an upgrade. A drop is only suggested when your roster is already full.
              </Note>
            )}
          </div>
        </main>
      </div>

      {showRoster && (
        <Drawer title="My roster" onClose={() => setShowRoster(false)} width={330}>
          {rosterPanel}
        </Drawer>
      )}
    </div>
  );
}

Object.assign(window, { WaiverScreen, WaiverRosterPanel });
