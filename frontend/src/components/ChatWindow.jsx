import { useEffect, useRef, useState } from "react";
import api from "../api/client.js";
import { getRoleColor, getRoleEmoji, formatRole, registerPersona } from "../roleStyles.js";
import CostPanel from "./CostPanel";
import CreatePersonaPanel from "./CreatePersonaPanel";
import DecisionBadge from "./DecisionBadge";
import InlineHumanInput from "./InlineHumanInput";
import MessageBubble from "./MessageBubble";
import ReasoningPanel from "./ReasoningPanel";
import { RecruitedCloseoutPrompt, RecruitedPanel, SavableExpertPanel } from "./RecruitedExperts";
import RosterBadges from "./RosterBadges";
import SolutionDocument from "./SolutionDocument";
import StenographerPanel from "./StenographerPanel";

// ── Typing indicator — RIGHT-aligned to match ExpertBubble ──────────────────

function TypingIndicator({ agent }) {
  const emoji = getRoleEmoji(agent);
  const bg    = getRoleColor(agent);

  return (
    <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginBottom: 16 }}>
      {/* Label + dots — right of center, left of avatar */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text)", marginBottom: 4 }}>
          {formatRole(agent)}
        </div>
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            background: bg,
            borderRadius: "8px 0 8px 8px",
            padding: "10px 16px",
          }}
        >
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              style={{
                width: 7, height: 7, borderRadius: "50%", background: "var(--faint)",
                display: "inline-block",
                animation: `typing-dot 1.2s ease-in-out ${i * 0.2}s infinite`,
              }}
            />
          ))}
        </div>
      </div>

      {/* Avatar — rightmost */}
      <div
        style={{
          width: 36, height: 36, borderRadius: "50%", background: bg,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 18, flexShrink: 0,
          fontFamily: "Apple Color Emoji, Segoe UI Emoji, Noto Color Emoji, sans-serif",
        }}
      >
        {emoji}
      </div>

      <style>{`
        @keyframes typing-dot {
          0%, 80%, 100% { opacity: 0.25; transform: scale(0.8); }
          40%            { opacity: 1;    transform: scale(1);   }
        }
      `}</style>
    </div>
  );
}

// ── Placeholder panel ────────────────────────────────────────────────────────

