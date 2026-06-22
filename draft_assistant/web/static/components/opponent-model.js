// Opponent Roster Model
//
// Predicts what each opposing team is likely to draft at every pick between
// now and your next turn, based on:
//   1. Their current roster vs the league's roster slots (positional need)
//   2. ADP of the best players still available
//   3. Draft mode per team: 'live' (need-driven human) vs 'auto' (autodraft
//      follows ADP strictly, only constrained by hard roster caps)
//
// Output is a per-player survival probability — P(player is still on the
// board at your next pick) — which feeds the scoring engine's urgency term,
// plus per-team predictions for the Opponents panel.

(function () {

  var POSITIONS = ['QB', 'RB', 'WR', 'TE', 'K', 'DST'];
  var FLEX_POS  = { RB: true, WR: true, TE: true };
  var CANDIDATES_PER_PICK = 14;

  function snakeTeam(pickNum, numTeams) {
    var round = Math.ceil(pickNum / numTeams);
    var pos   = pickNum - (round - 1) * numTeams;
    return round % 2 === 1 ? pos : numTeams - pos + 1;
  }

  function posCounts(players) {
    var c = {};
    players.forEach(function (p) { c[p.pos] = (c[p.pos] || 0) + 1; });
    return c;
  }

  function totalSlots(slots) {
    var t = 0;
    Object.keys(slots).forEach(function (k) {
      if (k !== 'IR') t += slots[k] || 0;  // IR slots aren't drafted
    });
    return t;
  }

  // How much does a team with roster counts `c` want position `pos`?
  // Live drafters chase open starting slots; autodrafters take best ADP
  // available and only deviate at hard caps (2nd K, 3rd QB, full position).
  function needFactor(pos, c, slots, mode, picksLeft) {
    var have      = c[pos] || 0;
    var starters  = slots[pos] || 0;
    var flexSlots = slots.FLEX || 0;

    var flexUsed = 0;
    ['RB', 'WR', 'TE'].forEach(function (fp) {
      flexUsed += Math.max(0, (c[fp] || 0) - (slots[fp] || 0));
    });
    var flexOpen = Math.max(0, flexSlots - flexUsed);

    if ((pos === 'K' || pos === 'DST') && have >= starters) return 0.01;
    if (pos === 'QB' && have >= Math.max(starters, 1) + 1)  return 0.02;

    // Endgame pressure: if remaining picks barely cover unfilled starting
    // slots, the team is forced to fill them (this is when K/DST go).
    var mustFill = 0;
    POSITIONS.forEach(function (p2) {
      mustFill += Math.max(0, (slots[p2] || 0) - (c[p2] || 0));
    });
    var slack = picksLeft - mustFill;
    if (have < starters && slack <= 1) return 5.0;
    if ((pos === 'K' || pos === 'DST') && slack > 2) return mode === 'auto' ? 0.04 : 0.02;

    if (have < starters)                 return mode === 'live' ? 1.5 : 1.1;
    if (FLEX_POS[pos] && flexOpen > 0)   return mode === 'live' ? 1.0 : 0.95;
    if (pos === 'QB')                    return 0.15;
    return mode === 'live' ? 0.45 : 0.7;   // bench depth
  }

  // One pick by one team: distribute take-probability across the top
  // available candidates. Autodrafters concentrate hard on best ADP;
  // live drafters spread more and weight by need.
  function predictPick(teamPlayers, cands, slots, mode, picksLeft) {
    var c       = posCounts(teamPlayers);
    var weights = [];
    var total   = 0;

    cands.forEach(function (cd, i) {
      var w = Math.exp(-i / (mode === 'auto' ? 1.8 : 3.0));
      w *= needFactor(cd.player.pos, c, slots, mode, picksLeft);
      w *= cd.surv;   // discount players probably already gone
      weights.push(w);
      total += w;
    });

    var posProbs = {};
    var take     = [];
    cands.forEach(function (cd, i) {
      var p = total > 0 ? weights[i] / total : 0;
      take.push(p);
      posProbs[cd.player.pos] = (posProbs[cd.player.pos] || 0) + p;
    });
    return { posProbs: posProbs, take: take };
  }

  window.OpponentModel = {

    // available:  undrafted players (need .id, .pos, .adp)
    // picks:      [{pickNum, teamNum, playerId}]
    // teamModes:  {teamNum: 'live'|'auto'}, default 'live'
    // playersById: {id: player}
    analyze: function (available, picks, league, teamModes, playersById) {
      var numTeams = league.numTeams;
      var slots    = league.rosterSlots;
      var modes    = teamModes || {};

      var rosters = {};
      for (var t = 1; t <= numTeams; t++) rosters[t] = [];
      picks.forEach(function (pk) {
        var pl = playersById[pk.playerId];
        if (pl && rosters[pk.teamNum]) rosters[pk.teamNum].push(pl);
      });

      var byAdp = available.slice().sort(function (a, b) { return a.adp - b.adp; });
      var surv  = {};
      byAdp.forEach(function (p) { surv[p.id] = 1.0; });

      var tot      = totalSlots(slots);
      var nextPick = picks.length + 1;
      var upcoming = [];
      var expectedByPos = {};

      // If it's my pick right now, predict the stretch AFTER it — that's
      // what "will he make it back to me?" means.
      var start = nextPick;
      if (snakeTeam(start, numTeams) === league.draftPosition) start += 1;

      for (var pickNum = start; pickNum < start + numTeams * 2; pickNum++) {
        var team = snakeTeam(pickNum, numTeams);
        if (team === league.draftPosition) break;

        var mode      = modes[team] === 'auto' ? 'auto' : 'live';
        var picksLeft = Math.max(1, tot - rosters[team].length);

        var cands = [];
        for (var j = 0; j < byAdp.length && cands.length < CANDIDATES_PER_PICK; j++) {
          var pl = byAdp[j];
          if (surv[pl.id] > 0.03) cands.push({ player: pl, surv: surv[pl.id] });
        }
        if (cands.length === 0) break;

        var pred = predictPick(rosters[team], cands, slots, mode, picksLeft);
        cands.forEach(function (cd, k) {
          surv[cd.player.id] = Math.max(0.02, surv[cd.player.id] * (1 - pred.take[k]));
        });
        Object.keys(pred.posProbs).forEach(function (pos) {
          expectedByPos[pos] = (expectedByPos[pos] || 0) + pred.posProbs[pos];
        });

        upcoming.push({
          teamNum:      team,
          pickNum:      pickNum,
          mode:         mode,
          rosterCounts: posCounts(rosters[team]),
          posProbs:     pred.posProbs,
        });
      }

      return {
        survival:      surv,
        upcoming:      upcoming,
        expectedByPos: expectedByPos,
        rosters:       rosters,
      };
    },
  };

})();
