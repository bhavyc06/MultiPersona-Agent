import { useState } from "react";
import api from "../api/client";
import { ROLE_COLORS, ROLE_EMOJIS, formatRole } from "../roleStyles";
import CreatePersonaPanel from "./CreatePersonaPanel";

const MAX_CHARS = 2000;

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

export default function ChatInterface({ onSessionCreated }) {
  const [problem,     setProblem]    = useState("");
  const [loading,     setLoading]    = useState(false);
  const [error,       setError]      = useState(null);
  const [rosterMode,  setRosterMode] = useState("auto");
  const [selected,    setSelected]   = useState(new Set(ALL));
  // Pre-session custom personas
  const [customPersonas,      setCustomPersonas]      = useState([]);
  const [showPersonaCreator,  setShowPersonaCreator]  = useState(false);
  const [depthTier,           setDepthTier]           = useState("shallow");

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

  const pillActive = {
    background: "#1a56db", color: "#fff", border: "none",
    borderRadius: 20, padding: "6px 18px", fontSize: 14, cursor: "pointer", fontWeight: 600,
  };
  const pillInactive = {
    background: "#e2e8f0", color: "#475569", border: "none",
    borderRadius: 20, padding: "6px 18px", fontSize: 14, cursor: "pointer", fontWeight: 500,
  };

  return (
    <div style={{ maxWidth: 700, margin: "60px auto", fontFamily: "sans-serif" }}>
      <h1 style={{ marginBottom: 8 }}>Multi-Agent Consulting Simulator</h1>
      <p style={{ color: "#555", marginBottom: 24 }}>
        Describe your technical problem and AI specialist personas will collaborate in real time.
      </p>

      <form onSubmit={handleSubmit}>
        <textarea
          value={problem}
          onChange={(e) => setProblem(e.target.value.slice(0, MAX_CHARS))}
          placeholder="e.g. We need to build a real-time ML feature store that serves 50k predictions/sec..."
          rows={6}
          style={{
            width: "100%", padding: 12, fontSize: 15, borderRadius: 6,
            border: "1px solid #ccc", resize: "vertical", boxSizing: "border-box",
          }}
          disabled={loading}
        />

        {/* ── Roster picker ───────────────────────────────────────────────── */}
        <div style={{ marginTop: 16, marginBottom: 4 }}>
          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            <button type="button" style={rosterMode === "auto" ? pillActive : pillInactive}
              onClick={() => setRosterMode("auto")}>
              🤖 AI picks the team
            </button>
            <button type="button" style={rosterMode === "manual" ? pillActive : pillInactive}
              onClick={() => setRosterMode("manual")}>
              ✋ I'll pick the team
            </button>
          </div>

          {rosterMode === "manual" && (
            <div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {ALL.map((role) => {
                  const isPM = role === "project_manager";
                  const isSelected = selected.has(role);
                  const bg = ROLE_COLORS[role] ?? "#f1f5f9";
                  return (
                    <div
                      key={role}
                      onClick={() => toggleRole(role)}
                      style={{
                        display: "flex", alignItems: "center", gap: 5,
                        padding: "6px 14px", borderRadius: 20, background: bg,
                        border: isSelected ? `2px solid ${adjustColor(bg)}` : "2px solid transparent",
                        opacity: isSelected ? 1 : 0.45,
                        cursor: isPM ? "default" : "pointer",
                        fontSize: 13, fontWeight: 500, userSelect: "none",
                        transition: "opacity 0.15s, border 0.15s",
                      }}
                    >
                      <span>{ROLE_EMOJIS[role]}</span>
                      <span>{formatRole(role)}</span>
                      {isPM ? (
                        <span style={{ fontSize: 11, marginLeft: 2 }}>🔒</span>
                      ) : isSelected ? (
                        <span style={{ fontSize: 11, marginLeft: 2 }}>✓</span>
                      ) : null}
                    </div>
                  );
                })}
              </div>
              <p style={{ fontSize: 11, color: "#94a3b8", marginTop: 6 }}>
                Project Manager is always included.
              </p>
              {manualInvalid && (
                <p style={{ fontSize: 13, color: "#dc2626", marginTop: 6 }}>
                  Pick at least 2 experts besides the Project Manager.
                </p>
              )}
            </div>
          )}
        </div>

        {/* ── Custom expert section (available in both roster modes) ──────── */}
        <div style={{ marginTop: 12, marginBottom: 8 }}>
          {/* Existing custom persona chips */}
          {customPersonas.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
              {customPersonas.map((p) => (
                <div
                  key={p.role}
                  style={{
                    display: "flex", alignItems: "center", gap: 6,
                    padding: "5px 10px", borderRadius: 20,
                    background: p.color || "#e2e8f0",
                    fontSize: 13, border: "1px solid rgba(0,0,0,0.08)",
                  }}
                >
                  <span>{p.emoji || "🤖"}</span>
                  <span style={{ fontWeight: 500 }}>{p.display_name}</span>
                  <button
                    type="button"
                    onClick={() => removePersona(p.role)}
                    style={{
                      background: "none", border: "none", cursor: "pointer",
                      fontSize: 15, color: "#64748b", padding: "0 0 0 2px",
                      lineHeight: 1, fontWeight: 700,
                    }}
                    title={`Remove ${p.display_name}`}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Inline persona creator (toggleable) */}
          {showPersonaCreator ? (
            <CreatePersonaPanel
              mode="pre-session"
              onPersonaConfirmed={handlePersonaConfirmed}
              onCancel={() => setShowPersonaCreator(false)}
            />
          ) : (
            <button
              type="button"
              onClick={() => setShowPersonaCreator(true)}
              style={{
                display: "flex", alignItems: "center", gap: 6,
                padding: "6px 14px", borderRadius: 8,
                border: "1px dashed #cbd5e1", background: "#f8fafc",
                color: "#475569", fontSize: 13, cursor: "pointer",
                fontWeight: 500, transition: "background 0.15s",
              }}
            >
              ✚ Add a custom expert
            </button>
          )}
        </div>

        {/* ── Depth tier selector ─────────────────────────────────────────── */}
        <div style={{ marginTop: 12, marginBottom: 8 }}>
          <p style={{ fontSize: 13, color: "#475569", marginBottom: 6, fontWeight: 500 }}>
            Analysis depth
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            {[
              { value: "shallow", label: "Faster, lighter pass" },
              { value: "deep",    label: "Slower, more thorough" },
            ].map(({ value, label }) => (
              <button
                key={value}
                type="button"
                onClick={() => setDepthTier(value)}
                style={depthTier === value ? pillActive : pillInactive}
              >
                {value === "shallow" ? "⚡" : "🔍"} {label}
              </button>
            ))}
          </div>
        </div>

        {/* ── Submit row ──────────────────────────────────────────────────── */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 8 }}>
          <span style={{ fontSize: 12, color: problem.length >= MAX_CHARS ? "red" : "#888" }}>
            {problem.length} / {MAX_CHARS}
          </span>
          <button
            type="submit"
            disabled={loading || !problem.trim() || manualInvalid}
            style={{
              padding: "10px 28px", fontSize: 15, borderRadius: 6, border: "none",
              background: loading || manualInvalid ? "#aaa" : "#1a56db",
              color: "#fff",
              cursor: loading || manualInvalid ? "not-allowed" : "pointer",
            }}
          >
            {loading ? "Starting..." : "Submit Problem"}
          </button>
        </div>
      </form>

      {error && (
        <p style={{ marginTop: 16, color: "red" }}>Error: {error}</p>
      )}
    </div>
  );
}

// Darken a hex color slightly for selected-border contrast
function adjustColor(hex) {
  const n = parseInt(hex.replace("#", ""), 16);
  const r = Math.max(0, ((n >> 16) & 0xff) - 50);
  const g = Math.max(0, ((n >> 8) & 0xff) - 50);
  const b = Math.max(0, (n & 0xff) - 50);
  return `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}
