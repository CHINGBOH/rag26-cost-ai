/**
 * 递归节点浏览器
 * 核心组件：每一层都是自我相似的结构
 * 
 * 设计哲学：
 * - 当前焦点是"太阳"，位于中心
 * - 子节点是"行星"，围绕太阳
 * - 父节点是"上一颗恒星"，通过"返回"可达
 * - 元信息是"宇宙背景辐射"，无处不在
 */

import { useState, useCallback, useMemo } from 'react';
import {
  RecursiveNode,
  RecursiveViewState,
  RecursiveUIEvent
} from '@rag/shared';
import './RecursiveNodeBrowser.css';

interface RecursiveNodeBrowserProps {
  // 当前视野状态
  viewState: RecursiveViewState;
  
  // 当前焦点的节点
  focusNode: RecursiveNode;
  
  // 操作回调
  onDrillDown: (nodeId: string) => void;
  onClimbUp: () => void;
  onJumpTo: (path: string[]) => void;
  onCreateBranch: (fromNodeId: string, name: string) => void;
  onAnnotate: (nodeId: string, annotation: string) => void;

  
  // 事件监听
  onEvent?: (event: RecursiveUIEvent) => void;
}

export const RecursiveNodeBrowser: React.FC<RecursiveNodeBrowserProps> = ({
  viewState,
  focusNode,
  onDrillDown,
  onClimbUp,
  onJumpTo,
  onCreateBranch,
  onAnnotate,

  onEvent
}) => {
  const [showMeta, setShowMeta] = useState(true);
  const [branchName, setBranchName] = useState('');
  const [annotation, setAnnotation] = useState('');
  const [showBranchInput, setShowBranchInput] = useState(false);

  // 计算当前节点的元信息
  const meta = useMemo(() => ({
    depth: focusNode.recursionMeta.depth,
    confidence: focusNode.recursionMeta.confidence,
    gain: focusNode.recursionMeta.informationGain,
    children: focusNode.children.length,
    path: focusNode.recursionMeta.path
  }), [focusNode]);

  // 处理下钻
  const handleDrillDown = useCallback((childId: string) => {
    const child = focusNode.children.find(c => c.id === childId);
    if (child) {
      onDrillDown(childId);
      onEvent?.({
        type: 'drill_down',
        from: focusNode,
        to: child
      });
    }
  }, [focusNode, onDrillDown, onEvent]);

  // 处理上爬
  const handleClimbUp = useCallback(() => {
    if (focusNode.parent) {
      onClimbUp();
      onEvent?.({
        type: 'climb_up',
        from: focusNode,
        to: { id: focusNode.parent } as RecursiveNode // 简化，实际应从store获取
      });
    }
  }, [focusNode, onClimbUp, onEvent]);

  // 处理创建分支
  const handleCreateBranch = useCallback(() => {
    if (branchName.trim()) {
      onCreateBranch(focusNode.id, branchName.trim());
      setBranchName('');
      setShowBranchInput(false);
    }
  }, [branchName, focusNode.id, onCreateBranch]);

  // 处理标注
  const handleAnnotate = useCallback(() => {
    if (annotation.trim()) {
      onAnnotate(focusNode.id, annotation.trim());
      setAnnotation('');
    }
  }, [annotation, focusNode.id, onAnnotate]);

  // 获取节点类型图标
  const getNodeIcon = (type: string) => {
    switch (type) {
      case 'answer': return '🎯';
      case 'claim': return '📌';
      case 'evidence': return '📄';
      case 'source': return '📚';
      case 'contradiction': return '⚠️';
      case 'user-branch': return '🔀';
      default: return '📍';
    }
  };

  // 获取置信度颜色
  const getConfidenceColor = (confidence: number) => {
    if (confidence >= 0.8) return 'var(--color-success)';
    if (confidence >= 0.6) return 'var(--color-warning)';
    return 'var(--color-error)';
  };

  return (
    <div className="recursive-browser">
      {/* 宇宙背景：元信息层 */}
      {showMeta && (
        <div className="meta-layer">
          <div className="meta-grid">
            <div className="meta-item">
              <span className="meta-label">深度</span>
              <span className="meta-value depth">{meta.depth}</span>
            </div>
            <div className="meta-item">
              <span className="meta-label">置信度</span>
              <span 
                className="meta-value confidence"
                style={{ color: getConfidenceColor(meta.confidence) }}
              >
                {(meta.confidence * 100).toFixed(0)}%
              </span>
            </div>
            <div className="meta-item">
              <span className="meta-label">信息增益</span>
              <span className="meta-value gain">
                {(meta.gain * 100).toFixed(0)}%
              </span>
            </div>
            <div className="meta-item">
              <span className="meta-label">子节点</span>
              <span className="meta-value children">{meta.children}</span>
            </div>
          </div>
          
          {/* 路径导航 */}
          <div className="path-navigator">
            <span className="path-label">路径:</span>
            {meta.path.map((nodeId, idx) => (
              <span key={nodeId} className="path-segment">
                <button 
                  className="path-btn"
                  onClick={() => onJumpTo(meta.path.slice(0, idx + 1))}
                >
                  L{idx}
                </button>
                {idx < meta.path.length - 1 && (
                  <span className="path-arrow">→</span>
                )}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* 上一颗恒星：父节点返回 */}
      {focusNode.parent && (
        <div className="parent-access">
          <button className="parent-btn" onClick={handleClimbUp}>
            ↑ 返回上一层 (L{meta.depth - 1})
          </button>
        </div>
      )}

      {/* 当前太阳：焦点节点 */}
      <div className="focus-node">
        <div className="node-header">
          <span className="node-icon">{getNodeIcon(focusNode.type)}</span>
          <span className="node-type">{focusNode.type}</span>
          {focusNode.uiState.userModified && (
            <span className="user-modified-badge">✏️ 已编辑</span>
          )}
          {focusNode.uiState.branchFrom && (
            <span className="branch-badge">🔀 分支</span>
          )}
        </div>
        
        <div className="node-content">
          {focusNode.content}
        </div>

        {/* 专家判断（如果有） */}
        {focusNode.recursionMeta.expertJudgment && (
          <div className="expert-judgment-in-node">
            <div className="judgment-header">
              <span className="judgment-label">专家判断</span>
              <span 
                className="judgment-decision"
                style={{
                  color: focusNode.recursionMeta.expertJudgment.decision === 'satisfy' 
                    ? 'var(--color-success)' 
                    : 'var(--color-warning)'
                }}
              >
                {focusNode.recursionMeta.expertJudgment.decision}
              </span>
            </div>
            <p className="judgment-reasoning">
              {focusNode.recursionMeta.expertJudgment.reasoning}
            </p>
          </div>
        )}

        {/* 用户操作区 */}
        <div className="node-actions">
          <button 
            className="action-btn annotate"
            onClick={() => setAnnotation('')}
          >
            💬 标注
          </button>
          <button 
            className="action-btn branch"
            onClick={() => setShowBranchInput(!showBranchInput)}
          >
            🔀 创建分支
          </button>
          <button 
            className="action-btn meta-toggle"
            onClick={() => setShowMeta(!showMeta)}
          >
            {showMeta ? '📊' : '📈'} 元信息
          </button>
        </div>

        {/* 标注输入 */}
        {annotation !== undefined && (
          <div className="annotation-input">
            <textarea
              value={annotation}
              onChange={(e) => setAnnotation(e.target.value)}
              placeholder="输入你的质疑、补充或思考..."
              rows={3}
            />
            <button onClick={handleAnnotate}>提交标注</button>
          </div>
        )}

        {/* 分支输入 */}
        {showBranchInput && (
          <div className="branch-input">
            <input
              type="text"
              value={branchName}
              onChange={(e) => setBranchName(e.target.value)}
              placeholder="给分支起个名字..."
            />
            <button onClick={handleCreateBranch}>创建</button>
          </div>
        )}
      </div>

      {/* 行星系统：子节点 */}
      {focusNode.children.length > 0 && (
        <div className="children-orbit">
          <h3 className="orbit-title">
            支撑/关联 ({focusNode.children.length})
          </h3>
          <div className="children-grid">
            {focusNode.children.map((child) => (
              <div 
                key={child.id}
                className={`child-node ${child.uiState.expanded ? 'expanded' : ''}`}
                onClick={() => handleDrillDown(child.id)}
              >
                <div className="child-header">
                  <span className="child-icon">{getNodeIcon(child.type)}</span>
                  <span 
                    className="child-confidence"
                    style={{ color: getConfidenceColor(child.recursionMeta.confidence) }}
                  >
                    {(child.recursionMeta.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="child-preview">
                  {child.content.slice(0, 100)}
                  {child.content.length > 100 ? '...' : ''}
                </div>
                {child.children.length > 0 && (
                  <div className="child-has-children">
                    还有 {child.children.length} 层 ↓
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 并行分支面板 */}
      {viewState.branches.size > 0 && (
        <div className="branches-panel">
          <h3 className="branches-title">
            并行分支 ({viewState.branches.size})
          </h3>
          {Array.from(viewState.branches.values()).map((branch) => (
            <div key={branch.id} className="branch-item">
              <span className="branch-name">{branch.name}</span>
              <span className="branch-status">{branch.status}</span>
              <span className="branch-from">
                从 L{viewState.history.indexOf(branch.forkedFrom)} 分叉
              </span>
            </div>
          ))}
        </div>
      )}

      {/* 全局状态栏 */}
      <div className="global-status">
        <span>最大深度: {viewState.globalMeta.maxDepthReached}</span>
        <span>总节点: {viewState.globalMeta.totalNodes}</span>
        <span>用户分支: {viewState.globalMeta.userBranches}</span>
      </div>
    </div>
  );
};
