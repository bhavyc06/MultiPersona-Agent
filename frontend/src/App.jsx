import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import ChatInterface from "./components/ChatInterface";
import ClarificationPanel from "./components/ClarificationPanel";
import LiveAgentFeed from "./components/LiveAgentFeed";
import { useSSEStream } from "./hooks/useSSEStream";

// ── Session page ────────────────────────────────────────────────────────────

function SessionPage() {
  const [sessionId, setSessionId] = useState(null);
  const [appPhase, setAppPhase] = useState("idle");
  // "idle" | "clarifying" | "running" | "complete" | "error"
  const [clarificationData, setClarificationData] = useState(null);

  const { events, latestEvent, status, reconnectCount } = useSSEStream(sessionId);

  // Drive phase state from SSE events
  useEffect(() => {
    if (!latestEvent) return;
    const { event } = latestEvent;

    if (event === "clarification_required") {
      setAppPhase("clarifying");
      setClarificationData({
        questions: latestEvent.questions ?? [],
        round: latestEvent.round ?? 1,
        maxRounds: latestEvent.max_rounds ?? 3,
      });
    } else if (event === "clarification_complete") {
      setClarificationData(null);
      setAppPhase("running");
    } else if (event === "session_started") {
      setAppPhase("running");
    } else if (event === "session_complete") {
      setAppPhase("complete");
    } else if (event === "error" && !latestEvent.recoverable) {
      setAppPhase("error");
    }
  }, [latestEvent]);

  if (!localStorage.getItem("access_token")) {
    return <Navigate to="/login" replace />;
  }

  const handleSessionCreated = (id) => {
    setSessionId(id);
    setAppPhase("clarifying"); // optimistic — SSE will confirm
    setClarificationData(null);
  };

  const handleNewProblem = () => {
    setSessionId(null);
    setAppPhase("idle");
    setClarificationData(null);
  };

  return (
    <div style={{ minHeight: "100vh", background: "#f8fafc", padding: "16px 16px 48px" }}>
      {/* ── Top bar when session is active ── */}
      {sessionId && (
        <div
          style={{
            maxWidth: 900,
            margin: "0 auto 16px",
            display: "flex",
            alignItems: "center",
            gap: 12,
          }}
        >
          <button
            onClick={handleNewProblem}
            style={{
              padding: "6px 14px",
              border: "1px solid #cbd5e1",
              borderRadius: 6,
              background: "#fff",
              cursor: "pointer",
              fontSize: 13,
              color: "#374151",
            }}
          >
            ← New problem
          </button>
          <span style={{ fontSize: 12, color: "#94a3b8" }}>
            {status === "connected" ? "● Connected" :
             status === "connecting" ? "● Connecting…" :
             status === "closed" ? "● Closed" : "● " + status}
            {reconnectCount > 0 && ` (reconnect #${reconnectCount})`}
          </span>
        </div>
      )}

      {/* ── Idle: show chat interface ── */}
      {appPhase === "idle" && (
        <ChatInterface onSessionCreated={handleSessionCreated} />
      )}

      {/* ── Clarifying: show clarification panel ── */}
      {appPhase === "clarifying" && clarificationData && (
        <ClarificationPanel
          sessionId={sessionId}
          questions={clarificationData.questions}
          round={clarificationData.round}
          maxRounds={clarificationData.maxRounds}
          onComplete={() => setAppPhase("running")}
        />
      )}

      {/* ── Clarifying but no data yet: show spinner ── */}
      {appPhase === "clarifying" && !clarificationData && (
        <div style={{ textAlign: "center", padding: 60, color: "#64748b" }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>🔄</div>
          <p>Starting your session…</p>
        </div>
      )}

      {/* ── Running / complete: show live agent feed ── */}
      {(appPhase === "running" || appPhase === "complete") && (
        <LiveAgentFeed
          events={events}
          sessionId={sessionId}
          onSessionComplete={() => setAppPhase("complete")}
        />
      )}

      {/* ── Error ── */}
      {appPhase === "error" && (
        <div
          style={{
            maxWidth: 600,
            margin: "60px auto",
            padding: 24,
            background: "#fee2e2",
            borderRadius: 10,
            color: "#991b1b",
            textAlign: "center",
          }}
        >
          <p style={{ fontSize: 16, fontWeight: 600 }}>Session error</p>
          <p style={{ fontSize: 14, marginTop: 8 }}>
            Something went wrong. Partial results may be visible.
          </p>
          <button
            onClick={handleNewProblem}
            style={{
              marginTop: 16, padding: "8px 20px", borderRadius: 6,
              border: "none", background: "#991b1b", color: "#fff", cursor: "pointer",
            }}
          >
            Start over
          </button>
        </div>
      )}
    </div>
  );
}

// ── Login / register page ───────────────────────────────────────────────────

function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState("login");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  if (localStorage.getItem("access_token")) {
    return <Navigate to="/session" replace />;
  }

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const base = "http://localhost:8000";
    const endpoint = mode === "register" ? `${base}/api/auth/register` : `${base}/api/auth/login`;

    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.detail ?? "Request failed"); return; }

      if (mode === "login") {
        localStorage.setItem("access_token", data.access_token);
      } else {
        const lr = await fetch(`${base}/api/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        });
        const ld = await lr.json();
        localStorage.setItem("access_token", ld.access_token);
      }
      window.location.href = "/session";
    } catch {
      setError("Network error");
    } finally {
      setLoading(false);
    }
  };

  const inp = {
    width: "100%", padding: 11, borderRadius: 7, border: "1px solid #cbd5e1",
    fontSize: 15, boxSizing: "border-box", outline: "none",
  };

  return (
    <div
      style={{
        minHeight: "100vh", background: "#f8fafc",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}
    >
      <div
        style={{
          width: 400, background: "#fff", borderRadius: 12,
          border: "1px solid #e2e8f0", boxShadow: "0 4px 24px rgba(0,0,0,.07)",
          padding: 32,
        }}
      >
        <h2 style={{ margin: "0 0 6px", fontSize: 22, fontWeight: 700 }}>
          {mode === "login" ? "Welcome back" : "Create account"}
        </h2>
        <p style={{ margin: "0 0 24px", color: "#64748b", fontSize: 14 }}>
          Multi-Agent Consulting Simulator
        </p>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <input type="email" placeholder="Email" value={email}
              onChange={(e) => setEmail(e.target.value)} required style={inp} />
          </div>
          <div style={{ marginBottom: 20 }}>
            <input type="password" placeholder="Password" value={password}
              onChange={(e) => setPassword(e.target.value)} required style={inp} />
          </div>
          <button
            type="submit" disabled={loading}
            style={{
              width: "100%", padding: 12, borderRadius: 8, border: "none",
              background: loading ? "#94a3b8" : "#1a56db", color: "#fff",
              fontSize: 15, fontWeight: 600, cursor: loading ? "not-allowed" : "pointer",
            }}
          >
            {loading ? "…" : mode === "login" ? "Sign In" : "Create Account"}
          </button>
        </form>

        {error && <p style={{ color: "#dc2626", marginTop: 12, fontSize: 14 }}>{error}</p>}

        <p style={{ marginTop: 16, fontSize: 13, color: "#64748b" }}>
          {mode === "login" ? "No account? " : "Already have one? "}
          <button
            onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}
            style={{ background: "none", border: "none", color: "#1a56db", cursor: "pointer", padding: 0, fontSize: 13 }}
          >
            {mode === "login" ? "Register" : "Sign in"}
          </button>
        </p>
      </div>
    </div>
  );
}

// ── Root ────────────────────────────────────────────────────────────────────

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/session" element={<SessionPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
