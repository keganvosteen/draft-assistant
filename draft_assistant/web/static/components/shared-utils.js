// Shared frontend helpers. Loaded before opponent-model.js and React components.

// stdPts = standard (0 pt/rec) scoring from the backend; recPts = full
// 1-pt-per-reception bonus. K/DST stdPts are already computed server-side with
// the league's scoring config.
function calcCustomProjection(player, cs) {
  const s = player.stats;
  if (!s) return player.stdPts + player.recPts * ((cs && cs.reception) || 0);
  const perYd = denom => (denom ? 1 / denom : 0);
  const fumbleLost = cs.fumbleLost != null ? cs.fumbleLost : -2;
  const fumbleAny  = cs.fumble     != null ? cs.fumble     : 0;
  const twoPt      = cs.twoPt      || 0;
  const pts =
    (s.pass_yd  || 0) * perYd(cs.passYds) +
    (s.pass_td  || 0) * (cs.passTD  || 0) +
    (s.pass_int || 0) * (cs.passInt || 0) +
    (s.sack_taken || 0) * (cs.sackTaken || 0) +
    (s.rush_yd  || 0) * perYd(cs.rushYds) +
    (s.rush_td  || 0) * (cs.rushTD  || 0) +
    (s.rec_yd   || 0) * perYd(cs.recYds) +
    (s.rec_td   || 0) * (cs.recTD   || 0) +
    (s.rec      || 0) * (cs.reception || 0) +
    ((s.pass_2pt || 0) + (s.rush_2pt || 0) + (s.rec_2pt || 0)) * twoPt +
    (s.fum_ret_td   || 0) * (cs.fumRetTD || 0) +
    (s.fumbles_total || 0) * fumbleAny +
    (s.fumbles  || 0) * fumbleLost;
  return Math.round(pts * 10) / 10;
}

function calcProjection(player, scoringType, customScoring) {
  if (player.pos === 'K' || player.pos === 'DST') return player.stdPts;
  if (scoringType === 'standard') return player.stdPts;
  if (scoringType === 'ppr')      return player.stdPts + player.recPts;
  if (scoringType === 'half-ppr') return Math.round((player.stdPts + player.recPts * 0.5) * 10) / 10;
  if (scoringType === 'custom')   return calcCustomProjection(player, customScoring || {});
  return player.stdPts;
}

function effectiveImportedScoring(league) {
  if (!league.importedScoring) return null;
  const scoring = { ...league.importedScoring };
  if (league.scoringType === 'standard') scoring.rec = 0;
  if (league.scoringType === 'half-ppr') scoring.rec = 0.5;
  if (league.scoringType === 'ppr') scoring.rec = 1;
  if (league.scoringType === 'custom') {
    const cs = league.customScoring || {};
    const perYd = denom => (denom ? 1 / denom : 0);
    const twoPt = +(cs.twoPt || 0);
    Object.assign(scoring, {
      pass_yd: perYd(cs.passYds), pass_td: +(cs.passTD || 0), pass_int: +(cs.passInt || 0),
      rush_yd: perYd(cs.rushYds), rush_td: +(cs.rushTD || 0),
      rec_yd: perYd(cs.recYds), rec_td: +(cs.recTD || 0), rec: +(cs.reception || 0),
      pass_2pt: twoPt, rush_2pt: twoPt, rec_2pt: twoPt,
      fum_ret_td: +(cs.fumRetTD || 0), fumbles_total: +(cs.fumble || 0),
      fumbles: cs.fumbleLost == null ? (scoring.fumbles || -2) : +cs.fumbleLost,
    });
    if (cs.sackTaken) scoring.sack_taken = +cs.sackTaken;
  }
  return scoring;
}

function calcImportedProjection(player, league) {
  const scoring = effectiveImportedScoring(league);
  if (!scoring || !player.stats) return null;
  const points = Object.entries(scoring).reduce(
    (total, [stat, weight]) => total + (+(player.stats[stat] || 0) * (+weight || 0)), 0);
  return Math.round(points * 10) / 10;
}

function withProjections(players, league) {
  return players.map(p => {
    const imported = calcImportedProjection(p, league);
    return { ...p, projPts: imported == null
      ? calcProjection(p, league.scoringType, league.customScoring)
      : imported };
  });
}

var FLEX_TYPES_JS = {
  FLEX:      { label: 'FLX', elig: ['RB','WR','TE'] },
  WRTE:      { label: 'W/T', elig: ['WR','TE'] },
  RBWR:      { label: 'R/W', elig: ['RB','WR'] },
  SUPERFLEX: { label: 'SF',  elig: ['QB','RB','WR','TE'] },
  OP:        { label: 'OP',  elig: ['QB','RB','WR','TE'] },
};

function slotCount(rosterSlots, key, dflt) {
  return rosterSlots[key] == null ? dflt : rosterSlots[key];
}

