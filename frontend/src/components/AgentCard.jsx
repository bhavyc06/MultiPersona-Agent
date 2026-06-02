const ROLE_EMOJIS = {
  data_engineer: "⚙️",
  data_scientist: "📊",
  solution_engineer: "🔧",
  solution_architect: "🏗️",
  ai_architect: "🧠",
  ai_engineer: "🤖",
  ui_builder: "🎨",
  project_manager: "📋",
};

const STATUS_COLORS = {
  waiting: "#94a3b8",
  thinking: "#3b82f6",
  streaming: "#10b981",
  done: "#10b981",
  error: "#ef4444",
};

const STATUS_BORDER = {
  waiting: "#e2e8f0",
  thinking: "#bfdbfe",
  streaming: "#bbf7d0",
  done: "#bbf7d0",
  error: "#fecaca",
};

function formatRole(role) {
  return role
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function StatusDot({ status }) {
  const color = STATUS_COLORS[status] ?? "#94a3b8";
  const isPulsing = status === "thinking" || status === "streaming";

  return (
    <span
      style={{
        display: "inline-block",
        width: 10,
        height: 10,
        borderRadius: "50%",
        background: color,
        marginRight: 6,
        animation: isPulsing ? "pulse 1.2s ease-in-out infinite" : "none",
        flexShrink: 0,
      }}
    />
  );
}

export default function AgentCard({ agentRole, status = "waiting", tokenText = "", decisionsLocked = [] }) {
  const emoji = ROLE_EMOJIS[agentRole] ?? "🤖";
  const name = formatRole(agentRole);
  const borderColor = STATUS_BORDER[status] ?? "#e2e8f0";

  return (
    <div
      style={{
        border: `2px solid ${borderColor}`,
        borderRadius: 10,
        padding: 14,
        background: "#fff",
        transition: "border-color .3s",
        minWidth: 0,
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", marginBottom: 8, gap: 6 }}>
        <span style={{ fontSize: 18 }}>{emoji}</span>
        <span style={{ fontWeight: 600, fontSize: 14, color: "#1e293b", flex: 1 }}>{name}</span>
        <StatusDot status={status} />
        <span style={{ fontSize: 12, color: STATUS_COLORS[status], fontWeight: 500 }}>
          {status === "done" ? "✓ Done" :
           status === "error" ? "✗ Error" :
           status === "thinking" ? "Thinking…" :
           status === "streaming" ? "Streaming…" : "Waiting"}
        </span>
      </div>

      {/* Token text */}
      {tokenText && (
        <pre
          style={{
            fontFamily: "ui-monospace, SFMono-Regular, monospace",
            fontSize: 12,
            color: "#334155",
            background: "#f8fafc",
            borderRadius: 6,
            padding: 10,
            margin: "0 0 8px",
            maxHeight: 180,
            overflowY: "auto",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {tokenText}
        </pre>
      )}

      {/* Decisions locked */}
      {decisionsLocked.length > 0 && (
        <div style={{ marginTop: 6 }}>
          {decisionsLocked.map((d, i) => (
            <span
              key={i}
              style={{
                display: "inline-block",
                margin: "2px 4px 2px 0",
                padding: "2px 8px",
                background: "#f0fdf4",
                border: "1px solid #bbf7d0",
                borderRadius: 12,
                fontSize: 11,
                color: "#166534",
              }}
            >
              🔒 {d.length > 60 ? d.slice(0, 60) + "…" : d}
            </span>
          ))}
        </div>
      )}

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  );
}
