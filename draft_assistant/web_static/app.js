(function () {
  "use strict";

  const POSITIONS = ["ALL", "QB", "RB", "WR", "TE", "K", "DST"];
  const FLEX_POSITIONS = new Set(["RB", "WR", "TE"]);
  const app = document.getElementById("app");

  const state = {
    profile: new URLSearchParams(window.location.search).get("profile") || localStorage.getItem("da_profile") || "default",
    data: null,
    search: "",
    position: "ALL",
    sort: "score",
    showDrafted: false,
    settingsOpen: false,
    saving: false,
    toast: "",
  };

  function api(path, options) {
    return fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    }).then(async (response) => {
      const body = await response.json();
      if (!response.ok || body.ok === false) {
        throw new Error(body.error || "Request failed.");
      }
      return body;
    });
  }

  function loadSnapshot() {
    localStorage.setItem("da_profile", state.profile);
    return api(`/api/state?profile=${encodeURIComponent(state.profile)}`)
      .then((data) => {
        state.data = data;
        state.profile = data.profile;
        render();
      })
      .catch((error) => showError(error.message));
  }

  function post(path, payload) {
    state.saving = true;
    render();
    return api(path, {
      method: "POST",
      body: JSON.stringify({ profile: state.profile, ...payload }),
    })
      .then((data) => {
        state.data = data;
        state.profile = data.profile;
        state.saving = false;
        render();
      })
      .catch((error) => {
        state.saving = false;
        render();
        showError(error.message);
      });
  }

  function showError(message) {
    state.toast = message || "Something went wrong.";
    render();
    window.clearTimeout(showError.timer);
    showError.timer = window.setTimeout(() => {
      state.toast = "";
      render();
    }, 3600);
  }

  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function fmt(value, digits) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
    return Number(value).toFixed(digits);
  }

  function fmtInt(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
    return String(Math.round(Number(value)));
  }

  function metric(value, options) {
    const opts = options || {};
    const num = Number(value);
    let cls = "metric";
    if (opts.primary) cls += " primary";
    else if (num > 0 && opts.good !== false) cls += " good";
    else if (opts.warn) cls += " warn";
    const label = opts.integer ? fmtInt(value) : fmt(value, opts.digits ?? 1);
    const signed = opts.signed && num > 0 ? `+${label}` : label;
    return `<span class="${cls}">${signed}</span>`;
  }

  function posBadge(pos) {
    const cls = `pos-${String(pos || "").toLowerCase()}`;
    return `<span class="pos-badge ${cls}">${esc(pos || "-")}</span>`;
  }

  function button(label, action, extra) {
    const opts = extra || {};
    const disabled = opts.disabled ? " disabled" : "";
    const variant = opts.variant || "ghost";
    const attrs = opts.attrs || "";
    return `<button type="button" class="btn ${variant}" data-action="${esc(action)}"${disabled} ${attrs}>${esc(label)}</button>`;
  }

  function currentPlayers() {
    if (!state.data) return [];
    let rows = state.data.players.slice();
    if (!state.showDrafted) rows = rows.filter((player) => !player.drafted);
    if (state.position !== "ALL") rows = rows.filter((player) => player.position === state.position);
    const q = state.search.trim().toLowerCase();
    if (q) {
      rows = rows.filter((player) =>
        player.name.toLowerCase().includes(q) ||
        String(player.team || "").toLowerCase().includes(q)
      );
    }
    const sorters = {
      score: (a, b) => valueForSort(b.score) - valueForSort(a.score) || valueForSort(b.vor) - valueForSort(a.vor),
      vor: (a, b) => valueForSort(b.vor) - valueForSort(a.vor),
      points: (a, b) => valueForSort(b.points) - valueForSort(a.points),
      adp: (a, b) => adpForSort(a.adp) - adpForSort(b.adp),
      name: (a, b) => a.name.localeCompare(b.name),
    };
    rows.sort(sorters[state.sort] || sorters.score);
    return rows;
  }

  function valueForSort(value) {
    return value === null || value === undefined ? -999999 : Number(value);
  }

  function adpForSort(value) {
    return value === null || value === undefined ? 99999 : Number(value);
  }

  function render() {
    if (!state.data) {
      app.innerHTML = `
        <div class="loading-shell">
          <div class="brand-mark">DA</div>
          <div>
            <div class="loading-title">Draft Assistant</div>
            <div class="muted">Loading draft room...</div>
          </div>
        </div>`;
      return;
    }

    app.innerHTML = `
      <div class="app-shell">
        ${renderTopbar()}
        <div class="body">
          ${renderTeamPanel()}
          <main class="main">
            ${renderRecommendations()}
            ${renderToolbar()}
            ${renderPlayerTable()}
          </main>
        </div>
      </div>
      ${state.settingsOpen ? renderSettingsModal() : ""}
      ${state.toast ? `<div class="toast">${esc(state.toast)}</div>` : ""}
    `;
  }

  function renderTopbar() {
    const data = state.data;
    const draft = data.draft;
    const profiles = data.profiles || ["default"];
    const clockClass = draft.isMyPick ? "pick-clock mine" : "pick-clock";
    return `
      <header class="topbar">
        <div class="topbar-left">
          <div class="brand">
            <div class="brand-mark">DA</div>
            <div class="brand-title">
              <strong>Draft Assistant</strong>
              <span class="muted tiny">${esc(data.source.players)} players from ${esc(data.source.projectionsPath)}</span>
            </div>
          </div>
          <div class="divider"></div>
          <select class="profile-select" data-field="profile">
            ${profiles.map((profile) =>
              `<option value="${esc(profile)}" ${profile === data.profile ? "selected" : ""}>${esc(profile)}</option>`
            ).join("")}
          </select>
        </div>
        <div class="topbar-right">
          <div class="${clockClass}">
            <div>
              <div class="clock-label">${draft.isMyPick ? "Your pick" : `Team ${esc(draft.currentTeam)}`}</div>
              <div class="clock-value">Round ${esc(data.state.round)} / Pick ${esc(data.state.pickInRound)} of ${esc(data.config.teams)}</div>
            </div>
          </div>
          ${button("Settings", "open-settings")}
          ${button("Undo", "undo", { disabled: data.state.pickCount <= 0 })}
          ${button("Reset", "reset", { variant: "danger", disabled: data.state.pickCount <= 0 })}
        </div>
      </header>`;
  }

  function renderTeamPanel() {
    const data = state.data;
    const slots = buildSlots(data.config.roster);
    const assigned = assignRoster(slots, flattenRoster(data.roster));
    const needs = Object.entries(data.needs || {}).filter(([, count]) => count > 0);
    return `
      <aside class="team-panel">
        <div class="panel-head">
          <div class="eyebrow">My Team</div>
          <div class="muted tiny">${esc(data.state.myPicks.length)} / ${slots.length} roster spots filled</div>
        </div>
        <div class="team-slots">
          ${assigned.map(({ slot, player }) => `
            <div class="slot-row">
              <div class="slot-label">${esc(slot.label)}</div>
              <div class="slot-player">
                ${player ? `
                  <strong>${esc(player.name)}</strong>
                  <span>${esc(player.team || "-")} ${player.byeWeek ? `BYE ${esc(player.byeWeek)}` : ""}</span>
                ` : `<span class="muted">Open</span>`}
              </div>
            </div>
          `).join("")}
        </div>
        <div class="needs-box">
          <div class="eyebrow">Open Needs</div>
          <div class="needs-list">
            ${needs.length ? needs.map(([pos, count]) => `${posBadge(pos)} <span class="tiny muted">x${esc(count)}</span>`).join("") : `<span class="muted tiny">Starters filled</span>`}
          </div>
        </div>
        <div class="strategy-box">
          <div class="eyebrow">Next Turn</div>
          <div class="muted tiny" style="margin-top:7px;line-height:1.55">
            Pick ${esc(data.draft.nextMyPick)} now, then ${esc(data.draft.followingMyPick)}.
            ${esc(data.draft.picksUntilNext)} picks are projected before the board comes back.
          </div>
        </div>
      </aside>`;
  }

  function buildSlots(roster) {
    const slots = [];
    ["QB", "RB", "WR", "TE"].forEach((pos) => {
      for (let i = 0; i < Number(roster[pos] || 0); i += 1) slots.push({ label: pos, pos });
    });
    for (let i = 0; i < Number(roster.FLEX || 0); i += 1) slots.push({ label: "FLX", pos: "FLEX" });
    ["K", "DST"].forEach((pos) => {
      for (let i = 0; i < Number(roster[pos] || 0); i += 1) slots.push({ label: pos, pos });
    });
    for (let i = 0; i < Number(roster.BN || roster.BENCH || 0); i += 1) slots.push({ label: "BN", pos: null });
    return slots;
  }

  function flattenRoster(roster) {
    const players = [];
    ["QB", "RB", "WR", "TE", "K", "DST"].forEach((pos) => {
      (roster[pos] || []).forEach((player) => players.push(player));
    });
    return players;
  }

  function assignRoster(slots, players) {
    const remaining = players.slice();
    return slots.map((slot) => {
      let idx = -1;
      if (!slot.pos) idx = remaining.length ? 0 : -1;
      else if (slot.pos === "FLEX") idx = remaining.findIndex((player) => FLEX_POSITIONS.has(player.position));
      else idx = remaining.findIndex((player) => player.position === slot.pos);
      const player = idx >= 0 ? remaining.splice(idx, 1)[0] : null;
      return { slot, player };
    });
  }

  function renderRecommendations() {
    const recs = state.data.recommendations || [];
    const needs = state.data.needs || {};
    const best = recs[0];
    const bestNeed = recs.find((p) => needs[p.position] > 0 || (FLEX_POSITIONS.has(p.position) && needs.FLEX > 0)) || best;
    const scarce = recs.find((p) => Number(p.scarcity || 0) >= 5) || recs.find((p) => Number(p.vor || 0) >= 40);
    const waitRisk = recs.find((p) => Number(p.nextPickValue || 0) >= 5 || Number(p.scarcity || 0) >= 3);
    return `
      <section class="rec-strip">
        <div class="eyebrow">Recommendations</div>
        <div class="rec-grid">
          ${renderRecCard("Best Draft Score", best, "Highest blended score after VOR, scarcity, ADP timing, roster need, and bye checks.", true)}
          ${renderRecCard("Best By Need", bestNeed, bestNeed ? `${esc(bestNeed.reason)} with need x${fmt(bestNeed.needMultiplier, 2)}.` : "", false)}
          ${renderRecCard("Scarcity Watch", scarce, scarce ? `Same-position dropoff adds ${fmt(scarce.scarcity, 1)} points of urgency.` : "", false)}
          ${renderRecCard("Next Pick Risk", waitRisk, waitRisk ? `Expected next-turn value: ${fmt(waitRisk.nextPickValue, 1)}.` : "", false)}
        </div>
      </section>`;
  }

  function renderRecCard(label, player, reason, best) {
    if (!player) {
      return `
        <div class="rec-card">
          <div class="rec-label">${esc(label)}</div>
          <div class="muted tiny">No candidate available.</div>
        </div>`;
    }
    return `
      <div class="rec-card ${best ? "best" : ""}">
        <div class="rec-label">${esc(label)}</div>
        <div class="rec-name">${posBadge(player.position)}<span>${esc(player.name)}</span></div>
        <div class="metric-line">
          <span class="tiny muted">${esc(player.team || "-")}</span>
          ${metric(player.score, { primary: true, integer: true })}
          ${metric(player.vor, { signed: true, integer: true })}
          <span class="tiny muted">ADP ${fmt(player.adp, 1)}</span>
        </div>
        <div class="rec-reason">${reason}</div>
      </div>`;
  }

  function renderToolbar() {
    return `
      <section class="toolbar">
        <input class="search-input" data-field="search" value="${esc(state.search)}" placeholder="Search player or team">
        <div class="pos-tabs">
          ${POSITIONS.map((pos) => `
            <button class="pos-tab ${state.position === pos ? "active" : ""}" data-action="pos" data-pos="${esc(pos)}">${esc(pos)}</button>
          `).join("")}
        </div>
        <select class="field-select" data-field="sort">
          ${[
            ["score", "Draft Score"],
            ["vor", "VOR"],
            ["points", "Projected Points"],
            ["adp", "ADP"],
            ["name", "Name"],
          ].map(([value, label]) => `<option value="${value}" ${state.sort === value ? "selected" : ""}>${label}</option>`).join("")}
        </select>
        ${button(state.showDrafted ? "Hide Drafted" : "Show Drafted", "toggle-drafted")}
      </section>`;
  }

  function renderPlayerTable() {
    const rows = currentPlayers();
    return `
      <section class="table-wrap">
        <div class="player-grid">
          <div class="grid-row header">
            <div>#</div><div>Player</div><div>Pos</div><div>Team</div><div>Bye</div>
            <div style="text-align:right">Proj</div><div style="text-align:right">VOR</div>
            <div style="text-align:right">Gain</div><div style="text-align:right">Scarce</div>
            <div style="text-align:right">Need</div><div style="text-align:right">Score</div><div></div>
          </div>
          ${rows.length ? rows.map(renderPlayerRow).join("") : `<div class="empty-state">No players match the current filters.</div>`}
        </div>
      </section>`;
  }

  function renderPlayerRow(player, index) {
    const scoreMissing = player.score === null || player.score === undefined;
    const subline = player.drafted
      ? `Pick ${player.pickNumber}${player.myPick ? " - mine" : ""}`
      : `ADP ${fmt(player.adp, 1)} - ${esc(player.reason || player.slotType || "available")}`;
    return `
      <div class="grid-row player ${player.drafted ? "drafted" : ""}">
        <div class="rank">${index + 1}</div>
        <div class="player-cell">
          <div class="player-name"><span class="tier-dot"></span><span>${esc(player.name)}</span></div>
          <div class="subline">${subline}</div>
        </div>
        <div>${posBadge(player.position)}</div>
        <div class="muted">${esc(player.team || "-")}</div>
        <div class="mono muted">${esc(player.byeWeek || "-")}</div>
        <div>${metric(player.points, { integer: true, good: false })}</div>
        <div>${metric(player.vor, { signed: true, integer: true })}</div>
        <div>${metric(player.lineupGain, { integer: true, good: false })}</div>
        <div>${metric(player.scarcity, { integer: true, warn: Number(player.scarcity || 0) > 0 })}</div>
        <div>${scoreMissing ? `<span class="metric">-</span>` : metric(player.needMultiplier, { digits: 2, good: false })}</div>
        <div>${scoreMissing ? `<span class="metric">-</span>` : metric(player.score, { primary: true, integer: true })}</div>
        <div class="row-action">
          ${player.drafted ? `<span class="tiny muted">Drafted</span>` : button("Pick", "pick", { variant: "primary", attrs: `data-key="${esc(player.key)}"` })}
        </div>
      </div>`;
  }

  function renderSettingsModal() {
    const config = state.data.config;
    const roster = config.roster || {};
    const draft = config.draft || {};
    return `
      <div class="modal-backdrop" data-action="close-settings">
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="settings-title" data-modal="settings">
          <div class="modal-head">
            <div>
              <div class="modal-title" id="settings-title">League Settings</div>
              <div class="muted tiny">${esc(state.data.profile)} profile</div>
            </div>
            ${button("Close", "close-settings")}
          </div>
          <form data-form="settings">
            <div class="modal-body">
              <div class="settings-grid">
                ${field("Teams", "teams", config.teams, 4, 20)}
                ${field("Draft Slot", "slot", draft.slot || 1, 1, config.teams)}
                ${field("Monte Carlo Sims", "monte_carlo_sims", draft.monte_carlo_sims || 250, 0, 1000)}
                ${field("ADP Noise", "adp_noise", draft.adp_noise || 8, 0, 40, "0.5")}
                ${["QB", "RB", "WR", "TE", "FLEX", "K", "DST", "BN"].map((pos) =>
                  field(pos === "BN" ? "Bench" : pos, `roster_${pos}`, roster[pos] || 0, 0, 15)
                ).join("")}
              </div>
            </div>
            <div class="modal-actions">
              ${button("Cancel", "close-settings")}
              <button class="btn primary" type="submit">${state.saving ? "Saving..." : "Save Settings"}</button>
            </div>
          </form>
        </div>
      </div>`;
  }

  function field(label, name, value, min, max, step) {
    return `
      <div class="field">
        <label for="${esc(name)}">${esc(label)}</label>
        <input class="field-input" id="${esc(name)}" name="${esc(name)}" type="number"
          value="${esc(value)}" min="${esc(min)}" max="${esc(max)}" step="${esc(step || 1)}">
      </div>`;
  }

  function settingsPayload(form) {
    const fd = new FormData(form);
    const current = state.data.config;
    return {
      teams: Number(fd.get("teams")),
      roster: {
        QB: Number(fd.get("roster_QB")),
        RB: Number(fd.get("roster_RB")),
        WR: Number(fd.get("roster_WR")),
        TE: Number(fd.get("roster_TE")),
        FLEX: Number(fd.get("roster_FLEX")),
        K: Number(fd.get("roster_K")),
        DST: Number(fd.get("roster_DST")),
        BN: Number(fd.get("roster_BN")),
      },
      scoring: current.scoring,
      draft: {
        ...(current.draft || {}),
        slot: Number(fd.get("slot")),
        monte_carlo_sims: Number(fd.get("monte_carlo_sims")),
        adp_noise: Number(fd.get("adp_noise")),
      },
    };
  }

  document.addEventListener("click", (event) => {
    const actionEl = event.target.closest("[data-action]");
    if (!actionEl) return;
    const action = actionEl.dataset.action;
    if (action === "pick") {
      post("/api/pick", { key: actionEl.dataset.key });
    } else if (action === "undo") {
      post("/api/undo", { steps: 1 });
    } else if (action === "reset") {
      if (window.confirm("Reset this draft state?")) post("/api/reset", {});
    } else if (action === "toggle-drafted") {
      state.showDrafted = !state.showDrafted;
      render();
    } else if (action === "pos") {
      state.position = actionEl.dataset.pos || "ALL";
      render();
    } else if (action === "open-settings") {
      state.settingsOpen = true;
      render();
    } else if (action === "close-settings") {
      if (event.target.classList.contains("modal-backdrop") || actionEl.dataset.action === "close-settings") {
        state.settingsOpen = false;
        render();
      }
    }
  });

  document.addEventListener("change", (event) => {
    const field = event.target.dataset.field;
    if (field === "profile") {
      state.profile = event.target.value;
      state.data = null;
      render();
      loadSnapshot();
    } else if (field === "sort") {
      state.sort = event.target.value;
      render();
    }
  });

  document.addEventListener("input", (event) => {
    if (event.target.dataset.field === "search") {
      state.search = event.target.value;
      render();
      const input = document.querySelector("[data-field='search']");
      if (input) {
        input.focus();
        input.setSelectionRange(state.search.length, state.search.length);
      }
    }
  });

  document.addEventListener("submit", (event) => {
    if (event.target.dataset.form !== "settings") return;
    event.preventDefault();
    const config = settingsPayload(event.target);
    state.settingsOpen = false;
    post("/api/config", { config });
  });

  loadSnapshot();
})();
