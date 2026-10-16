// ─── WAIVER WIRE ──────────────────────────────────────────────────────────────
// The in-season half of the app, scoped to one league and completely separate
// from the draft room. It answers one question — who should I add, and who do
// I drop for them — using the same scoring and roster optimizer the draft
// engine uses, applied to the roster you actually own today.

// The roster the recommendations are measured against, laid out in lineup
// order so an "add" that only improves the bench reads differently from one
// that changes a starter.
function WaiverRosterPanel({ league, myPlayers, fullWidth = false, asOf = null }) {
  const lineup = buildLineup(myPlayers, league.rosterSlots);
  const needs = getRosterNeeds(myPlayers, league.rosterSlots);
  const starters = lineup.filter(r => !r.slot.bench);
  const bench = lineup.filter(r => r.slot.bench);
  const assigned = new Set(lineup.filter(r => r.player).map(r => r.player.id));
  const reserves = myPlayers.filter(player => !assigned.has(player.id));

  const row = ({ slot, player }, i, dim) => (
    <div key={i} style={{
      display: 'flex', alignItems: 'center', gap: 9, padding: '6px 4px',
      borderBottom: `1px solid ${T.borderLight}`, minHeight: 36,
    }}>
      <span style={{
        fontSize: 11, fontWeight: 800, color: dim ? T.mutedLight : T.muted,
        width: 30, flexShrink: 0, letterSpacing: .3,
      }}>{slot.label}</span>
      {player ? (
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="da-ellipsis" style={{ fontSize: 12.5, fontWeight: 600, color: T.text }}>
            {player.name}
          </div>
          <div style={{ fontSize: 11, color: T.muted, display: 'flex', gap: 6 }}>
            <span>{player.pos} · {player.nflTeam || 'FA'}</span>
            {player.byeWeek ? <span style={{ color: T.mutedLight }}>BYE {player.byeWeek}</span> : null}
            {player.unmatched && <span>No projection yet</span>}
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
          {myPlayers.length} players rostered · {lineup.length} lineup and bench slots
        </div>
        {/* On a phone this panel is a drawer that covers the screen's own warning. */}
        {asOf && (
          <div style={{ fontSize: 11.5, fontWeight: 700, color: T.amber, marginTop: 3 }}>
            As of {asOf} — the live sync failed
          </div>
        )}
      </div>
      <div style={{ padding: '4px 12px 10px', flex: 1 }}>
        <SectionLabel style={{ margin: '10px 0 2px' }}>Starters</SectionLabel>
        {starters.map((r, i) => row(r, i, false))}
        {bench.length > 0 && <SectionLabel style={{ margin: '14px 0 2px' }}>Bench</SectionLabel>}
        {bench.map((r, i) => row(r, `b${i}`, true))}
        {reserves.length > 0 && <SectionLabel style={{ margin: '14px 0 2px' }}>Other rostered players</SectionLabel>}
        {reserves.map((player, i) => row({ slot: { label: 'RES' }, player }, `r${i}`, true))}
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

function WaiverScreen({ league, picks, allPlayers, onBack, onSyncLeague, onEditLeague, onRefreshPlayers }) {
  const [topN, setTopN]           = React.useState(15);
  const [posFilter, setPosFilter] = React.useState('ALL');
  // "This week" answers the start/sit question; "Rest of season" answers the
  // stash question. They rank differently often enough that one number would
  // be misleading, so the engine returns both and this picks between them.
  const [horizon, setHorizon]     = React.useState('weekly');
  const [week, setWeek]           = React.useState(null); // null = whatever the server considers current
  const [data, setData]           = React.useState(null);
  const [loading, setLoading]     = React.useState(false);
  const [error, setError]         = React.useState(null);
  const [syncing, setSyncing]     = React.useState(false);
  const [rosterSnapshot, setRosterSnapshot] = React.useState(null);
  // Why the live sync failed — set only while `rosterSnapshot` is the league's
  // saved snapshot standing in for it. Null whenever the rosters are live.
  const [syncFailure, setSyncFailure] = React.useState(null);
  const [updating, setUpdating]   = React.useState(false);
  const [showRoster, setShowRoster] = React.useState(false);
  const { isMobile, isDesktop }   = useLayout();

  const linkedTo = league.sleeperLeagueId ? 'Sleeper'
    : league.espnLeagueId ? 'ESPN'
      : league.yahooLeagueKey ? 'Yahoo' : null;
  const rosterKey = rosterSyncKey(league);
  // Every visit verifies live ownership before ranking; a saved draft must
  // never decide who is available in a linked league, and an older roster
  // snapshot only may when that sync fails — and then never unlabelled.
  const rosterReady = !linkedTo || Boolean(rosterSnapshot && rosterSnapshot.leagueKey === rosterKey);
  const rosterPicks = React.useMemo(() => linkedTo
    ? (rosterReady ? rosterSnapshot.picks : []) : picks,
  [linkedTo, rosterReady, rosterSnapshot, picks]);
  // The label every stale ranking carries: when the rosters on screen were true.
  const rostersAsOf = linkedTo && rosterReady && syncFailure
    ? new Date(rosterSnapshot.syncedAt).toLocaleString() : null;

  const playersWithProj = React.useMemo(
    () => withProjections(allPlayers, league), [allPlayers, league]);
  const myPlayers = React.useMemo(() => ((data && data.rosterEntries) || rosterPicks)
    .filter(pk => pk.teamNum === league.draftPosition)
    .map(pk => playersWithProj.find(p => p.id === pk.playerId) || {
      id: pk.playerId, name: pk.sourceName || pk.playerId,
      pos: pk.sourcePosition || '?', nflTeam: pk.sourceTeam || '',
      projPts: null, unmatched: true,
    }), [data, rosterPicks, league.draftPosition, playersWithProj]);

  // Ask for the full window (the API caps at 30) and filter by position in the
  // browser, so switching position tabs is instant instead of a round trip.
  //
  // `week` stays the *user's* choice and is never written back from the
  // response: a scan that adopted the server's week re-armed this effect and
  // ran the whole free-agent ranking (top_n=None over the full pool) a second
  // time on every open. The resolved week is read off `data` instead.
  const scanSeq = React.useRef(0);
  const scan = React.useCallback(() => {
    if (!rosterReady) return;
    const seq = ++scanSeq.current;
    setLoading(true);
    setError(null);
    setData(null);
    fetch('/api/free-agents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        leagues: [league], rosters: { [league.id]: rosterPicks }, top: 30,
        ...(week ? { week } : {}),
      }),
    })
      .then(r => r.json())
      .then(d => {
        // A slower earlier scan must not overwrite a newer one's answer.
        if (seq !== scanSeq.current) return;
        if (d.error) { setError(d.error); setData(null); return; }
        // contextAsOf / contextStale / week are response-level, not per-league.
        const row = (d.leagues || [])[0] || null;
        setData(row ? { ...row, week: d.week, contextAsOf: d.contextAsOf, contextStale: d.contextStale } : null);
      })
      .catch(err => { if (seq === scanSeq.current) { setError(String(err)); setData(null); } })
      .finally(() => { if (seq === scanSeq.current) setLoading(false); });
  }, [league, rosterPicks, rosterReady, week]);

  // Typing "1" then "2" in the week box shouldn't cost two full rankings.
  React.useEffect(() => {
    if (!rosterReady) return;
    const timer = setTimeout(scan, 150);
    return () => { clearTimeout(timer); scanSeq.current++; };
  }, [scan, rosterReady]);

  // A re-rank that waits on the network first — a news refresh, a bye-week
  // reload — lands in a later render than the click that started it, and the
  // `scan` that click closed over still holds its rosters, week and league.
  // Pressed while the visit's own sync was running, that scan is the not-ready
  // no-op, so the list was never re-ranked against the board that came back.
  // Pressed while a failed sync's saved rosters were on screen and followed by
  // a Retry that succeeded, it ranked the saved rosters again — last, and with
  // the "rosters as of" label already cleared. Always run the latest one.
  const latestScan = React.useRef(scan);
  latestScan.current = scan;
  const rescan = () => latestScan.current();
  // Re-rank once the board is back: a player's week off changes what he is
  // worth this week, and the list on screen predates it.
  const reloadBoardAndRescan = () => Promise.resolve(onRefreshPlayers && onRefreshPlayers()).then(rescan);

  const syncSeq = React.useRef(0);
  // The league as of the latest render. A sync can fail long after it started,
  // and the snapshot worth falling back to is the one saved by then — the hub's
  // own sync may have landed while this one was still in flight.
  const latestLeague = React.useRef(league);
  latestLeague.current = league;
  const runSync = (announce = true) => {
    const seq = ++syncSeq.current;
    scanSeq.current++;
    setRosterSnapshot(null);
    setSyncFailure(null);
    setData(null);
    setError(null);
    setLoading(false);
    setSyncing(true);
    return onSyncLeague(league)
      .then(result => {
        if (seq !== syncSeq.current) return;
        // Whatever a sync that succeeded returns is the ownership record, zero
        // players included. Only a failure may reach for the saved snapshot.
        setRosterSnapshot(result.rosterSnapshot);
        if (announce) toast(result.message, 'ok');
      })
      .catch(err => {
        // A superseded sync failing late must not flip the newer result into
        // the fallback, and one that outlives the screen must not set state.
        if (seq !== syncSeq.current) return;
        const reason = String(err && err.message ? err.message : err);
        const saved = fallbackRosterSnapshot(latestLeague.current);
        if (saved) {
          // A provider outage used to leave nothing to rank. Rank against the
          // rosters last saved for this league instead — the render below
          // labels every part of the screen with how old they are.
          setRosterSnapshot(saved);
          setSyncFailure(reason);
          if (announce) toast(`Could not sync current rosters from ${linkedTo}. ${reason}`, 'error', 6000);
          return;
        }
        const message = `Could not sync current rosters from ${linkedTo}. `
          + `${reason} `
          + 'Check the league connection in League settings, then retry Sync.';
        setData(null);
        setError(message);
        if (announce) toast(message, 'error', 6000);
      })
      .finally(() => { if (seq === syncSeq.current) setSyncing(false); });
  };

  React.useEffect(() => {
    if (linkedTo) runSync(false);
    // Snapshot writes change the league object; only a connection or seat-map
    // change should repeat this initial sync, not the snapshot it just saved.
    return () => { syncSeq.current++; scanSeq.current++; };
  }, [rosterKey, linkedTo, onSyncLeague]);

  // What the week box shows and what "Refresh news" asks for: the user's pick
  // if they made one, otherwise whatever week the server said it ranked.
  const effectiveWeek = week != null ? week : (data && data.week) || null;

  // Poll one refresh task to completion. Every wait is *inside* the returned
  // promise chain — a `setTimeout(poll, …)` that drops the next promise on the
  // floor means only the first iteration can ever report a failure, and the
  // button sits on "Updating…" forever when a later one throws.
  const pollRefreshTask = (taskId, attempts = 0) =>
    fetch(`/api/task/${taskId}`)
      .then(r => r.json())
      .then(task => {
        if (task.status === 'done') return;
        // A pruned or unknown task id answers 404 with an error and no status;
        // that is terminal, not something to keep polling for two minutes.
        if (!task.status || task.status === 'error') {
          throw new Error(task.error || 'Update refresh failed');
        }
        if (attempts >= 120) throw new Error('Update refresh timed out');
        return new Promise(resolve => setTimeout(resolve, 1000))
          .then(() => pollRefreshTask(taskId, attempts + 1));
      });

  // Pull fresh injury / depth-chart / snap / trending signals, then re-rank.
  const refreshUpdates = () => {
    setUpdating(true);
    setError(null);
    fetch('/api/context/refresh', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      // Omitting the key lets the server pick the current week; sending an
      // explicit null is a 400.
      body: JSON.stringify({ force: true, ...(effectiveWeek ? { week: effectiveWeek } : {}) }),
    })
      .then(r => r.json())
      .then(started => {
        if (started.error) throw new Error(started.error);
        if (!started.taskId) throw new Error('Update refresh did not start');
        return pollRefreshTask(started.taskId);
      })
      .then(() => { toast('Player updates refreshed.', 'ok'); rescan(); })
      .catch(err => toast(String(err.message || err), 'error', 6000))
      .finally(() => setUpdating(false));
  };

  // The waiver wire ranks pickups against *your* starters, so a sync with no
  // seat marked leaves this screen with an empty roster and no way to tell
  // that the sync itself worked. Only the confirm branch syncs.
  const sync = () => {
    if (league.draftType === 'auction' || league.draftPosition) { runSync(); return; }
    confirmDialog({
      title: 'No team is marked as yours',
      body: `Nothing in ${league.name} is set as your seat yet, and synced players are attributed by seat — `
        + 'so the waiver wire would have no roster to rank pickups against. '
        + 'Set your seat first in League settings → Draft order, then sync.',
      confirmLabel: 'Sync anyway',
      cancelLabel: 'Not yet',
    }).then(ok => { if (ok) runSync(); });
  };

  const allRows = (data && (horizon === 'weekly' ? data.weeklyRecommendations : data.rosRecommendations))
    || (data && data.recommendations) || [];
  const rows = (posFilter === 'ALL' ? allRows : allRows.filter(r => r.pos === posFilter)).slice(0, topN);
  const counts = allRows.reduce((acc, r) => { acc[r.pos] = (acc[r.pos] || 0) + 1; return acc; }, {});

  const rosterPanel = <WaiverRosterPanel league={league} myPlayers={myPlayers} fullWidth={isMobile} asOf={rostersAsOf} />;

  const status = data
    ? `${horizon === 'weekly' ? `Week ${data.week || week || '—'}` : 'Rest of season'} · ${data.available} available · ${myPlayers.length} on your roster`
    : syncing ? 'Syncing current league rosters…' : error ? 'Roster scan needs attention' : 'Scanning the pool…';
  // The age of the rosters leads, because the subtitle truncates from the end
  // and this is the part a scrolled list still has to say.
  const subtitle = rostersAsOf ? `Rosters as of ${rostersAsOf} · ${status}` : status;

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: T.bg, overflow: 'hidden' }}>
      {/* A phone header holds a back arrow, the title and three buttons, and
          nothing more: with the league name beside the arrow and the provider
          spelled out on Sync, the title was squeezed to nothing and the back
          label ran under the Roster button. The draft room drops its back
          label on a phone for the same reason. */}
      <AppBar
        onBack={onBack} backLabel={isMobile ? '' : league.name}
        title="Waiver wire"
        subtitle={subtitle}
        compact>
        {isMobile && (
          <Btn variant="secondary" size="sm" onClick={() => setShowRoster(true)}>
            Roster ({myPlayers.length})
          </Btn>
        )}
        {linkedTo && (
          <Btn variant="secondary" size="sm" onClick={sync} disabled={syncing}
            aria-label={syncing ? undefined : `Sync from ${linkedTo}`}>
            {syncing ? 'Syncing…' : isMobile ? 'Sync' : `Sync from ${linkedTo}`}
          </Btn>
        )}
        <Btn variant="secondary" size="sm" onClick={scan} disabled={loading || syncing || !rosterReady}>
          {loading ? 'Scanning…' : 'Refresh'}
        </Btn>
      </AppBar>

      {/* Outside the scrolling list on purpose: it has to stay on screen for as
          long as anything below is ranked against rosters that may have moved. */}
      {rostersAsOf && (
        <Note tone="warn" style={{
          flexShrink: 0, borderRadius: 0, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
        }}>
          <span style={{ flex: '1 1 260px' }}>
            <b>Could not sync current rosters from {linkedTo}.</b> Showing rosters as
            of <b>{rostersAsOf}</b> — adds, drops and trades since then are not reflected, so a
            player listed here may already be on a roster. Sync error: {syncFailure}
          </span>
          <Btn variant="secondary" size="sm" onClick={sync}>Retry sync</Btn>
        </Note>
      )}

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

          <div style={{
            padding: '8px 14px', background: T.surface, borderBottom: `1px solid ${T.border}`,
            display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', flexShrink: 0,
          }}>
            <div role="group" aria-label="Ranking horizon" style={{ display: 'inline-flex', gap: 5 }}>
              {[['weekly', 'This week'], ['ros', 'Rest of season']].map(([value, label]) => (
                <Chip key={value} on={horizon === value} onClick={() => setHorizon(value)}
                  style={{ fontSize: 12.5, padding: '5px 13px' }}>{label}</Chip>
              ))}
            </div>

            {horizon === 'weekly' && (
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: T.muted }}>
                Week
                <Input type="number" min={1} max={18} value={effectiveWeek || ''}
                  aria-label="NFL week"
                  onChange={e => setWeek(Math.max(1, Math.min(parseInt(e.target.value, 10) || 1, 18)))}
                  style={{ width: 64, padding: '5px 8px', fontSize: 12 }} />
              </label>
            )}

            <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 11.5, color: data && data.contextStale ? T.amber : T.mutedLight }}>
                {data && data.contextAsOf
                  ? `Player news as of ${new Date(data.contextAsOf).toLocaleString()}${data.contextStale ? ' · may be stale' : ''}`
                  : 'Player news not refreshed yet'}
              </span>
              <Btn variant="secondary" size="sm" onClick={refreshUpdates} disabled={updating || syncing || !rosterReady}>
                {updating ? 'Updating…' : 'Refresh news'}
              </Btn>
            </div>
          </div>

          <div style={{ flex: 1, overflowY: 'auto', padding: isMobile ? 12 : 18 }}>
            <ByeWeeksNotice players={allPlayers} style={{ marginBottom: 14 }} onLoaded={reloadBoardAndRescan} />
            {error && <Note tone="error" style={{ marginBottom: 14 }}>{error}</Note>}

            {(loading || syncing) && !data && (
              <div className="loading-screen" style={{ height: 260 }}>
                <Spinner />
                <span>{syncing ? 'Syncing every team’s current roster…' : 'Ranking the free-agent pool…'}</span>
              </div>
            )}

            {!loading && !syncing && myPlayers.length === 0 && (
              <EmptyState
                title="No roster loaded for this league"
                body={linkedTo
                  ? `Waiver picks are ranked against the players you already own. Pull your roster from ${linkedTo} and the board fills in.`
                  : 'Waiver picks are ranked against the players you already own. Link this league to ESPN, Yahoo, or Sleeper in league settings, or draft in the draft room, so the app knows your roster.'}
                action={linkedTo
                  ? <Btn onClick={sync} disabled={syncing}>{syncing ? 'Syncing…' : `Sync from ${linkedTo}`}</Btn>
                  : <Btn onClick={() => onEditLeague(league.id)}>Open league settings</Btn>} />
            )}

            {!loading && !syncing && !error && data && myPlayers.length > 0 && rows.length === 0 && (
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
                        <th style={{ textAlign: 'right', width: 70 }}
                          title={horizon === 'weekly'
                            ? 'Projected points for this player in the selected week'
                            : 'Projected points for this player over the rest of the season'}>
                          {horizon === 'weekly' ? 'Wk pts' : 'ROS pts'}
                        </th>
                        <th style={{ textAlign: 'right', width: 84 }} title="Points this add gains your starting lineup">
                          Starters
                        </th>
                        {isDesktop && (
                          <th style={{ textAlign: 'right', width: 84 }} title="Points this add gains your whole roster, starters and bench">
                            Roster
                          </th>
                        )}
                        <th style={{ textAlign: 'center', width: 60 }}
                          title="Momentum from the news feed - trending adds, snap share, and depth-chart moves">
                          Trend
                        </th>
                        <th style={{ width: 140 }}>Drop</th>
                        {!isMobile && <th>Why</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row, i) => (
                        <tr key={row.id}>
                          <td className="da-num" style={{ color: T.mutedLight, fontSize: 12 }}>{i + 1}</td>
                          <td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <span style={{ fontWeight: 700, color: T.text }}>{row.name}</span>
                              <AvailabilityChip status={row.availability} />
                            </div>
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
                          <td className="da-num" style={{ textAlign: 'right', fontWeight: 700, color: T.text }}>
                            {Number(row.points || 0).toFixed(1)}
                          </td>
                          <td className="da-num" style={{
                            textAlign: 'right', fontWeight: 800,
                            color: row.starterGain > 0 ? T.green : T.mutedLight,
                          }}>{signed(row.starterGain)}</td>
                          {isDesktop && (
                            <td className="da-num" style={{
                              textAlign: 'right', fontWeight: 700,
                              color: row.rosterGain > 0 ? T.text : T.mutedLight,
                            }}>{signed(row.rosterGain)}</td>
                          )}
                          <td className="da-num" style={{
                            textAlign: 'center', fontWeight: 800,
                            color: row.urgency > 0 ? T.green : row.urgency < 0 ? T.red : T.mutedLight,
                          }} title="Positive means the news is trending this player up">
                            {row.urgency > 0 ? `+${row.urgency}` : (row.urgency || '—')}
                          </td>
                          <td style={{ color: row.drop ? T.text : T.muted, fontSize: 12.5 }}>
                            {row.drop
                              ? <span>{row.drop.name} <span style={{ color: T.muted }}>({row.drop.pos})</span></span>
                              : <span style={{ color: T.green }}>Open slot</span>}
                          </td>
                          {!isMobile && (
                            <td style={{ color: T.muted, fontSize: 12, lineHeight: 1.45 }}>
                              <div>{row.reason}</div>
                              {playerNewsSignals(row.signals).slice(0, 2).map((sig, si) => (
                                <div key={si} title={`${sig.source} · ${sig.observed_at}`}
                                  style={{ fontSize: 11, marginTop: 2, color: T.primary }}>
                                  {sig.attribution || sig.source}: {String(sig.kind).replace(/_/g, ' ')} {sig.value}
                                </div>
                              ))}
                              {horizon === 'weekly' && row.weeklyProjectionOrigin && (
                                <div style={{ fontSize: 11, marginTop: 2, color: T.mutedLight }}>
                                  {row.weeklyProjectionOrigin}
                                </div>
                              )}
                            </td>
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
                <b style={{ color: T.text }}>Starters</b> is the point swing to your starting lineup —
                the number that decides most weeks. <b style={{ color: T.text }}>Roster</b> counts bench
                depth too, so a high roster gain with a flat starter gain is insurance, not an upgrade.
                <b style={{ color: T.text }}> Trend</b> and the blue notes come from the news feed
                (injuries, depth chart, snap share, trending adds) — that is what moves a player between
                refreshes. A drop is only suggested when your roster is already full.
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
