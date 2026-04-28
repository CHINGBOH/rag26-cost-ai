/**
 * Agent Management Page — Task Queue + Active Agents 看板
 * 当前为 .agent/agents/ 配置文件的演示视图，数据为本地种子，
 * 待后端 agent registry / task queue 接口完成后接通真实数据。
 */

import { useState, useEffect } from 'react';
import { PageHeader } from '../components/common/PageHeader';
import './AgentManagePage.css';

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

export const AgentManagePage: React.FC = () => {
  const [tasks, setTasks] = useState<Task[]>(SEED_TASKS);
  const [agents] = useState<ActiveAgent[]>(SEED_AGENTS);

  // Simulate runtime ticking (replace with real WebSocket/polling)
  useEffect(() => {
    const interval = setInterval(() => {
      setTasks((prev) => [...prev]); // trigger re-render for live feel
    }, 30_000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="agent-manage-page">
      <PageHeader
        title="Agents 看板"
        subtitle="任务队列与运行中的 agent 概览"
        actions={<span className="demo-tag">演示数据</span>}
      />

      {/* Task Queue */}
      <section className="section-block">
        <h2 className="section-title">Task Queue</h2>
        <div className="task-queue-grid">
          <TaskColumn
            title="Pending" status="pending"
            count={countByStatus(tasks, 'pending')} tasks={tasks}
            accentClass="accent-pending"
          />
          <TaskColumn
            title="In Progress" status="in_progress"
            count={countByStatus(tasks, 'in_progress')} tasks={tasks}
            accentClass="accent-inprogress"
          />
          <TaskColumn
            title="Completed" status="completed"
            count={countByStatus(tasks, 'completed')} tasks={tasks}
            accentClass="accent-completed"
          />
          <TaskColumn
            title="Failed" status="failed"
            count={countByStatus(tasks, 'failed')} tasks={tasks}
            accentClass="accent-failed"
          />
        </div>
      </section>

      {/* Active Agents */}
      <section className="section-block">
        <h2 className="section-title">Active Agents</h2>
        <div className="agents-grid">
          {agents.map((a) => <AgentCard key={a.id} agent={a} />)}
        </div>
      </section>
    </div>
  );
};

export default AgentManagePage;
