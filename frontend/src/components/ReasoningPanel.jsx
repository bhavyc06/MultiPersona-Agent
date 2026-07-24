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
  s.textContent = `.rp-header:hover { background: var(--hover) !important; }`;
  document.head.appendChild(s);
}

export default function ReasoningPanel({ sessionId, refreshKey, turns }) {
  // V5-E: when `turns` is provided (live full_text per expert turn), this panel
  // is prop-driven and shows the COMPLETE expert text (left = deepest depth).
  // Otherwise it falls back to fetching persisted private reasoning (legacy).
  const liveMode = Array.isArray(turns);

  const [fetched, setFetched] = useState([]);
  const [loading, setLoading] = useState(false);
  // openIds: Set of entry.id strings that are currently expanded.
  const [openIds, setOpenIds] = useState(() => new Set());

  const bottomRef    = useRef(null);
  const prevLenRef   = useRef(0);   // tracks previous entry count for auto-expand

  const entries = liveMode
    ? turns.map((t) => ({ id: `${t.role}-${t.turn}`, role: t.role, turn: t.turn, content: t.full_text }))
    : fetched;

  // ── Fetch (legacy path only — skipped in live mode) ───────────────────────
  useEffect(() => {
    if (liveMode || !sessionId) return;
    let cancelled = false;

    // 400 ms delay: the SSE "message" event fires before _persist_message's
    // asyncio.create_task commits. Give the DB write time to land.
    const timer = setTimeout(() => {
      if (fetched.length === 0) setLoading(true);

      api
        .get(`/api/sessions/${sessionId}/messages`)
        .then(({ data }) => {
          if (cancelled) return;
          setFetched((data ?? []).filter((m) => m.is_private));
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
  }, [sessionId, refreshKey, liveMode]); // eslint-disable-line react-hooks/exhaustive-deps

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
        background: "var(--surface)",
        borderRadius: 10,
        border: "1px solid var(--border)",
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
          background: "var(--bg)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>
          🧠 Agent Reasoning
        </span>
        {entries.length > 0 && (
          <span
            style={{
              padding: "1px 7px",
              borderRadius: 10,
              background: "var(--border)",
              fontSize: 11,
              fontWeight: 700,
              color: "var(--text)",
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
              color: "var(--faint)",
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
                  border: "1px solid var(--border)",
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
                    background: isOpen ? "var(--surface-2)" : "var(--bg)",
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
                      color: "var(--text)",
                      flex: 1,
                    }}
                  >
                    {formatRole(entry.role)}
                  </span>
                  <span style={{ fontSize: 11, color: "var(--dim)" }}>
                    turn {entry.turn}
                  </span>
                  <span
                    style={{
                      fontSize: 10,
                      color: "var(--faint)",
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
                      background: "var(--bg)",
                      fontSize: 13,
                      color: "var(--slate-2)",
                      lineHeight: 1.55,
                      wordBreak: "break-word",
                      borderTop: "1px solid var(--border)",
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
