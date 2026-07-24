import { useState } from "react";
import api from "../api/client";
import { ROLE_COLORS, ROLE_EMOJIS, formatRole } from "../roleStyles";
import CreatePersonaPanel from "./CreatePersonaPanel";

const MAX_CHARS = 2000;

// Fonts loaded in index.html — used only on this landing view.
const FONT_HEAD = "'Space Grotesk', system-ui, sans-serif";
const FONT_BODY = "'IBM Plex Sans', system-ui, sans-serif";
const FONT_MONO = "'IBM Plex Mono', ui-monospace, monospace";

const ALL = [
  "ai_architect",
  "solution_architect",
  "data_engineer",
  "data_scientist",
  "ai_engineer",
  "solution_engineer",
  "ui_builder",
  "project_manager",
];

const TEAM_MODES = [
  { value: "auto", icon: "🤖", label: "AI picks the team",
    desc: "Recommended — we assemble the right specialists for your problem." },
  { value: "manual", icon: "✋", label: "I'll pick the team",
    desc: "Choose your own specialists before the run." },
];

const DEPTH_TIERS = [
  { value: "shallow",  icon: "⚡", label: "Shallow",  desc: "Faster, lighter pass · ~10 min" },
  { value: "standard", icon: "◆", label: "Standard", desc: "Balanced depth · ~20 min" },
  { value: "deep",     icon: "🔍", label: "Deep",     desc: "Slower, more thorough · ~30 min" },
];

// Scoped focus-ring + placeholder styling (token-derived, injected once).
if (typeof document !== "undefined" && !document.getElementById("landing-styles")) {
  const s = document.createElement("style");
  s.id = "landing-styles";
  s.textContent = `
    .li-ta:focus { border-color: var(--accent) !important;
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 30%, transparent); }
    .li-ta::placeholder { color: var(--faint); }
    .li-card:hover { border-color: var(--border-strong); }
  `;
  document.head.appendChild(s);
}

