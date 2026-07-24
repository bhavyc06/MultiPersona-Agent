// CostPanel — shows real token + cost data from session_complete SSE.
// usageData is null until the session ends; panel shows a placeholder until then.

// Map both bare IDs (legacy) and inference-profile ARNs → friendly names.
// ARNs contain the AWS account ID — never display them directly.
const MODEL_NAMES = {
  // US West cross-region inference profile ARNs (current)
  "arn:aws:bedrock:us-west-1:654654399581:application-inference-profile/ejpjsea13wpw": "Opus 4.5 (deep)",
  "arn:aws:bedrock:us-west-1:654654399581:application-inference-profile/wxs8vfomtgt9": "Sonnet 4.5 (shallow)",
  "arn:aws:bedrock:us-west-1:654654399581:application-inference-profile/drf1d6igxbea": "Haiku 4.5 (utility)",
  // APAC cross-region inference profile ARNs (legacy — kept for old session data)
  "arn:aws:bedrock:ap-south-1:654654399581:application-inference-profile/xz6f6fgbpcmy": "Opus 4.5 (deep)",
  "arn:aws:bedrock:ap-south-1:654654399581:application-inference-profile/tvbo89xo0vxp": "Sonnet 4.5 (shallow)",
  "arn:aws:bedrock:ap-south-1:654654399581:application-inference-profile/mokx0bgyqra7": "Haiku 4.5 (utility)",
  // Bare model IDs (legacy / fallback)
  "claude-opus-4-5":           "Opus 4.5",
  "claude-sonnet-4-5":         "Sonnet 4.5",
  "claude-haiku-4-5-20251001": "Haiku 4.5",
};

const MODEL_COLORS = {
  // US West ARNs (current)
  "arn:aws:bedrock:us-west-1:654654399581:application-inference-profile/ejpjsea13wpw": "var(--violet-100)",
  "arn:aws:bedrock:us-west-1:654654399581:application-inference-profile/wxs8vfomtgt9": "var(--blue-100)",
  "arn:aws:bedrock:us-west-1:654654399581:application-inference-profile/drf1d6igxbea": "var(--success-bg)",
  // APAC ARNs (legacy)
  "arn:aws:bedrock:ap-south-1:654654399581:application-inference-profile/xz6f6fgbpcmy": "var(--violet-100)",
  "arn:aws:bedrock:ap-south-1:654654399581:application-inference-profile/tvbo89xo0vxp": "var(--blue-100)",
  "arn:aws:bedrock:ap-south-1:654654399581:application-inference-profile/mokx0bgyqra7": "var(--success-bg)",
  // Legacy bare IDs
  "claude-opus-4-5":           "var(--violet-100)",
  "claude-sonnet-4-5":         "var(--blue-100)",
  "claude-haiku-4-5-20251001": "var(--success-bg)",
};

function friendlyName(modelId) {
  if (MODEL_NAMES[modelId]) return MODEL_NAMES[modelId];
  // Never show ARNs — if an unknown ARN slips through, strip it to "Unknown model"
  if (modelId && modelId.startsWith("arn:")) return "Unknown model";
  return modelId ?? "Unknown";
}

function modelColor(modelId) {
  return MODEL_COLORS[modelId] ?? "var(--surface-2)";
}

function formatCost(usd) {
  if (!usd && usd !== 0) return "—";
  return `$${Number(usd).toFixed(4)}`;
}

