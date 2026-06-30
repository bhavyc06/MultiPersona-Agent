import { useEffect, useState } from "react";
import api from "../api/client";

const S = {
  card: {
    maxWidth: 700, margin: "40px auto", background: "#fff",
    borderRadius: 12, border: "1px solid #e2e8f0",
    boxShadow: "0 4px 24px rgba(0,0,0,.07)", overflow: "hidden",
  },
  header: {
    background: "linear-gradient(135deg, #1a56db 0%, #2563eb 100%)",
    color: "#fff", padding: "20px 24px",
  },
  title: { margin: 0, fontSize: 18, fontWeight: 600 },
  sub: { margin: "4px 0 0", fontSize: 13, opacity: 0.85 },
  progressWrap: { height: 4, background: "#dbeafe" },
  progressFill: { height: "100%", background: "#1a56db", transition: "width .4s ease" },
  body: { padding: 24 },
  qBlock: { marginBottom: 20 },
  qLabel: { display: "block", fontSize: 14, fontWeight: 500, color: "#1e293b", marginBottom: 6 },
  textarea: {
    width: "100%", padding: 10, borderRadius: 6, border: "1px solid #cbd5e1",
    fontSize: 14, resize: "vertical", minHeight: 60, boxSizing: "border-box",
    fontFamily: "inherit", outline: "none",
  },
  btn: {
    display: "block", width: "100%", padding: "12px 0", marginTop: 8,
    background: "#1a56db", color: "#fff", border: "none", borderRadius: 8,
    fontSize: 15, fontWeight: 600, cursor: "pointer", transition: "opacity .2s",
  },
  processing: {
    textAlign: "center", padding: "32px 0", color: "#64748b",
    fontSize: 15, fontStyle: "italic",
  },
};

export default function ClarificationPanel({
  sessionId, questions, round, maxRounds, onComplete,
}) {
  const [answers, setAnswers] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);

  // Reset when new round arrives
  useEffect(() => {
    setAnswers({});
    setSubmitting(false);
    setSubmitError(null);
  }, [round, questions]);

  const allAnswered = questions.length > 0 &&
    questions.every((_, i) => (answers[i] ?? "").trim().length > 0);

  const handleSubmit = async () => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const combined = questions
        .map((q, i) => `${i + 1}. ${q}\nAnswer: ${(answers[i] ?? "").trim()}`)
        .join("\n\n");
      await api.post(`/api/sessions/${sessionId}/respond`, {
        answer: combined,
      });
      // Wait for next SSE event to advance the UI — don't call onComplete here
    } catch (err) {
      setSubmitError(err.response?.data?.detail ?? "Failed to submit answers");
      setSubmitting(false);
    }
  };

  return (
    <div style={S.card}>
      <div style={S.header}>
        <h3 style={S.title}>Helping the team understand your problem better</h3>
        <p style={S.sub}>Round {round} of {maxRounds} — answer these questions to guide the analysis</p>
      </div>

      <div style={S.progressWrap}>
        <div style={{ ...S.progressFill, width: `${(round / maxRounds) * 100}%` }} />
      </div>

      <div style={S.body}>
        {submitting ? (
          <p style={S.processing}>Processing your answers...</p>
        ) : (
          <>
            {questions.map((q, i) => (
              <div key={i} style={S.qBlock}>
                <label style={S.qLabel}>{i + 1}. {q}</label>
                <textarea
                  style={S.textarea}
                  value={answers[i] ?? ""}
                  onChange={(e) => setAnswers((prev) => ({ ...prev, [i]: e.target.value }))}
                  placeholder="Your answer..."
                  rows={2}
                />
              </div>
            ))}

            <button
              style={{ ...S.btn, opacity: allAnswered ? 1 : 0.45, cursor: allAnswered ? "pointer" : "not-allowed" }}
              onClick={handleSubmit}
              disabled={!allAnswered}
            >
              Submit Answers
            </button>

            {submitError && (
              <p style={{ color: "red", marginTop: 10, fontSize: 14 }}>{submitError}</p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
