/* Social Sim dashboard app.
 *
 * Polls the Supabase REST endpoint (entity_state) every ~45s and renders a
 * dashboard of all 16 entities grouped by scenario. Dependency-free vanilla JS
 * for static hosting (e.g. Cloudflare Pages).
 *
 * The deployer sets window.SOCIAL_SIM_CONFIG (supabaseUrl + supabaseAnonKey)
 * in index.html. RLS grants the anon role SELECT-only on entity_state and
 * sim_turn_log.
 */

(function () {
  "use strict";

  const CFG = window.SOCIAL_SIM_CONFIG || {};

  // Scenario metadata (ids must match sim/personas.py SCENARIO_IDS).
  const SCENARIOS = [
    {
      id: "family",
      title: "Family household",
      blurb: "Whether to relocate the family for a parent's promotion.",
    },
    {
      id: "corporation",
      title: "Software team",
      blurb: "Ship on the client date, or slip to refactor a fragile core?",
    },
    {
      id: "university",
      title: "Research group",
      blurb: "How strongly to claim a gut–brain causal relationship.",
    },
    {
      id: "ward",
      title: "Therapeutic community",
      // ETHICS: ward-specific notice, visible in the scenario header.
      blurb:
        "Whether the daily community meeting should be mandatory or voluntary.",
      ethicsNotice:
        "This is a fictional therapeutic-community simulation (Maxwell Jones " +
        "tradition). It is about how a community discusses and resolves a shared " +
        "issue. It does not depict real patients, real institutions, diagnoses, " +
        "symptoms, self-harm, crisis content, or real clinical practice.",
    },
  ];

  const FICTION_NOTICE =
    "This scenario is an entirely fictional AI simulation. Not real people, " +
    "institutions, patients, or clinical/scientific practice.";

  const dashboard = document.getElementById("dashboard");
  const lastUpdated = document.getElementById("last-updated");
  const refreshBtn = document.getElementById("refresh-btn");
  const dryFlag = document.getElementById("dry-run-flag");

  function apiUrl(resource, query) {
    const base = `${CFG.supabaseUrl}/rest/v1/${resource}`;
    return query ? `${base}?${query}` : base;
  }

  async function fetchEntityStates() {
    if (!CFG.supabaseUrl || !CFG.supabaseAnonKey) {
      // No backend configured: show a friendly empty state with the skeleton.
      return { rows: [], offline: true };
    }
    const res = await fetch(apiUrl("entity_state", "select=*"), {
      headers: {
        apikey: CFG.supabaseAnonKey,
        Authorization: `Bearer ${CFG.supabaseAnonKey}`,
      },
    });
    if (!res.ok) throw new Error(`entity_state HTTP ${res.status}`);
    const rows = await res.json();
    return { rows: rows || [], offline: false };
  }

  function stressClass(stress) {
    if (stress === "high") return "stress-high";
    if (stress === "low") return "stress-low";
    return "stress-medium";
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function timeAgo(iso) {
    if (!iso) return "—";
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return "—";
    const mins = Math.round((Date.now() - then) / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    return `${hrs}h ago`;
  }

  function renderEntity(entity) {
    const stances = entity.stances || {};
    const stanceItems = Object.entries(stances)
      .map(
        ([target, stance]) =>
          `<li><span class="stance-target">${escapeHtml(target)}</span>` +
          `<span class="stance-text">${escapeHtml(stance)}</span></li>`
      )
      .join("");
    return (
      `<article class="entity-card">` +
      `<header class="entity-head">` +
      `<h3 class="entity-name">${escapeHtml(entity.entity_id)}</h3>` +
      `<span class="stress-pill ${stressClass(entity.stress)}">${escapeHtml(
        entity.stress || "—"
      )} stress</span>` +
      `</header>` +
      `<p class="mood"><span class="label">Mood</span> ${escapeHtml(
        entity.mood || "—"
      )}</p>` +
      `<div class="stances">` +
      `<span class="label">Stance toward each peer</span>` +
      `<ul>${stanceItems || "<li><em>—</em></li>"}</ul>` +
      `</div>` +
      `<p class="last-utterance"><span class="label">Last said</span> ` +
      `<q>${escapeHtml(entity.last_utterance || "—")}</q></p>` +
      `<p class="last-turn"><span class="label">Updated</span> ${timeAgo(
        entity.last_turn_ts
      )}</p>` +
      `</article>`
    );
  }

  function renderScenario(scenario, entities) {
    const isWard = scenario.id === "ward";
    const ethics = isWard
      ? `<div class="scenario-ethics ward-ethics">${escapeHtml(
          scenario.ethicsNotice
        )}</div>`
      : `<div class="scenario-ethics">${escapeHtml(FICTION_NOTICE)}</div>`;
    const cards =
      entities.map(renderEntity).join("") ||
      `<p class="empty">No entities yet — the simulation may not have completed its first cycle.</p>`;
    return (
      `<section class="scenario" id="scenario-${scenario.id}">` +
      `<header class="scenario-header">` +
      `<h2>${escapeHtml(scenario.title)}</h2>` +
      `<p class="scenario-blurb">${escapeHtml(scenario.blurb)}</p>` +
      `<p class="fiction-inline">⚠️ ${escapeHtml(FICTION_NOTICE)}</p>` +
      ethics +
      `</header>` +
      `<div class="entity-grid">${cards}</div>` +
      `</section>`
    );
  }

  function render({ rows, offline }) {
    const byScenario = {};
    for (const r of rows || []) {
      (byScenario[r.scenario_id] = byScenario[r.scenario_id] || []).push(r);
    }
    const html = SCENARIOS.map((s) =>
      renderScenario(s, byScenario[s.id] || [])
    ).join("");
    let prefix = "";
    if (offline) {
      prefix =
        `<div class="offline-note">No Supabase backend configured ` +
        `(set <code>window.SOCIAL_SIM_CONFIG</code> in index.html). ` +
        `Showing the dashboard skeleton.</div>`;
      dryFlag.hidden = false;
    } else {
      dryFlag.hidden = true;
    }
    dashboard.innerHTML = prefix + html;
    lastUpdated.textContent = offline
      ? "Skeleton view"
      : `Updated ${new Date().toLocaleTimeString()}`;
  }

  async function tick() {
    try {
      const data = await fetchEntityStates();
      render(data);
    } catch (err) {
      dashboard.innerHTML =
        `<div class="error">Could not load the simulation feed: ` +
        `${escapeHtml(err.message)}</div>`;
      lastUpdated.textContent = "Update failed";
    }
  }

  refreshBtn.addEventListener("click", tick);

  // Initial render + polling every pollSeconds (~45s).
  tick();
  const pollMs = (CFG.pollSeconds || 45) * 1000;
  setInterval(tick, pollMs);
})();