export default function ChatInterface({ onSessionCreated }) {
  const [problem,     setProblem]    = useState("");
  const [loading,     setLoading]    = useState(false);
  const [error,       setError]      = useState(null);
  const [rosterMode,  setRosterMode] = useState("auto");
  const [selected,    setSelected]   = useState(new Set(ALL));
  // Pre-session custom personas
  const [customPersonas,      setCustomPersonas]      = useState([]);
  const [showPersonaCreator,  setShowPersonaCreator]  = useState(false);
  const [depthTier,           setDepthTier]           = useState("standard");

  const toggleRole = (role) => {
    if (role === "project_manager") return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(role)) next.delete(role);
      else next.add(role);
      return next;
    });
  };

  const manualInvalid = rosterMode === "manual" && selected.size < 3;

  // Called when CreatePersonaPanel confirms a persona in pre-session mode
  const handlePersonaConfirmed = (personaDef) => {
    setCustomPersonas((prev) => {
      // Dedup by role
      const rest = prev.filter((p) => p.role !== personaDef.role);
      return [...rest, personaDef];
    });
    setShowPersonaCreator(false);
  };

  const removePersona = (role) => {
    setCustomPersonas((prev) => prev.filter((p) => p.role !== role));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!problem.trim() || loading || manualInvalid) return;

    setLoading(true);
    setError(null);

    try {
      const payload = { problem_statement: problem.trim(), depth_tier: depthTier };
      if (rosterMode === "manual") {
        payload.roster = [...selected];
      }
      if (customPersonas.length > 0) {
        payload.custom_personas = customPersonas;
      }
      const { data } = await api.post("/api/sessions", payload);
      onSessionCreated(data.session_id);
    } catch (err) {
      setError(err.response?.data?.detail ?? "Failed to create session");
    } finally {
      setLoading(false);
    }
  };

  // ── Reusable styles ────────────────────────────────────────────────────────
  const monoLabel = {
    fontFamily: FONT_MONO, fontSize: 11, letterSpacing: "0.18em",
    textTransform: "uppercase", color: "var(--faint)", margin: "0 0 10px",
  };
  const card = (isSel) => ({
    flex: 1, textAlign: "left", cursor: "pointer",
    background: isSel ? "color-mix(in srgb, var(--accent) 12%, var(--surface-2))" : "var(--surface-2)",
    border: isSel ? "1.5px solid var(--accent)" : "1.5px solid var(--line, var(--border))",
    borderRadius: 12, padding: "12px 14px", transition: "border-color .15s, background .15s",
  });
  const cardTitle = { fontSize: 14, fontWeight: 600, color: "var(--text)", fontFamily: FONT_BODY };
  const cardDesc  = { fontSize: 12, color: "var(--dim)", marginTop: 4, lineHeight: 1.4 };

  const canSubmit = problem.trim().length > 0 && !loading && !manualInvalid;

  return (
    <div style={{ maxWidth: 680, margin: "56px auto 80px", padding: "0 20px", fontFamily: FONT_BODY }}>
      {/* 1 — Eyebrow */}
      <p style={{
        fontFamily: FONT_MONO, fontSize: 12, letterSpacing: "0.24em",
        textTransform: "uppercase", color: "var(--accent)", margin: 0,
      }}>
        Multi-Agent Consulting Simulator
      </p>

      {/* 2 — Headline */}
      <h1 style={{
        fontFamily: FONT_HEAD, fontWeight: 600, fontSize: 40, lineHeight: 1.08,
        letterSpacing: "-0.01em", color: "var(--text)", maxWidth: "15ch", margin: "14px 0 0",
      }}>
        Bring a problem. Get a room of specialists.
      </h1>

      {/* 3 — Subtitle */}
      <p style={{ fontSize: 16, color: "var(--dim)", maxWidth: "52ch", lineHeight: 1.55, margin: "14px 0 28px" }}>
        Describe your technical problem and a team of AI specialist personas will
        deliberate it in real time — then hand you an auditable solution document.
      </p>

      <form onSubmit={handleSubmit}>
        {/* 4 — Problem textarea + counter */}
        <textarea
          className="li-ta"
          value={problem}
          onChange={(e) => setProblem(e.target.value.slice(0, MAX_CHARS))}
          placeholder="e.g. We need a real-time ML feature store that serves 50k predictions/sec…"
          disabled={loading}
          style={{
            width: "100%", minHeight: 130, boxSizing: "border-box",
            background: "var(--surface)", color: "var(--text)",
            border: "1px solid var(--line, var(--border))", borderRadius: 12,
            padding: "14px 16px", fontFamily: FONT_MONO, fontSize: 13.5, lineHeight: 1.6,
            resize: "vertical", outline: "none", transition: "border-color .15s, box-shadow .15s",
          }}
        />
        <div style={{
          textAlign: "right", fontFamily: FONT_MONO, fontSize: 12, marginTop: 6,
          color: problem.length >= MAX_CHARS ? "var(--error)" : "var(--faint)",
        }}>
          {problem.length} / {MAX_CHARS}
        </div>

        {/* 5 — Team assembly */}
        <div style={{ marginTop: 24 }}>
          <p style={monoLabel}>Team assembly</p>
          <div style={{ display: "flex", gap: 12 }}>
            {TEAM_MODES.map((m) => (
              <button type="button" key={m.value} className="li-card"
                onClick={() => setRosterMode(m.value)} style={card(rosterMode === m.value)}>
                <div style={cardTitle}>{m.icon} {m.label}</div>
                <div style={cardDesc}>{m.desc}</div>
              </button>
            ))}
          </div>

          {/* Manual roster picker — preserved behavior */}
          {rosterMode === "manual" && (
            <div style={{ marginTop: 14 }}>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {ALL.map((role) => {
                  const isPM = role === "project_manager";
                  const isSelected = selected.has(role);
                  const bg = ROLE_COLORS[role] ?? "var(--surface-2)";
                  return (
                    <div key={role} onClick={() => toggleRole(role)}
                      style={{
                        display: "flex", alignItems: "center", gap: 5,
                        padding: "6px 14px", borderRadius: 20, background: bg,
                        border: isSelected ? "2px solid var(--accent)" : "2px solid transparent",
                        opacity: isSelected ? 1 : 0.45, cursor: isPM ? "default" : "pointer",
                        fontSize: 13, fontWeight: 500, color: "var(--text)", userSelect: "none",
                        transition: "opacity 0.15s, border 0.15s",
                      }}>
                      <span>{ROLE_EMOJIS[role]}</span>
                      <span>{formatRole(role)}</span>
                      {isPM ? <span style={{ fontSize: 11, marginLeft: 2 }}>🔒</span>
                        : isSelected ? <span style={{ fontSize: 11, marginLeft: 2 }}>✓</span> : null}
                    </div>
                  );
                })}
              </div>
              <p style={{ fontSize: 11, color: "var(--faint)", marginTop: 6 }}>
                Project Manager is always included.
              </p>
              {manualInvalid && (
                <p style={{ fontSize: 13, color: "var(--danger)", marginTop: 6 }}>
                  Pick at least 2 experts besides the Project Manager.
                </p>
              )}
            </div>
          )}

          {/* Custom expert section — preserved behavior (both modes) */}
          <div style={{ marginTop: 12 }}>
            {customPersonas.length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
                {customPersonas.map((p) => (
                  <div key={p.role} style={{
                    display: "flex", alignItems: "center", gap: 6, padding: "5px 10px",
                    borderRadius: 20, background: p.color || "var(--border)",
                    fontSize: 13, color: "var(--text)", border: "1px solid var(--tint-08)",
                  }}>
                    <span>{p.emoji || "🤖"}</span>
                    <span style={{ fontWeight: 500 }}>{p.display_name}</span>
                    <button type="button" onClick={() => removePersona(p.role)}
                      style={{
                        background: "none", border: "none", cursor: "pointer",
                        fontSize: 15, color: "var(--muted)", padding: "0 0 0 2px",
                        lineHeight: 1, fontWeight: 700,
                      }} title={`Remove ${p.display_name}`}>×</button>
                  </div>
                ))}
              </div>
            )}
            {showPersonaCreator ? (
              <CreatePersonaPanel mode="pre-session"
                onPersonaConfirmed={handlePersonaConfirmed}
                onCancel={() => setShowPersonaCreator(false)} />
            ) : (
              <button type="button" onClick={() => setShowPersonaCreator(true)}
                style={{
                  display: "flex", alignItems: "center", gap: 6, padding: "6px 14px",
                  borderRadius: 8, border: "1px dashed var(--border-strong)", background: "var(--bg)",
                  color: "var(--slate)", fontSize: 13, cursor: "pointer", fontWeight: 500,
                }}>
                ✚ Add a custom expert
              </button>
            )}
          </div>
        </div>

        {/* 6 — Analysis depth (3 tiers) */}
        <div style={{ marginTop: 24 }}>
          <p style={monoLabel}>Analysis depth</p>
          <div style={{ display: "flex", gap: 12 }}>
            {DEPTH_TIERS.map((t) => (
              <button type="button" key={t.value} className="li-card"
                onClick={() => setDepthTier(t.value)} style={card(depthTier === t.value)}>
                <div style={cardTitle}>{t.icon} {t.label}</div>
                <div style={cardDesc}>{t.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* 7 — Footer */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          gap: 16, marginTop: 28,
        }}>
          <span style={{ fontSize: 13, color: "var(--faint)", maxWidth: "42ch", lineHeight: 1.45 }}>
            You'll review the recommended team and depth before anything runs.
          </span>
          <button type="submit" disabled={!canSubmit}
            style={{
              fontFamily: FONT_HEAD, fontWeight: 600, fontSize: 15,
              padding: "12px 22px", borderRadius: 11, border: "none",
              background: "var(--accent)", color: "var(--accent-text)",
              cursor: canSubmit ? "pointer" : "not-allowed",
              opacity: canSubmit ? 1 : 0.45, whiteSpace: "nowrap",
              transition: "opacity .15s",
            }}>
            {loading ? "Assembling…" : "Assemble the room →"}
          </button>
        </div>
      </form>

      {error && (
        <p style={{ marginTop: 16, color: "var(--error)" }}>Error: {error}</p>
      )}
    </div>
  );
}
