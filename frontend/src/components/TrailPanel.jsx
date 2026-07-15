// TrailPanel — read-only stenographer view for a completed session.
// Fetches GET /api/sessions/{id}/stenographer and displays the decision trail
// + transcript. Read-only: never POSTs, never touches deliberation.

import { useEffect, useState } from "react";

const PROVENANCE_COLOR = {
  moderator:             "#fce7f3",
  human:                 "#fce7f3",
  converged:             "#dcfce7",
  consensus_by_supervisor: "#dbeafe",
  converged_by_supervisor: "#dbeafe",
  ceiling:               "#fef3c7",
  budget_ceiling:        "#fef3c7",
  orchestrator:          "#ede9fe",
};

function provenanceColor(p) {
  return PROVENANCE_COLOR[p] ?? "#f1f5f9";
}

function ts(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch { return iso; }
}

function Badge({ label, color }) {
  return (
    <span style={{
      display: "inline-block",
      padding: "1px 7px",
      borderRadius: 4,
      fontSize: 10,
      fontWeight: 600,
      background: color ?? "#f1f5f9",
      color: "#374151",
      border: "1px solid rgba(0,0,0,.08)",
      textTransform: "uppercase",
      letterSpacing: "0.04em",
    }}>
      {label ?? "—"}
    </span>
  );
}

export default function TrailPanel({ sessionId }) {
  const [trail, setTrail]     = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [tab, setTab]         = useState("decisions"); // "decisions" | "messages"

  useEffect(() => {
    if (!sessionId) return;
    const token = localStorage.getItem("access_token");
    setLoading(true);
    setError(null);
    fetch(`/api/sessions/${sessionId}/stenographer`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(r => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then(data => { setTrail(data); setLoading(false); })
      .catch(e  => { setError(e.message); setLoading(false); });
  }, [sessionId]);

  if (loading) return (
    <div style={{ padding: 16, fontSize: 13, color: "#94a3b8" }}>Loading trail…</div>
  );
  if (error) return (
    <div style={{ padding: 16, fontSize: 13, color: "#ef4444" }}>Trail error: {error}</div>
  );
  if (!trail) return null;

  const ownerDecisions = trail.decisions.filter(
    d => d.provenance === "moderator" || d.provenance === "human"
  );
  const otherDecisions = trail.decisions.filter(
    d => d.provenance !== "moderator" && d.provenance !== "human"
  );

  return (
    <div style={{
      background: "#fff",
      border: "1px solid #e2e8f0",
      borderRadius: 10,
      overflow: "hidden",
    }}>
      {/* Header */}
      <div style={{
        padding: "10px 14px",
        background: "#f8fafc",
        borderBottom: "1px solid #e2e8f0",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
      }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "#374151" }}>
          📋 Decision Trail
        </span>
        <span style={{ fontSize: 11, color: "#94a3b8" }}>
          {trail.decisions.length} decisions · {trail.messages.length} messages
        </span>
      </div>

      {/* Haiku summary (if present) */}
      {trail.trail_summary && (
        <div style={{
          padding: "10px 14px",
          background: "#fffbeb",
          borderBottom: "1px solid #fef3c7",
          fontSize: 12,
          color: "#92400e",
          lineHeight: 1.5,
        }}>
          <strong>Summary:</strong> {trail.trail_summary}
        </div>
      )}

      {/* Owner rulings highlight (if any) */}
      {ownerDecisions.length > 0 && (
        <div style={{ padding: "10px 14px", borderBottom: "1px solid #fce7f3", background: "#fff7f9" }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#be185d", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Owner Rulings — Authoritative
          </div>
          {ownerDecisions.map(d => (
            <div key={d.id} style={{
              fontSize: 12, color: "#374151", marginBottom: 4,
              paddingLeft: 8, borderLeft: "3px solid #fbcfe8",
            }}>
              <span style={{ color: "#94a3b8", marginRight: 6 }}>{ts(d.created_at)}</span>
              {d.text}
            </div>
          ))}
        </div>
      )}

      {/* Tab bar */}
      <div style={{ display: "flex", borderBottom: "1px solid #e2e8f0" }}>
        {["decisions", "messages"].map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              flex: 1,
              padding: "8px 0",
              border: "none",
              borderBottom: tab === t ? "2px solid #6366f1" : "2px solid transparent",
              background: "none",
              cursor: "pointer",
              fontSize: 12,
              fontWeight: tab === t ? 700 : 400,
              color: tab === t ? "#6366f1" : "#6b7280",
            }}
          >
            {t === "decisions" ? `Decisions (${trail.decisions.length})` : `Transcript (${trail.messages.length})`}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div style={{ maxHeight: 400, overflowY: "auto" }}>
        {tab === "decisions" && (
          <div style={{ padding: "10px 14px" }}>
            {trail.decisions.length === 0 && (
              <p style={{ fontSize: 12, color: "#94a3b8", margin: 0 }}>No decisions recorded.</p>
            )}
            {trail.decisions.map(d => (
              <div key={d.id} style={{
                marginBottom: 10,
                padding: "8px 10px",
                borderRadius: 6,
                background: provenanceColor(d.provenance),
                border: "1px solid rgba(0,0,0,.06)",
              }}>
                <div style={{ display: "flex", gap: 6, marginBottom: 4, alignItems: "center" }}>
                  <Badge label={d.provenance ?? d.state} color={provenanceColor(d.provenance)} />
                  <Badge label={d.state} color={d.state === "locked" ? "#dcfce7" : "#fef3c7"} />
                  <span style={{ fontSize: 10, color: "#94a3b8", marginLeft: "auto" }}>{ts(d.created_at)}</span>
                </div>
                <div style={{ fontSize: 12, color: "#374151", lineHeight: 1.5 }}>{d.text}</div>
                <div style={{ fontSize: 10, color: "#9ca3af", marginTop: 3 }}>by {d.proposed_by}</div>
              </div>
            ))}
          </div>
        )}

        {tab === "messages" && (
          <div style={{ padding: "10px 14px" }}>
            {trail.messages.length === 0 && (
              <p style={{ fontSize: 12, color: "#94a3b8", margin: 0 }}>No transcript recorded.</p>
            )}
            {trail.messages.map(m => (
              <div key={m.id} style={{ marginBottom: 12 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 3 }}>
                  <span style={{ fontSize: 11, fontWeight: 600, color: "#374151" }}>{m.agent_role}</span>
                  <span style={{ fontSize: 10, color: "#94a3b8" }}>turn {m.turn}</span>
                  <span style={{ fontSize: 10, color: "#94a3b8", marginLeft: "auto" }}>{ts(m.created_at)}</span>
                </div>
                <div style={{
                  fontSize: 12, color: "#4b5563", lineHeight: 1.6,
                  paddingLeft: 8, borderLeft: "2px solid #e2e8f0",
                }}>
                  {m.content}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