function flexExpectation(rosterSlots) {
  const add = { QB: 0, RB: 0, WR: 0, TE: 0 };
  Object.keys(FLEX_TYPES_JS).forEach(fk => {
    const n = rosterSlots[fk] || 0;
    if (!n) return;
    const elig = FLEX_TYPES_JS[fk].elig;
    const w = {}; let tot = 0;
    elig.forEach(pos => { w[pos] = (pos === 'RB' || pos === 'WR') ? 1.0 : 0.4; tot += w[pos]; });
    elig.forEach(pos => { add[pos] += n * w[pos] / tot; });
  });
  return add;
}

function withVORP(players, league) {
  const { numTeams, rosterSlots } = league;
  const fx = flexExpectation(rosterSlots);
  const repRank = {
    QB:  Math.floor(numTeams * (slotCount(rosterSlots,'QB',1) + fx.QB) + 1),
    RB:  Math.floor(numTeams * (slotCount(rosterSlots,'RB',2) + fx.RB) + 1),
    WR:  Math.floor(numTeams * (slotCount(rosterSlots,'WR',2) + fx.WR) + 1),
    TE:  Math.floor(numTeams * (slotCount(rosterSlots,'TE',1) + fx.TE) + 1),
    K:   Math.floor(numTeams * slotCount(rosterSlots,'K',1) + 1),
    DST: Math.floor(numTeams * slotCount(rosterSlots,'DST',1) + 1),
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

// Draftable roster size. IR is a roster slot but never a draft round, so
// counting it inflated "N slots" on the league cards and drew a phantom extra
// round on the pick ticker.
function rosterTotal(rosterSlots) {
  return Object.entries(rosterSlots || {})
    .reduce((sum, [key, value]) => key === 'IR' ? sum : sum + (value || 0), 0);
}

// Slot a roster into its lineup: starters first (position slots, then the
// tightest flex first so a WR/TE slot isn't consumed by a player only the
// wide-open FLEX could have taken), then bench. Shared by the draft room's
// team panel and the waiver wire's roster panel so both agree on what a
// "starter" is.
function buildLineup(players, rosterSlots) {
  const slots = rosterSlots || {};
  const defs = [];
  const push = (n, def) => { for (let i = 0; i < (n || 0); i++) defs.push(def); };
  push(slots.QB, { label: 'QB', pos: 'QB' });
  push(slots.RB, { label: 'RB', pos: 'RB' });
  push(slots.WR, { label: 'WR', pos: 'WR' });
  push(slots.TE, { label: 'TE', pos: 'TE' });
  Object.keys(FLEX_TYPES_JS)
    .filter(fk => (slots[fk] || 0) > 0)
    .sort((a, b) => FLEX_TYPES_JS[a].elig.length - FLEX_TYPES_JS[b].elig.length)
    .forEach(fk => push(slots[fk], { label: FLEX_TYPES_JS[fk].label, pos: 'FLEX', elig: FLEX_TYPES_JS[fk].elig }));
  push(slots.K, { label: 'K', pos: 'K' });
  push(slots.DST, { label: 'DST', pos: 'DST' });
  push(slots.BN, { label: 'BN', pos: null, bench: true });

  const remaining = players.slice();
  return defs.map(slot => {
    if (!slot.pos) return { slot, player: remaining.shift() || null };
    if (slot.pos === 'FLEX') {
      const elig = new Set(slot.elig || ['RB', 'WR', 'TE']);
      const idx = remaining.findIndex(p => elig.has(p.pos));
      return { slot, player: idx >= 0 ? remaining.splice(idx, 1)[0] : null };
    }
    const idx = remaining.findIndex(p => p.pos === slot.pos);
    return { slot, player: idx >= 0 ? remaining.splice(idx, 1)[0] : null };
  });
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
  const fx = flexExpectation(rosterSlots);
  const maxByPos = {
    QB:  slotCount(rosterSlots,'QB',1) + Math.round(fx.QB),
    RB:  slotCount(rosterSlots,'RB',2) + Math.ceil(fx.RB),
    WR:  slotCount(rosterSlots,'WR',2) + Math.ceil(fx.WR),
    TE:  slotCount(rosterSlots,'TE',1) + Math.floor(fx.TE),
    K:   slotCount(rosterSlots,'K',1),
    DST: slotCount(rosterSlots,'DST',1),
  };
  return Object.entries(maxByPos)
    .filter(([pos, max]) => (counts[pos] || 0) < max)
    .sort(([a], [b]) => {
      const aOpen = (counts[a] || 0) < (rosterSlots[a] || 0) ? 0 : 1;
      const bOpen = (counts[b] || 0) < (rosterSlots[b] || 0) ? 0 : 1;
      return aOpen - bOpen;
    })
    .map(([pos]) => pos);
}
