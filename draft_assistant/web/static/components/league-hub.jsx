// ─── LEAGUE HUB ───────────────────────────────────────────────────────────────
// The entry point for a single league. Draft day and the in-season waiver wire
// are separate destinations reached from here — they share a league but nothing
// else, so neither one is buried inside the other's chrome.

// Big navigation tile. Renders as a button so keyboard and screen readers get
// the same affordance the mouse does.
function HubTile({ title, description, meta, cta, onClick, disabled, accent, badge }) {
  return (
    <button className="da-card da-card-link" onClick={onClick} disabled={disabled}
      aria-label={`${cta} — ${title}`}
      style={{
        padding: 22, display: 'flex', flexDirection: 'column', gap: 10,
        opacity: disabled ? .55 : 1, cursor: disabled ? 'not-allowed' : 'pointer',
        borderTop: `3px solid ${accent || T.primary}`,
      }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 9, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 17, fontWeight: 700, color: T.text }}>{title}</span>
        {badge}
      </div>
      <div style={{ fontSize: 13, color: T.muted, lineHeight: 1.55 }}>{description}</div>
      <div style={{ flex: 1 }} />
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        gap: 10, paddingTop: 12, borderTop: `1px solid ${T.borderLight}`, width: '100%',
      }}>
        <span style={{ fontSize: 12, color: T.muted }}>{meta}</span>
        <span style={{ fontSize: 13, fontWeight: 700, color: disabled ? T.mutedLight : T.primary }}>
          {cta} →
        </span>
      </div>
    </button>
  );
}

function HubFact({ label, value }) {
  return (
    <div>
      <SectionLabel style={{ marginBottom: 3 }}>{label}</SectionLabel>
      <div style={{ fontSize: 13.5, fontWeight: 600, color: T.text }}>{value}</div>
    </div>
  );
}

