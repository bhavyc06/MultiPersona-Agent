import { getRoleColor, getRoleEmoji, formatRole } from "../roleStyles.js";

// Display-only strip of expert pills from the "roster_selected" SSE event.
// Backend always auto-selects the roster — this is not a picker.

export default function RosterBadges({ roster = [] }) {
  if (!roster.length) return null;

  return (
    <div
      style={{
        background: "var(--surface)",
        borderRadius: 10,
        border: "1px solid var(--border)",
        padding: "12px 16px",
        marginBottom: 16,
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: "var(--faint)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          marginBottom: 10,
        }}
      >
        Team assembled
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {roster.map((role) => {
          const bg    = getRoleColor(role);
          const emoji = getRoleEmoji(role);
          return (
            <span
              key={role}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "5px 12px",
                borderRadius: 20,
                background: bg,
                fontSize: 13,
                fontWeight: 500,
                color: "var(--text-strong)",
                border: "1px solid var(--tint-06)",
              }}
            >
              <span
                style={{
                  fontFamily:
                    "Apple Color Emoji, Segoe UI Emoji, Noto Color Emoji, sans-serif",
                  fontSize: 15,
                  lineHeight: 1,
                }}
              >
                {emoji}
              </span>
              {formatRole(role)}
            </span>
          );
        })}
      </div>
    </div>
  );
}
