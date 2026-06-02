export default function UiMockupViewer({ previewHtml }) {
  if (!previewHtml) {
    return (
      <div
        style={{
          padding: 24,
          background: "#f8fafc",
          borderRadius: 8,
          border: "1px dashed #cbd5e1",
          textAlign: "center",
          color: "#64748b",
          fontSize: 14,
          margin: "12px 0",
        }}
      >
        UI mockup will appear here when the Builder agent completes
      </div>
    );
  }

  const openInTab = () => {
    const blob = new Blob([previewHtml], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank");
    // Blob URLs auto-revoke when the tab closes
  };

  const downloadHtml = () => {
    const blob = new Blob([previewHtml], { type: "text/html" });
    const a = window.document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "ui-mockup.html";
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div style={{ margin: "12px 0" }}>
      <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        <button
          onClick={openInTab}
          style={{
            padding: "6px 14px", fontSize: 12, borderRadius: 6,
            border: "1px solid #cbd5e1", background: "#fff", cursor: "pointer",
          }}
        >
          Open in new tab
        </button>
        <button
          onClick={downloadHtml}
          style={{
            padding: "6px 14px", fontSize: 12, borderRadius: 6,
            border: "1px solid #cbd5e1", background: "#fff", cursor: "pointer",
          }}
        >
          Download HTML
        </button>
      </div>
      {/* sandbox="allow-scripts" only — no allow-same-origin (CSP) */}
      <iframe
        sandbox="allow-scripts"
        srcDoc={previewHtml}
        style={{
          width: "100%",
          height: 500,
          border: "1px solid #e2e8f0",
          borderRadius: 8,
        }}
        title="UI Mockup Preview"
      />
    </div>
  );
}
