import AgentCard from "./AgentCard";

const PHASE_NAMES = {
  1: "Frame",
  2: "Data",
  3: "Build",
  4: "Plan",
};

export default function PhaseCluster({ phaseNumber, phaseName, agents = [], parallel, agentStates = {}, isComplete, decisionsLocked = [] }) {
  const name = phaseName || PHASE_NAMES[phaseNumber] || `Phase ${phaseNumber}`;

  return (
    <div
      style={{
        marginBottom: 24,
        border: isComplete ? "2px solid #bbf7d0" : "2px solid #e2e8f0",
        borderRadius: 12,
        overflow: "hidden",
        transition: "border-color .4s",
      }}
    >
      {/* Phase banner */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 16px",
          background: isComplete ? "#f0fdf4" : "#f8fafc",
          borderBottom: "1px solid #e2e8f0",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontWeight: 700, fontSize: 14, color: "#1e293b" }}>
            Phase {phaseNumber} — {name}
          </span>
          <span
            style={{
              fontSize: 11,
              padding: "2px 8px",
              borderRadius: 12,
              background: parallel ? "#eff6ff" : "#fefce8",
              color: parallel ? "#1d4ed8" : "#854d0e",
              border: `1px solid ${parallel ? "#bfdbfe" : "#fef08a"}`,
            }}
          >
            {parallel ? "Running simultaneously" : "Sequential"}
          </span>
        </div>

        {isComplete && (
          <span
            style={{
              fontSize: 12,
              padding: "3px 10px",
              borderRadius: 12,
              background: "#dcfce7",
              color: "#166534",
              fontWeight: 600,
            }}
          >
            ✓ Phase complete
          </span>
        )}
      </div>

      {/* Agent grid */}
      <div
        style={{
          padding: 16,
          display: "grid",
          gridTemplateColumns: parallel && agents.length > 1 ? "repeat(auto-fit, minmax(260px, 1fr))" : "1fr",
          gap: 12,
        }}
      >
        {agents.map((role) => (
          <AgentCard
            key={role}
            agentRole={role}
            {...(agentStates[role] ?? { status: "waiting" })}
          />
        ))}
      </div>

      {/* Phase footer */}
      {isComplete && decisionsLocked.length > 0 && (
        <div
          style={{
            padding: "8px 16px",
            borderTop: "1px solid #dcfce7",
            background: "#f0fdf4",
            fontSize: 12,
            color: "#166534",
          }}
        >
          🔒 {decisionsLocked.length} decision{decisionsLocked.length !== 1 ? "s" : ""} locked
        </div>
      )}
    </div>
  );
}
