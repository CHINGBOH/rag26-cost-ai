/**
 * Agent Management Page — Task Queue + Active Agents 看板
 * Real data sources:
 *   - Active Agents: /api/v1/agents/registry (reads .agent/agents/*.md)
 *   - Task Queue:    /api/v1/agents/tasks    (reads ingest_jobs)
 * Falls back to seed data if backend is unreachable.
 */

import { useState, useEffect } from 'react';
import { PageHeader } from '../components/common/PageHeader';
import './AgentManagePage.css';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

/* ── Types ───────────────────────────────────────────── */

type TaskStatus = 'pending' | 'in_progress' | 'completed' | 'failed';
type AgentStatus = 'active' | 'completed' | 'idle';

interface Task {
  id: string;
  label: string;
  tag: string;
  status: TaskStatus;
}

interface ActiveAgent {
  id: string;
  name: string;
  role: string;
  model: 'SONNET' | 'HAIKU' | 'OPUS';
  description: string;
  runtimeSec: number;
  taskCount: number;
  status: AgentStatus;
}

/* ── Static seed data (replace with API when backend ready) ── */

const SEED_TASKS: Task[] = [
  { id: 'task-001', label: 'Setup Express server with TypeScript', tag: 'eng-backend', status: 'completed' },
  { id: 'task-002', label: 'Create initial SQLite schema', tag: 'eng-database', status: 'completed' },
  { id: 'task-003', label: 'Initialize React with Vite', tag: 'eng-frontend', status: 'completed' },
  { id: 'task-004', label: 'Configure ESLint and Prettier', tag: 'ops-devops', status: 'completed' },
  { id: 'task-005', label: 'Implement user registration endpoint', tag: 'eng-backend', status: 'completed' },
  { id: 'task-012', label: 'Implement JWT refresh token rotation', tag: 'eng-backend', status: 'in_progress' },
  { id: 'task-013', label: 'Add form validation to signup page', tag: 'eng-frontend', status: 'in_progress' },
  { id: 'task-015', label: 'Create migration for user preferences table', tag: 'eng-database', status: 'pending' },
  { id: 'task-016', label: 'Implement dark mode toggle component', tag: 'eng-frontend', status: 'pending' },
  { id: 'task-017', label: 'Write E2E tests for checkout flow', tag: 'qa-testing', status: 'pending' },
];

const SEED_AGENTS: ActiveAgent[] = [
  {
    id: 'eng-001-backend-api', name: 'eng-001-backend-api', role: 'Engineering Backend',
    model: 'SONNET', status: 'active', runtimeSec: 754,
    taskCount: 5, description: 'Implementing POST /api/todos endpoint with validation and SQLite storage',
  },
  {
    id: 'eng-002-frontend-ui', name: 'eng-002-frontend-ui', role: 'Engineering Frontend',
    model: 'SONNET', status: 'active', runtimeSec: 501,
    taskCount: 3, description: 'Building React components for todo list with Tailwind styling',
  },
  {
    id: 'qa-001-testing', name: 'qa-001-testing', role: 'QA Testing',
    model: 'HAIKU', status: 'active', runtimeSec: 345,
    taskCount: 8, description: 'Writing unit tests for authentication module',
  },
  {
    id: 'review-security-001', name: 'review-security-001', role: 'Security Review',
    model: 'OPUS', status: 'active', runtimeSec: 192,
    taskCount: 2, description: 'Analyzing auth flow for OWASP vulnerabilities',
  },
  {
    id: 'ops-devops-001', name: 'ops-devops-001', role: 'Operations DevOps',
    model: 'SONNET', status: 'active', runtimeSec: 908,
    taskCount: 4, description: 'Configuring GitHub Actions CI/CD pipeline',
  },
  {
    id: 'biz-marketing-001', name: 'biz-marketing-001', role: 'Business Marketing',
    model: 'HAIKU', status: 'completed', runtimeSec: 393,
    taskCount: 2, description: 'Creating landing page copy and SEO meta tags',
  },
];

/* ── Helpers ─────────────────────────────────────────── */

