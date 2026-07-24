// Shared role presentation constants — imported by MessageBubble, RosterBadges, ChatWindow

export const ROLE_COLORS = {
  ai_architect:       "var(--blue-100)",
  solution_architect: "var(--violet-100)",
  data_engineer:      "var(--success-bg)",
  data_scientist:     "var(--yellow-bg)",
  ai_engineer:        "var(--pink-200)",
  solution_engineer:  "var(--sky-100)",
  ui_builder:         "var(--pink-100)",
  project_manager:    "var(--green-50)",
};

export const ROLE_EMOJIS = {
  ai_architect:       "🧠",
  solution_architect: "🏗️",
  data_engineer:      "⚙️",
  data_scientist:     "📊",
  ai_engineer:        "🤖",
  solution_engineer:  "🔧",
  ui_builder:         "🎨",
  project_manager:    "📋",
};

export function formatRole(role) {
  if (!role) return "Agent";
  return role.split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

// ── Dynamic registry for custom personas registered at runtime ────────────────
// Populated by registerPersona() when persona_added SSE fires.
// Module-level so ALL components see updates without prop-drilling.
const _dynamicEmojis = {};
const _dynamicColors = {};

export function registerPersona(role, emoji, color) {
  if (emoji) _dynamicEmojis[role] = emoji;
  if (color) _dynamicColors[role] = color;
}

export function getRoleEmoji(role) {
  return ROLE_EMOJIS[role] ?? _dynamicEmojis[role] ?? "🤖";
}

export function getRoleColor(role) {
  return ROLE_COLORS[role] ?? _dynamicColors[role] ?? "var(--border)";
}