function PlaceholderPanel({ title, body }) {
  return (
    <div
      style={{
        background: "var(--surface)",
        borderRadius: 10,
        border: "1px solid var(--border)",
        padding: 14,
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text)", marginBottom: 8 }}>
        {title}
      </div>
      <div style={{ fontSize: 12, color: "var(--faint)", fontStyle: "italic" }}>
        {body}
      </div>
    </div>
  );
}

// ── ChatWindow ───────────────────────────────────────────────────────────────

export default function ChatWindow({ events = [], sessionId, onSessionComplete }) {
  const [messages,        setMessages]        = useState([]);
  const [decisions,       setDecisions]       = useState({});   // keyed by id
  const [roster,          setRoster]          = useState([]);
  const [currentAgent,    setCurrentAgent]    = useState(null);
  const [isSynthesizing,  setIsSynthesizing]  = useState(false);
  const [sessionComplete, setSessionComplete] = useState(false);
  const [solutionDoc,     setSolutionDoc]     = useState(null);
  const [streamStatus,    setStreamStatus]    = useState("preparing");
  const [elapsedSec,      setElapsedSec]      = useState(0);
  const [decisionsOpen,       setDecisionsOpen]       = useState(true);
  const [humanQuestion,       setHumanQuestion]       = useState(null);
  const [finalizing,          setFinalizing]          = useState(false);
  const [reasoningRefreshKey, setReasoningRefreshKey] = useState(0);
  const [steerPrompt,         setSteerPrompt]         = useState(null);
  const [isPausing,           setIsPausing]           = useState(false);
  const [usageData,           setUsageData]           = useState(null);
  const [recruited,           setRecruited]           = useState([]);   // V5-D: recruited experts (savable)
  const [manualExperts,       setManualExperts]       = useState([]);   // V5-D follow-up: manually-added experts (savable)
  const [closeoutDismissed,   setCloseoutDismissed]   = useState(false);

  const startTimeRef  = useRef(null);
  const timerRef      = useRef(null);
  const processedRef  = useRef(0);
  const chatBottomRef = useRef(null);

  // Auto-scroll to newest message / indicator / inline input
  useEffect(() => {
    if (chatBottomRef.current) {
      chatBottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, currentAgent, isSynthesizing, humanQuestion, steerPrompt]);

  // Consume SSE events
  useEffect(() => {
    const newEvents = events.slice(processedRef.current);
    if (!newEvents.length) return;
    processedRef.current = events.length;

    newEvents.forEach((evt) => {
      const { event } = evt;

      // ── Roster ──────────────────────────────────────────────────────────
      if (event === "roster_selected") {
        setRoster(evt.roster ?? []);
        // Register custom persona emoji/colors emitted alongside the roster
        // so TEAM ASSEMBLED shows correct styling for pre-session personas
        (evt.custom_personas ?? []).forEach((p) => {
          registerPersona(p.role, p.emoji, p.color);
        });
      }

      // ── Agent status ─────────────────────────────────────────────────────
      if (event === "agent_thinking") {
        setCurrentAgent(evt.agent ?? null);
        setStreamStatus("running");
        if (!startTimeRef.current) {
          startTimeRef.current = Date.now();
          timerRef.current = setInterval(
            () => setElapsedSec(Math.floor((Date.now() - startTimeRef.current) / 1000)),
            1000,
          );
        }
      }

      // ── Expert / human messages ──────────────────────────────────────────
      if (event === "message" && !evt.is_private) {
        // V5-E: a turn carries three depths. chat_line → middle 1-liner,
        // full_text → left reasoning, steno_summary → right stenographer.
        // Human/system messages have no summaries → fall back to content.
        setMessages((prev) => [
          ...prev,
          {
            role:          evt.role,
            content:       evt.content,
            turn:          evt.turn,
            chat_line:     evt.chat_line     ?? evt.content,
            steno_summary: evt.steno_summary ?? null,
            full_text:     evt.full_text     ?? evt.content,
          },
        ]);
        setCurrentAgent(null);
        setStreamStatus("running");
        if (!startTimeRef.current) {
          startTimeRef.current = Date.now();
          timerRef.current = setInterval(
            () => setElapsedSec(Math.floor((Date.now() - startTimeRef.current) / 1000)),
            1000,
          );
        }
        // Expert just finished → reasoning row now committing to DB
        setReasoningRefreshKey((k) => k + 1);
        // Steering message from supervisor_node arrives as role="human" message
        if (evt.role === "human") {
          setSteerPrompt(null);
        }
      }

      // ── V5-E: Haiku summaries arrive after the turn (non-blocking) ────────
      if (event === "turn_summary") {
        setMessages((prev) =>
          prev.map((m) =>
            m.role === evt.role && m.turn === evt.turn
              ? {
                  ...m,
                  chat_line:     evt.chat_line     ?? m.chat_line,
                  steno_summary: evt.steno_summary ?? m.steno_summary,
                }
              : m
          )
        );
      }

      // ── Decisions ────────────────────────────────────────────────────────
      if (event === "decision") {
        setDecisions((prev) => ({ ...prev, [evt.id]: evt }));
      }

      // ── Contradiction — inline system bubble ─────────────────────────────
      if (event === "contradiction") {
        setMessages((prev) => [
          ...prev,
          {
            role: "system",
            content: `⚡ Contradiction (round ${evt.round}): ${evt.challenged_by} challenges ${evt.original_proposer} — ${evt.conflict?.summary ?? ""}`,
            turn: -1,
          },
        ]);
      }

      // ── Arbitration — inline system bubble ───────────────────────────────
      if (event === "arbitration") {
        setMessages((prev) => [
          ...prev,
          {
            role: "system",
            content: `🔨 Supervisor resolved: ${evt.note || evt.conflict?.summary || "decision locked by supervisor"}`,
            turn: -1,
          },
        ]);
      }

      // ── Synthesis ────────────────────────────────────────────────────────
      if (event === "synthesizing") {
        setIsSynthesizing(true);
        setCurrentAgent(null);
      }

      // ── Session complete ─────────────────────────────────────────────────
      if (event === "session_complete") {
        if (evt.locked_decisions?.length) {
          setDecisions((prev) => {
            const next = { ...prev };
            evt.locked_decisions.forEach((d) => {
              if (d.supersedes_id) delete next[d.supersedes_id];
              next[d.id] = d;
            });
            return next;
          });
        }
        setSessionComplete(true);
        setSolutionDoc(evt.solution_document);
        setStreamStatus("done");
        setIsSynthesizing(false);
        setCurrentAgent(null);
        // Extract real usage data from session_complete payload
        setUsageData({
          total_cost_usd:        evt.total_cost_usd        ?? 0,
          total_input_tokens:    evt.total_input_tokens    ?? 0,
          total_output_tokens:   evt.total_output_tokens   ?? 0,
          cache_creation_tokens: evt.cache_creation_tokens ?? 0,
          cache_read_tokens:     evt.cache_read_tokens     ?? 0,
          total_duration_ms:     evt.total_duration_ms     ?? 0,
          by_model:              evt.by_model              ?? {},
        });
        // Final refresh — capture any reasoning rows written during synthesis
        setReasoningRefreshKey((k) => k + 1);
        clearInterval(timerRef.current);
        if (onSessionComplete) onSessionComplete(evt.solution_document);
      }

      // ── Error ────────────────────────────────────────────────────────────
      if (event === "error") {
        setStreamStatus("error");
        clearInterval(timerRef.current);
      }

      // ── Human input (ask_human_node) ─────────────────────────────────────
      if (event === "human_input_required") {
        setHumanQuestion(evt.question ?? "");
      }

      if (event === "human_input_received") {
        setHumanQuestion(null);
        setMessages((prev) => [
          ...prev,
          {
            role:    "human",
            content: evt.answer ?? "",
            turn:    evt.turn ?? -1,
          },
        ]);
      }

      // ── Pause & steer (user-initiated) ────────────────────────────────────
      if (event === "pause_requested") {
        setIsPausing(true);
      }

      if (event === "pause_armed") {
        setSteerPrompt(evt.prompt ?? "What direction should the team take next?");
        setIsPausing(false);
      }

      // ── V5-D: dynamically recruited expert (savable to library) ──────────
      if (event === "expert_recruited") {
        registerPersona(evt.role, evt.emoji, evt.color);
        setRoster((prev) => (prev.includes(evt.role) ? prev : [...prev, evt.role]));
        setRecruited((prev) =>
          prev.some((e) => e.role === evt.role) ? prev : [...prev, evt]
        );
      }

      // ── Custom persona added mid-session ──────────────────────────────────
      if (event === "persona_added") {
        // Register color/emoji so all components render the custom role correctly
        registerPersona(evt.role, evt.emoji, evt.color);
        // Add to the roster strip so the persona appears in TEAM ASSEMBLED
        setRoster((prev) =>
          prev.includes(evt.role) ? prev : [...prev, evt.role]
        );
        // V5-D follow-up: manually-added experts are savable to the library too.
        // domain isn't part of a manual persona → fall back to the display name.
        setManualExperts((prev) =>
          prev.some((e) => e.role === evt.role) ? prev : [...prev, {
            role:               evt.role,
            display_name:       evt.display_name,
            domain:             evt.display_name || evt.role,
            domain_lock_prompt: evt.domain_lock_prompt || "",
            default_level:      "L1",
            emoji:              evt.emoji,
            color:              evt.color,
          }]
        );
      }
    });
  }, [events, onSessionComplete]);

  useEffect(() => () => clearInterval(timerRef.current), []);

  // ── Finalize handler ─────────────────────────────────────────────────────
  async function handleFinalize() {
    setFinalizing(true);
    try {
      await api.post(`/api/sessions/${sessionId}/finalize`);
    } catch (err) {
      console.error("Finalize failed:", err);
      setFinalizing(false);
    }
  }

  // ── Pause & steer handler ─────────────────────────────────────────────────
  async function handlePause() {
    setIsPausing(true);
    try {
      await api.post(`/api/sessions/${sessionId}/pause`);
      // isPausing stays true; pause_requested SSE confirms, pause_armed clears it
    } catch (err) {
      console.error("Pause failed:", err);
      setIsPausing(false);
    }
  }

  // ── Derived values ────────────────────────────────────────────────────────
  const mins = String(Math.floor(elapsedSec / 60)).padStart(2, "0");
  const secs = String(elapsedSec % 60).padStart(2, "0");

  const showChat     = messages.length > 0 || currentAgent !== null || isSynthesizing
                       || !!humanQuestion || !!steerPrompt;
  const decisionList = Object.values(decisions);
  const decisionCount = decisionList.length;

  // V5-E: expert turns only (exclude human/system bubbles) — drive the LEFT
  // (full_text) and RIGHT (steno_summary → full_text) panels.
  const expertTurns = messages.filter(
    (m) => m.role && m.role !== "system" && m.role !== "human" && m.turn >= 0
  );

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div>

      {/* ── Status bar (full width) ─────────────────────────────────────── */}
      <div
        style={{
          display: "flex", alignItems: "center", gap: 12,
          padding: "10px 16px", background: "var(--bg)",
          borderRadius: 10, border: "1px solid var(--border)",
          marginBottom: 12, flexWrap: "wrap",
        }}
      >
        <span style={{ fontSize: 13, color: "var(--muted)" }}>
          Session <code style={{ fontSize: 12 }}>{sessionId?.slice(0, 8)}…</code>
        </span>

        {currentAgent && (
          <span style={{ fontSize: 12, color: "var(--primary-3)", fontStyle: "italic" }}>
            {getRoleEmoji(currentAgent)} {formatRole(currentAgent)} is thinking…
          </span>
        )}

        {isSynthesizing && (
          <span style={{ fontSize: 12, color: "var(--violet)", fontStyle: "italic" }}>
            ⚗️ Synthesizing solution…
          </span>
        )}

        {streamStatus === "preparing" && !currentAgent && !isSynthesizing && (
          <span style={{ fontSize: 13, color: "var(--muted)", fontStyle: "italic" }}>
            Preparing expert team…
          </span>
        )}

        {streamStatus === "running" && startTimeRef.current && (
          <span style={{ fontSize: 12, color: "var(--muted)", marginLeft: "auto" }}>
            ⏱ {mins}:{secs}
          </span>
        )}

        {streamStatus === "done" && (
          <span style={{
            marginLeft: "auto", padding: "3px 12px", borderRadius: 12,
            background: "var(--success-bg)", color: "var(--success-text)", fontWeight: 600, fontSize: 12,
          }}>
            ✓ Complete
          </span>
        )}

        {/* Pause & Steer — shown when running, hidden during synthesis / overlays */}
        {streamStatus === "running" && !sessionComplete && !isSynthesizing && (
          isPausing ? (
            <span
              style={{
                marginLeft: "auto",
                fontSize:   12,
                color:      "var(--warning)",
                fontStyle:  "italic",
              }}
            >
              ⏸ Pausing… (after current expert)
            </span>
          ) : !humanQuestion && !steerPrompt ? (
            <button
              onClick={handlePause}
              title="Pause after current expert and send guidance"
              style={{
                marginLeft:   "auto",
                padding:      "5px 14px",
                borderRadius: 6,
                border:       "none",
                background:   "var(--warning)",
                color:        "var(--on-accent)",
                fontSize:     12,
                fontWeight:   600,
                cursor:       "pointer",
                transition:   "background .15s",
              }}
            >
              ⏸ Pause &amp; Steer
            </button>
          ) : null
        )}

        {!sessionComplete && (
          <button
            onClick={handleFinalize}
            disabled={finalizing || isSynthesizing}
            title="Force synthesis now with current decisions"
            style={{
              marginLeft:   "auto",
              padding:      "5px 14px",
              borderRadius: 6,
              border:       "none",
              background:   (finalizing || isSynthesizing) ? "var(--faint)" : "var(--success-text)",
              color:        "var(--on-accent)",
              fontSize:     12,
              fontWeight:   600,
              cursor:       (finalizing || isSynthesizing) ? "not-allowed" : "pointer",
              transition:   "background .15s",
            }}
          >
            {finalizing ? "Finalizing…" : "⏹ Finalize"}
          </button>
        )}
      </div>

      {/* ── Roster strip (full width) ───────────────────────────────────── */}
      {roster.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <RosterBadges roster={roster} />
        </div>
      )}

      {/* ── Three-column work area ──────────────────────────────────────── */}
      <div
        style={{
          display: "flex",
          gap: 16,
          alignItems: "flex-start",
          marginBottom: 20,
        }}
      >

        {/* ── LEFT column (300px) ─────────────────────────────────────────── */}
        <div
          style={{
            width: 300,
            flexShrink: 0,
            display: "flex",
            flexDirection: "column",
            gap: 12,
          }}
        >
          <ReasoningPanel
            sessionId={sessionId}
            refreshKey={reasoningRefreshKey}
            turns={expertTurns}
          />
          <CreatePersonaPanel sessionId={sessionId} />
        </div>

        {/* ── CENTER column (flex 1) — chat feed ──────────────────────────── */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {showChat && (
            <div
              style={{
                maxWidth: 760,
                margin: "0 auto",
                background: "var(--surface)",
                borderRadius: 10,
                border: "1px solid var(--border)",
                padding: "20px 20px 12px",
                maxHeight: "64vh",
                overflowY: "auto",
              }}
            >
              {messages.map((msg, i) => (
                <MessageBubble
                  key={i}
                  role={msg.role}
                  content={msg.chat_line ?? msg.content}
                  turn={msg.turn}
                />
              ))}

              {currentAgent && <TypingIndicator agent={currentAgent} />}

              {isSynthesizing && (
                <div style={{
                  textAlign: "center", padding: "16px 0",
                  color: "var(--violet)", fontSize: 14, fontStyle: "italic",
                }}>
                  ⚗️ The team has finished deliberating — synthesizing the solution document…
                </div>
              )}

              {/* Inline human-input — ask_human_node question */}
              {humanQuestion && (
                <InlineHumanInput
                  mode="question"
                  question={humanQuestion}
                  sessionId={sessionId}
                  onSubmitted={() => setHumanQuestion(null)}
                />
              )}

              {/* Inline steer input — user-initiated pause */}
              {steerPrompt && (
                <InlineHumanInput
                  mode="steer"
                  question={steerPrompt}
                  sessionId={sessionId}
                  onSubmitted={() => setSteerPrompt(null)}
                />
              )}

              <div ref={chatBottomRef} />
            </div>
          )}

          {/* Empty state — roster set but no messages yet */}
          {!showChat && roster.length > 0 && (
            <div style={{
              maxWidth: 760, margin: "0 auto",
              background: "var(--surface)", borderRadius: 10,
              border: "1px solid var(--border)",
              padding: 40, textAlign: "center",
              color: "var(--faint)", fontSize: 14,
            }}>
              Expert discussion is starting…
            </div>
          )}
        </div>

        {/* ── RIGHT column (340px) ────────────────────────────────────────── */}
        <div
          style={{
            width: 340,
            flexShrink: 0,
            display: "flex",
            flexDirection: "column",
            gap: 12,
          }}
        >
          {/* V5-E: live Stenographer — paragraph summaries, click to expand */}
          <StenographerPanel turns={expertTurns} />

          {/* Decisions panel */}
          <div
            style={{
              background: "var(--surface)",
              borderRadius: 10,
              border: "1px solid var(--border)",
              overflow: "hidden",
            }}
          >
            {/* Panel header */}
            <div
              style={{
                display: "flex", alignItems: "center",
                justifyContent: "space-between",
                padding: "9px 12px",
                background: "var(--bg)",
                borderBottom: "1px solid var(--border)",
              }}
            >
              <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>
                Decisions{" "}
                {decisionCount > 0 && (
                  <span
                    style={{
                      marginLeft: 6, padding: "1px 7px", borderRadius: 10,
                      background: "var(--border)", fontSize: 11,
                      fontWeight: 700, color: "var(--text)",
                    }}
                  >
                    {decisionCount}
                  </span>
                )}
              </span>
              <button
                onClick={() => setDecisionsOpen((v) => !v)}
                title={decisionsOpen ? "Collapse" : "Expand"}
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  fontSize: 13, color: "var(--faint)", padding: "0 2px", lineHeight: 1,
                }}
              >
                {decisionsOpen ? "▲" : "▼"}
              </button>
            </div>

            {/* Decision list (collapsible) */}
            {decisionsOpen && (
              <div
                style={{
                  padding: "10px 10px 4px",
                  maxHeight: "calc(64vh - 44px)",
                  overflowY: "auto",
                }}
              >
                {decisionList.length === 0 ? (
                  <p style={{
                    fontSize: 12, color: "var(--faint)",
                    textAlign: "center", margin: "20px 0",
                    fontStyle: "italic",
                  }}>
                    Decisions will appear here…
                  </p>
                ) : (
                  decisionList.map((d) => (
                    <DecisionBadge key={d.id} decision={d} />
                  ))
                )}
              </div>
            )}
          </div>

          {/* V5-D: recruited specialists — live save affordance */}
          <RecruitedPanel experts={recruited} sessionId={sessionId} />

          {/* V5-D follow-up: manually-added experts — same save affordance */}
          <SavableExpertPanel
            title="Custom experts"
            experts={manualExperts}
            sessionId={sessionId}
            kindLabel="custom"
          />

          {/* Session Cost — real data from session_complete SSE */}
          <CostPanel usageData={usageData} />
        </div>
      </div>

      {/* ── V5-D: close-out prompt — offer to save recruited experts ──────── */}
      {sessionComplete && !closeoutDismissed && recruited.length > 0 && (
        <RecruitedCloseoutPrompt
          experts={recruited}
          sessionId={sessionId}
          onDismiss={() => setCloseoutDismissed(true)}
        />
      )}

      {/* ── Solution document (full width, below three-column area) ─────── */}
      {sessionComplete && solutionDoc && (
        <SolutionDocument document={solutionDoc} sessionId={sessionId} />
      )}

      {/* ── Error state ──────────────────────────────────────────────────── */}
      {streamStatus === "error" && (
        <div style={{
          padding: 16, background: "var(--danger-bg)", borderRadius: 8,
          color: "var(--danger-text)", fontSize: 14, marginTop: 16,
        }}>
          An error occurred during the session. Partial results may be shown above.
        </div>
      )}
    </div>
  );
}
