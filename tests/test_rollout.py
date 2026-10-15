"""Tests for the rest-of-draft Monte Carlo rollout engine.

The headline guarantee is the scarcity test: when one position has a steep
talent cliff and another is deep, the engine should prefer taking the scarce
player now even if the deep-position player scores MORE points in isolation,
because that yields more total season points across the finished roster.
"""
import unittest

from draft_assistant.models import DraftState, LeagueConfig, Player
from draft_assistant.rollout import rollout_values, RolloutResult


def _p(name, pos, pts, adp=None, bye=None):
    # scoring below maps rush_yd / rec_yd 1:1 to points, so `pts` is exact.
    stat = "rush_yd" if pos == "RB" else "rec_yd" if pos == "WR" else "rush_yd"
    return Player(id=f"{name}|{pos}", name=name, position=pos,
                  projections={stat: float(pts)}, adp=adp, bye_week=bye)


SCORING = {"rush_yd": 1.0, "rec_yd": 1.0, "rec": 0.0, "fg_0_39": 3}


def _config(roster, teams=2, slot=1, sims=24, noise=1.0):
    return LeagueConfig(
        teams=teams, roster=roster, scoring=SCORING, provider={},
        draft={"slot": slot, "rollout_sims": sims, "adp_noise": noise},
    )


class TestScarcity(unittest.TestCase):
    def test_prefers_scarce_position_over_higher_points(self):
        # WR position is a cliff (300 then 100); RB is deep (310/300/295).
        # The higher-scoring player at pick 1 is the RB (310 > 300), but taking
        # the elite WR now is worth more season points because a near-equal RB
        # is still there at the next pick while the WR drops off a cliff.
        available = [
            _p("WR_elite", "WR", 300, adp=1.0),
            _p("RB_good", "RB", 310, adp=1.5),
            _p("RB_ok", "RB", 300, adp=2.0),
            _p("RB_ok2", "RB", 295, adp=2.5),
            _p("WR_bad", "WR", 100, adp=3.0),
            _p("RB_fill", "RB", 50, adp=6.0),
            _p("WR_fill", "WR", 50, adp=7.0),
            _p("RB_fill2", "RB", 45, adp=8.0),
        ]
        cfg = _config({"RB": 1, "WR": 1, "BN": 1})
        res = rollout_values(cfg, available, {}, state=None, top_n=8)
        by_name = {r.player.name: r for r in res}

        # Sanity: the RB really does score more in isolation.
        self.assertGreater(by_name["RB_good"].points, by_name["WR_elite"].points)
        # But the engine ranks the scarce WR first and gives it higher impact.
        self.assertEqual(res[0].player.name, "WR_elite")
        self.assertGreater(by_name["WR_elite"].impact, by_name["RB_good"].impact)

    def test_deep_position_is_replaceable(self):
        # Two equal RBs, one elite WR. With RB deep, the engine should not panic
        # over RB; the WR (scarce) should out-rank both RBs.
        available = [
            _p("WR_elite", "WR", 280, adp=1.0),
            _p("RB_a", "RB", 285, adp=1.5),
            _p("RB_b", "RB", 282, adp=2.0),
            _p("WR_bad", "WR", 90, adp=3.0),
            _p("RB_fill", "RB", 60, adp=6.0),
            _p("WR_fill", "WR", 55, adp=7.0),
        ]
        cfg = _config({"RB": 1, "WR": 1, "BN": 1})
        res = rollout_values(cfg, available, {}, state=None, top_n=6)
        self.assertEqual(res[0].player.position, "WR")


