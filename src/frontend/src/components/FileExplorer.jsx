function TreeNode({ node, depth = 0, selectedPath = "", onSelect }) {
  const isDirectory = node?.type === "directory";
  const isSelected = node?.path === selectedPath;

  return (
    <div>
      <button
        type="button"
        className={`file-tree-node ${isSelected ? "active" : ""} ${isDirectory ? "directory" : "file"}`}
        style={{ paddingLeft: `${12 + depth * 14}px` }}
        onClick={() => !isDirectory && onSelect?.(node)}
      >
        <span className="file-tree-icon">{isDirectory ? "📁" : "📄"}</span>
        <span className="file-tree-name">{node?.name || "(unknown)"}</span>
      </button>

      {isDirectory && Array.isArray(node.children) && node.children.map((child) => (
        <TreeNode key={`${child.path}-${child.name}`} node={child} depth={depth + 1} selectedPath={selectedPath} onSelect={onSelect} />
      ))}
    </div>
  );
}


function FileExplorer({ treeData, loading, error, scope, onScopeChange, onRefresh, selectedPath, onSelect }) {
  return (
    <section className="ide-panel ide-file-explorer">
      <div className="ide-panel-header">
        <div>
          <div className="ide-panel-title">文件树</div>
          <div className="ide-panel-subtitle">浏览 project / workspace 文件</div>
        </div>
        <div className="ide-toolbar-row">
          <select value={scope} onChange={(event) => onScopeChange?.(event.target.value)}>
            <option value="project">Project</option>
            <option value="workspace">Workspace</option>
          </select>
          <button type="button" onClick={onRefresh}>刷新</button>
        </div>
      </div>

      <div className="file-tree-shell">
        {loading && <div className="panel-hint">正在加载文件树…</div>}
        {!loading && error && <div className="panel-hint error">{error}</div>}
        {!loading && treeData?.tree && (
          <TreeNode node={treeData.tree} selectedPath={selectedPath} onSelect={onSelect} />
        )}
        {!loading && !error && !treeData?.tree && <div className="panel-hint">暂无文件树数据。</div>}
      </div>
    </section>
  );
}


export default FileExplorer;
