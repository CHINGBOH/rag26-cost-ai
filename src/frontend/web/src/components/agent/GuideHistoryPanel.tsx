/**
 * GuideHistoryPanel — surfaces the system-导览助手 (guide agent) conversation
 * history persisted in `conversation_turns` (source='guide').
 *
 * Lives on AgentRuntimePage so that user-visible assistant interactions and
 * their iteration material appear next to the actual agent runtime.
 */

import { useEffect, useState } from 'react';
import { fmtTime } from '../../utils/dateUtils';
import { getConversations, ConversationTurn } from '../../services/metricsApi';

type GuideTurn = ConversationTurn;

interface GuideStats {
  total: number;
  uniqueSessions: number;
  avgAnswerLen: number;
  topQuestions: Array<{ q: string; n: number }>;
}

function computeStats(turns: GuideTurn[]): GuideStats {
  if (turns.length === 0) {
    return { total: 0, uniqueSessions: 0, avgAnswerLen: 0, topQuestions: [] };
  }
  const sessions = new Set(turns.map((t) => t.session_id));
  const totalLen = turns.reduce((s, t) => s + (t.assistant_content?.length || 0), 0);
  const counts = new Map<string, number>();
  turns.forEach((t) => {
    const q = (t.user_content || '').slice(0, 40).trim();
    if (!q) return;
    counts.set(q, (counts.get(q) || 0) + 1);
  });
  const topQuestions = Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([q, n]) => ({ q, n }));
  return {
    total: turns.length,
    uniqueSessions: sessions.size,
    avgAnswerLen: Math.round(totalLen / turns.length),
    topQuestions,
  };
}

export const GuideHistoryPanel: React.FC = () => {
  const [turns, setTurns] = useState<GuideTurn[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const load = async () => {
    try {
      setLoading(true);
      const list = await getConversations(50, 'guide');
      setTurns(list);
      setError('');
    } catch (e: any) {
      setError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  const stats = computeStats(turns);

  return (
    <section
      className="guide-history-panel"
      style={{
        background: 'var(--bg-elevated, #1f1f1f)',
        border: '1px solid var(--border-default, #333)',
        borderRadius: 8,
        padding: 16,
        marginBottom: 16,
      }}
    >
      <header
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 12,
        }}
      >
        <div>
          <h3 style={{ margin: 0, fontSize: 15 }}>🤖 导览助手对话历史</h3>
          <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--text-muted, #888)' }}>
            来自系统右下角导览助手的真实问答 · 30 秒自动刷新 ·
            数据源 <code>conversation_turns(source='guide')</code>
          </p>
        </div>
        <button
          onClick={load}
          style={{
            background: 'transparent',
            border: '1px solid var(--border-default)',
            color: 'var(--text-primary)',
            padding: '4px 10px',
            borderRadius: 4,
            cursor: 'pointer',
            fontSize: 12,
          }}
          disabled={loading}
        >
          {loading ? '刷新中…' : '刷新'}
        </button>
      </header>

      {/* KPI strip */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 12,
          marginBottom: 14,
        }}
      >
        <Kpi label="累计问答" value={stats.total} />
        <Kpi label="独立会话" value={stats.uniqueSessions} />
        <Kpi label="均答复长度" value={`${stats.avgAnswerLen} 字`} />
        <Kpi
          label="最常问"
          value={stats.topQuestions[0]?.q.slice(0, 14) || '—'}
          hint={stats.topQuestions[0] ? `${stats.topQuestions[0].n} 次` : ''}
        />
      </div>

      {error && (
        <div style={{ color: 'var(--color-bad, #d66)', fontSize: 12, marginBottom: 8 }}>
          ⚠️ {error}
        </div>
      )}

      {turns.length === 0 && !loading && !error && (
        <div
          style={{
            padding: 14,
            color: 'var(--text-muted, #888)',
            textAlign: 'center',
            fontSize: 13,
            border: '1px dashed var(--border-default)',
            borderRadius: 6,
          }}
        >
          尚无导览助手对话。打开右下角 🤖 提问后，记录会自动入库并在此显示。
        </div>
      )}

      {turns.length > 0 && (
        <div style={{ minHeight: 120, height: 360, overflowY: 'auto', resize: 'vertical' }}>
        <ul
          style={{
            listStyle: 'none',
            margin: 0,
            padding: 0,
          }}
        >
          {turns.slice(0, 20).map((t) => {
            const isOpen = expanded.has(t.id);
            return (
              <li
                key={t.id}
                onClick={() => {
                  const next = new Set(expanded);
                  if (isOpen) next.delete(t.id);
                  else next.add(t.id);
                  setExpanded(next);
                }}
                style={{
                  borderBottom: '1px solid var(--border-default)',
                  padding: '8px 4px',
                  cursor: 'pointer',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                  <strong style={{ color: 'var(--text-primary)' }}>
                    {(t.user_content || '').slice(0, 80) || '（空问题）'}
                  </strong>
                  <span style={{ color: 'var(--text-muted)', flexShrink: 0, marginLeft: 12 }}>
                    {fmtTime(t.ts)}
                  </span>
                </div>
                {isOpen && (
                  <div
                    style={{
                      marginTop: 6,
                      fontSize: 12,
                      color: 'var(--text-secondary, #ccc)',
                      whiteSpace: 'pre-wrap',
                      paddingLeft: 8,
                      borderLeft: '2px solid var(--color-primary)',
                    }}
                  >
                    {t.assistant_content || '（无回答）'}
                  </div>
                )}
                {!isOpen && t.assistant_content && (
                  <div
                    style={{
                      marginTop: 4,
                      fontSize: 11,
                      color: 'var(--text-muted)',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    → {t.assistant_content.slice(0, 100)}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
        </div>
      )}
    </section>
  );
};

const Kpi: React.FC<{ label: string; value: string | number; hint?: string }> = ({
  label,
  value,
  hint,
}) => (
  <div
    style={{
      background: 'var(--bg-canvas, #111)',
      borderRadius: 6,
      padding: '10px 12px',
      border: '1px solid var(--border-default)',
    }}
  >
    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{label}</div>
    <div style={{ fontSize: 18, fontWeight: 600, marginTop: 2 }}>{value}</div>
    {hint && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{hint}</div>}
  </div>
);
