// Single decision pill with state-based styling, proposed_by, and optional provenance.

const STATE_STYLES = {
  proposed: {
    background: "var(--yellow-bg)",
    border:     "1px solid var(--amber-border)",
    color:      "var(--amber-text)",
    badgeBg:    "var(--amber-border)",
    badgeColor: "var(--amber-text-2)",
    label:      "PROPOSED",
  },
  challenged: {
    background: "var(--orange-bg)",
    border:     "1px solid var(--orange)",
    color:      "var(--orange-text)",
    badgeBg:    "var(--orange)",
    badgeColor: "var(--surface)",
    label:      "CHALLENGED",
  },
  locked: {
    background: "var(--success-bg)",
    border:     "1px solid var(--success-border)",
    color:      "var(--success-text)",
    badgeBg:    "var(--success-border)",
    badgeColor: "var(--success-text-2)",
    label:      "LOCKED",
  },
};

const FALLBACK = {
  background: "var(--surface-2)",
  border:     "1px solid var(--border-strong)",
  color:      "var(--slate)",
  badgeBg:    "var(--border-strong)",
  badgeColor: "var(--slate)",
  label:      "UNKNOWN",
};

export default function DecisionBadge({ decision }) {
  const { text = "", proposed_by = "", state = "proposed", provenance } = decision;
  const s = STATE_STYLES[state] ?? FALLBACK;

  const shortProposedBy =
    proposed_by.length > 20 ? proposed_by.slice(0, 20) + "…" : proposed_by;
  const shortText = text.length > 80 ? text.slice(0, 80) + "…" : text;

  return (
    <div
      style={{
        background: s.background,
        border:     s.border,
        borderRadius: 8,
        padding:    "6px 10px",
        marginBottom: 8,
        color:      s.color,
        fontSize:   13,
      }}
    >
      {/* Top row: state badge + proposed_by */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
        <span
          style={{
            display:    "inline-block",
            padding:    "1px 6px",
            borderRadius: 4,
            fontSize:   10,
            fontWeight: 700,
            letterSpacing: "0.05em",
            background: s.badgeBg,
            color:      s.badgeColor,
          }}
        >
          {s.label}
        </span>
        <span style={{ fontSize: 11, color: s.color, opacity: 0.7, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {shortProposedBy}
        </span>
      </div>

      {/* Decision text */}
      <div
        title={text}
        style={{
          fontSize:   12,
          lineHeight: 1.45,
          wordBreak:  "break-word",
        }}
      >
        {shortText}
      </div>

      {/* Provenance (only when set) */}
      {provenance && (
        <div
          style={{
            marginTop:  4,
            fontSize:   11,
            fontStyle:  "italic",
            opacity:    0.7,
          }}
        >
          via {provenance}
        </div>
      )}
    </div>
  );
}
