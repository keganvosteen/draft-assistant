// Draft Scoring Engine
// Draft Score = (VORP * 2.5 + urgency * scarcityWeight + adpAdj) * availProb * needMult * slotMult - byePenalty
//
// 1. VORP is the primary signal — encodes position scarcity vs replacement level.
// 2. Urgency = dropoff to next-best at same position * P(player gone at next pick).
// 3. Availability is MULTIPLICATIVE — player 80% likely gone is worth 20% of face value.
// 4. Need multiplier suppresses QB/K/DST in early rounds.

(function () {

  var TEAM_BYES = {
    ARI:13, ATL:12, BAL:8,  BUF:6,  CAR:6,  CHI:14, CIN:8,  CLE:14,
    DAL:10, DEN:11, DET:5,  GB:13,  HOU:11, IND:11, JAX:11, KC:6,
    LAC:10, LAR:5,  LV:12,  MIA:9,  MIN:13, NE:14,  NO:12,  NYG:11,
    NYJ:7,  PHI:7,  PIT:14, SEA:14, SF:10,  TB:9,   TEN:9,  WAS:14,
  };

  function snakeTeam(pickNum, numTeams) {
    var round = Math.ceil(pickNum / numTeams);
    var pos   = pickNum - (round - 1) * numTeams;
    return round % 2 === 1 ? pos : numTeams - pos + 1;
  }

  function picksToMyTurn(totalPicksMade, league) {
    var numTeams = league.numTeams;
    var draftPosition = league.draftPosition;
    var nextPick = totalPicksMade + 1;
    if (snakeTeam(nextPick, numTeams) === draftPosition) return 0;
    for (var i = 1; i <= numTeams * 2 + 2; i++) {
      if (snakeTeam(nextPick + i, numTeams) === draftPosition) return i;
    }
    return numTeams;
  }

  function availProb(player, currentPickNum, picksAhead, sigma) {
    var drift  = (currentPickNum + picksAhead) - player.adp;
    var pTaken = 1 / (1 + Math.exp(-drift / (sigma || 18)));
    return Math.max(0.02, Math.min(0.98, 1 - pTaken));
  }

  function getSlotType(player, myPlayers, slots) {
    var cnt     = myPlayers.filter(function(p) { return p.pos === player.pos; }).length;
    var starters = slots[player.pos] || 0;
    var flexElig = ['RB', 'WR', 'TE'].indexOf(player.pos) >= 0;
    var flexSlots = slots.FLEX || 0;

    if (cnt < starters) return 'starter';

    if (flexElig) {
      var flexUsed = 0;
      ['RB', 'WR', 'TE'].forEach(function(pos) {
        var pCnt   = myPlayers.filter(function(p) { return p.pos === pos; }).length;
        var pStart = slots[pos] || 0;
        flexUsed += Math.max(0, pCnt - pStart);
      });
      if (flexUsed < flexSlots) return 'flex';
    }
    return 'bench';
  }

  function computeNeedMult(player, myPlayers, league, pickNum) {
    var rosterSlots = league.rosterSlots;
    var numTeams = league.numTeams;
    var round    = Math.ceil(pickNum / numTeams);
    var cnt      = myPlayers.filter(function(p) { return p.pos === player.pos; }).length;
    var starters = rosterSlots[player.pos] || 0;
    var flexElig = ['RB', 'WR', 'TE'].indexOf(player.pos) >= 0;
    var flexSlots = rosterSlots.FLEX || 0;
    var bnSlots  = rosterSlots.BN   || 0;
    var isOneQB  = (rosterSlots.QB || 1) <= 1;

    var flexUsed = 0;
    ['RB', 'WR', 'TE'].forEach(function(pos) {
      var pCnt   = myPlayers.filter(function(p) { return p.pos === pos; }).length;
      var pStart = rosterSlots[pos] || 0;
      flexUsed += Math.max(0, pCnt - pStart);
    });
    var flexOpen = Math.max(0, flexSlots - flexUsed);

    if (player.pos === 'K'   && round <= 11) return 0.20;
    if (player.pos === 'DST' && round <= 11) return 0.25;
    if (isOneQB && player.pos === 'QB' && round <= 4) return 0.55;
    if (isOneQB && player.pos === 'QB' && round <= 7) return 0.82;

    if (cnt < starters)           return 1.20;
    if (flexElig && flexOpen > 0) return 1.08;
    if (cnt < starters + (flexElig ? flexSlots : 0) + bnSlots) return 0.80;
    return 0.55;
  }

  function computeByePenalty(player, myPlayers, penaltyPer) {
    var bye  = player.byeWeek || TEAM_BYES[player.nflTeam];
    if (!bye) return 0;
    var same = myPlayers.filter(function(p) {
      return (p.byeWeek || TEAM_BYES[p.nflTeam]) === bye;
    }).length;
    return same * penaltyPer;
  }

  function computeADPAdj(player, pickNum) {
    var diff = player.adp - pickNum;
    if (diff >  15) return  0.8;
    if (diff >   5) return  0.3;
    if (diff < -15) return -1.0;
    if (diff <  -5) return -0.3;
    return 0;
  }

  window.computeDraftScores = function (available, myPlayers, league, totalPicksMade, w) {
    var pickNum = totalPicksMade + 1;
    var ahead   = picksToMyTurn(totalPicksMade, league);
    var sigma   = w.adpSigma || 18;

    var byPos = {};
    available.forEach(function(p) {
      (byPos[p.pos] = byPos[p.pos] || []).push(p);
    });
    Object.values(byPos).forEach(function(arr) {
      arr.sort(function(a, b) { return (b.vorp || 0) - (a.vorp || 0); });
    });

    return available.map(function(player) {
      var ap   = availProb(player, pickNum, ahead, sigma);
      var vorp = player.vorp || 0;

      var posPool     = (byPos[player.pos] || []).filter(function(p) { return p.id !== player.id; });
      var nextVORP    = posPool[0] ? (posPool[0].vorp || 0) : Math.min(vorp - 5, 0);
      var vorpDropoff = Math.max(0, vorp - nextVORP);
      var urgency     = vorpDropoff * (1 - ap);

      var st      = getSlotType(player, myPlayers, league.rosterSlots);
      var benchDisc = { RB: w.benchRBWR, WR: w.benchRBWR, TE: w.benchTE, QB: w.benchQB, K: 0, DST: 0 };
      var slotMult  = st === 'starter' ? 1.0 : st === 'flex' ? 0.90 : (benchDisc[player.pos] || 0.08);

      var adj    = computeADPAdj(player, pickNum);
      var byePen = computeByePenalty(player, myPlayers, w.byePenalty);
      var nm     = computeNeedMult(player, myPlayers, league, pickNum);

      var base       = vorp * 2.5 + urgency * w.scarcityWeight + adj;
      var draftScore = base * ap * nm * slotMult - byePen;

      return Object.assign({}, player, {
        draftScore:    Math.round(draftScore * 10) / 10,
        lineupGain:    Math.round(player.projPts * slotMult),
        scarcityBonus: Math.round(urgency * 10) / 10,
        availPct:      Math.round(ap * 100),
        needMult:      Math.round(nm * 100) / 100,
        byePen:        Math.round(byePen * 10) / 10,
        byeWeek:       player.byeWeek || TEAM_BYES[player.nflTeam] || null,
        slotType:      st,
      });
    });
  };

  window.TEAM_BYES = TEAM_BYES;

})();
