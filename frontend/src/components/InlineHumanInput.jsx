import { useEffect, useRef, useState } from "react";
import api from "../api/client.js";

// Inline human-input card rendered inside the chat feed (not a fixed overlay).
// mode="question" — triggered by ask_human_node (expert needs clarification)
// mode="steer"    — triggered by user-initiated pause (steer the team)
// Submits to POST /api/sessions/{id}/respond in both cases.

export default function InlineHumanInput({ mode, question, sessionId, onSubmitted }) {
  const [answer,     setAnswer]     = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error,      setError]      = useState(null);
  const textareaRef                 = useRef(null);

  const isQuestion = mode === "question";

  // Palette — blue for expert questions, amber for user steer
  const accent      = isQuestion ? "var(--info-text)" : "var(--warning-text)";
  const accentBg    = isQuestion ? "var(--info-bg)"  : "var(--warning-bg)";
  const accentBorder = isQuestion ? "var(--info-border)" : "var(--amber-weak)";
  const btnActive   = isQuestion ? "var(--primary)"  : "var(--warning)";

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  const canSubmit = answer.trim().length > 0 && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.post(`/api/sessions/${sessionId}/respond`, {
        answer:      answer.trim(),
        branch:      null,
        decision_id: null,
      });
      onSubmitted();
    } catch (err) {
      setError(err.response?.data?.detail ?? "Failed to send — please try again.");
      setSubmitting(false);
    }
  };

  const handleKeyDown = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") handleSubmit();
  };

  return (
    <div
      style={{
        margin: "12px 0",
        border: `1px solid ${accentBorder}`,
        borderRadius: 8,
        overflow: "hidden",
      }}
    >
      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div
        style={{
          padding:      "8px 12px",
          background:   accentBg,
          borderBottom: `1px solid ${accentBorder}`,
          fontSize:     13,
          fontWeight:   600,
          color:        accent,
        }}
      >
        {isQuestion ? "💬 Expert team has a question" : "🎯 Steer the team"}
      </div>

      {/* ── Body ──────────────────────────────────────────────────────────── */}
      <div style={{ padding: "12px", background: "var(--surface)" }}>
        {/* Question / prompt text */}
        {question && (
          <div
            style={{
              padding:      "8px 10px",
              background:   accentBg,
              border:       `1px solid ${accentBorder}`,
              borderRadius: 6,
              marginBottom: 10,
              fontSize:     14,
              color:        accent,
              lineHeight:   1.5,
            }}
          >
            {question}
          </div>
        )}

        {/* Answer textarea */}
        <textarea
          ref={textareaRef}
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            isQuestion
              ? "Your answer…"
              : "What direction should the team take?"
          }
          rows={3}
          style={{
            width:       "100%",
            padding:     "8px 10px",
            border:      "1px solid var(--border-strong)",
            borderRadius: 6,
            fontSize:    14,
            resize:      "vertical",
            boxSizing:   "border-box",
            fontFamily:  "inherit",
            outline:     "none",
            minHeight:   72,
            marginBottom: 8,
          }}
        />

        {/* Submit row */}
        <div
          style={{
            display:        "flex",
            alignItems:     "center",
            justifyContent: "space-between",
          }}
        >
          <span style={{ fontSize: 11, color: "var(--faint)" }}>
            Ctrl+Enter to submit
          </span>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            style={{
              padding:      "7px 18px",
              background:   canSubmit ? btnActive : "var(--faint)",
              color:        "var(--on-accent)",
              border:       "none",
              borderRadius: 6,
              fontSize:     13,
              fontWeight:   600,
              cursor:       canSubmit ? "pointer" : "not-allowed",
              transition:   "background .15s",
            }}
          >
            {submitting
              ? "Sending…"
              : isQuestion
              ? "Send answer →"
              : "Send guidance →"}
          </button>
        </div>

        {error && (
          <p style={{ margin: "6px 0 0", fontSize: 12, color: "var(--danger)" }}>
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
