import { useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import ChatInterface from "./components/ChatInterface";
import LiveAgentFeed from "./components/LiveAgentFeed";

function SessionPage() {
  const [sessionId, setSessionId] = useState(null);

  if (!localStorage.getItem("access_token")) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div style={{ padding: 24 }}>
      {!sessionId ? (
        <ChatInterface onSessionCreated={setSessionId} />
      ) : (
        <div>
          <div style={{ maxWidth: 800, margin: "0 auto", marginBottom: 16 }}>
            <button
              onClick={() => setSessionId(null)}
              style={{
                background: "none",
                border: "1px solid #ccc",
                borderRadius: 4,
                padding: "4px 12px",
                cursor: "pointer",
                fontSize: 13,
              }}
            >
              &larr; New problem
            </button>
            <span style={{ marginLeft: 16, fontSize: 13, color: "#555" }}>
              Session: <code>{sessionId}</code>
            </span>
          </div>
          <LiveAgentFeed sessionId={sessionId} />
        </div>
      )}
    </div>
  );
}

function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState("login"); // login | register
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  if (localStorage.getItem("access_token")) {
    return <Navigate to="/session" replace />;
  }

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const endpoint =
      mode === "register"
        ? "http://localhost:8000/api/auth/register"
        : "http://localhost:8000/api/auth/login";

    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail ?? "Request failed");
        return;
      }
      if (mode === "login") {
        localStorage.setItem("access_token", data.access_token);
        window.location.href = "/session";
      } else {
        // Auto-login after register
        const loginRes = await fetch("http://localhost:8000/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        });
        const loginData = await loginRes.json();
        localStorage.setItem("access_token", loginData.access_token);
        window.location.href = "/session";
      }
    } catch {
      setError("Network error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 400, margin: "100px auto", fontFamily: "sans-serif", padding: 24 }}>
      <h2 style={{ marginBottom: 24 }}>
        {mode === "login" ? "Sign In" : "Create Account"}
      </h2>
      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: 12 }}>
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            style={{ width: "100%", padding: 10, borderRadius: 6, border: "1px solid #ccc", boxSizing: "border-box" }}
          />
        </div>
        <div style={{ marginBottom: 16 }}>
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            style={{ width: "100%", padding: 10, borderRadius: 6, border: "1px solid #ccc", boxSizing: "border-box" }}
          />
        </div>
        <button
          type="submit"
          disabled={loading}
          style={{
            width: "100%",
            padding: 10,
            background: "#1a56db",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            fontSize: 15,
            cursor: loading ? "not-allowed" : "pointer",
          }}
        >
          {loading ? "..." : mode === "login" ? "Sign In" : "Register"}
        </button>
      </form>
      {error && <p style={{ color: "red", marginTop: 12 }}>{error}</p>}
      <p style={{ marginTop: 16, fontSize: 13, color: "#555" }}>
        {mode === "login" ? "No account? " : "Already have one? "}
        <button
          onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}
          style={{ background: "none", border: "none", color: "#1a56db", cursor: "pointer", padding: 0 }}
        >
          {mode === "login" ? "Register" : "Sign in"}
        </button>
      </p>
    </div>
  );
}

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
