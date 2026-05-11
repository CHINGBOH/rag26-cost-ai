import React from 'react';
import {
  BlindspotCluster,
  LearningEngineStatus,
} from '../../services/metricsApi';
import { fmtDateTime } from '../../utils/dateUtils';
import { TYPE_ZH, ENGINE_TRIGGER_MODE_ZH } from '../../pages/learning-i18n';
import './SystemDiagnosticsDrawer.css';

interface AdvancedDataDrawerProps {
  open: boolean;
  onClose: () => void;
  blindspots: BlindspotCluster[];
  topTools: Array<[string, number]>;
  topTypes: Array<[string, number]>;
  engine: LearningEngineStatus | null;
}

export const AdvancedDataDrawer: React.FC<AdvancedDataDrawerProps> = ({
  open,
  onClose,
  blindspots,
  topTools,
  topTypes,
  engine,
}) => {
  if (!open) return null;

  return (
    <div className="diag-drawer-backdrop" onClick={onClose}>
      <aside
        className="diag-drawer"
        role="dialog"
        aria-label="高级数据"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="diag-drawer-head">
          <h2>📊 高级数据</h2>
          <button className="diag-close" onClick={onClose} aria-label="关闭">
            ✕
          </button>
        </header>
        <p className="diag-intro muted">
          这里是详细的技术统计：相似失败问题分组、工具调用频率、问题类型分布、学习引擎触发状态。
          普通使用者不需要看这里。
        </p>

        {/* 盲点聚类 */}
        <section className="diag-section">
          <div className="diag-section-head">
            <h3>相似失败问题分组（盲点聚类） <span className="muted small">({blindspots.length})</span></h3>
          </div>
          {blindspots.length === 0 ? (
            <p className="diag-empty">还没形成可聚合的盲点（需要 ≥ 2 个相近的失败问题）。</p>
          ) : (
            <ul className="gap-list" style={{ margin: 0, padding: 0, listStyle: 'none', display: 'grid', gap: 8 }}>
              {blindspots.map((c, i) => (
                <li key={i} className="gap-item q-failure">
                  <div className="gap-q">代表问题：{c.representative}</div>
                  <div className="gap-meta">
                    <span className="badge q-failure">规模 {c.size}</span>
                    <span className="muted small">{c.diagnosis}</span>
                  </div>
                  {c.queries && c.queries.length > 0 && (
                    <details className="gap-detail">
                      <summary>展开相似问题（{c.queries.length} 个）</summary>
                      <ul className="gap-sample-list">
                        {c.queries.map((q, j) => (
                          <li key={j}>{q}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* 工具使用频率 */}
        <section className="diag-section">
          <div className="diag-section-head">
            <h3>工具使用频率</h3>
          </div>
          {topTools.length === 0 ? (
            <p className="diag-empty">还没有工具调用记录。</p>
          ) : (
            <ul className="bar-list">
              {topTools.map(([tool, count]) => {
                const max = topTools[0][1];
                const pct = Math.max(2, Math.round((count / max) * 100));
                return (
                  <li key={tool}>
                    <div className="bar-label">
                      <code>{tool}</code>
                      <span className="muted small">{count}</span>
                    </div>
                    <div className="bar-track">
                      <div className="bar-fill" style={{ width: `${pct}%` }} />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {/* 问题类型分布 */}
        <section className="diag-section">
          <div className="diag-section-head">
            <h3>问题类型分布</h3>
          </div>
          {topTypes.length === 0 ? (
            <p className="diag-empty">还没有类型数据。</p>
          ) : (
            <ul className="bar-list">
              {topTypes.map(([type, count]) => {
                const max = topTypes[0][1];
                const pct = Math.max(2, Math.round((count / max) * 100));
                return (
                  <li key={type}>
                    <div className="bar-label">
                      <code>{TYPE_ZH[type] ?? type}</code>
                      <span className="muted small">{count}</span>
                    </div>
                    <div className="bar-track">
                      <div className="bar-fill alt" style={{ width: `${pct}%` }} />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {/* 学习引擎 */}
        <section className="diag-section">
          <div className="diag-section-head">
            <h3>🧠 学习引擎</h3>
          </div>
          {engine ? (
            <>
              <p className="muted small" style={{ marginTop: 0 }}>
                触发模式：{ENGINE_TRIGGER_MODE_ZH[engine.trigger_mode] ?? engine.trigger_mode}
              </p>
              <p className="muted small">{engine.trigger_description}</p>

              <h4 style={{ marginTop: 12, marginBottom: 4 }}>触发条件</h4>
              <table className="learn-runs-table" style={{ marginTop: 4 }}>
                <thead>
                  <tr>
                    <th>条件</th>
                    <th>状态</th>
                    <th>说明</th>
                  </tr>
                </thead>
                <tbody>
                  {engine.trigger_conditions.map((c, i) => (
                    <tr key={i}>
                      <td>{c.name}</td>
                      <td>
                        <span className={`badge q-${c.active ? 'good' : 'weak'}`}>
                          {c.active ? '已启用' : '未启用'}
                        </span>
                      </td>
                      <td className="muted small">
                        {c.command ? <code>{c.command}</code> : c.note || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <h4 style={{ marginTop: 12, marginBottom: 4 }}>上次回归</h4>
              {engine.last_run.summary ? (
                <ul className="diag-meta-list">
                  <li>时间：<code>{engine.last_run.ts ? fmtDateTime(engine.last_run.ts) : '—'}</code></li>
                  <li>金标题数：<b>{engine.last_run.summary.total ?? '—'}</b></li>
                  <li>通过：<b>{engine.last_run.summary.passed ?? '—'}</b></li>
                  <li>平均置信：<b>{engine.last_run.summary.avg_confidence?.toFixed(2) ?? '—'}</b></li>
                </ul>
              ) : (
                <p className="muted small">
                  无历史回归记录。运行 <code>python tests/test_agent_16.py</code> 生成。
                </p>
              )}

              <h4 style={{ marginTop: 12, marginBottom: 4 }}>近 24h 信号</h4>
              <ul className="diag-meta-list">
                <li>弱/失败运行：<b>{engine.signals_24h.weak_or_failed_runs}</b></li>
                <li>带评论的负面反馈：<b>{engine.signals_24h.pending_negative_feedback_with_text}</b></li>
              </ul>

              {engine.next_actions.length > 0 && (
                <>
                  <h4 style={{ marginTop: 12, marginBottom: 4 }}>建议下一步</h4>
                  <ul className="diag-meta-list">
                    {engine.next_actions.map((a, i) => (
                      <li key={i}>{a}</li>
                    ))}
                  </ul>
                </>
              )}
            </>
          ) : (
            <p className="diag-empty">加载中…</p>
          )}
        </section>
      </aside>
    </div>
  );
};

export default AdvancedDataDrawer;
