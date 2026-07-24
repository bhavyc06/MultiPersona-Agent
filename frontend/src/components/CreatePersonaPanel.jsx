import { useState } from "react";
import api from "../api/client.js";

// Converts a display name to a safe snake_case role identifier
function toRoleId(name) {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, "")
    .trim()
    .replace(/\s+/g, "_");
}

const PANEL_STYLE = {
  background: "var(--surface)",
  borderRadius: 10,
  border: "1px solid var(--border)",
  overflow: "hidden",
};

const HEADER_STYLE = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "9px 12px",
  background: "var(--bg)",
  borderBottom: "1px solid var(--border)",
  fontSize: 13,
  fontWeight: 600,
  color: "var(--text)",
};

const BODY_STYLE = { padding: 12 };

const INPUT_STYLE = {
  width: "100%",
  padding: "7px 10px",
  border: "1px solid var(--border-strong)",
  borderRadius: 6,
  fontSize: 13,
  boxSizing: "border-box",
  fontFamily: "inherit",
  outline: "none",
};

const BTN = (bg, disabled) => ({
  padding: "7px 14px",
  borderRadius: 6,
  border: "none",
  background: disabled ? "var(--faint)" : bg,
  color: "var(--on-accent)",
  fontSize: 12,
  fontWeight: 600,
  cursor: disabled ? "not-allowed" : "pointer",
  transition: "background .15s",
});

