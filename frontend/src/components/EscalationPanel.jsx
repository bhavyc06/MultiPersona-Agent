import { useState } from "react";
import api from "../api/client";

const S = {
  card: {
    maxWidth: 680, margin: "40px auto", background: "var(--surface)",
    borderRadius: 12, border: "1px solid var(--border)",
    boxShadow: "0 4px 24px var(--tint-07)", overflow: "hidden",
  },
  header: {
    background: "var(--surface-2)", borderBottom: "1px solid var(--border)",
    color: "var(--text)", padding: "20px 24px",
  },
  title:   { margin: 0, fontSize: 18, fontWeight: 600 },
  summary: { margin: "6px 0 0", fontSize: 13, opacity: 0.9, lineHeight: 1.5 },
  body:    { padding: 24 },
  label:   { display: "block", fontSize: 14, fontWeight: 500, color: "var(--muted)", marginBottom: 14 },
  options: { display: "flex", flexDirection: "column", gap: 10 },
  optBtn: (selected, submitting) => ({
    padding: "14px 16px",
    borderRadius: 8,
    border: selected ? "2px solid var(--violet)" : "1px solid var(--border)",
    background: selected ? "var(--violet-bg)" : submitting ? "var(--surface-2)" : "var(--surface)",
    cursor: submitting ? "not-allowed" : "pointer",
    textAlign: "left",
    transition: "border .15s, background .15s",
    opacity: submitting && !selected ? 0.5 : 1,
  }),
  optLabel:  { fontSize: 15, fontWeight: 600, color: "var(--text-strong)", marginBottom: 4 },
  optImpact: { fontSize: 13, color: "var(--muted)" },
  submitRow: { marginTop: 18, display: "flex", justifyContent: "flex-end" },
  submitBtn: (ready) => ({
    padding: "10px 24px", background: ready ? "var(--violet)" : "var(--violet-weak)",
    color: "var(--on-accent)", border: "none", borderRadius: 8, fontSize: 15,
    fontWeight: 600, cursor: ready ? "pointer" : "not-allowed",
    transition: "background .2s",
  }),
  processing: {
    textAlign: "center", padding: "32px 0",
    color: "var(--muted)", fontSize: 15, fontStyle: "italic",
  },
};

export default function EscalationPanel({ sessionId, summary, options }) {
  const [chosen, setChosen]     = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError]       = useState(null);

  const handleSubmit = async () => {
    if (!chosen || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.post(`/api/sessions/${sessionId}/respond`, { answer: chosen });
    } catch (err) {
      setError(err.response?.data?.detail ?? "Failed to submit choice");
      setSubmitting(false);
    }
  };

  return (
    <div style={S.card}>
      <div style={S.header}>
        <h3 style={S.title}>Council needs your guidance</h3>
        <p style={S.summary}>{summary}</p>
      </div>

      <div style={S.body}>
        {submitting ? (
          <p style={S.processing}>Relaying your decision to the council…</p>
        ) : (
          <>
            <span style={S.label}>Select an option — the council will incorporate your choice:</span>
            <div style={S.options}>
              {(options || []).map((opt) => (
                <button
                  key={opt.id}
                  style={S.optBtn(chosen === opt.id, submitting)}
                  onClick={() => !submitting && setChosen(opt.id)}
                >
                  <div style={S.optLabel}>{opt.label}</div>
                  <div style={S.optImpact}>{opt.impact}</div>
                </button>
              ))}
            </div>

            <div style={S.submitRow}>
              <button
                style={S.submitBtn(!!chosen)}
                onClick={handleSubmit}
                disabled={!chosen}
              >
                Confirm choice
              </button>
            </div>

            {error && <p style={{ color: "var(--error)", marginTop: 10, fontSize: 14 }}>{error}</p>}
          </>
        )}
      </div>
    </div>
  );
}
