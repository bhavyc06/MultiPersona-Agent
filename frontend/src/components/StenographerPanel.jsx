import { useEffect, useRef, useState } from "react";
import { marked } from "marked";
import { getRoleColor, getRoleEmoji, formatRole } from "../roleStyles.js";

// ── V5-E: live Stenographer (RIGHT panel) ─────────────────────────────────────
// Line-of-record per expert turn: the paragraph summary (steno_summary), and on
// click it expands to the in-depth view (full text). Light styling to match the
// current app — Part 2 handles the dark conversion.

function renderMd(text) {
  if (!text) return "";
  return marked.parse(String(text), { breaks: true, gfm: true });
}

if (typeof document !== "undefined" && !document.getElementById("steno-panel-styles")) {
  const s = document.createElement("style");
  s.id = "steno-panel-styles";
  s.textContent = `.sp-header:hover { background: var(--hover) !important; }`;
  document.head.appendChild(s);
}

export default function StenographerPanel({ turns = [] }) {
  // Expanded rows keyed by stable role-turn id, so new turns don't collapse others.
  const [openIds, setOpenIds] = useState(() => new Set());
  const bottomRef = useRef(null);

  useEffect(() => {
    if (bottomRef.current) bottomRef.current.scrollIntoView({ behavior: "smooth" });
  }, [turns.length]);

  const toggle = (id) =>
    setOpenIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  return (
    <div style={{ background: "var(--surface)", borderRadius: 10, border: "1px solid var(--border)", overflow: "hidden" }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "9px 12px", background: "var(--bg)", borderBottom: "1px solid var(--border)",
      }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>🗒 Stenographer</span>
        {turns.length > 0 && (
          <span style={{
            padding: "1px 7px", borderRadius: 10, background: "var(--border)",
            fontSize: 11, fontWeight: 700, color: "var(--text)",
          }}>
            {turns.length}
          </span>
        )}
      </div>

      <div style={{ padding: 8, maxHeight: "calc(64vh - 100px)", overflowY: "auto" }}>
        {turns.length === 0 ? (
          <p style={{ fontSize: 12, color: "var(--faint)", fontStyle: "italic", textAlign: "center", margin: "20px 0" }}>
            A running summary of each turn will appear here.
          </p>
        ) : (
          turns.map((t) => {
            const id = `${t.role}-${t.turn}`;
            const isOpen = openIds.has(id);
            const roleColor = getRoleColor(t.role);
            const full  = (t.full_text || "").trim();
            const steno = (t.steno_summary || "").trim();
            // Deeper detail exists only if the full text adds something beyond
            // the line-of-record summary. If not, show no expand control (no dead button).
            const hasMore = full && full !== steno;
            const shown = isOpen ? (full || steno) : (steno || full || "…");
            return (
              <div
                key={id}
                onClick={hasMore ? () => toggle(id) : undefined}
                style={{
                  marginBottom: 6, border: "1px solid var(--border)",
                  borderLeft: `3px solid ${roleColor}`, borderRadius: "0 6px 6px 0",
                  overflow: "hidden", cursor: hasMore ? "pointer" : "default",
                }}
              >
                <div
                  className={hasMore ? "sp-header" : undefined}
                  style={{
                    display: "flex", alignItems: "center", gap: 6, padding: "7px 10px",
                    background: isOpen ? "var(--surface-2)" : "var(--bg)", userSelect: "none",
                  }}
                >
                  <span style={{ fontSize: 13 }}>{getRoleEmoji(t.role)}</span>
                  <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text)", flex: 1 }}>
                    {formatRole(t.role)}
                  </span>
                  <span style={{ fontSize: 11, color: "var(--dim)" }}>turn {t.turn}</span>
                  {hasMore && (
                    <span style={{ fontSize: 10, color: "var(--faint)", marginLeft: 8 }}>
                      {isOpen ? "▼" : "▶"}
                    </span>
                  )}
                </div>

                {/* Collapsed = paragraph summary (line-of-record); expanded = full detail */}
                <div
                  className="md-bubble"
                  style={{
                    padding: "8px 10px", background: "var(--surface)",
                    fontSize: 12.5, color: isOpen ? "var(--text)" : "var(--slate-2)",
                    lineHeight: 1.55, wordBreak: "break-word", borderTop: "1px solid var(--hairline)",
                  }}
                  dangerouslySetInnerHTML={{ __html: renderMd(shown) }}
                />
                {hasMore && !isOpen && (
                  <div style={{ padding: "0 10px 7px", fontSize: 10.5, color: "var(--faint)" }}>
                    click to expand →
                  </div>
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
