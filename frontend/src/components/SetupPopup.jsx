import { useEffect, useMemo, useState } from "react";
import api from "../api/client";
import { formatRole, getRoleEmoji } from "../roleStyles";

// ── V5-C: pre-run setup popup (bench approval) ────────────────────────────────
// Self-contained DARK modal over the (light) app. All colors are CSS variables
// scoped to `.v5c-setup-overlay` so the dark styling neither leaks out nor is
// affected by the app's light theme / OS color-scheme. The token NAMES mirror
// the mock (--bg / --surface / --text / --l1|l2|l3 / --accent …) so a future
// full dark-theme conversion is a token remap, not a rewrite.

const CSS = `
.v5c-setup-overlay{
  --bg:#0b0f1a; --surface:#141b2b; --surface-2:#1b2334; --row:#161e2f;
  --border:#2a3348; --border-strong:#3a475f;
  --text:#e8eef9; --muted:#93a1ba; --faint:#6b7890;
  --track:#28324a;
  --l1:#64748b; --l2:#2dd4bf; --l3:#f59e0b;         /* depth ramp: slate → teal → amber */
  --accent:#6366f1; --accent-hover:#4f46e5; --accent-text:#ffffff;
  --edited:#fbbf24;
  position:fixed; inset:0; z-index:1000;
  display:flex; align-items:center; justify-content:center; padding:24px;
  background:rgba(4,7,14,.68); backdrop-filter:blur(3px);
  font-family:system-ui,'Segoe UI',Roboto,sans-serif;
  color:var(--text); letter-spacing:.1px;
}
.v5c-setup-card{
  width:100%; max-width:720px; max-height:90vh; overflow:auto;
  background:var(--surface); border:1px solid var(--border);
  border-radius:16px; box-shadow:0 24px 64px rgba(0,0,0,.55);
}
.v5c-setup-hd{ padding:22px 26px 18px; border-bottom:1px solid var(--border); }
.v5c-eyebrow{ font-size:11px; font-weight:700; letter-spacing:1.6px;
  text-transform:uppercase; color:var(--accent); margin:0 0 6px; }
.v5c-title{ font-size:22px; font-weight:650; color:var(--text); margin:0; }
.v5c-brief{ font-size:13px; line-height:1.5; color:var(--muted);
  margin:10px 0 0; }
.v5c-body{ padding:20px 26px; }
.v5c-sect-label{ font-size:11px; font-weight:700; letter-spacing:1.2px;
  text-transform:uppercase; color:var(--faint); margin:0 0 10px; }

/* Tier selector */
.v5c-tiers{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }
.v5c-tier{ position:relative; text-align:left; cursor:pointer;
  background:var(--surface-2); border:1.5px solid var(--border);
  border-radius:11px; padding:12px 13px; transition:border-color .15s, background .15s; }
.v5c-tier:hover{ border-color:var(--border-strong); }
.v5c-tier.sel{ border-color:var(--accent); background:rgba(99,102,241,.12); }
.v5c-tier-name{ font-size:14px; font-weight:650; text-transform:capitalize; }
.v5c-tier-budget{ font-size:12px; color:var(--muted); margin-top:3px; }
.v5c-rec-badge{ position:absolute; top:9px; right:9px; font-size:9px;
  font-weight:700; letter-spacing:.6px; text-transform:uppercase;
  color:var(--l2); background:rgba(45,212,191,.13); padding:2px 6px; border-radius:5px; }
.v5c-tier-reason{ font-size:12px; color:var(--muted); margin:10px 2px 0; line-height:1.45; }

/* Expert table */
.v5c-table{ margin-top:22px; }
.v5c-row{ display:flex; align-items:center; gap:14px;
  background:var(--row); border:1px solid var(--border);
  border-radius:10px; padding:11px 13px; margin-bottom:8px; }
.v5c-row-main{ flex:1; min-width:0; }
.v5c-role{ font-size:14px; font-weight:600; color:var(--text);
  display:flex; align-items:center; gap:7px; }
.v5c-edited{ font-size:11px; font-weight:600; color:var(--edited); letter-spacing:.2px; }
.v5c-reason{ font-size:12px; color:var(--muted); margin-top:2px; line-height:1.4;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.v5c-meter{ display:flex; gap:3px; }
.v5c-seg{ width:16px; height:8px; border-radius:2px; background:var(--track);
  transition:background .18s; }
.v5c-level-sel{ background:var(--surface-2); color:var(--text);
  border:1px solid var(--border-strong); border-radius:7px;
  padding:6px 8px; font-size:13px; font-weight:600; cursor:pointer; outline:none; }

/* Legend */
.v5c-legend{ display:flex; gap:16px; margin-top:14px; padding-top:2px; }
.v5c-leg{ display:flex; align-items:center; gap:6px; font-size:11px; color:var(--muted); }
.v5c-dot{ width:10px; height:10px; border-radius:3px; }

/* Footer */
.v5c-ft{ display:flex; align-items:center; gap:12px;
  padding:16px 26px; border-top:1px solid var(--border); }
.v5c-summary{ flex:1; font-size:13px; color:var(--muted); }
.v5c-summary b{ color:var(--text); font-weight:650; }
.v5c-reset{ background:none; border:1px solid var(--border-strong); color:var(--muted);
  border-radius:8px; padding:9px 14px; font-size:13px; font-weight:500; cursor:pointer; }
.v5c-reset:hover{ color:var(--text); border-color:var(--faint); }
.v5c-start{ background:var(--accent); color:var(--accent-text); border:none;
  border-radius:8px; padding:10px 22px; font-size:14px; font-weight:650; cursor:pointer;
  transition:background .15s; }
.v5c-start:hover{ background:var(--accent-hover); }
.v5c-start:disabled{ opacity:.6; cursor:not-allowed; }
/* V5-D: saved specialists library (display-only) — reuses the dark tokens */
.v5c-lib{ margin-top:22px; padding-top:18px; border-top:1px solid var(--border); }
.v5c-lib-empty{ font-size:13px; color:var(--faint); font-style:italic; margin:2px 0 0; }
.v5c-lib-item{ display:flex; align-items:center; gap:10px;
  background:var(--surface-2); border:1px solid var(--border);
  border-radius:9px; padding:9px 11px; margin-bottom:7px; }
.v5c-lib-emoji{ font-size:15px; }
.v5c-lib-main{ flex:1; min-width:0; }
.v5c-lib-name{ font-size:13px; font-weight:600; color:var(--text); }
.v5c-lib-meta{ font-size:11px; color:var(--muted); margin-top:1px;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.v5c-lib-lvl{ font-size:11px; font-weight:700; color:var(--l2);
  background:rgba(45,212,191,.12); padding:2px 7px; border-radius:5px; }
.v5c-err{ color:#fca5a5; font-size:13px; padding:0 26px 14px; }
.v5c-busy{ padding:44px 26px; text-align:center; color:var(--muted);
  font-size:15px; font-style:italic; }
`;

