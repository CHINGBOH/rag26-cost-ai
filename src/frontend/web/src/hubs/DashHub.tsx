/**
 * DashHub — 综合面板
 * 将 6 个功能页封装为子标签，底层组件零修改。
 * 路由格式: /hub/:tab  (tab 默认 runtime)
 */

import { useNavigate, useParams, Navigate } from 'react-router-dom';

import { AgentRuntimePage } from '../pages/AgentRuntimePage';
import { SearchPage }        from '../pages/SearchPage';
import { OpsPage }           from '../pages/OpsPage';
import { SystemPage }        from '../pages/SystemPage';
import { LearningPage }      from '../pages/LearningPage';
import { AgentManagePage }   from '../pages/AgentManagePage';
import { ModuleIcon }        from '../components/icons/ModuleIcon';
import type { ModuleName }   from '../components/icons/ModuleIcon';

import './DashHub.css';

const TABS: { key: string; label: string; icon: ModuleName }[] = [
  { key: 'runtime',  label: '运行时', icon: 'runtime'  },
  { key: 'search',   label: '检索',   icon: 'search'   },
  { key: 'ops',      label: '运维',   icon: 'ops'      },
  { key: 'system',   label: '系统',   icon: 'system'   },
  { key: 'learning', label: '学习',   icon: 'learning' },
  { key: 'agents',   label: 'AI 助手', icon: 'agents'  },
];

type TabKey = (typeof TABS)[number]['key'];

const VALID_TABS = new Set<string>(TABS.map((t) => t.key));

function TabContent({ tab }: { tab: TabKey }) {
  switch (tab) {
    case 'runtime':  return <AgentRuntimePage />;
    case 'search':   return <SearchPage />;
    case 'ops':      return <OpsPage />;
    case 'system':   return <SystemPage />;
    case 'learning': return <LearningPage />;
    case 'agents':   return <AgentManagePage />;
  }
}

export function DashHub() {
  const { tab } = useParams<{ tab?: string }>();
  const navigate = useNavigate();

  const activeTab: TabKey = (tab && VALID_TABS.has(tab) ? tab : 'runtime') as TabKey;

  // 若 URL 是 /hub 或 /hub/unknown，重定向到 /hub/runtime
  if (!tab || !VALID_TABS.has(tab)) {
    return <Navigate to="/hub/runtime" replace />;
  }

  return (
    <div className="dashhub">
      <nav className="dashhub-tabs" aria-label="综合面板子标签">
        {TABS.map(({ key, label, icon }) => (
          <button
            key={key}
            type="button"
            className={`dashhub-tab ${activeTab === key ? 'active' : ''}`}
            onClick={() => navigate(`/hub/${key}`)}
            aria-current={activeTab === key ? 'page' : undefined}
          >
            <span className="dashhub-tab-icon" aria-hidden="true">
              <ModuleIcon name={icon} size={15} />
            </span>
            <span className="dashhub-tab-label">{label}</span>
          </button>
        ))}
      </nav>

      <div className="dashhub-content">
        <TabContent tab={activeTab} />
      </div>
    </div>
  );
}
