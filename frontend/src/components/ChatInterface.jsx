import { useState } from "react";
import api from "../api/client";

const MAX_CHARS = 2000;

export default function ChatInterface({ onSessionCreated }) {
  const [problem, setProblem] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!problem.trim() || loading) return;

    setLoading(true);
    setError(null);

    try {
      const { data } = await api.post("/api/sessions", {
        problem_statement: problem.trim(),
      });
      onSessionCreated(data.session_id);
    } catch (err) {
      setError(err.response?.data?.detail ?? "Failed to create session");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 700, margin: "60px auto", fontFamily: "sans-serif" }}>
      <h1 style={{ marginBottom: 8 }}>Multi-Agent Consulting Simulator</h1>
      <p style={{ color: "#555", marginBottom: 24 }}>
        Describe your technical problem and 8 AI specialist personas will collaborate in real time.
      </p>

      <form onSubmit={handleSubmit}>
        <textarea
          value={problem}
          onChange={(e) => setProblem(e.target.value.slice(0, MAX_CHARS))}
          placeholder="e.g. We need to build a real-time ML feature store that serves 50k predictions/sec..."
          rows={6}
          style={{
            width: "100%",
            padding: 12,
            fontSize: 15,
            borderRadius: 6,
            border: "1px solid #ccc",
            resize: "vertical",
            boxSizing: "border-box",
          }}
          disabled={loading}
        />
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 8 }}>
          <span style={{ fontSize: 12, color: problem.length >= MAX_CHARS ? "red" : "#888" }}>
            {problem.length} / {MAX_CHARS}
          </span>
          <button
            type="submit"
            disabled={loading || !problem.trim()}
            style={{
              padding: "10px 28px",
              fontSize: 15,
              borderRadius: 6,
              border: "none",
              background: loading ? "#aaa" : "#1a56db",
              color: "#fff",
              cursor: loading ? "not-allowed" : "pointer",
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
