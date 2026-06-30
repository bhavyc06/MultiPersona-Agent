import { useEffect, useRef, useState } from "react";
import { marked } from "marked";
import api from "../api/client.js";
import { getRoleColor, getRoleEmoji, formatRole } from "../roleStyles.js";

function renderMd(text) {
  if (!text) return "";
  return marked.parse(String(text), { breaks: true, gfm: true });
}

// Inject hover style once on module load — avoids per-render <style> duplication.
if (typeof document !== "undefined" && !document.getElementById("reasoning-panel-styles")) {
  const s = document.createElement("style");
  s.id = "reasoning-panel-styles";
  s.textContent = `.rp-header:hover { background: #edf2f7 !important; }`;
  document.head.appendChild(s);
}

export default function ReasoningPanel({ sessionId, refreshKey }) {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);
  // openIds: Set of entry.id strings that are currently expanded.
  // Keyed by stable DB id so refetches don't collapse user-opened entries.
  const [openIds, setOpenIds] = useState(() => new Set());

  const bottomRef    = useRef(null);
  const prevLenRef   = useRef(0);   // tracks previous entry count for auto-expand

  // ── Fetch ────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;

    // 400 ms delay: the SSE "message" event fires before _persist_message's
    // asyncio.create_task commits. Give the DB write time to land.
    const timer = setTimeout(() => {
      if (entries.length === 0) setLoading(true);

      api
        .get(`/api/sessions/${sessionId}/messages`)
        .then(({ data }) => {
          if (cancelled) return;
          setEntries((data ?? []).filter((m) => m.is_private));
        })
        .catch(() => {})
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 400);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [sessionId, refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Auto-expand newest entry when count grows ────────────────────────────
  useEffect(() => {
    if (entries.length > prevLenRef.current && entries.length > 0) {
      const newest = entries[entries.length - 1];
      setOpenIds((prev) => {
        const next = new Set(prev);
        next.add(newest.id);
        return next;
      });
    }
    prevLenRef.current = entries.length;
  }, [entries]);

  // ── Scroll to bottom when new entry arrives ──────────────────────────────
  useEffect(() => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [entries.length]);

  // ── Toggle a single accordion row ───────────────────────────────────────
  const toggle = (id) => {
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div
      style={{
        background: "#fff",
        borderRadius: 10,
        border: "1px solid #e2e8f0",
        overflow: "hidden",
      }}
    >
      {/* ── Panel header ────────────────────────────────────────────────── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "9px 12px",
          background: "#f8fafc",
          borderBottom: "1px solid #e2e8f0",
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 600, color: "#374151" }}>
          🧠 Agent Reasoning
        </span>
        {entries.length > 0 && (
          <span
            style={{
              padding: "1px 7px",
              borderRadius: 10,
              background: "#e2e8f0",
              fontSize: 11,
              fontWeight: 700,
              color: "#374151",
            }}
          >
            {entries.length}
          </span>
        )}
      </div>

      {/* ── Body ────────────────────────────────────────────────────────── */}
      <div
        style={{
          padding: "8px",
          maxHeight: "calc(64vh - 100px)",
          overflowY: "auto",
        }}
      >
        {entries.length === 0 ? (
          <p
            style={{
              fontSize: 12,
              color: "#94a3b8",
              fontStyle: "italic",
              textAlign: "center",
              margin: "20px 0",
            }}
          >
            {loading ? "Loading…" : "Reasoning will appear here as experts work."}
          </p>
        ) : (
          entries.map((entry) => {
            const isOpen    = openIds.has(entry.id);
            const roleColor = getRoleColor(entry.role);

            return (
              <div
                key={entry.id}
                style={{
                  marginBottom: 6,
                  borderLeft: `3px solid ${roleColor}`,
                  borderRadius: "0 6px 6px 0",
                  overflow: "hidden",
                  border: "1px solid #e2e8f0",
                  borderLeftWidth: 3,
                  borderLeftColor: roleColor,
                }}
              >
                {/* ── Accordion header (always visible, clickable) ────── */}
                <div
                  className="rp-header"
                  onClick={() => toggle(entry.id)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "7px 10px",
                    background: isOpen ? "#f1f5f9" : "#f8fafc",
                    cursor: "pointer",
                    userSelect: "none",
                  }}
                >
                  <span style={{ fontSize: 13 }}>
                    {getRoleEmoji(entry.role)}
                  </span>
                  <span
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      color: "#374151",
                      flex: 1,
                    }}
                  >
                    {formatRole(entry.role)}
                  </span>
                  <span style={{ fontSize: 11, color: "#9ca3af" }}>
                    turn {entry.turn}
                  </span>
                  <span
                    style={{
                      fontSize: 10,
                      color: "#94a3b8",
                      marginLeft: 8,
                      lineHeight: 1,
                    }}
                  >
                    {isOpen ? "▼" : "▶"}
                  </span>
                </div>

                {/* ── Expanded reasoning content ───────────────────────── */}
                {isOpen && (
                  <div
                    className="md-bubble"
                    style={{
                      padding: "8px 10px",
                      background: "#f8fafc",
                      fontSize: 13,
                      color: "#4b5563",
                      lineHeight: 1.55,
                      wordBreak: "break-word",
                      borderTop: "1px solid #e2e8f0",
                    }}
                    dangerouslySetInnerHTML={{ __html: renderMd(entry.content) }}
                  />
                )}
              </div>
            );
          })
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