function LeagueHub({ league, picks, playerCount, onBack, onOpenDraft, onOpenWaivers,
                     onEditLeague, onDeleteLeague, onSyncLeague, onPullData }) {
  const [syncing, setSyncing] = React.useState(false);
  const [showAuction, setShowAuction] = React.useState(false);
  const { isMobile } = useLayout();

  const myPicks = picks.filter(p => p.teamNum === league.draftPosition);
  const totalSlots = rosterTotal(league.rosterSlots);
  const linkedTo = league.sleeperLeagueId ? 'Sleeper'
    : league.espnLeagueId ? 'ESPN'
      : league.yahooLeagueKey ? 'Yahoo' : null;
  const isAuction = league.draftType === 'auction';
  const hasNames = (league.teamNames || []).some(Boolean);

  const sync = () => {
    setSyncing(true);
    onSyncLeague(league)
      .then(msg => toast(msg, 'ok'))
      .catch(err => toast(String(err && err.message ? err.message : err), 'error', 6000))
      .finally(() => setSyncing(false));
  };

  const remove = () => {
    confirmDialog({
      title: `Remove ${league.name}?`,
      body: 'The league settings and every pick recorded for it are deleted from this browser. Player data and other leagues are untouched.',
      confirmLabel: 'Remove league', tone: 'danger',
    }).then(ok => { if (ok) { onDeleteLeague(league.id); onBack(); } });
  };

  return (
    <div style={{ minHeight: '100vh', background: T.bg, display: 'flex', flexDirection: 'column' }}>
      <AppBar
        onBack={onBack} backLabel="Leagues"
        title={league.name}
        subtitle={`${league.platform} · ${league.numTeams} teams · ${SCORING_LABELS[league.scoringType]}`}
        badges={linkedTo ? <Badge label={`Linked to ${linkedTo}`} color="green" /> : null}>
        {linkedTo && (
          <Btn variant="secondary" size="sm" onClick={sync} disabled={syncing}>
            {syncing ? 'Syncing…' : 'Sync rosters'}
          </Btn>
        )}
        <Btn variant="secondary" size="sm" onClick={() => onEditLeague(league.id)}>League settings</Btn>
        <Menu label="More" items={[
          { label: 'Pull player data', hint: `${playerCount || 0} loaded`, onClick: onPullData },
          { type: 'sep' },
          { label: 'Remove league', tone: 'danger', onClick: remove },
        ]} />
      </AppBar>

      <div style={{ flex: 1, width: '100%', maxWidth: 940, margin: '0 auto', padding: isMobile ? '24px 16px' : '32px 24px' }}>
        {(playerCount || 0) === 0 && (
          <Note tone="warn" style={{ marginBottom: 20 }}>
            No player data is loaded yet, so the board and the waiver wire have nothing to rank.{' '}
            <button onClick={onPullData} style={{
              background: 'none', border: 'none', padding: 0, color: T.primary,
              fontWeight: 700, cursor: 'pointer', textDecoration: 'underline',
            }}>Pull player data</button> first.
          </Note>
        )}

        <h2 style={{ fontSize: 13, fontWeight: 800, color: T.muted, letterSpacing: .6, textTransform: 'uppercase', margin: '0 0 12px' }}>
          What do you want to do?
        </h2>

        <div style={{
          display: 'grid', gap: 16, marginBottom: 28,
          gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fit, minmax(280px, 1fr))',
        }}>
          <HubTile
            title="Draft room"
            accent={T.primary}
            badge={picks.length > 0 ? <Badge label="In progress" color="blue" /> : null}
            description="Live pick recommendations from the rest-of-draft simulation, a running pick ticker, and opponent predictions."
            meta={picks.length > 0
              ? `${picks.length} picks recorded · ${myPicks.length} yours`
              : `Not started · you pick #${league.draftPosition}`}
            cta={picks.length > 0 ? 'Resume draft' : 'Open draft room'}
            onClick={onOpenDraft} />

          <HubTile
            title="Waiver wire"
            accent={T.green}
            badge={myPicks.length === 0 ? <Badge label="Needs roster" color="amber" /> : null}
            description="In-season pickups ranked by what they add to your actual starting lineup, with the drop each add implies."
            meta={myPicks.length > 0
              ? `${myPicks.length} players on your roster`
              : linkedTo ? `Sync from ${linkedTo} to load your roster` : 'Add your roster first'}
            cta="Open waiver wire"
            onClick={onOpenWaivers} />

          {isAuction && (
            <HubTile
              title="Auction values"
              accent={T.amber}
              description="Dollar values for every player, scaled to this league's budget, roster, and scoring."
              meta={`$${league.auctionBudget || 200} per team`}
              cta="View values"
              onClick={() => setShowAuction(true)} />
          )}
        </div>

        <div className="da-card" style={{ padding: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
            <SectionLabel>League setup</SectionLabel>
            <Btn variant="subtle" size="sm" onClick={() => onEditLeague(league.id)}>Edit</Btn>
          </div>
          <div style={{
            display: 'grid', gap: 18,
            gridTemplateColumns: isMobile ? 'repeat(2, 1fr)' : 'repeat(4, 1fr)',
          }}>
            <HubFact label="Scoring" value={SCORING_LABELS[league.scoringType]} />
            <HubFact label="Teams" value={league.numTeams} />
            <HubFact label="Draft" value={isAuction ? `Auction · $${league.auctionBudget || 200}` : `Snake · pick #${league.draftPosition}`} />
            <HubFact label="Roster" value={`${totalSlots} slots`} />
          </div>
          <div style={{ marginTop: 16, paddingTop: 14, borderTop: `1px solid ${T.borderLight}`, fontSize: 12.5, color: T.muted }}>
            {['QB', 'RB', 'WR', 'TE', 'K', 'DST'].map(pos => `${pos} ${league.rosterSlots[pos] || 0}`).join(' · ')}
            {league.rosterSlots.FLEX ? ` · FLEX ${league.rosterSlots.FLEX}` : ''}
            {league.rosterSlots.BN ? ` · Bench ${league.rosterSlots.BN}` : ''}
          </div>
          {!hasNames && !isAuction && (
            <Note style={{ marginTop: 14 }}>
              Team names and draft order aren't set. The draft room works without them, but naming
              the seats makes the pick ticker and opponent panel readable.{' '}
              <button onClick={() => onEditLeague(league.id)} style={{
                background: 'none', border: 'none', padding: 0, color: T.primary,
                fontWeight: 700, cursor: 'pointer', textDecoration: 'underline',
              }}>Set draft order</button>
            </Note>
          )}
        </div>
      </div>

      {showAuction && <AuctionModal league={league} onClose={() => setShowAuction(false)} />}
    </div>
  );
}

Object.assign(window, { LeagueHub });