class TestConfigDriven(unittest.TestCase):
    def test_points_follow_league_scoring(self):
        # A pass-catching back is worth more under PPR than standard — the
        # engine must read scoring from config, never hard-code it.
        catcher = Player(id="Catch|RB", name="Catch", position="RB",
                         projections={"rush_yd": 500, "rec": 80, "rec_yd": 600}, adp=1.0)
        field = [catcher,
                 Player(id="Rush|RB", name="Rush", position="RB",
                        projections={"rush_yd": 1100}, adp=1.2),
                 Player(id="Wr|WR", name="Wr", position="WR",
                        projections={"rec": 90, "rec_yd": 1200}, adp=1.5)]
        roster = {"RB": 2, "WR": 1, "BN": 1}
        std = LeagueConfig(teams=2, roster=roster, provider={},
                           scoring={"rush_yd": 0.1, "rec_yd": 0.1, "rec": 0.0},
                           draft={"slot": 1, "rollout_sims": 8})
        ppr = LeagueConfig(teams=2, roster=roster, provider={},
                           scoring={"rush_yd": 0.1, "rec_yd": 0.1, "rec": 1.0},
                           draft={"slot": 1, "rollout_sims": 8})
        std_pts = {r.player.name: r.points for r in rollout_values(std, [p for p in field], {}, top_n=3)}
        ppr_pts = {r.player.name: r.points for r in rollout_values(ppr, [p for p in field], {}, top_n=3)}
        # 80 receptions -> +80 points under full PPR.
        self.assertAlmostEqual(ppr_pts["Catch"] - std_pts["Catch"], 80.0, places=1)

    def test_roster_shape_changes_pick_structure(self):
        # Just assert the engine runs and ranks under a different roster shape
        # without any hard-coded assumptions blowing up.
        available = [_p(f"RB{i}", "RB", 300 - i * 5, adp=float(i + 1)) for i in range(6)]
        available += [_p(f"WR{i}", "WR", 290 - i * 5, adp=float(i + 1.3)) for i in range(6)]
        cfg = _config({"QB": 0, "RB": 2, "WR": 3, "FLEX": 1, "BN": 2}, teams=4)
        res = rollout_values(cfg, available, {}, state=None, top_n=10)
        self.assertGreater(len(res), 0)
        self.assertTrue(all(isinstance(r, RolloutResult) for r in res))


