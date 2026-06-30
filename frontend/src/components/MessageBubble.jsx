import { useState } from "react";
import { marked } from "marked";
import { getRoleColor, getRoleEmoji, formatRole } from "../roleStyles.js";

// Inject scoped markdown styles once on module load.
const _MD_CSS = `
.md-bubble p             { margin: 4px 0; }
.md-bubble p:first-child { margin-top: 0; }
.md-bubble p:last-child  { margin-bottom: 0; }
.md-bubble ul,
.md-bubble ol            { margin: 4px 0; padding-left: 18px; }
.md-bubble li            { margin-bottom: 2px; }
.md-bubble h1,
.md-bubble h2,
.md-bubble h3            { margin: 8px 0 4px; font-size: 1em; font-weight: 700; }
.md-bubble strong        { font-weight: 700; }
.md-bubble em            { font-style: italic; }
.md-bubble code          {
  background: rgba(0,0,0,.07); border-radius: 3px;
  padding: 1px 5px; font-family: monospace; font-size: .9em; }
.md-bubble pre           {
  background: rgba(0,0,0,.07); border-radius: 4px;
  padding: 8px 10px; overflow-x: auto; font-size: .85em; margin: 6px 0; }
.md-bubble pre code      { background: none; padding: 0; }
.md-bubble blockquote    {
  margin: 4px 0; padding-left: 10px;
  border-left: 3px solid rgba(0,0,0,.15); opacity: .85; }
.md-bubble table         { border-collapse: collapse; font-size: .9em; margin: 4px 0; }
.md-bubble th,
.md-bubble td            { border: 1px solid rgba(0,0,0,.15); padding: 3px 8px; }
`;

if (typeof document !== "undefined" && !document.getElementById("md-bubble-styles")) {
  const s = document.createElement("style");
  s.id = "md-bubble-styles";
  s.textContent = _MD_CSS;
  document.head.appendChild(s);
}

function renderMd(text) {
  if (!text) return "";
  return marked.parse(String(text), { breaks: true, gfm: true });
}

// ── System message — centered, muted ──

function SystemBubble({ content }) {
  return (
    <div
      className="md-bubble"
      style={{
        textAlign: "center",
        margin: "10px 0",
        fontSize: 12,
        color: "#94a3b8",
        fontStyle: "italic",
        padding: "4px 16px",
      }}
      dangerouslySetInnerHTML={{ __html: renderMd(content) }}
    />
  );
}

// ── Human/"You" message — LEFT-aligned, grey ──

function HumanBubble({ content }) {
  return (
    <div style={{ display: "flex", justifyContent: "flex-start", marginBottom: 16 }}>
      <div style={{ maxWidth: "80%" }}>
        <div
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: "#374151",
            marginBottom: 4,
          }}
        >
          You
        </div>
        <div
          className="md-bubble"
          style={{
            background: "#f1f5f9",
            borderRadius: "0 8px 8px 8px",   // notch top-left → points toward label
            padding: "10px 14px",
            fontSize: 14,
            lineHeight: 1.6,
            color: "#1f2937",
            wordBreak: "break-word",
          }}
          dangerouslySetInnerHTML={{ __html: renderMd(content) }}
        />
      </div>
    </div>
  );
}

// ── Expert message — RIGHT-aligned, role-colored ──

function ExpertBubble({ role, content, turn }) {
  const [reasoningOpen, setReasoningOpen] = useState(false);

  const bg    = getRoleColor(role);
  const emoji = getRoleEmoji(role);

  return (
    <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 16 }}>
      {/* 80% max-width wrapper — keeps bubble from spanning the full feed width */}
      <div style={{ display: "flex", gap: 10, maxWidth: "80%", minWidth: 0 }}>
        {/* Content column */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Role + turn — right-aligned */}
          <div
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: "#374151",
              marginBottom: 4,
              textAlign: "right",
            }}
          >
            {formatRole(role)}
            <span style={{ fontWeight: 400, color: "#9ca3af", marginLeft: 8 }}>
              turn {turn}
            </span>
          </div>

          {/* Message bubble — notch top-right toward avatar */}
          <div
            className="md-bubble"
            style={{
              background: bg,
              borderRadius: "8px 0 8px 8px",
              padding: "10px 14px",
              fontSize: 14,
              lineHeight: 1.6,
              color: "#1f2937",
              wordBreak: "break-word",
            }}
            dangerouslySetInnerHTML={{ __html: renderMd(content) }}
          />

          {/* Reasoning expander — hidden until Phase 8 surfaces private reasoning */}
          <div style={{ display: "none" }}>
            <button
              onClick={() => setReasoningOpen((v) => !v)}
              style={{
                fontSize: 11,
                color: "#94a3b8",
                background: "none",
                border: "none",
                cursor: "pointer",
                padding: "4px 0",
              }}
            >
              {reasoningOpen ? "▲ Hide reasoning" : "▼ Show reasoning"}
            </button>
            {reasoningOpen && (
              <div
                style={{
                  marginTop: 4,
                  padding: "8px 12px",
                  background: "#f8fafc",
                  borderRadius: 6,
                  fontSize: 12,
                  color: "#64748b",
                  fontStyle: "italic",
                  whiteSpace: "pre-wrap",
                }}
              >
                (Reasoning not available in live stream — Phase 8)
              </div>
            )}
          </div>
        </div>

        {/* Avatar — rightmost within the 80% wrapper */}
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: "50%",
            background: bg,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 18,
            flexShrink: 0,
            fontFamily: "Apple Color Emoji, Segoe UI Emoji, Noto Color Emoji, sans-serif",
          }}
        >
          {emoji}
        </div>
      </div>
    </div>
  );
}

// ── Public API ──

export default function MessageBubble({ role, content, turn }) {
  if (role === "system") return <SystemBubble content={content} />;
  if (role === "human") return <HumanBubble content={content} />;
  return <ExpertBubble role={role} content={content} turn={turn} />;
}
