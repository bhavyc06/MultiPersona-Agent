import { useState } from "react";
import api from "../api/client";

const S = {
  card: {
    maxWidth: 700, margin: "40px auto", background: "var(--surface)",
    borderRadius: 12, border: "1px solid var(--border)",
    boxShadow: "0 4px 24px var(--tint-07)", overflow: "hidden",
  },
  header: {
    background: "var(--surface-2)", borderBottom: "1px solid var(--border)",
    color: "var(--text)", padding: "20px 24px",
  },
  title: { margin: 0, fontSize: 18, fontWeight: 600 },
  sub: { margin: "4px 0 0", fontSize: 13, opacity: 0.85 },
  progressWrap: { height: 4, background: "var(--teal-bg)" },
  progressFill: { height: "100%", background: "var(--teal)", transition: "width .4s ease" },
  body: { padding: 24 },
  qLabel: {
    display: "block", fontSize: 15, fontWeight: 500,
    color: "var(--text-strong)", marginBottom: 12, lineHeight: 1.5,
  },
  textarea: {
    width: "100%", padding: 10, borderRadius: 6, border: "1px solid var(--border-strong)",
    fontSize: 14, resize: "vertical", minHeight: 72, boxSizing: "border-box",
    fontFamily: "inherit", outline: "none",
  },
  btnRow: { display: "flex", gap: 10, marginTop: 14 },
  btnPrimary: {
    flex: 1, padding: "11px 0", background: "var(--teal)", color: "var(--on-accent)",
    border: "none", borderRadius: 8, fontSize: 15, fontWeight: 600,
    cursor: "pointer", transition: "opacity .2s",
  },
  btnSkip: {
    padding: "11px 18px", background: "var(--surface-2)", color: "var(--muted)",
    border: "1px solid var(--border)", borderRadius: 8, fontSize: 14,
    fontWeight: 500, cursor: "pointer",
  },
  processing: {
    textAlign: "center", padding: "32px 0",
    color: "var(--muted)", fontSize: 15, fontStyle: "italic",
  },
};

export default function QuestionnairePanel({
  sessionId,
  question,
  questionNumber,
  maxQuestions,
  canSkip,
}) {
  const [answer, setAnswer]     = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);

  const handleSubmit = async (skipFlag = false) => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      await api.post(`/api/sessions/${sessionId}/respond`, {
        answer: skipFlag ? "[SKIP]" : answer.trim(),
      });
      // Wait for next SSE event ("questionnaire_question" or "questionnaire_complete")
      // to advance the UI — don't clear state here
    } catch (err) {
      setSubmitError(err.response?.data?.detail ?? "Failed to submit answer");
      setSubmitting(false);
    }
  };

  const progress = maxQuestions > 0 ? (questionNumber / maxQuestions) * 100 : 0;
  const canSubmit = answer.trim().length > 0;

  return (
    <div style={S.card}>
      <div style={S.header}>
        <h3 style={S.title}>Understanding your goal</h3>
        <p style={S.sub}>
          Question {questionNumber} of {maxQuestions} — helping us tailor the analysis
        </p>
      </div>

      <div style={S.progressWrap}>
        <div style={{ ...S.progressFill, width: `${progress}%` }} />
      </div>

      <div style={S.body}>
        {submitting ? (
          <p style={S.processing}>Processing your answer…</p>
        ) : (
          <>
            <label style={S.qLabel}>{question}</label>
            <textarea
              style={S.textarea}
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder="Type your answer here…"
              rows={3}
              autoFocus
            />

            <div style={S.btnRow}>
              <button
                style={{ ...S.btnPrimary, opacity: canSubmit ? 1 : 0.45, cursor: canSubmit ? "pointer" : "not-allowed" }}
                onClick={() => handleSubmit(false)}
                disabled={!canSubmit}
              >
                Submit
              </button>
              {canSkip && (
                <button style={S.btnSkip} onClick={() => handleSubmit(true)}>
                  Skip
                </button>
              )}
            </div>

            {submitError && (
              <p style={{ color: "var(--error)", marginTop: 10, fontSize: 14 }}>{submitError}</p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