class TestPolicyDetails(unittest.TestCase):
    def test_provider_alias_pick_does_not_add_a_duplicate_roster_placeholder(self):
        owned = _p("RB1", "RB", 100)
        owned.id = "sleeper:11"
        owned.metadata = {"ffc_player_id": "77"}
        board = [_p("Needed", "TE", 50), _p("Bench", "RB", 90)]
        cfg = _config({"RB": 1, "TE": 1, "BN": 1}, teams=1, sims=4, noise=0)
        aliased = DraftState("Me", ["Me"], picks=["ffc:77"], my_picks=["ffc:77"])
        canonical = DraftState("Me", ["Me"], picks=[owned.key()], my_picks=[owned.key()])
        actual = rollout_values(cfg, board, {"RB": [owned]}, aliased, top_n=2)
        expected = rollout_values(cfg, board, {"RB": [owned]}, canonical, top_n=2)
        self.assertEqual(actual, expected)

    def test_vor_uses_remaining_league_demand_mid_draft(self):
        drafted = [
            _p("RB1", "RB", 100, adp=1.0),
            _p("RB2", "RB", 90, adp=2.0),
            _p("RB3", "RB", 80, adp=3.0),
        ]
        available = [
            _p("RB4", "RB", 70, adp=4.0),
            _p("RB5", "RB", 60, adp=5.0),
            _p("RB6", "RB", 50, adp=6.0),
            _p("RB7", "RB", 40, adp=7.0),
        ]
        cfg = _config({"RB": 1}, teams=4, slot=4, sims=0, noise=0.0)
        state = DraftState(
            "Me",
            ["T1", "T2", "T3", "Me"],
            picks=[player.key() for player in drafted],
        )

        result = rollout_values(
            cfg,
            available,
            {},
            state=state,
            top_n=4,
            drafted_players=drafted,
        )

        by_name = {row.player.name: row for row in result}
        self.assertEqual(by_name["RB4"].vor, 0.0)
        self.assertLess(by_name["RB5"].vor, 0.0)

    def test_off_board_synced_pick_still_consumes_league_demand(self):
        # A live provider pick we could not match keeps its slot as "name|POS"
        # (see synced_draft_to_picks).  Callers build their drafted list by
        # looking each pick up on the board, so that pick reaches us only via
        # state.picks.  Dropping it would leave two RB starters apparently
        # unfilled instead of one, pushing replacement from RB4 down to RB5.
        drafted = [
            _p("RB1", "RB", 100, adp=1.0),
            _p("RB2", "RB", 90, adp=2.0),
        ]
        off_board_key = "Deep Rookie|RB"
        available = [
            _p("RB4", "RB", 70, adp=4.0),
            _p("RB5", "RB", 60, adp=5.0),
            _p("RB6", "RB", 50, adp=6.0),
        ]
        cfg = _config({"RB": 1}, teams=4, slot=4, sims=0, noise=0.0)
        state = DraftState(
            "Me",
            ["T1", "T2", "T3", "Me"],
            picks=[*(player.key() for player in drafted), off_board_key],
        )

        result = rollout_values(
            cfg,
            available,
            {},
            state=state,
            top_n=3,
            drafted_players=drafted,  # the off-board pick is not resolvable
        )

        by_name = {row.player.name: row for row in result}
        self.assertEqual(by_name["RB4"].vor, 0.0)
        self.assertLess(by_name["RB5"].vor, 0.0)

    def test_off_board_pick_counted_once_when_caller_resolves_it(self):
        # The same pick arriving through both channels must not be double
        # counted: a board player whose key is name|POS-shaped is already in
        # the caller's drafted list, so it must not also become a placeholder.
        drafted = [_p("RB1", "RB", 100, adp=1.0)]
        available = [
            _p("RB2", "RB", 90, adp=2.0),
            _p("RB3", "RB", 80, adp=3.0),
            _p("RB4", "RB", 70, adp=4.0),
        ]
        cfg = _config({"RB": 1}, teams=3, slot=3, sims=0, noise=0.0)
        state = DraftState(
            "Me", ["T1", "T2", "Me"],
            picks=[player.key() for player in drafted],
        )

        result = rollout_values(
            cfg, available, {}, state=state, top_n=3, drafted_players=drafted,
        )

        # One RB gone of three starters => two remain => replacement is RB3.
        by_name = {row.player.name: row for row in result}
        self.assertEqual(by_name["RB2"].vor, 10.0)
        self.assertEqual(by_name["RB3"].vor, 0.0)

    def test_kicker_not_recommended_early(self):
        available = [
            _p("RB1", "RB", 300, adp=1.0),
            _p("WR1", "WR", 290, adp=1.2),
            Player(id="K1|K", name="K1", position="K",
                   projections={"fg_0_39": 50}, adp=1.1),  # absurd kicker
            _p("RB2", "RB", 250, adp=2.0),
            _p("WR2", "WR", 240, adp=2.2),
        ]
        cfg = _config({"QB": 0, "RB": 2, "WR": 2, "K": 1, "BN": 1}, teams=2)
        res = rollout_values(cfg, available, {}, state=None, top_n=5)
        # The kicker should be deferred — never the top pick when skill is open.
        self.assertNotEqual(res[0].player.position, "K")

    def test_deterministic(self):
        available = [_p(f"RB{i}", "RB", 300 - i * 7, adp=float(i + 1)) for i in range(8)]
        cfg = _config({"RB": 2, "WR": 1, "BN": 1})
        a = rollout_values(cfg, [p for p in available], {}, top_n=5)
        b = rollout_values(cfg, [p for p in available], {}, top_n=5)
        self.assertEqual([(r.player.name, r.impact) for r in a],
                         [(r.player.name, r.impact) for r in b])

    def test_displayed_impact_matches_sort_order(self):
        available = [_p(f"RB{i}", "RB", 300 - i * 7, adp=float(i + 1)) for i in range(8)]
        cfg = _config({"RB": 2, "WR": 1, "BN": 1})
        res = rollout_values(cfg, available, {}, top_n=5)
        impacts = [r.impact for r in res if r.simulated]
        self.assertEqual(impacts, sorted(impacts, reverse=True))

    def test_future_candidate_is_not_reserved_through_opponent_pick(self):
        available = [
            _p("WR_taken", "WR", 300, adp=1.0),
            _p("RB_fallback", "RB", 250, adp=2.0),
            _p("WR_fallback", "WR", 100, adp=3.0),
        ]
        cfg = _config({"RB": 1, "WR": 1}, teams=2, slot=2, sims=8, noise=0.0)
        # Team 1 picks before our first decision. WR_taken is first by ADP, so
        # forcing it at pick 2 must fall back exactly like the baseline.
        state = DraftState("Me", ["Opponent", "Me"])
        by_name = {
            row.player.name: row
            for row in rollout_values(cfg, available, {}, state=state, top_n=3)
        }
        self.assertAlmostEqual(by_name["WR_taken"].impact, 0.0, places=2)

    def test_unmatched_personal_pick_occupies_slot_and_forces_kicker(self):
        available = [
            _p("RB_luxury", "RB", 400, adp=1.0),
            _p("RB_luxury_2", "RB", 390, adp=2.0),
            Player(id="K_required|K", name="K_required", position="K",
                   projections={"fg_0_39": 30}, adp=99.0),
        ]
        cfg = _config({"RB": 1, "K": 1}, teams=2, slot=1, sims=8, noise=0.0)
        # The first-round synced pick is not on the projection board, but it is
        # still our RB and leaves only pick 4 to fill the required K slot.
        state = DraftState(
            "Me", ["Me", "Opponent"],
            picks=["Deep Rookie|RB", "Other One|WR", "Other Two|WR"],
            my_picks=["Deep Rookie|RB"],
        )
        result = rollout_values(cfg, available, {}, state=state, top_n=3)
        self.assertEqual(result[0].player.position, "K")

    def test_last_two_picks_complete_kicker_and_defense(self):
        available = [
            _p("RB_luxury", "RB", 400, adp=1.0),
            Player(id="K_required|K", name="K_required", position="K",
                   projections={"fg_0_39": 30}, adp=50.0),
            _p("DST_required", "DST", 20, adp=60.0),
        ]
        cfg = _config({"K": 1, "DST": 1}, teams=2, slot=1, sims=8, noise=0.0)
        result = rollout_values(cfg, available, {}, state=None, top_n=3)
        self.assertIn(result[0].player.position, {"K", "DST"})
        self.assertTrue(all(row.player.position in {"K", "DST"}
                            for row in result if row.simulated))


