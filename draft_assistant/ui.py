from __future__ import annotations

import json
from typing import Dict, List, Tuple

from .draft import DraftTracker
from .models import DraftState, LeagueConfig, Player
from .profiles import (
    DEFAULT_PROFILE,
    ProfilePaths,
    ensure_profile,
    list_profiles,
    load_profile_config,
    save_profile_config,
)
from .providers.base import build_provider
from .sample_data import sample_players
from .storage import load_state, save_players, save_state
from .suggest import needs_by_position, suggest_players

try:
    import tkinter as tk
    from tkinter import messagebox, simpledialog, ttk
except Exception as exc:  # pragma: no cover - platform dependent
    tk = None
    messagebox = None
    simpledialog = None
    ttk = None
    _TK_IMPORT_ERROR = exc
else:
    _TK_IMPORT_ERROR = None


POSITION_CHOICES = ["", "QB", "RB", "WR", "TE", "K", "DST"]
ROSTER_FIELDS = ["QB", "RB", "WR", "TE", "FLEX", "K", "DST", "BN", "IR"]
SCORING_PRESETS: Dict[str, Dict[str, float]] = {
    "PPR": {
        "pass_yd": 0.04,
        "pass_td": 4.0,
        "pass_int": -2.0,
        "rush_yd": 0.1,
        "rush_td": 6.0,
        "rec": 1.0,
        "rec_yd": 0.1,
        "rec_td": 6.0,
        "fumbles": -2.0,
    },
    "Half PPR": {
        "pass_yd": 0.04,
        "pass_td": 4.0,
        "pass_int": -2.0,
        "rush_yd": 0.1,
        "rush_td": 6.0,
        "rec": 0.5,
        "rec_yd": 0.1,
        "rec_td": 6.0,
        "fumbles": -2.0,
    },
    "Standard": {
        "pass_yd": 0.04,
        "pass_td": 4.0,
        "pass_int": -2.0,
        "rush_yd": 0.1,
        "rush_td": 6.0,
        "rec": 0.0,
        "rec_yd": 0.1,
        "rec_td": 6.0,
        "fumbles": -2.0,
    },
}


