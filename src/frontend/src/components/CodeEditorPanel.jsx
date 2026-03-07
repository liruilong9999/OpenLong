function buildSimpleDiff(originalContent, editedContent) {
  const left = String(originalContent || "").split("\n");
  const right = String(editedContent || "").split("\n");
  const size = Math.max(left.length, right.length);
  const rows = [];

  for (let index = 0; index < size; index += 1) {
    const before = left[index] ?? "";
    const after = right[index] ?? "";
    if (before === after) {
      rows.push({ type: "same", before, after });
      continue;
    }
    if (before) {
      rows.push({ type: "removed", before, after: "" });
    }
    if (after) {
      rows.push({ type: "added", before: "", after });
    }
  }

  return rows;
}


function CodeEditorPanel({
  selectedFile,
  originalContent,
  editedContent,
  onChange,
  onSave,
  saving,
}) {
  const diffRows = buildSimpleDiff(originalContent, editedContent);
  const dirty = String(originalContent || "") !== String(editedContent || "");

  return (
    <section className="ide-panel ide-editor-panel">
      <div className="ide-panel-header">
        <div>
          <div className="ide-panel-title">代码编辑器</div>
          <div className="ide-panel-subtitle">{selectedFile ? `${selectedFile.scope} · ${selectedFile.path}` : "选择一个文件开始编辑"}</div>
        </div>
        <div className="ide-toolbar-row">
          <button data-testid="ide-save" type="button" onClick={onSave} disabled={!selectedFile || !dirty || saving}>
            {saving ? "保存中" : "保存文件"}
          </button>
        </div>
      </div>

      {!selectedFile ? (
        <div className="panel-hint">请选择文件树中的文件。</div>
      ) : (
        <>
          <textarea
            data-testid="ide-editor"
            className="ide-editor-textarea"
            value={editedContent}
            onChange={(event) => onChange?.(event.target.value)}
            spellCheck={false}
          />

          <div className="ide-diff-block">
            <div className="ide-subtitle-row">Diff 预览</div>
            <div className="ide-diff-shell" data-testid="ide-diff">
              {diffRows.map((row, index) => (
                <div key={`${row.type}-${index}`} className={`ide-diff-line ${row.type}`}>
                  <span className="ide-diff-marker">{row.type === "added" ? "+" : row.type === "removed" ? "-" : " "}</span>
                  <code>{row.type === "removed" ? row.before : row.after}</code>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </section>
  );
}


export default CodeEditorPanel;
