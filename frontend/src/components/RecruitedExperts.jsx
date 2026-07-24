import { useState } from "react";
import api from "../api/client.js";
import { formatRole } from "../roleStyles.js";

// ── V5-D: SAVE half of the persona library ────────────────────────────────────
// Recruited (NOT core-8) experts surface here with a "Save to library" action.
// Two containers share one save button:
//   RecruitedPanel        — live right-column card during the run
//   RecruitedCloseoutPrompt — close-out prompt offering per-expert save
// Styling matches the light ChatWindow (the SetupPopup's dark tokens are scoped
// to that modal; this lives in the light app surface).

function buildPayload(exp, sessionId) {
  return {
    role:               exp.role,
    display_name:       exp.display_name || formatRole(exp.role),
    domain:             exp.domain || exp.role,
    domain_lock_prompt: exp.domain_lock_prompt || "",
    default_level:      exp.default_level || "L1",
    source_session_id:  sessionId || null,
  };
}

function SaveSpecialistButton({ expert, sessionId }) {
  const [state, setState] = useState("idle"); // idle | saving | saved | error
  const [msg, setMsg] = useState(null);

  const save = async () => {
    if (state === "saving" || state === "saved") return;
    setState("saving");
    setMsg(null);
    try {
      const res = await api.post("/api/library/personas", buildPayload(expert, sessionId));
      setState("saved");
      setMsg(res.data?.deduped ? "Already in library" : "Saved to library");
    } catch (err) {
      setState("error");
      setMsg(err.response?.data?.detail ?? "Save failed");
    }
  };

  const saved = state === "saved";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <button
        onClick={save}
        disabled={state === "saving" || saved}
        style={{
          padding: "4px 10px",
          borderRadius: 6,
          border: saved ? "1px solid var(--success)" : "1px solid var(--border-strong)",
          background: saved ? "var(--success-bg)" : state === "saving" ? "var(--surface-2)" : "var(--surface)",
          color: saved ? "var(--success-text)" : "var(--text)",
          fontSize: 12,
          fontWeight: 600,
          cursor: saved || state === "saving" ? "default" : "pointer",
          whiteSpace: "nowrap",
        }}
      >
        {saved ? "✓ Saved" : state === "saving" ? "Saving…" : "☆ Save to library"}
      </button>
      {msg && state === "error" && (
        <span style={{ fontSize: 11, color: "var(--danger)" }}>{msg}</span>
      )}
    </div>
  );
}

function ExpertRow({ expert, sessionId, kindLabel = "recruited" }) {
  return (
    <div
      style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "8px 4px", borderTop: "1px solid var(--surface-2)",
      }}
    >
      <span
        style={{
          width: 28, height: 28, borderRadius: "50%",
          background: expert.color || "var(--border)",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 15, flexShrink: 0,
          fontFamily: "Apple Color Emoji, Segoe UI Emoji, Noto Color Emoji, sans-serif",
        }}
      >
        {expert.emoji || "🔍"}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-strong)" }}>
          {expert.display_name || formatRole(expert.role)}
        </div>
        <div style={{ fontSize: 11, color: "var(--faint)" }}>
          {kindLabel} · {expert.domain || expert.role}
        </div>
      </div>
      <SaveSpecialistButton expert={expert} sessionId={sessionId} />
    </div>
  );
}

// Live right-column card listing savable experts (recruited OR manually-added).
// Both card kinds reuse the same ExpertRow + SaveSpecialistButton (same API
// call, same saved-state flip, same dedup). Core-8 never reach here.
export function SavableExpertPanel({ title, experts = [], sessionId, kindLabel }) {
  if (!experts.length) return null;
  return (
    <div style={{ background: "var(--surface)", borderRadius: 10, border: "1px solid var(--border)", overflow: "hidden" }}>
      <div style={{
        padding: "9px 12px", background: "var(--bg)", borderBottom: "1px solid var(--border)",
        fontSize: 13, fontWeight: 600, color: "var(--text)",
      }}>
        {title}
      </div>
      <div style={{ padding: "2px 12px 8px" }}>
        {experts.map((e) => (
          <ExpertRow key={e.role} expert={e} sessionId={sessionId} kindLabel={kindLabel} />
        ))}
      </div>
    </div>
  );
}

// Recruited-specialists panel — thin wrapper preserving the V5-D call site.
export function RecruitedPanel({ experts = [], sessionId }) {
  return (
    <SavableExpertPanel
      title="Recruited this session"
      experts={experts}
      sessionId={sessionId}
      kindLabel="recruited"
    />
  );
}

// Close-out prompt — offered when the session ends and experts were recruited.
export function RecruitedCloseoutPrompt({ experts = [], sessionId, onDismiss }) {
  if (!experts.length) return null;
  const names = experts.map((e) => e.display_name || formatRole(e.role)).join(", ");
  return (
    <div style={{
      maxWidth: 900, margin: "16px auto 0",
      background: "var(--surface)", borderRadius: 10, border: "1px solid var(--indigo-border)",
      boxShadow: "0 2px 12px var(--indigo-shadow)", overflow: "hidden",
    }}>
      <div style={{
        padding: "12px 16px", background: "var(--indigo-bg)", borderBottom: "1px solid var(--indigo-bg-2)",
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <span style={{ fontSize: 14, fontWeight: 650, color: "var(--indigo-text)" }}>
          This session recruited {names} — keep for future problems?
        </span>
        <button
          onClick={onDismiss}
          style={{
            background: "none", border: "none", color: "var(--accent)",
            fontSize: 13, fontWeight: 500, cursor: "pointer",
          }}
        >
          Skip
        </button>
      </div>
      <div style={{ padding: "4px 16px 12px" }}>
        {experts.map((e) => (
          <ExpertRow key={e.role} expert={e} sessionId={sessionId} />
        ))}
      </div>
    </div>
  );
}