class DraftAssistantApp:
    def __init__(self, initial_profile: str = DEFAULT_PROFILE) -> None:
        if tk is None or ttk is None:
            raise RuntimeError(f"Tkinter UI is unavailable: {_TK_IMPORT_ERROR}")

        self.root = tk.Tk()
        self.root.title("Draft Assistant")
        self.root.geometry("1180x760")
        self.root.minsize(980, 640)

        self.paths: ProfilePaths
        self.config: LeagueConfig
        self.state: DraftState
        self.players: List[Player]
        self.tracker: DraftTracker

        self.profile_var = tk.StringVar(value=initial_profile)
        self.player_var = tk.StringVar()
        self.position_var = tk.StringVar(value="")
        self.top_n_var = tk.IntVar(value=20)
        self.status_var = tk.StringVar(value="Loading...")

        self.profile_combo: ttk.Combobox
        self.suggestion_tree: ttk.Treeview
        self.roster_text: tk.Text
        self.picks_text: tk.Text

        self._build_layout()
        self._activate_profile(initial_profile)

    def run(self) -> None:
        self.root.mainloop()

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(1, weight=1)
        self.root.rowconfigure(2, weight=1)

        controls = ttk.Frame(self.root, padding=10)
        controls.grid(row=0, column=0, columnspan=2, sticky="ew")
        controls.columnconfigure(7, weight=1)

        ttk.Label(controls, text="League").grid(row=0, column=0, sticky="w")
        self.profile_combo = ttk.Combobox(
            controls,
            textvariable=self.profile_var,
            values=list_profiles(),
            width=18,
            state="readonly",
        )
        self.profile_combo.grid(row=0, column=1, sticky="w", padx=(6, 6))
        self.profile_combo.bind("<<ComboboxSelected>>", lambda _e: self.switch_profile())
        ttk.Button(controls, text="Switch", command=self.switch_profile).grid(row=0, column=2, sticky="w")
        ttk.Button(controls, text="New League", command=self.create_profile).grid(row=0, column=3, sticky="w", padx=(6, 0))
        ttk.Button(controls, text="Settings", command=self.open_settings).grid(row=0, column=4, sticky="w", padx=(6, 10))

        ttk.Label(controls, text="Player").grid(row=0, column=5, sticky="w")
        player_entry = ttk.Entry(controls, textvariable=self.player_var, width=30)
        player_entry.grid(row=0, column=6, sticky="ew", padx=(6, 8))
        player_entry.bind("<Return>", lambda _e: self.record_pick(my_pick=False))

        ttk.Label(controls, text="Pos").grid(row=0, column=8, sticky="e")
        pos_cb = ttk.Combobox(
            controls,
            textvariable=self.position_var,
            values=POSITION_CHOICES,
            width=6,
            state="readonly",
        )
        pos_cb.grid(row=0, column=9, sticky="w", padx=(6, 8))

        ttk.Label(controls, text="Top").grid(row=0, column=10, sticky="e")
        top_spin = ttk.Spinbox(controls, from_=5, to=60, increment=1, textvariable=self.top_n_var, width=5)
        top_spin.grid(row=0, column=11, sticky="w", padx=(6, 8))
        ttk.Button(controls, text="Refresh", command=self.reload_data).grid(row=0, column=12, sticky="w")
        ttk.Button(controls, text="League Pick", command=lambda: self.record_pick(my_pick=False)).grid(
            row=0,
            column=13,
            sticky="w",
            padx=(8, 0),
        )
        ttk.Button(controls, text="My Pick", command=lambda: self.record_pick(my_pick=True)).grid(
            row=0,
            column=14,
            sticky="w",
            padx=(8, 0),
        )
        ttk.Button(controls, text="Undo", command=self.undo_last).grid(row=0, column=15, sticky="w", padx=(8, 0))
        ttk.Button(controls, text="Seed Sample Data", command=self.seed_sample_data).grid(
            row=0,
            column=16,
            sticky="w",
            padx=(8, 0),
        )

        suggestion_frame = ttk.LabelFrame(self.root, text="Suggestions", padding=10)
        suggestion_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0, 10))
        suggestion_frame.columnconfigure(0, weight=1)
        suggestion_frame.rowconfigure(0, weight=1)

        cols = ("name", "pos", "pts", "vor", "score", "adp")
        self.suggestion_tree = ttk.Treeview(
            suggestion_frame,
            columns=cols,
            show="headings",
            height=16,
            selectmode="browse",
        )
        self.suggestion_tree.heading("name", text="Name")
        self.suggestion_tree.heading("pos", text="Pos")
        self.suggestion_tree.heading("pts", text="Proj Pts")
        self.suggestion_tree.heading("vor", text="VOR")
        self.suggestion_tree.heading("score", text="Score")
        self.suggestion_tree.heading("adp", text="ADP")
        self.suggestion_tree.column("name", width=320, anchor="w")
        self.suggestion_tree.column("pos", width=60, anchor="center")
        self.suggestion_tree.column("pts", width=90, anchor="e")
        self.suggestion_tree.column("vor", width=90, anchor="e")
        self.suggestion_tree.column("score", width=90, anchor="e")
        self.suggestion_tree.column("adp", width=90, anchor="e")
        self.suggestion_tree.grid(row=0, column=0, sticky="nsew")
        self.suggestion_tree.bind("<<TreeviewSelect>>", self._on_suggestion_selected)

        scrollbar = ttk.Scrollbar(suggestion_frame, orient="vertical", command=self.suggestion_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.suggestion_tree.configure(yscrollcommand=scrollbar.set)

        roster_frame = ttk.LabelFrame(self.root, text="Roster & Needs", padding=10)
        roster_frame.grid(row=2, column=0, sticky="nsew", padx=(10, 5), pady=(0, 10))
        roster_frame.columnconfigure(0, weight=1)
        roster_frame.rowconfigure(0, weight=1)

        self.roster_text = tk.Text(roster_frame, height=12, wrap="word")
        self.roster_text.grid(row=0, column=0, sticky="nsew")
        self.roster_text.configure(state="disabled")

        picks_frame = ttk.LabelFrame(self.root, text="Draft Log", padding=10)
        picks_frame.grid(row=2, column=1, sticky="nsew", padx=(5, 10), pady=(0, 10))
        picks_frame.columnconfigure(0, weight=1)
        picks_frame.rowconfigure(0, weight=1)

        self.picks_text = tk.Text(picks_frame, height=12, wrap="word")
        self.picks_text.grid(row=0, column=0, sticky="nsew")
        self.picks_text.configure(state="disabled")

        status = ttk.Label(self.root, textvariable=self.status_var, anchor="w", padding=(10, 6))
        status.grid(row=3, column=0, columnspan=2, sticky="ew")

    def _refresh_profile_list(self, selected: str | None = None) -> None:
        profiles = list_profiles()
        self.profile_combo.configure(values=profiles)
        if selected and selected in profiles:
            self.profile_var.set(selected)
        elif self.profile_var.get() not in profiles and profiles:
            self.profile_var.set(profiles[0])

    def _activate_profile(self, profile_name: str) -> None:
        try:
            self.paths = ensure_profile(profile_name)
        except Exception as exc:
            if messagebox:
                messagebox.showerror("Profile Error", str(exc))
            self.paths = ensure_profile(DEFAULT_PROFILE)
        self._refresh_profile_list(self.paths.profile)
        self.reload_data()

    def switch_profile(self) -> None:
        self._activate_profile(self.profile_var.get())

    def create_profile(self) -> None:
        if simpledialog is None:
            self.status_var.set("New league creation is unavailable on this platform.")
            return
        name = simpledialog.askstring("New League", "Enter a league/profile name:")
        if not name:
            return
        self._activate_profile(name)

    def reload_data(self) -> None:
        self.config = load_profile_config(self.paths)
        self.state = load_state(self.paths.state_path)
        provider = build_provider(self.config.provider)
        self.players = provider.fetch_players()
        self.tracker = DraftTracker(self.config, self.state, self.players)
        self._refresh_view()

    def _refresh_view(self) -> None:
        self._refresh_suggestions()
        self._refresh_roster()
        self._refresh_picks()
        self.status_var.set(
            f"League: {self.paths.profile} | Players: {len(self.players)} | Picks: {len(self.state.picks)} | My picks: {len(self.state.my_picks)}"
        )

    def _refresh_suggestions(self) -> None:
        for item in self.suggestion_tree.get_children():
            self.suggestion_tree.delete(item)

        available = self.tracker.available_players()
        top_n = max(1, int(self.top_n_var.get() or 20))
        ranked: List[Tuple[Player, float, float, float]] = suggest_players(
            self.config,
            available,
            self.tracker.my_roster(),
            top_n=top_n,
        )
        for p, pts, vor, score in ranked:
            adp = "" if p.adp is None else f"{p.adp:.1f}"
            self.suggestion_tree.insert(
                "",
                "end",
                values=(p.name, p.position, f"{pts:.1f}", f"{vor:.1f}", f"{score:.1f}", adp),
            )

    def _refresh_roster(self) -> None:
        roster = self.tracker.my_roster()
        needs = needs_by_position(self.config, roster)
        lines = ["My roster"]
        for pos in ["QB", "RB", "WR", "TE", "K", "DST"]:
            names = ", ".join(p.name for p in roster.get(pos, []))
            lines.append(f"{pos}: {names if names else '-'}")
        lines.append("")
        lines.append("Needs")
        for pos in ["QB", "RB", "WR", "TE", "K", "DST"]:
            lines.append(f"{pos}: {needs.get(pos, 0)}")
        self._set_text(self.roster_text, "\n".join(lines))

    def _refresh_picks(self) -> None:
        if not self.state.picks:
            self._set_text(self.picks_text, "No picks recorded yet.")
            return
        mine_set = set(self.state.my_picks)
        lines = []
        for idx, key in enumerate(self.state.picks, start=1):
            mine = " (mine)" if key in mine_set else ""
            lines.append(f"{idx}. {key}{mine}")
        self._set_text(self.picks_text, "\n".join(lines))

    def _set_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _on_suggestion_selected(self, _event: object) -> None:
        selected = self.suggestion_tree.selection()
        if not selected:
            return
        values = self.suggestion_tree.item(selected[0], "values")
        if not values:
            return
        self.player_var.set(str(values[0]))
        self.position_var.set(str(values[1]))

    def record_pick(self, my_pick: bool) -> None:
        player_name = self.player_var.get().strip()
        if not player_name:
            self.status_var.set("Enter a player name or click one from suggestions.")
            return
        position = self.position_var.get().strip() or None
        picked = self.tracker.record_pick(player_name, position=position, my_pick=my_pick)
        if not picked:
            self.status_var.set("No matching available player found.")
            return
        save_state(self.state, self.paths.state_path)
        self.player_var.set("")
        self.position_var.set("")
        tag = "My pick" if my_pick else "Pick"
        self.status_var.set(f"{tag}: {picked.name} ({picked.position})")
        self._refresh_view()

    def undo_last(self) -> None:
        last = self.tracker.undo()
        if not last:
            self.status_var.set("No picks to undo.")
            return
        save_state(self.state, self.paths.state_path)
        self.status_var.set(f"Undid: {last}")
        self._refresh_view()

    def seed_sample_data(self) -> None:
        out_path = self.paths.projections_path
        provider = self.config.provider or {}
        if provider.get("type") == "local_json":
            opts = provider.get("options", {}) or {}
            out_path = str(opts.get("path", out_path))
        save_players(sample_players(), out_path)
        self.status_var.set(f"Seeded sample data to {out_path}")
        self.reload_data()
        if messagebox:
            messagebox.showinfo("Sample Data Ready", f"Seeded sample projections at:\n{out_path}")

    def open_settings(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title(f"League Settings - {self.paths.profile}")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("760x680")

        frame = ttk.Frame(dialog, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text=f"Profile: {self.paths.profile}").grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(frame, text="Teams").grid(row=1, column=0, sticky="w", pady=(10, 4))
        teams_var = tk.StringVar(value=str(self.config.teams))
        ttk.Entry(frame, textvariable=teams_var, width=10).grid(row=1, column=1, sticky="w", pady=(10, 4))

        roster_box = ttk.LabelFrame(frame, text="Roster Slots", padding=8)
        roster_box.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 8))
        roster_vars: Dict[str, tk.StringVar] = {}
        for idx, pos in enumerate(ROSTER_FIELDS):
            ttk.Label(roster_box, text=pos).grid(row=idx // 3, column=(idx % 3) * 2, sticky="w", padx=(0, 4), pady=3)
            var = tk.StringVar(value=str(int(self.config.roster.get(pos, 0))))
            roster_vars[pos] = var
            ttk.Entry(roster_box, textvariable=var, width=6).grid(row=idx // 3, column=(idx % 3) * 2 + 1, sticky="w", pady=3)

        scoring_ctl = ttk.Frame(frame)
        scoring_ctl.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 4))
        scoring_ctl.columnconfigure(2, weight=1)
        ttk.Label(scoring_ctl, text="Preset").grid(row=0, column=0, sticky="w")
        preset_var = tk.StringVar(value="Half PPR")
        preset = ttk.Combobox(scoring_ctl, textvariable=preset_var, values=list(SCORING_PRESETS.keys()), width=12, state="readonly")
        preset.grid(row=0, column=1, sticky="w", padx=(6, 8))

        scoring_label = ttk.Label(frame, text="Scoring JSON")
        scoring_label.grid(row=4, column=0, columnspan=2, sticky="w")

        scoring_text = tk.Text(frame, height=20, wrap="none")
        scoring_text.grid(row=5, column=0, columnspan=2, sticky="nsew")
        frame.rowconfigure(5, weight=1)
        scoring_text.insert("1.0", json.dumps(self.config.scoring, indent=2, sort_keys=True))

        def _set_scoring(mapping: Dict[str, float]) -> None:
            scoring_text.delete("1.0", "end")
            scoring_text.insert("1.0", json.dumps(mapping, indent=2, sort_keys=True))

        def apply_preset() -> None:
            selected = preset_var.get()
            base = SCORING_PRESETS.get(selected)
            if not base:
                return
            try:
                current = json.loads(scoring_text.get("1.0", "end").strip() or "{}")
            except json.JSONDecodeError:
                current = {}
            if not isinstance(current, dict):
                current = {}
            current.update(base)
            _set_scoring(current)

        ttk.Button(scoring_ctl, text="Apply Preset", command=apply_preset).grid(row=0, column=2, sticky="w")

        button_row = ttk.Frame(frame)
        button_row.grid(row=6, column=0, columnspan=2, sticky="e", pady=(10, 0))

        def save_settings() -> None:
            try:
                teams = int(teams_var.get())
                if teams < 1:
                    raise ValueError
            except ValueError:
                if messagebox:
                    messagebox.showerror("Invalid Teams", "Teams must be a positive integer.")
                return

            roster_updates: Dict[str, int] = {}
            try:
                for pos, var in roster_vars.items():
                    val = int(var.get())
                    if val < 0:
                        raise ValueError
                    roster_updates[pos] = val
            except ValueError:
                if messagebox:
                    messagebox.showerror("Invalid Roster", "Roster slots must be non-negative integers.")
                return

            raw = scoring_text.get("1.0", "end").strip()
            try:
                parsed = json.loads(raw or "{}")
            except json.JSONDecodeError as exc:
                if messagebox:
                    messagebox.showerror("Invalid Scoring JSON", f"Could not parse scoring JSON:\n{exc}")
                return
            if not isinstance(parsed, dict):
                if messagebox:
                    messagebox.showerror("Invalid Scoring JSON", "Scoring JSON must be an object.")
                return
            try:
                scoring = {str(k): float(v) for k, v in parsed.items()}
            except (TypeError, ValueError):
                if messagebox:
                    messagebox.showerror("Invalid Scoring JSON", "All scoring values must be numeric.")
                return

            updated_roster = dict(self.config.roster)
            updated_roster.update(roster_updates)
            self.config.teams = teams
            self.config.roster = updated_roster
            self.config.scoring = scoring
            save_profile_config(self.config, self.paths)

            if len(self.state.league_teams) != teams:
                self.state.league_teams = [f"Team {i+1}" for i in range(teams)]
                save_state(self.state, self.paths.state_path)

            self.reload_data()
            self.status_var.set(f"Saved settings for league '{self.paths.profile}'.")
            dialog.destroy()

        ttk.Button(button_row, text="Cancel", command=dialog.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(button_row, text="Save Settings", command=save_settings).grid(row=0, column=1)


def run_ui(initial_profile: str = DEFAULT_PROFILE) -> None:
    app = DraftAssistantApp(initial_profile=initial_profile)
    app.run()
