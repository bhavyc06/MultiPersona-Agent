// Shared role presentation constants — imported by MessageBubble, RosterBadges, ChatWindow

export const ROLE_COLORS = {
  ai_architect:       "#dbeafe",
  solution_architect: "#ede9fe",
  data_engineer:      "#dcfce7",
  data_scientist:     "#fef9c3",
  ai_engineer:        "#ffe4e6",
  solution_engineer:  "#e0f2fe",
  ui_builder:         "#fce7f3",
  project_manager:    "#f0fdf4",
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
  return ROLE_COLORS[role] ?? _dynamicColors[role] ?? "#e2e8f0";
}