// Props:
//   mode             "mid-session" (default) | "pre-session"
//   sessionId        required for mid-session mode
//   onPersonaConfirmed  called with the persona def in pre-session mode;
//                       in mid-session mode called after successful API write
//   onCancel         optional — called when user cancels from idle/input mode
export default function CreatePersonaPanel({
  sessionId,
  mode = "mid-session",
  onPersonaConfirmed,
  onCancel,
}) {
  const [panelMode,    setPanelMode]   = useState("idle");
  const [inputMode,    setInputMode]   = useState("auto");
  const [roleInput,    setRoleInput]   = useState("");
  const [generated,    setGenerated]   = useState(null);
  const [editName,     setEditName]    = useState("");
  const [editPrompt,   setEditPrompt]  = useState("");
  const [editEmoji,    setEditEmoji]   = useState("🤖");
  const [editColor,    setEditColor]   = useState("var(--border)");
  const [error,        setError]       = useState(null);
  const [confirmed,    setConfirmed]   = useState(false);

  const isPreSession = mode === "pre-session";
  const addLabel     = isPreSession ? "✓ Add to plan" : "✓ Add to session";

  const reset = () => {
    setPanelMode("idle"); setRoleInput(""); setGenerated(null);
    setEditName(""); setEditPrompt(""); setEditEmoji("🤖"); setEditColor("var(--border)");
    setError(null); setConfirmed(false);
  };

  const handleCancel = () => {
    reset();
    onCancel?.();
  };

  // ── AUTO: generate via API ─────────────────────────────────────────────────
  const handleGenerate = async () => {
    if (!roleInput.trim()) return;
    setPanelMode("generating"); setError(null);
    try {
      const { data } = await api.post("/api/personas/generate", {
        role_description: roleInput.trim(),
      });
      setGenerated(data);
      setEditName(data.display_name);
      setEditPrompt(data.system_prompt);
      setEditEmoji(data.emoji);
      setEditColor(data.color);
      setPanelMode("review");
    } catch (err) {
      setError(err.response?.data?.detail ?? "Generation failed — try again.");
      setPanelMode("input");
    }
  };

  // ── MANUAL: user fills in all fields ──────────────────────────────────────
  const handleManualContinue = () => {
    const name = roleInput.trim() || "Custom Expert";
    setGenerated({ role: toRoleId(name) });
    setEditName(name);
    setEditPrompt("");
    setEditEmoji("🤖");
    setEditColor("var(--border)");
    setPanelMode("review");
  };

  // ── CONFIRM (add to plan or to running session) ───────────────────────────
  const handleAdd = async () => {
    if (!editPrompt.trim()) { setError("System prompt is required."); return; }
    if (!editName.trim())   { setError("Display name is required."); return; }
    setError(null);

    const role = generated?.role || toRoleId(editName);
    const personaDef = {
      role,
      display_name:  editName.trim(),
      system_prompt: editPrompt.trim(),
      emoji:         editEmoji || "🤖",
      color:         editColor || "var(--border)",
    };

    if (isPreSession) {
      // Pre-session: hand the definition to the parent; no API call here
      onPersonaConfirmed?.(personaDef);
      reset();
      return;
    }

    // Mid-session: POST to the running session endpoint
    setPanelMode("adding");
    try {
      await api.post(`/api/sessions/${sessionId}/personas`, personaDef);
      onPersonaConfirmed?.(personaDef);
      setConfirmed(true);
      setTimeout(reset, 1800);
    } catch (err) {
      setError(err.response?.data?.detail ?? "Failed to add persona.");
      setPanelMode("review");
    }
  };

  // ── Render ─────────────────────────────────────────────────────────────────

  if (panelMode === "idle") {
    return (
      <div style={PANEL_STYLE}>
        <div style={HEADER_STYLE}>✚ Create Persona</div>
        <div style={BODY_STYLE}>
          {confirmed && (
            <div style={{ fontSize: 12, color: "var(--success-text)", marginBottom: 8 }}>
              ✓ Persona added to the team!
            </div>
          )}
          <button
            onClick={() => setPanelMode("input")}
            style={{ ...BTN("var(--primary)", false), width: "100%" }}
          >
            ✚ Add a custom expert
          </button>
          <p style={{ fontSize: 11, color: "var(--faint)", margin: "8px 0 0", lineHeight: 1.4 }}>
            Add a domain expert the team is missing — cybersecurity,
            legal, sustainability, etc.
          </p>
        </div>
      </div>
    );
  }

  if (panelMode === "input") {
    const isAuto = inputMode === "auto";
    return (
      <div style={PANEL_STYLE}>
        <div style={HEADER_STYLE}>✚ Create Persona</div>
        <div style={BODY_STYLE}>
          {/* Auto / Manual toggle */}
          <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
            {[["auto", "🤖 Auto-generate"], ["manual", "✍️ Write prompt"]].map(([m, label]) => (
              <button
                key={m}
                onClick={() => setInputMode(m)}
                style={{
                  flex: 1, padding: "5px 0", borderRadius: 6, border: "none",
                  fontSize: 11, fontWeight: 600, cursor: "pointer",
                  background: inputMode === m ? "var(--primary)" : "var(--border)",
                  color: inputMode === m ? "var(--surface)" : "var(--slate)",
                }}
              >
                {label}
              </button>
            ))}
          </div>

          <input
            type="text"
            placeholder={isAuto ? "e.g. cybersecurity expert" : "e.g. Legal Counsel"}
            value={roleInput}
            onChange={(e) => setRoleInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") isAuto ? handleGenerate() : handleManualContinue();
            }}
            style={{ ...INPUT_STYLE, marginBottom: 8 }}
          />

          {error && (
            <p style={{ fontSize: 12, color: "var(--danger)", margin: "0 0 8px" }}>{error}</p>
          )}

          <div style={{ display: "flex", gap: 6 }}>
            <button onClick={handleCancel} style={BTN("var(--faint)", false)}>
              Cancel
            </button>
            <button
              onClick={isAuto ? handleGenerate : handleManualContinue}
              disabled={!roleInput.trim()}
              style={{ ...BTN("var(--primary)", !roleInput.trim()), flex: 1 }}
            >
              {isAuto ? "Generate →" : "Continue →"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (panelMode === "generating") {
    return (
      <div style={PANEL_STYLE}>
        <div style={HEADER_STYLE}>✚ Create Persona</div>
        <div style={{ ...BODY_STYLE, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>
          <div style={{ fontSize: 20, marginBottom: 8 }}>⏳</div>
          Generating persona…
        </div>
      </div>
    );
  }

  if (panelMode === "review") {
    return (
      <div style={PANEL_STYLE}>
        <div style={HEADER_STYLE}>✚ Review Persona</div>
        <div style={BODY_STYLE}>
          {/* Emoji + color + name row */}
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
            <input
              type="text"
              value={editEmoji}
              onChange={(e) => setEditEmoji(e.target.value.slice(0, 4))}
              style={{ ...INPUT_STYLE, width: 48, textAlign: "center", fontSize: 18, padding: "4px 6px" }}
              title="Emoji"
            />
            <input
              type="color"
              value={editColor}
              onChange={(e) => setEditColor(e.target.value)}
              style={{ width: 32, height: 32, border: "1px solid var(--border)", borderRadius: 4, padding: 2, cursor: "pointer" }}
              title="Bubble color"
            />
            <input
              type="text"
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              placeholder="Display name"
              style={{ ...INPUT_STYLE, flex: 1 }}
            />
          </div>

          {/* System prompt */}
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--muted-2)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            System Prompt
          </div>
          <textarea
            value={editPrompt}
            onChange={(e) => setEditPrompt(e.target.value)}
            placeholder="Describe this expert's role, focus, and communication style…"
            rows={6}
            style={{ ...INPUT_STYLE, resize: "vertical", minHeight: 90, marginBottom: 8, lineHeight: 1.5 }}
          />

          {error && (
            <p style={{ fontSize: 12, color: "var(--danger)", margin: "0 0 8px" }}>{error}</p>
          )}

          <div style={{ display: "flex", gap: 6 }}>
            <button onClick={handleCancel} style={BTN("var(--faint)", false)}>✗ Cancel</button>
            <button
              onClick={handleAdd}
              disabled={!editPrompt.trim() || !editName.trim()}
              style={{ ...BTN("var(--success-text)", !editPrompt.trim() || !editName.trim()), flex: 1 }}
            >
              {addLabel}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // "adding" mode — only reached in mid-session (pre-session path returns synchronously)
  if (panelMode === "adding") {
    return (
      <div style={PANEL_STYLE}>
        <div style={HEADER_STYLE}>✚ Create Persona</div>
        <div style={{ ...BODY_STYLE, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>
          <div style={{ fontSize: 20, marginBottom: 8 }}>⏳</div>
          Adding to team…
        </div>
      </div>
    );
  }

  return null;
}