function formatTokens(n) {
  if (!n) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}k`;
  return n.toString();
}

function formatDuration(ms) {
  if (!ms) return "—";
  const totalSec = Math.floor(ms / 1000);
  const mins = Math.floor(totalSec / 60);
  const secs = totalSec % 60;
  return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
}

// ── Panel header (shared) ─────────────────────────────────────────────────────

function PanelHeader() {
  return (
    <div
      style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "9px 12px", background: "var(--bg)",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>
        📊 Session Cost
      </span>
    </div>
  );
}

// ── Empty / loading state ─────────────────────────────────────────────────────

function CostPending() {
  return (
    <div
      style={{
        background: "var(--surface)", borderRadius: 10,
        border: "1px solid var(--border)", overflow: "hidden",
      }}
    >
      <PanelHeader />
      <div style={{ padding: "14px 12px" }}>
        <p style={{ fontSize: 12, color: "var(--faint)", fontStyle: "italic", margin: 0 }}>
          Cost summary appears when the session completes.
        </p>
      </div>
    </div>
  );
}

// ── Full cost breakdown ───────────────────────────────────────────────────────

export default function CostPanel({ usageData }) {
  if (!usageData) return <CostPending />;

  const {
    total_cost_usd     = 0,
    total_input_tokens  = 0,
    total_output_tokens = 0,
    cache_creation_tokens = 0,
    cache_read_tokens   = 0,
    total_duration_ms   = 0,
    by_model            = {},
  } = usageData;

  const totalTokens = total_input_tokens + total_output_tokens;
  const byModelEntries = Object.entries(by_model).sort(
    ([, a], [, b]) => b.cost_usd - a.cost_usd    // sort by cost descending
  );

  return (
    <div
      style={{
        background: "var(--surface)", borderRadius: 10,
        border: "1px solid var(--border)", overflow: "hidden",
      }}
    >
      <PanelHeader />

      <div style={{ padding: "12px" }}>

        {/* ── Total cost (headline) ──────────────────────────────────────── */}
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 26, fontWeight: 700, color: "var(--text-max)", lineHeight: 1 }}>
            {formatCost(total_cost_usd)}
          </div>
          <div style={{ fontSize: 11, color: "var(--faint)", marginTop: 4, lineHeight: 1.4 }}>
            Development cost via Claude CLI (includes CLI context caching
            overhead). Production API cost would be substantially lower.
          </div>
        </div>

        {/* ── Per-model breakdown ───────────────────────────────────────── */}
        {byModelEntries.length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--muted-2)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>
              By Model
            </div>
            {byModelEntries.map(([modelId, stats]) => {
              const barPct = total_cost_usd > 0
                ? Math.round((stats.cost_usd / total_cost_usd) * 100)
                : 0;
              const bg = modelColor(modelId);
              return (
                <div key={modelId} style={{ marginBottom: 10 }}>
                  {/* Model label row */}
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span
                        style={{
                          display: "inline-block", width: 10, height: 10,
                          borderRadius: 2, background: bg, border: "1px solid var(--tint-10)",
                        }}
                      />
                      <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text)" }}>
                        {friendlyName(modelId)}
                      </span>
                      <span style={{ fontSize: 11, color: "var(--dim)" }}>
                        {stats.calls} call{stats.calls !== 1 ? "s" : ""}
                      </span>
                    </div>
                    <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text)" }}>
                      {formatCost(stats.cost_usd)}
                    </span>
                  </div>

                  {/* Cost share bar */}
                  <div
                    style={{
                      height: 6, background: "var(--surface-2)",
                      borderRadius: 3, overflow: "hidden",
                    }}
                  >
                    <div
                      style={{
                        height: "100%", width: `${barPct}%`,
                        background: bg,
                        border: "1px solid var(--tint-08)",
                        borderRadius: 3,
                        transition: "width .3s ease",
                        minWidth: barPct > 0 ? 4 : 0,
                      }}
                    />
                  </div>

                  {/* Token sub-line */}
                  <div style={{ fontSize: 11, color: "var(--dim)", marginTop: 3 }}>
                    {formatTokens(stats.input_tokens)} in · {formatTokens(stats.output_tokens)} out
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* ── Token totals ──────────────────────────────────────────────── */}
        <div
          style={{
            borderTop: "1px solid var(--surface-2)",
            paddingTop: 10,
            marginBottom: 10,
          }}
        >
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--muted-2)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
            Tokens
          </div>
          {[
            ["Input",         total_input_tokens],
            ["Output",        total_output_tokens],
            ["Cache created", cache_creation_tokens],
            ["Cache read",    cache_read_tokens],
          ].map(([label, val]) => (
            <div
              key={label}
              style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}
            >
              <span style={{ fontSize: 12, color: "var(--muted-2)" }}>{label}</span>
              <span style={{ fontSize: 12, fontWeight: 500, color: "var(--text)" }}>
                {formatTokens(val)}
              </span>
            </div>
          ))}
        </div>

        {/* ── Duration ──────────────────────────────────────────────────── */}
        <div
          style={{
            borderTop: "1px solid var(--surface-2)",
            paddingTop: 10,
            display: "flex", justifyContent: "space-between",
          }}
        >
          <span style={{ fontSize: 12, color: "var(--muted-2)" }}>API time</span>
          <span style={{ fontSize: 12, fontWeight: 500, color: "var(--text)" }}>
            {formatDuration(total_duration_ms)}
          </span>
        </div>

      </div>
    </div>
  );
}
