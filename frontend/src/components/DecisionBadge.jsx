// Single decision pill with state-based styling, proposed_by, and optional provenance.

const STATE_STYLES = {
  proposed: {
    background: "#fef9c3",
    border:     "1px solid #fde047",
    color:      "#854d0e",
    badgeBg:    "#fde047",
    badgeColor: "#713f12",
    label:      "PROPOSED",
  },
  challenged: {
    background: "#ffedd5",
    border:     "1px solid #fb923c",
    color:      "#9a3412",
    badgeBg:    "#fb923c",
    badgeColor: "#fff",
    label:      "CHALLENGED",
  },
  locked: {
    background: "#dcfce7",
    border:     "1px solid #86efac",
    color:      "#166534",
    badgeBg:    "#86efac",
    badgeColor: "#14532d",
    label:      "LOCKED",
  },
};

const FALLBACK = {
  background: "#f1f5f9",
  border:     "1px solid #cbd5e1",
  color:      "#475569",
  badgeBg:    "#cbd5e1",
  badgeColor: "#475569",
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
