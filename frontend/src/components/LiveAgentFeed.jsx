import { useSSEStream } from "../hooks/useSSEStream";

const STATUS_COLORS = {
  idle: "#888",
  connecting: "#f59e0b",
  connected: "#10b981",
  closed: "#6b7280",
  error: "#ef4444",
};

export default function LiveAgentFeed({ sessionId }) {
  const { events, status, error } = useSSEStream(sessionId);

  return (
    <div style={{ maxWidth: 800, margin: "0 auto", fontFamily: "monospace", fontSize: 13 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
        <span
          style={{
            width: 10,
            height: 10,
            borderRadius: "50%",
            background: STATUS_COLORS[status] ?? "#888",
            display: "inline-block",
          }}
        />
        <span style={{ color: "#555" }}>Stream: {status}</span>
        {error && <span style={{ color: "red", marginLeft: 8 }}>{error}</span>}
      </div>

      <div
        style={{
          background: "#111",
          color: "#d4f0a0",
          borderRadius: 8,
          padding: 16,
          minHeight: 200,
          overflowY: "auto",
          maxHeight: 500,
        }}
      >
        {events.length === 0 ? (
          <span style={{ color: "#555" }}>Waiting for events...</span>
        ) : (
          events.map((ev, i) => (
            <div key={i} style={{ marginBottom: 4 }}>
              <span style={{ color: "#6ee7b7" }}>[{ev.event ?? "message"}]</span>{" "}
              <span>{JSON.stringify(ev)}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