class TestSimulatedPool(unittest.TestCase):
    """Only the leading candidates get a full rollout; the rest fill the board.

    The simulated pool is deliberately decoupled from ``top_n`` — tying them
    together made every extra board row cost a full set of simulations.
    """

    def _board(self, n):
        return [_p(f"RB{i}", "RB", 400 - i * 3, adp=float(i + 1)) for i in range(n)]

    def test_requesting_more_rows_does_not_simulate_more(self):
        cfg = _config({"RB": 2, "WR": 1, "BN": 2}, teams=4)
        board = self._board(60)
        few = rollout_values(cfg, board, {}, top_n=10)
        many = rollout_values(cfg, board, {}, top_n=40)
        self.assertEqual(len(many), 40)
        simulated_many = [r for r in many if r.simulated]
        # More rows requested, but the simulated pool is unchanged.
        self.assertLessEqual(len(simulated_many), 20)
        self.assertTrue(all(r.simulated for r in few))

    def test_estimated_rows_sort_below_every_simulated_row(self):
        cfg = _config({"RB": 2, "WR": 1, "BN": 2}, teams=4)
        res = rollout_values(cfg, self._board(60), {}, top_n=40)
        flags = [r.simulated for r in res]
        # All True then all False — never interleaved.
        self.assertEqual(flags, sorted(flags, reverse=True))

    def test_estimated_rows_are_marked_and_unsimulated(self):
        cfg = _config({"RB": 2, "WR": 1, "BN": 2}, teams=4)
        res = rollout_values(cfg, self._board(60), {}, top_n=40)
        estimated = [r for r in res if not r.simulated]
        self.assertTrue(estimated, "expected the board to be filled past the sim pool")
        self.assertTrue(all(r.sims == 0 for r in estimated))
        self.assertTrue(all(r.sims > 0 for r in res if r.simulated))

    def test_rollout_candidates_setting_controls_the_pool(self):
        cfg = _config({"RB": 2, "WR": 1, "BN": 2}, teams=4)
        cfg.draft["rollout_candidates"] = 4
        res = rollout_values(cfg, self._board(60), {}, top_n=30)
        # The pool is the configured size plus the positional/greedy top-ups,
        # which is still far short of the 30 rows requested.
        self.assertLess(len([r for r in res if r.simulated]), 15)

    def test_no_duplicate_players_across_the_split(self):
        cfg = _config({"RB": 2, "WR": 1, "BN": 2}, teams=4)
        res = rollout_values(cfg, self._board(60), {}, top_n=40)
        keys = [r.player.key() for r in res]
        self.assertEqual(len(keys), len(set(keys)))