function fmtRuntime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}m ${String(s).padStart(2, '0')}s`;
}

function countByStatus(tasks: Task[], status: TaskStatus): number {
  return tasks.filter((t) => t.status === status).length;
}

const MODEL_COLOR: Record<ActiveAgent['model'], string> = {
  SONNET: 'model-sonnet',
  HAIKU: 'model-haiku',
  OPUS: 'model-opus',
};

/* ── Sub-components ──────────────────────────────────── */

function TaskCard({ task }: { task: Task }) {
  return (
    <div className="task-card">
      <div className="task-id">{task.id}</div>
      <div className={`task-tag tag-${task.tag.split('-')[0]}`}>{task.tag}</div>
      <div className="task-label">{task.label}</div>
    </div>
  );
}

function TaskColumn({ title, status, count, tasks, accentClass }: {
  title: string; status: TaskStatus; count: number; tasks: Task[]; accentClass: string;
}) {
  const col = tasks.filter((t) => t.status === status);
  return (
    <div className="task-column">
      <div className={`task-column-header ${accentClass}`}>
        <span className="col-title">{title}</span>
        <span className="col-count">{count}</span>
      </div>
      <div className="task-column-body">
        {col.map((t) => <TaskCard key={t.id} task={t} />)}
      </div>
    </div>
  );
}

function AgentCard({ agent }: { agent: ActiveAgent }) {
  return (
    <div className={`agent-card ${agent.status === 'completed' ? 'agent-completed' : ''}`}>
      <div className="agent-card-header">
        <span className="agent-name">{agent.name}</span>
        <span className={`agent-model-badge ${MODEL_COLOR[agent.model]}`}>{agent.model}</span>
      </div>
      <div className="agent-role">{agent.role}</div>
      <div className="agent-desc">{agent.description}</div>
      <div className="agent-meta">
        <span>Runtime: {fmtRuntime(agent.runtimeSec)}</span>
        <span>Tasks: {agent.taskCount}</span>
      </div>
      <div className="agent-footer">
        {agent.status === 'active'
          ? <span className="agent-status-dot active">● Active</span>
          : <span className="agent-status-dot completed">Completed</span>}
      </div>
    </div>
  );
}

/* ── Main page ───────────────────────────────────────── */

function normalizeModel(raw: string | undefined): ActiveAgent['model'] {
  const m = (raw || '').toUpperCase();
  if (m.includes('OPUS')) return 'OPUS';
  if (m.includes('HAIKU')) return 'HAIKU';
  return 'SONNET';
}

export const AgentManagePage: React.FC = () => {
  const [tasks, setTasks] = useState<Task[]>(SEED_TASKS);
  const [agents, setAgents] = useState<ActiveAgent[]>(SEED_AGENTS);
  const [dataSource, setDataSource] = useState<'live' | 'seed' | 'partial'>('seed');
  const [error, setError] = useState<string | null>(null);

  async function loadAll() {
    let liveTasks = false;
    let liveAgents = false;
    try {
      const r = await fetch(`${API_BASE}/api/v1/agents/registry`);
      if (r.ok) {
        const j = await r.json();
        const list: ActiveAgent[] = (j.agents || []).map((a: Record<string, unknown>) => ({
          id: String(a.id),
          name: String(a.name || a.id),
          role: String(a.role || ''),
          model: normalizeModel(a.model as string | undefined),
          description: String(a.description || a.role || ''),
          runtimeSec: 0,
          taskCount: 0,
          status: 'idle' as AgentStatus,
        }));
        if (list.length) {
          setAgents(list);
          liveAgents = true;
        }
      }
    } catch (e) {
      console.warn('[AgentManage] registry fetch failed', e);
    }
    try {
      const r = await fetch(`${API_BASE}/api/v1/agents/tasks?limit=50`);
      if (r.ok) {
        const j = await r.json();
        const list: Task[] = (j.tasks || []).map((t: Record<string, unknown>) => ({
          id: String(t.id),
          label: String(t.label || t.id),
          tag: String(t.tag || 'ingest'),
          status: (t.status as TaskStatus) || 'pending',
        }));
        if (list.length) {
          setTasks(list);
          liveTasks = true;
        }
      }
    } catch (e) {
      console.warn('[AgentManage] tasks fetch failed', e);
    }
    if (liveTasks && liveAgents) setDataSource('live');
    else if (liveTasks || liveAgents) setDataSource('partial');
    else {
      setDataSource('seed');
      setError('后端 /api/v1/agents/* 不可达，显示种子数据');
    }
  }

  useEffect(() => {
    loadAll();
    const interval = setInterval(loadAll, 30_000);
    return () => clearInterval(interval);
  }, []);

  const sourceTag =
    dataSource === 'live' ? '实时数据'
    : dataSource === 'partial' ? '部分实时'
    : '演示数据';

  return (
    <div className="agent-manage-page">
      <PageHeader
        title="Agent 管理看板"
        subtitle={
          dataSource === 'live'
            ? '任务来自 ingest_jobs，agent 来自 .agent/agents/'
            : '任务队列与运行中的 agent 概览'
        }
        actions={<span className="demo-tag">{sourceTag}</span>}
      />

      {error && dataSource === 'seed' && (
        <div className="section-block" style={{ padding: '8px 12px', background: '#fff3cd', borderRadius: 4, marginBottom: 12 }}>
          ⚠ {error}
        </div>
      )}      {/* 任务队列 */}
      <section className="section-block">
        <h2 className="section-title">任务队列</h2>
        <div className="task-queue-grid">
          <TaskColumn
            title="待处理" status="pending"
            count={countByStatus(tasks, 'pending')} tasks={tasks}
            accentClass="accent-pending"
          />
          <TaskColumn
            title="进行中" status="in_progress"
            count={countByStatus(tasks, 'in_progress')} tasks={tasks}
            accentClass="accent-inprogress"
          />
          <TaskColumn
            title="已完成" status="completed"
            count={countByStatus(tasks, 'completed')} tasks={tasks}
            accentClass="accent-completed"
          />
          <TaskColumn
            title="失败" status="failed"
            count={countByStatus(tasks, 'failed')} tasks={tasks}
            accentClass="accent-failed"
          />
        </div>
      </section>

      {/* 活跃 Agent */}
      <section className="section-block">
        <h2 className="section-title">活跃 Agent</h2>
        <div className="agents-grid">
          {agents.map((a) => <AgentCard key={a.id} agent={a} />)}
        </div>
      </section>
    </div>
  );
};

export default AgentManagePage;