const FILL = { L1: 1, L2: 2, L3: 3 };
const LEVEL_VAR = { L1: "--l1", L2: "--l2", L3: "--l3" };

function DepthMeter({ level }) {
  const filled = FILL[level] || 1;
  return (
    <div className="v5c-meter" aria-label={`depth ${level}`}>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="v5c-seg"
          style={{ background: i < filled ? `var(${LEVEL_VAR[level]})` : "var(--track)" }}
        />
      ))}
    </div>
  );
}

export default function SetupPopup({ sessionId, data }) {
  const {
    brief = "",
    recommended_tier = "standard",
    tier_reason = "",
    seats = [],
    options = { tiers: ["shallow", "standard", "deep"], levels: ["L1", "L2", "L3"] },
    tier_budgets = {},
  } = data || {};

  // Recommended level per role (baseline for "· edited" detection + reset).
  const recLevels = useMemo(() => {
    const m = {};
    seats.forEach((s) => { m[s.role] = s.recommended_level; });
    return m;
  }, [seats]);

  const [tier, setTier] = useState(recommended_tier);
  const [levels, setLevels] = useState(recLevels);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  // V5-D: the user's saved specialists — DISPLAY ONLY (no click-to-add yet).
  const [library, setLibrary] = useState(null); // null = loading, [] = empty
  useEffect(() => {
    let alive = true;
    api.get("/api/library/personas")
      .then((res) => { if (alive) setLibrary(res.data?.personas ?? []); })
      .catch(() => { if (alive) setLibrary([]); });
    return () => { alive = false; };
  }, []);

  const minutes = (t) => {
    const s = tier_budgets[t];
    return s ? Math.round(s / 60) : { shallow: 10, standard: 20, deep: 30 }[t] ?? "?";
  };

  const tierEdited = tier !== recommended_tier;
  const anyEdited = tierEdited || seats.some((s) => levels[s.role] !== recLevels[s.role]);

  const reset = () => { setTier(recommended_tier); setLevels(recLevels); };

  const start = async () => {
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      // Response contract defined by Part 1 (_resolve_setup_choice parses a JSON
      // string): OMIT unchanged fields so the backend logs "recommended" vs
      // "user override" accurately. Only send what the user actually changed.
      const payload = { type: "setup" };
      if (tier !== recommended_tier) payload.tier = tier;
      const changed = {};
      seats.forEach((s) => {
        if (levels[s.role] !== recLevels[s.role]) changed[s.role] = levels[s.role];
      });
      if (Object.keys(changed).length) payload.levels = changed;
      // Reuse the SAME /respond resume endpoint as escalation/questionnaire.
      await api.post(`/api/sessions/${sessionId}/respond`, { answer: JSON.stringify(payload) });
      // Do not clear here — the run resumes; App hides the popup on setup_applied.
    } catch (err) {
      setError(err.response?.data?.detail ?? "Failed to start the run");
      setSubmitting(false);
    }
  };

  return (
    <div className="v5c-setup-overlay">
      <style>{CSS}</style>
      <div className="v5c-setup-card">
        <div className="v5c-setup-hd">
          <p className="v5c-eyebrow">Pre-run setup</p>
          <h2 className="v5c-title">Assemble the room</h2>
          {brief && <p className="v5c-brief">{brief}</p>}
        </div>

        {submitting ? (
          <div className="v5c-busy">Assembling the room…</div>
        ) : (
          <>
            <div className="v5c-body">
              {/* Tier selector */}
              <p className="v5c-sect-label">Depth tier · clock budget</p>
              <div className="v5c-tiers">
                {options.tiers.map((t) => (
                  <button
                    key={t}
                    className={`v5c-tier${tier === t ? " sel" : ""}`}
                    onClick={() => setTier(t)}
                  >
                    {t === recommended_tier && <span className="v5c-rec-badge">Rec</span>}
                    <div className="v5c-tier-name">{t}</div>
                    <div className="v5c-tier-budget">~{minutes(t)} min</div>
                  </button>
                ))}
              </div>
              {tier_reason && <p className="v5c-tier-reason">{tier_reason}</p>}

              {/* Expert table */}
              <div className="v5c-table">
                <p className="v5c-sect-label">The room · {seats.length} experts</p>
                {seats.map((s) => {
                  const lvl = levels[s.role] || s.recommended_level;
                  const edited = lvl !== recLevels[s.role];
                  return (
                    <div className="v5c-row" key={s.role}>
                      <DepthMeter level={lvl} />
                      <div className="v5c-row-main">
                        <div className="v5c-role">
                          <span>{getRoleEmoji(s.role)}</span>
                          {formatRole(s.role)}
                          {edited && <span className="v5c-edited">· edited</span>}
                        </div>
                        {s.reason && <div className="v5c-reason" title={s.reason}>{s.reason}</div>}
                      </div>
                      <select
                        className="v5c-level-sel"
                        value={lvl}
                        onChange={(e) =>
                          setLevels((prev) => ({ ...prev, [s.role]: e.target.value }))
                        }
                      >
                        {options.levels.map((L) => (
                          <option key={L} value={L}>{L}</option>
                        ))}
                      </select>
                    </div>
                  );
                })}

                {/* Legend */}
                <div className="v5c-legend">
                  <span className="v5c-leg"><span className="v5c-dot" style={{ background: "var(--l1)" }} />L1 surface</span>
                  <span className="v5c-leg"><span className="v5c-dot" style={{ background: "var(--l2)" }} />L2 moderate</span>
                  <span className="v5c-leg"><span className="v5c-dot" style={{ background: "var(--l3)" }} />L3 deep · challenge</span>
                </div>
              </div>

              {/* V5-D: your saved specialists — DISPLAY ONLY (click-to-add is deferred) */}
              <div className="v5c-lib">
                <p className="v5c-sect-label">Your saved specialists</p>
                {library === null ? (
                  <p className="v5c-lib-empty">Loading…</p>
                ) : library.length === 0 ? (
                  <p className="v5c-lib-empty">
                    Specialists you save from a run will appear here.
                  </p>
                ) : (
                  library.map((p) => (
                    <div className="v5c-lib-item" key={p.id}>
                      <span className="v5c-lib-emoji">{getRoleEmoji(p.role)}</span>
                      <div className="v5c-lib-main">
                        <div className="v5c-lib-name">{p.display_name || formatRole(p.role)}</div>
                        <div className="v5c-lib-meta">
                          {p.domain}
                          {p.source_session_id
                            ? ` · saved from ${String(p.source_session_id).slice(0, 8)}…`
                            : ""}
                        </div>
                      </div>
                      <span className="v5c-lib-lvl">{p.default_level}</span>
                    </div>
                  ))
                )}
              </div>
            </div>

            {error && <div className="v5c-err">{error}</div>}

            <div className="v5c-ft">
              <div className="v5c-summary">
                <b>{seats.length}</b> experts · <b>{tier}</b> · ~<b>{minutes(tier)} min</b>
                {anyEdited && <span> · edited</span>}
              </div>
              <button className="v5c-reset" onClick={reset} disabled={!anyEdited}>
                Reset to recommended
              </button>
              <button className="v5c-start" onClick={start} disabled={submitting}>
                Start run →
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