class TestDegenerate(unittest.TestCase):
    def test_zero_sims_falls_back(self):
        available = [_p("RB1", "RB", 300, adp=1.0), _p("WR1", "WR", 290, adp=1.2)]
        cfg = _config({"RB": 1, "WR": 1, "BN": 1}, sims=0)
        res = rollout_values(cfg, available, {}, top_n=5)
        self.assertGreater(len(res), 0)
        self.assertTrue(all(isinstance(r, RolloutResult) for r in res))
        self.assertEqual(res[0].sims, 0)

    def test_empty_board(self):
        cfg = _config({"RB": 1, "WR": 1, "BN": 1})
        self.assertEqual(rollout_values(cfg, [], {}, top_n=5), [])


class TestMandatoryCompletion(unittest.TestCase):
    def test_last_pick_fills_every_required_position_even_without_simulation(self):
        for required in ("QB", "RB", "WR", "TE", "K", "DST"):
            for sims in (0, 4):
                filler = "RB" if required != "RB" else "WR"
                rostered = [_p("Starter", filler, 100), _p("Bench", filler, 90)]
                board = [_p(f"Luxury{i}", filler, 400 - i) for i in range(30)]
                board.append(_p("Needed", required, 50))
                config = _config({filler: 1, required: 1, "BN": 1}, teams=1, sims=sims)
                with self.subTest(position=required, sims=sims):
                    rows = rollout_values(config, board, {filler: rostered}, top_n=40)
                    self.assertEqual([row.player.name for row in rows], ["Needed"])
                    self.assertTrue(rows[0].roster_feasible)

    def test_final_pick_fills_overlapping_flex(self):
        owned = [_p("TE1", "TE", 100), _p("TE2", "TE", 90)]
        board = [_p("LuxuryTE", "TE", 400), _p("NeededWR", "WR", 50)]
        cfg = _config({"WRTE": 1, "RBWR": 1, "BN": 1}, teams=1, sims=4)
        rows = rollout_values(cfg, board, {"TE": owned}, top_n=10)
        self.assertEqual([row.player.name for row in rows], ["NeededWR"])

    def test_multi_pick_rollout_completes_skill_and_flex_slots(self):
        from draft_assistant.draft_value import roster_value
        from draft_assistant.projections import compute_points
        config = _config({"WRTE": 1, "RBWR": 1, "QB": 1, "BN": 1}, teams=1, sims=4, noise=0)
        board = [_p(f"TE{i}", "TE", 500 - i) for i in range(5)]
        board += [_p("WR", "WR", 50), _p("QB", "QB", 1)]
        owned = {}
        for _ in range(4):
            row = rollout_values(config, board, owned, top_n=1)[0]
            owned.setdefault(row.player.position, []).append(row.player)
            board.remove(row.player)
            self.assertTrue(row.roster_feasible)
        chosen = [p for group in owned.values() for p in group]
        lineup = roster_value(chosen, compute_points(chosen, SCORING), config.roster)
        self.assertEqual(len(lineup.starters), 3)
        self.assertEqual({p.position for p in lineup.starters}, {"QB", "WR", "TE"})

    def test_impossible_pool_is_identified(self):
        config = _config({"RB": 1, "TE": 1}, teams=1, sims=4)
        rows = rollout_values(config, [_p("RB", "RB", 100)], {}, top_n=10)
        self.assertTrue(rows)
        self.assertTrue(all(not row.roster_feasible for row in rows))


