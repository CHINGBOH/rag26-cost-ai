import React, { useState } from 'react';
import {
  getLearningProjectionDrift,
  reconcileLearningProjections,
  LearningProjectionDriftSummary,
  LearningProjectionReconcileAuditSummary,
} from '../../services/metricsApi';
import { fmtDateTime } from '../../utils/dateUtils';
import './SystemDiagnosticsDrawer.css';

interface SystemDiagnosticsDrawerProps {
  open: boolean;
  onClose: () => void;
  globalDrift: LearningProjectionDriftSummary | null | undefined;
  lastReconcile: LearningProjectionReconcileAuditSummary | null | undefined;
  onAfterReconcile?: () => void | Promise<void>;
}

export const SystemDiagnosticsDrawer: React.FC<SystemDiagnosticsDrawerProps> = ({
  open,
  onClose,
  globalDrift,
  lastReconcile,
  onAfterReconcile,
}) => {
  const [globalReconciling, setGlobalReconciling] = useState(false);
  const [globalNote, setGlobalNote] = useState<string | null>(null);
  const [runIdInput, setRunIdInput] = useState('');
  const [runDrift, setRunDrift] = useState<LearningProjectionDriftSummary | null>(null);
  const [runDriftLoading, setRunDriftLoading] = useState(false);
  const [runReconciling, setRunReconciling] = useState(false);
  const [runNote, setRunNote] = useState<string | null>(null);

  const totalDrift = globalDrift?.total_drift_count ?? 0;
  const driftedProjections = globalDrift?.drifted_projections ?? [];

  const handleGlobalReconcile = async () => {
    setGlobalReconciling(true);
    setGlobalNote(null);
    const result = await reconcileLearningProjections();
    if (!result) {
      setGlobalNote('重建请求失败，请稍后重试。');
    } else {
      setGlobalNote(
        `已重建 ${result.rebuilt_total} 条投影记录，剩余漂移 ${result.remaining_drift_count}。`,
      );
      if (onAfterReconcile) await onAfterReconcile();
    }
    setGlobalReconciling(false);
  };

  const handleInspectRun = async () => {
    const trimmed = runIdInput.trim();
    if (!trimmed) return;
    setRunDriftLoading(true);
    setRunNote(null);
    const drift = await getLearningProjectionDrift(trimmed);
    setRunDrift(drift);
    if (!drift) setRunNote('未能获取该 run 的 drift 诊断。');
    setRunDriftLoading(false);
  };

  const handleReconcileRun = async () => {
    const trimmed = runIdInput.trim();
    if (!trimmed) return;
    setRunReconciling(true);
    const result = await reconcileLearningProjections(trimmed);
    if (!result) {
      setRunNote('该 run 的 reconcile 请求失败。');
    } else {
      setRunNote(
        `已重建 ${result.rebuilt_total} 条记录，剩余漂移 ${result.remaining_drift_count}。`,
      );
      const drift = await getLearningProjectionDrift(trimmed);
      setRunDrift(drift);
      if (onAfterReconcile) await onAfterReconcile();
    }
    setRunReconciling(false);
  };

  const renderDriftGrid = (
    projections: Record<string, LearningProjectionDriftSummary['projections'][string]> | undefined,
  ) => {
    if (!projections) return null;
    const entries = Object.entries(projections);
    if (entries.length === 0) return null;
    return (
      <div className="diag-drift-grid">
        {entries.map(([name, detail]) => (
          <div
            key={name}
            className={`diag-drift-card ${(detail.drift_count || 0) > 0 ? 'has-drift' : ''}`}
          >
            <div className="diag-drift-card-title">{name}</div>
            <div className="diag-drift-card-count">{detail.drift_count || 0}</div>
            <div className="diag-drift-card-meta">
              <span>ledger {detail.ledger_count ?? 0}</span>
              <span>projection {detail.projection_count ?? 0}</span>
              <span>missing {(detail.missing_in_projection || []).length}</span>
              <span>stale {(detail.stale_in_projection || []).length}</span>
              <span>mismatch {(detail.mismatches || []).length}</span>
            </div>
          </div>
        ))}
      </div>
    );
  };

  if (!open) return null;

  return (
    <div className="diag-drawer-backdrop" onClick={onClose}>
      <aside
        className="diag-drawer"
        role="dialog"
        aria-label="系统自检"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="diag-drawer-head">
          <h2>🔧 系统自检</h2>
          <button className="diag-close" onClick={onClose} aria-label="关闭">
            ✕
          </button>
        </header>
        <p className="diag-intro muted">
          以下是 canonical event ledger 与投影读面（projection）的一致性诊断，面向运维/开发人员。
          普通使用者不需要关心此区域。
        </p>

        {/* 全局漂移 */}
        <section className="diag-section">
          <div className="diag-section-head">
            <h3>Projection 漂移（全局）</h3>
            <div className="diag-section-actions">
              <span className={`diag-total ${totalDrift > 0 ? 'warning' : 'healthy'}`}>
                {totalDrift}
              </span>
              <button
                className="diag-action-btn"
                onClick={handleGlobalReconcile}
                disabled={globalReconciling}
              >
                {globalReconciling ? '重建中…' : '重建全部 projection'}
              </button>
            </div>
          </div>
          {globalNote && <p className="diag-note">{globalNote}</p>}
          {driftedProjections.length === 0 ? (
            <p className="diag-empty">当前三张核心 projection 与 canonical ledger 保持一致。</p>
          ) : (
            <>
              <p className="muted small">
                受影响读面：{driftedProjections.join(', ')}
              </p>
              {renderDriftGrid(globalDrift?.projections)}
            </>
          )}
        </section>

        {/* 最近一次 Reconcile */}
        <section className="diag-section">
          <div className="diag-section-head">
            <h3>最近一次 Reconcile</h3>
          </div>
          {lastReconcile ? (
            <ul className="diag-meta-list">
              <li>
                时间：
                <code>
                  {lastReconcile.occurred_at ? fmtDateTime(lastReconcile.occurred_at) : '—'}
                </code>
              </li>
              <li>
                范围：
                <b>
                  {lastReconcile.scope === 'run'
                    ? `Run ${lastReconcile.run_id ?? '—'}`
                    : '全局'}
                </b>
              </li>
              <li>
                重建条目：<b>{lastReconcile.rebuilt_total}</b>
              </li>
              <li>
                剩余漂移：<b>{lastReconcile.remaining_drift_count}</b>
              </li>
            </ul>
          ) : (
            <p className="diag-empty">暂无 reconcile 审计记录。</p>
          )}
        </section>

        {/* 按 Run 诊断 */}
        <section className="diag-section">
          <div className="diag-section-head">
            <h3>按 Run 诊断 / 修复</h3>
          </div>
          <div className="diag-run-input">
            <input
              type="text"
              value={runIdInput}
              onChange={(e) => setRunIdInput(e.target.value)}
              placeholder="粘贴 run_id"
              spellCheck={false}
              autoComplete="off"
            />
            <button
              className="diag-action-btn"
              onClick={handleInspectRun}
              disabled={runDriftLoading || !runIdInput.trim()}
            >
              {runDriftLoading ? '加载中…' : '查看漂移'}
            </button>
            <button
              className="diag-action-btn"
              onClick={handleReconcileRun}
              disabled={runReconciling || !runIdInput.trim()}
            >
              {runReconciling ? '重建中…' : '重建该 run'}
            </button>
          </div>
          {runNote && <p className="diag-note">{runNote}</p>}
          {runDrift && (
            <>
              <div className="diag-run-summary">
                <span
                  className={`diag-total ${runDrift.total_drift_count > 0 ? 'warning' : 'healthy'}`}
                >
                  {runDrift.total_drift_count}
                </span>
                <span className="muted small">
                  受影响读面：
                  {runDrift.drifted_projections.length > 0
                    ? runDrift.drifted_projections.join(', ')
                    : '无'}
                </span>
              </div>
              {renderDriftGrid(runDrift.projections)}
            </>
          )}
        </section>
      </aside>
    </div>
  );
};

export default SystemDiagnosticsDrawer;
