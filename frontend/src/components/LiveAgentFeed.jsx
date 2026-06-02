import { useEffect, useRef, useState } from "react";
import PhaseCluster from "./PhaseCluster";
import SolutionDocument from "./SolutionDocument";
import UiMockupViewer from "./UiMockupViewer";

const COMPLEXITY_COLORS = {
  simple: { bg: "#dcfce7", color: "#166534", border: "#bbf7d0" },
  standard: { bg: "#fefce8", color: "#854d0e", border: "#fef08a" },
  complex: { bg: "#fee2e2", color: "#991b1b", border: "#fecaca" },
};

export default function LiveAgentFeed({ events = [], sessionId, onSessionComplete }) {
  const [phases, setPhases] = useState({});          // phaseNum → phase state
  const [agentStates, setAgentStates] = useState({}); // role → card props
  const [complexity, setComplexity] = useState(null);
  const [phasePlan, setPhasePlan] = useState([]);
  const [phaseOrder, setPhaseOrder] = useState([]);
  const [turnCount, setTurnCount] = useState(0);
  const [elapsedSec, setElapsedSec] = useState(0);
  const [sessionComplete, setSessionComplete] = useState(false);
  const [solutionDoc, setSolutionDoc] = useState(null);
  const [mockupHtml, setMockupHtml] = useState(null);
  const [streamStatus, setStreamStatus] = useState("preparing"); // preparing|running|done

  const startTimeRef = useRef(null);
  const timerRef = useRef(null);
  const processedRef = useRef(0); // index into events array we've already processed

  // Process only new events
  useEffect(() => {
    const newEvents = events.slice(processedRef.current);
    if (!newEvents.length) return;
    processedRef.current = events.length;

    newEvents.forEach((evt) => {
      const { event } = evt;

      if (event === "session_started") {
        setComplexity(evt.complexity);
        setPhasePlan(evt.phase_plan ?? []);
        setStreamStatus("running");
        startTimeRef.current = Date.now();
        timerRef.current = setInterval(
          () => setElapsedSec(Math.floor((Date.now() - startTimeRef.current) / 1000)),
          1000
        );
      }

      if (event === "phase_start") {
        const num = evt.phase;
        setPhaseOrder((prev) => prev.includes(num) ? prev : [...prev, num]);
        setPhases((prev) => ({
          ...prev,
          [num]: {
            phaseNumber: num,
            phaseName: evt.name,
            agents: evt.agents ?? [],
            parallel: evt.parallel ?? true,
            isComplete: false,
            decisionsLocked: [],
          },
        }));
      }

      if (event === "agent_start") {
        const role = evt.agent_role;
        setTurnCount((c) => c + 1);
        setAgentStates((prev) => ({
          ...prev,
          [role]: { ...(prev[role] ?? {}), status: "thinking", tokenText: "" },
        }));
      }

      if (event === "token") {
        const role = evt.agent_role;
        // Parse text if it's JSON-like; otherwise display raw
        let displayText = evt.text ?? "";
        try {
          const parsed = JSON.parse(displayText);
          displayText = parsed.recommended_approach
            ? `${parsed.recommended_approach}`
            : displayText.slice(0, 500);
        } catch {
          displayText = displayText.slice(0, 800);
        }
        setAgentStates((prev) => ({
          ...prev,
          [role]: { ...(prev[role] ?? {}), status: "streaming", tokenText: displayText },
        }));
      }

      if (event === "agent_end") {
        const role = evt.agent_role;
        setAgentStates((prev) => ({
          ...prev,
          [role]: {
            ...(prev[role] ?? {}),
            status: "done",
            decisionsLocked: evt.decisions_locked ?? [],
          },
        }));
        // Look for mockup in decisions (simple heuristic)
        if (role === "ui_builder" && evt.mockup_html) {
          setMockupHtml(evt.mockup_html);
        }
      }

      if (event === "phase_complete") {
        const num = evt.phase;
        setPhases((prev) => ({
          ...prev,
          [num]: {
            ...(prev[num] ?? {}),
            isComplete: true,
            decisionsLocked: evt.decisions_locked ?? [],
          },
        }));
      }

      if (event === "session_complete") {
        setSessionComplete(true);
        setSolutionDoc(evt.solution_document);
        setStreamStatus("done");
        clearInterval(timerRef.current);
        if (onSessionComplete) onSessionComplete(evt.solution_document);
      }

      if (event === "error") {
        setStreamStatus("error");
        clearInterval(timerRef.current);
      }
    });
  }, [events]);

  // Cleanup timer on unmount
  useEffect(() => () => clearInterval(timerRef.current), []);

  const cmpl = COMPLEXITY_COLORS[complexity] ?? COMPLEXITY_COLORS.standard;
  const mins = String(Math.floor(elapsedSec / 60)).padStart(2, "0");
  const secs = String(elapsedSec % 60).padStart(2, "0");

  return (
    <div style={{ maxWidth: 900, margin: "0 auto" }}>
      {/* ── Status header ── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "12px 16px",
          background: "#f8fafc",
          borderRadius: 10,
          border: "1px solid #e2e8f0",
          marginBottom: 20,
          flexWrap: "wrap",
        }}
      >
        <span style={{ fontSize: 13, color: "#64748b" }}>
          Session <code style={{ fontSize: 12 }}>{sessionId?.slice(0, 8)}…</code>
        </span>

        {complexity && (
          <span
            style={{
              padding: "3px 10px",
              borderRadius: 12,
              fontSize: 12,
              fontWeight: 600,
              background: cmpl.bg,
              color: cmpl.color,
              border: `1px solid ${cmpl.border}`,
            }}
          >
            {complexity.toUpperCase()}
          </span>
        )}

        {streamStatus === "running" && (
          <>
            <span style={{ fontSize: 12, color: "#64748b" }}>
              Turn <strong>{turnCount}</strong>/12
            </span>
            <span style={{ fontSize: 12, color: "#64748b", marginLeft: "auto" }}>
              ⏱ {mins}:{secs}
            </span>
          </>
        )}

        {streamStatus === "done" && (
          <span
            style={{
              marginLeft: "auto",
              padding: "3px 12px",
              borderRadius: 12,
              background: "#dcfce7",
              color: "#166534",
              fontWeight: 600,
              fontSize: 12,
            }}
          >
            ✓ Complete
          </span>
        )}

        {streamStatus === "preparing" && (
          <span style={{ color: "#64748b", fontSize: 13, fontStyle: "italic" }}>
            Preparing consulting team…
          </span>
        )}
      </div>

      {/* ── Phase clusters ── */}
      {phaseOrder.map((num) => {
        const phase = phases[num] ?? {};
        return (
          <PhaseCluster
            key={num}
            phaseNumber={num}
            phaseName={phase.phaseName}
            agents={phase.agents ?? []}
            parallel={phase.parallel ?? true}
            agentStates={agentStates}
            isComplete={phase.isComplete ?? false}
            decisionsLocked={phase.decisionsLocked ?? []}
          />
        );
      })}

      {/* ── UI mockup (if builder produced one) ── */}
      {mockupHtml && (
        <div style={{ marginBottom: 24 }}>
          <h3 style={{ fontSize: 15, fontWeight: 600, color: "#1e293b", marginBottom: 8 }}>
            🎨 UI Mockup (from Builder Agent)
          </h3>
          <UiMockupViewer previewHtml={mockupHtml} />
        </div>
      )}

      {/* ── Solution document ── */}
      {sessionComplete && solutionDoc && (
        <SolutionDocument document={solutionDoc} sessionId={sessionId} />
      )}

      {streamStatus === "error" && (
        <div
          style={{
            padding: 16,
            background: "#fee2e2",
            borderRadius: 8,
            color: "#991b1b",
            fontSize: 14,
            marginTop: 16,
          }}
        >
          An error occurred during the session. Partial results may be shown above.
        </div>
      )}
    </div>
  );
}