class TestExplanationMetrics(unittest.TestCase):
    def test_bye_penalty_uses_requested_season_in_simulated_and_fallback_rows(self):
        incumbent = _p("Owned", "RB", 100, bye=9)
        incumbent.team = "BUF"
        incumbent.metadata = {"bye_season": 2026, "bye_team": "BUF"}
        candidate = _p("Candidate", "RB", 90, bye=9)
        candidate.team = "KC"
        candidate.metadata = {"bye_season": 2026, "bye_team": "KC"}
        for sims in (0, 4):
            cfg = _config({"RB": 2}, teams=1, sims=sims)
            for season, expected_penalty in ((2026, 1.5), (2027, 0.0)):
                with self.subTest(sims=sims, season=season):
                    rows = rollout_values(cfg, [candidate], {"RB": [incumbent]}, season=season)
                    self.assertEqual(rows[0].bye_penalty, expected_penalty)

    def test_gain_excludes_vor_bonus_in_simulated_and_fallback_rows(self):
        from draft_assistant.draft_value import roster_value
        from draft_assistant.projections import compute_points
        board = [_p(f"RB{i}", "RB", 100 - i * 2) for i in range(30)]
        for sims in (0, 4):
            cfg = _config({"RB": 1}, teams=2, sims=sims)
            cfg.draft["rollout_candidates"] = 1
            rows = rollout_values(cfg, board, {}, top_n=30)
            points = compute_points(board, SCORING)
            for row in rows:
                expected = roster_value([row.player], points, cfg.roster).total_value
                self.assertEqual(row.immediate_gain, expected)
                if not row.simulated:
                    self.assertEqual(row.expected_roster_points, expected)

    def test_waiting_counts_opponents_before_upcoming_pick(self):
        cfg = _config({"RB": 1, "BN": 1}, teams=2, slot=2, sims=4, noise=0)
        board = [_p("First", "RB", 100, 1), _p("Second", "RB", 90, 2), _p("Third", "RB", 80, 3)]
        rows = rollout_values(cfg, board, {}, DraftState("Me", ["Opponent", "Me"]), top_n=3)
        risk = {row.player.name: row.gone_risk for row in rows}
        self.assertEqual(risk["First"], 1)
        self.assertEqual(risk["Second"], 0)

    def test_on_turn_accounts_for_the_alternative_pick(self):
        cfg = _config({"RB": 1, "BN": 1}, teams=2, slot=1, sims=4, noise=0)
        board = [_p(f"RB{i}", "RB", 100 - i, i + 1) for i in range(5)]
        rows = rollout_values(cfg, board, {}, DraftState("Me", ["Me", "Opponent"]), top_n=5)
        risk = {row.player.name: row.gone_risk for row in rows}
        self.assertEqual(risk["RB2"], 1)  # our alternative RB0 is removed first
        self.assertEqual(risk["RB3"], 0)

    def test_turnaround_and_last_pick_have_no_intervening_opponents(self):
        board = [_p(f"RB{i}", "RB", 100 - i, i + 1) for i in range(3)]
        cfg = _config({"RB": 1, "BN": 1}, teams=2, slot=2, sims=4, noise=0)
        state = DraftState("Me", ["Opponent", "Me"], picks=["Other|WR"])
        self.assertTrue(all(row.gone_risk == 0 for row in rollout_values(cfg, board, {}, state, top_n=3)))
        cfg = _config({"RB": 1}, teams=2, slot=1, sims=4, noise=0)
        self.assertTrue(all(row.gone_risk == 0 for row in rollout_values(cfg, board, {}, top_n=3)))


if __name__ == "__main__":
    unittest.main()
