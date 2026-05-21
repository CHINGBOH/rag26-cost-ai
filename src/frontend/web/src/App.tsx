/**
 * 主应用 — 三板块架构 (#141)
 * 🏠 资源介绍 /
 * 💬 咨询  /rag
 * ⛓  管道  /pipeline
 * 🧩 综合  /hub/:tab  (运行时·检索·运维·系统·学习·Agent)
 */

import { useEffect, useState, useRef, useCallback, Component } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { BrowserRouter, Routes, Route, Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { ModuleIcon } from './components/icons/ModuleIcon';
import type { ModuleName } from './components/icons/ModuleIcon';
import { AUTH_STORAGE_KEY, clearAuthState, type AuthState, readAuthState } from './services/auth';

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null };
  static getDerivedStateFromError(e: Error) { return { error: e }; }
  render() {
    if (this.state.error) {
      const e = this.state.error as Error;
      return (
        <div style={{ padding: 32, fontFamily: 'monospace', color: '#dc2626', background: '#fef2f2', minHeight: '100vh' }}>
          <h2>⚠ React 渲染错误（请截图发给 Copilot）</h2>
          <pre style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{e.message}</pre>
          <pre style={{ whiteSpace: 'pre-wrap', fontSize: 11, color: '#6b7280' }}>{e.stack}</pre>
        </div>
      );
    }
    return this.props.children;
  }
}

// 核心页面（主导航直接加载）
import { LibraryPage }   from './pages/LibraryPage';
import { AgentChat }     from './pages/AgentChat';
import { PipelinePage }  from './pages/PipelinePage';

// 综合面板外壳（包裹 6 个子标签页）
import { DashHub } from './hubs/DashHub';

// 归档页 — 懒加载，防止 DocsReader 的 ?raw 路径拖垮主包
import { lazy, Suspense } from 'react';
const AgentRuntimeDeepDive = lazy(() => import('./components/common/AgentRuntimeDeepDive'));
const AgentRuntimeFolk     = lazy(() => import('./components/common/AgentRuntimeFolk'));
const DocsReader           = lazy(() => import('./components/common/DocsReader'));

import './App.css';
import './styles/theme.css';

const PUBLIC_NAV_ITEMS: { path: string; label: string; icon: ModuleName }[] = [
  { path: '/',         label: '项目资源', icon: 'hub'      },
];

const PRIVATE_NAV_ITEMS: { path: string; label: string; icon: ModuleName }[] = [
  { path: '/rag',      label: '智能检索', icon: 'library'  },
  { path: '/pipeline', label: '管道',    icon: 'pipeline' },
  { path: '/hub',      label: '综合面板', icon: 'hub'      },
];

const SITE_URL = 'https://threefirestone.com';
const GITHUB_OWNER_URL = 'https://github.com/CHINGBOH';
const PUBLIC_RESUME_URL = '/resume.html';
const PUBLIC_RAG_REPO_URL = 'https://github.com/CHINGBOH/threefirestone-cost-intelligence';
const PUBLIC_BEAUTYOS_REPO_URL = 'https://github.com/CHINGBOH/ai-beautyos';
const PUBLIC_HERMES_FRAMEWORK_URL = 'https://github.com/CHINGBOH/hermes-agent';
const PUBLIC_BEAUTYOS_HERMES_URL = 'https://github.com/CHINGBOH/beautyos-hermes';
const RAG_ENTRY_URL = `${SITE_URL}/rag`;
const BEAUTYOS_ENTRY_URL = `${SITE_URL}/beautyos/`;
const PIPELINE_URL = `${SITE_URL}/pipeline`;
const HUB_URL = `${SITE_URL}/hub/runtime`;

type Lang = 'zh' | 'en';
const LANG_STORAGE_KEY = 'landing-lang';

type ProductCard = {
  name: string;
  tier: 'P0' | 'P1' | 'P2';
  category: string;
  summary: string;
  stack: string;
  status: string;
  url: string;
  liveUrl?: string;
};

type LandingCopy = {
  langLabel: string;
  eyebrow: string;
  title: string;
  subtitle: string;
  repoStripMain: string;
  repoStripLive: string;
  ctaPrimary: string;
  ctaGithub: string;
  ctaResume: string;
  metrics: { value: string; label: string }[];
  panelLabel: string;
  panelTitle: string;
  panelBody: string;
  panelLinks: { label: string; href: string }[];
  introKicker: string;
  introTitle: string;
  introBody: string;
  introLinks: { label: string; href: string; external?: boolean }[];
  matrixKicker: string;
  matrixTitle: string;
  matrixSubtitle: string;
  matrixViewRepo: string;
  matrixLiveDemo: string;
  products: ProductCard[];
  liveKicker: string;
  liveTitle: string;
  liveSubtitle: string;
  liveEntries: { name: string; tag: string; desc: string; href: string; external?: boolean }[];
  funnelKicker: string;
  funnelTitle: string;
  funnelSubtitle: string;
  funnelSteps: { step: string; title: string; body: string }[];
  boundaryKicker: string;
  boundaryTitle: string;
  boundarySubtitle: string;
  boundaries: { layer: string; title: string; body: string }[];
  capabilityKicker: string;
  capabilityTitle: string;
  capabilitySubtitle: string;
  capabilityGroups: { title: string; description: string; items: string[] }[];
  principlesKicker: string;
  principles: { title: string; description: string }[];
  ctaCardKicker: string;
  ctaCardTitle: string;
  ctaCardBody: string;
  ctaCardLinks: { label: string; href: string }[];
  standardsKicker: string;
  standardsTitle: string;
  standardsSubtitle: string;
  standards: { title: string; body: string }[];
};

const REPO_LINKS: Record<string, string> = {
  'Three Fire Stone Cost Intelligence': PUBLIC_RAG_REPO_URL,
  'BeautyOS Hermes Runtime':            PUBLIC_BEAUTYOS_HERMES_URL,
  'Hermes Agent Framework':             PUBLIC_HERMES_FRAMEWORK_URL,
  'AI BeautyOS':                        PUBLIC_BEAUTYOS_REPO_URL,
};
// Reserved for capability map (currently unused after lean rewrite, kept for re-enable)
void REPO_LINKS;

const LANDING: Record<Lang, LandingCopy> = {
  zh: {
    langLabel: 'EN',
    eyebrow: 'Repository Portfolio',
    title: 'Three Fire Stone AI 解决方案作品集',
    subtitle: '以真实仓库展示项目方向、系统能力与交付经验，再把智能检索、医美 Demo 与运行面板作为现网体验入口接入。',
    repoStripMain: '主仓库：Three Fire Stone Cost Intelligence',
    repoStripLive: '在线 Demo：BeautyOS 医美工作台',
    ctaPrimary: '进入智能检索',
    ctaGithub: '查看 GitHub 仓库',
    ctaResume: '查看公开简历',
    metrics: [
      { value: '4',          label: '公开仓库作品' },
      { value: '2 套',       label: '在线可体验系统' },
      { value: 'AI / Agent', label: '核心工程方向' },
      { value: 'Docker',     label: '统一交付形态' },
    ],
    panelLabel: '作品总纲',
    panelTitle: '作品证明与系统入口分层',
    panelBody: '首页负责展示旗舰知识系统、Agent 运行时、BeautyOS 在线 Demo 与公开作品链接；真实操作入口保留在智能检索、综合面板和数据管道中，按需登录进入。',
    panelLinks: [
      { label: '旗舰项目仓', href: PUBLIC_RAG_REPO_URL },
      { label: '在线 Demo', href: BEAUTYOS_ENTRY_URL },
      { label: '综合面板',  href: HUB_URL },
    ],
    introKicker: 'Project introduction',
    introTitle: 'Three Fire Stone Cost Intelligence',
    introBody: '面向工程造价标准、企业知识库和专业资料问答的智能知识系统。把 PDF 标准、结构化费率表、文档片段和在线问答界面串成完整链路，证明从资料解析、检索召回、Agent 编排到前端产品化的整链交付能力。',
    introLinks: [
      { label: '打开项目仓库',  href: PUBLIC_RAG_REPO_URL, external: true },
      { label: '体验在线检索',  href: RAG_ENTRY_URL },
      { label: '查看更多仓库',  href: GITHUB_OWNER_URL,    external: true },
    ],
    matrixKicker: 'Product matrix',
    matrixTitle: '作品矩阵 · 分层展示',
    matrixSubtitle: '按 P0 旗舰 / P1 在线系统 / P2 工程框架三层组织，让访客一眼看到主推作品、运行中的系统与底层能力。',
    matrixViewRepo: '查看仓库',
    matrixLiveDemo: '在线体验',
    products: [
      {
        name: 'Three Fire Stone Cost Intelligence',
        tier: 'P0',
        category: '旗舰知识系统',
        summary: '工程造价标准 / 企业知识库 / 专业问答 一体化 RAG。多向量拓扑切换、编排式推理、结构化回答与可审计的工具调用。',
        stack: 'Python · TypeScript · Go · LangGraph · Milvus · pgvector · PaddleOCR',
        status: '在线运行',
        url: PUBLIC_RAG_REPO_URL,
        liveUrl: RAG_ENTRY_URL,
      },
      {
        name: 'AI BeautyOS',
        tier: 'P0',
        category: '医美 Agent-Native 工作台',
        summary: '医美 CRM 与 AI 落地页系统，融合 System Registry、MCP Tool Server 与 Hermes Adapter，给到访者一份可点的医美 Agent 演示。',
        stack: 'TypeScript · React · tRPC · Postgres · Docker Compose · Hermes Agent',
        status: '在线 Demo',
        url: PUBLIC_BEAUTYOS_REPO_URL,
        liveUrl: BEAUTYOS_ENTRY_URL,
      },
      {
        name: 'BeautyOS Hermes Runtime',
        tier: 'P1',
        category: 'Agent Runtime 包装',
        summary: '面向 BeautyOS 的 Hermes runtime / profile / adapter 整合仓，承担与上游 Hermes Agent Framework 的同步与定制。',
        stack: 'Hermes runtime · wrapper · agent integration',
        status: '工程演进中',
        url: PUBLIC_BEAUTYOS_HERMES_URL,
      },
      {
        name: 'Hermes Agent Framework',
        tier: 'P2',
        category: 'Upstream Agent',
        summary: '上游 Agent 框架公开 fork，承接 runtime、技能体系与上游能力同步，作为 AI agent 底层工程证明。',
        stack: 'agent framework · runtime · upstream sync',
        status: '上游跟随',
        url: PUBLIC_HERMES_FRAMEWORK_URL,
      },
    ],
    liveKicker: 'Live entries',
    liveTitle: '现网在线入口',
    liveSubtitle: '直接可点的真实系统，所有入口都是真实流量在跑，不是截图。',
    liveEntries: [
      { name: '智能检索',     tag: 'RAG',       desc: '工程造价标准问答与结构化检索，按企业知识库语义召回。', href: RAG_ENTRY_URL },
      { name: 'BeautyOS Demo', tag: 'Agent · Demo', desc: '医美工作台融合 Hermes Agent，访客可直接体验业务问答与工具调用。', href: BEAUTYOS_ENTRY_URL },
      { name: '综合面板',     tag: 'Ops',       desc: '运行时拓扑、检索工具箱、运维与版本面板（登录后可见）。',               href: HUB_URL },
      { name: '数据管道',     tag: 'Pipeline',  desc: '文档上传 / OCR / 索引 / 投影一站式管道（登录后可见）。',                  href: PIPELINE_URL },
    ],
    funnelKicker: 'Commercial funnel',
    funnelTitle: '从作品到合作的四步漏斗',
    funnelSubtitle: '首页负责公开晒肌肉；现网系统承接真实体验；仓库阅读承接技术尽调；合作落地按企业场景定制。',
    funnelSteps: [
      { step: '01', title: '公开晒肌肉',     body: '首页展示仓库矩阵、技术栈与设计原则，让访客快速判断方向是否匹配。' },
      { step: '02', title: '在线真实体验',   body: 'RAG 与 BeautyOS Demo 真实在跑，证明系统能上线而不是 PPT。' },
      { step: '03', title: '仓库技术尽调',   body: '公开仓库展示架构、文档、CI 与部署形态，便于第三方阅读评估。' },
      { step: '04', title: '合作场景落地',   body: '基于 Agent-Native + RAG 框架，按企业知识、业务流与权限边界做定制部署。' },
    ],
    boundaryKicker: 'Boundary model',
    boundaryTitle: '公开 / 系统 / Agent 三层边界',
    boundarySubtitle: '清楚划分什么可以对外展示、什么作为运行入口、什么留在 Agent 内部，保证既能晒肌肉又不泄露策略。',
    boundaries: [
      { layer: 'Public',  title: '公开作品层',   body: '仓库链接、技术栈、产品定位、设计原则 —— 对外的"证明层"，全部可被搜索引擎收录。' },
      { layer: 'System',  title: '在线系统层',   body: 'RAG / BeautyOS / Hub / Pipeline，部分免登录体验、部分登录后启用，承载真实业务流。' },
      { layer: 'Agent',   title: 'Agent 运行层', body: 'Hermes runtime + 受控工具 + 审计日志，所有数据写入与外部副作用都收口到这里。' },
    ],
    capabilityKicker: 'Capability map',
    capabilityTitle: '作品能力分区',
    capabilitySubtitle: '按方向聚合仓库，让首页更像作品总览，而不是单一系统说明页。',
    capabilityGroups: [
      {
        title: 'AI / Agent / RAG',
        description: '旗舰项目负责展示专业知识检索、证据召回、结构化回答和在线系统化落地能力。',
        items: ['Three Fire Stone Cost Intelligence', 'AI BeautyOS'],
      },
      {
        title: 'Agent 运行层',
        description: '围绕 Hermes 运行时与上游 Agent 框架做封装、同步与上游能力对接。',
        items: ['BeautyOS Hermes Runtime', 'Hermes Agent Framework'],
      },
      {
        title: '作品链接策略',
        description: '首页只放真实可访问的公开仓库链接；私有 / 整理中的项目通过 GitHub 主页与公开简历承接。',
        items: ['Three Fire Stone Cost Intelligence', 'AI BeautyOS', 'BeautyOS Hermes Runtime', 'Hermes Agent Framework'],
      },
    ],
    principlesKicker: 'Why this layout',
    principles: [
      { title: '仓库即作品证明', description: '首页不空讲概念，直接用仓库链接、技术栈和项目说明做证明层。' },
      { title: '架构与问题并重', description: '不只展示做过什么，也强调如何处理 issue、收敛结构、稳定系统。' },
      { title: '公开介绍 + 私有运行', description: '公开首页负责展示作品，登录后进入 RAG、管道和综合面板等运行能力。' },
    ],
    ctaCardKicker: 'System entry',
    ctaCardTitle: '作品展示之后，继续进入系统',
    ctaCardBody: '保留 RAG、数据管道和综合面板能力，但入口退到第二层，首页主角是仓库作品本身。',
    ctaCardLinks: [
      { label: '智能检索入口', href: RAG_ENTRY_URL },
      { label: 'BeautyOS Demo', href: BEAUTYOS_ENTRY_URL },
      { label: '综合面板',     href: HUB_URL },
      { label: '数据管道',     href: PIPELINE_URL },
    ],
    standardsKicker: 'Delivery standards',
    standardsTitle: '统一交付标准',
    standardsSubtitle: '每个作品都按相同的工程标准交付，便于第三方阅读、验证和接手。',
    standards: [
      { title: '可移植部署',     body: '统一 Docker / Docker Compose、环境变量样例、健康检查、卷策略与回滚路径。' },
      { title: '数据进入系统',   body: '客户、线索、标准、招采、知识资产先结构化入库，然后才允许 Agent 调用。' },
      { title: '商业 README',    body: '每个仓库说明谁是买家、解决什么痛、怎么收钱、怎么部署、下一阶段由哪个 Plan Issue 推进。' },
      { title: '公开导出契约',   body: '公开简历与首页只消费"公开安全字段"，不继承私有销售策略和运营细节。' },
    ],
  },
  en: {
    langLabel: '中',
    eyebrow: 'Repository Portfolio',
    title: 'Three Fire Stone AI Solutions Portfolio',
    subtitle: 'Real repositories proving direction, system capability and delivery experience, with live RAG search and a BeautyOS demo wired in as production entries.',
    repoStripMain: 'Flagship repo · Three Fire Stone Cost Intelligence',
    repoStripLive: 'Live demo · BeautyOS medical-beauty workspace',
    ctaPrimary: 'Open RAG search',
    ctaGithub: 'GitHub profile',
    ctaResume: 'Public resume',
    metrics: [
      { value: '4',            label: 'Public repos' },
      { value: '2',            label: 'Live systems' },
      { value: 'AI / Agent',   label: 'Core direction' },
      { value: 'Docker',       label: 'Delivery format' },
    ],
    panelLabel: 'Portfolio thesis',
    panelTitle: 'Proof layer + system layer, kept separate',
    panelBody: 'The landing surface showcases the flagship knowledge system, agent runtimes, the BeautyOS demo and public repositories. Real operational entries — RAG, ops console, pipeline — sit one level deeper, behind login when needed.',
    panelLinks: [
      { label: 'Flagship repo', href: PUBLIC_RAG_REPO_URL },
      { label: 'Live demo',     href: BEAUTYOS_ENTRY_URL },
      { label: 'Ops hub',       href: HUB_URL },
    ],
    introKicker: 'Project introduction',
    introTitle: 'Three Fire Stone Cost Intelligence',
    introBody: 'A knowledge system for construction cost standards, enterprise knowledge bases and professional Q&A. PDF standards, structured rate tables, document chunks and an online assistant are wired into one chain, proving end-to-end delivery from parsing, retrieval and agent orchestration to a productized frontend.',
    introLinks: [
      { label: 'Open repository',  href: PUBLIC_RAG_REPO_URL, external: true },
      { label: 'Try live search',  href: RAG_ENTRY_URL },
      { label: 'More repositories', href: GITHUB_OWNER_URL,   external: true },
    ],
    matrixKicker: 'Product matrix',
    matrixTitle: 'Tiered product matrix',
    matrixSubtitle: 'Organized as P0 flagship · P1 live systems · P2 framework, so visitors immediately see what is shipped, what runs and what powers it.',
    matrixViewRepo: 'View repo',
    matrixLiveDemo: 'Live demo',
    products: [
      {
        name: 'Three Fire Stone Cost Intelligence',
        tier: 'P0',
        category: 'Flagship RAG system',
        summary: 'Cost standards + enterprise KB + professional Q&A unified as one RAG. Multi-vector topologies, orchestrated reasoning, structured answers and auditable tool calls.',
        stack: 'Python · TypeScript · Go · LangGraph · Milvus · pgvector · PaddleOCR',
        status: 'Live',
        url: PUBLIC_RAG_REPO_URL,
        liveUrl: RAG_ENTRY_URL,
      },
      {
        name: 'AI BeautyOS',
        tier: 'P0',
        category: 'Agent-native medical-beauty workspace',
        summary: 'CRM + AI landing system, fused with a System Registry, MCP Tool Server and Hermes adapter — visitors get a clickable medical-beauty agent demo.',
        stack: 'TypeScript · React · tRPC · Postgres · Docker Compose · Hermes Agent',
        status: 'Live demo',
        url: PUBLIC_BEAUTYOS_REPO_URL,
        liveUrl: BEAUTYOS_ENTRY_URL,
      },
      {
        name: 'BeautyOS Hermes Runtime',
        tier: 'P1',
        category: 'Agent runtime wrapper',
        summary: 'Hermes runtime / profile / adapter integration for BeautyOS, handling sync and customization against the upstream Hermes Agent Framework.',
        stack: 'Hermes runtime · wrapper · agent integration',
        status: 'In progress',
        url: PUBLIC_BEAUTYOS_HERMES_URL,
      },
      {
        name: 'Hermes Agent Framework',
        tier: 'P2',
        category: 'Upstream agent framework',
        summary: 'Public fork carrying runtime, skills and upstream capability sync — the foundational engineering proof for AI agents.',
        stack: 'agent framework · runtime · upstream sync',
        status: 'Tracking upstream',
        url: PUBLIC_HERMES_FRAMEWORK_URL,
      },
    ],
    liveKicker: 'Live entries',
    liveTitle: 'Production entries',
    liveSubtitle: 'Clickable, running systems — not screenshots.',
    liveEntries: [
      { name: 'RAG search',     tag: 'RAG',           desc: 'Cost standards Q&A and structured search, semantically recalled against the enterprise KB.', href: RAG_ENTRY_URL },
      { name: 'BeautyOS demo',  tag: 'Agent · demo',  desc: 'Medical-beauty workspace fused with Hermes Agent — try business Q&A and tool calls.',         href: BEAUTYOS_ENTRY_URL },
      { name: 'Ops hub',        tag: 'Ops',           desc: 'Runtime topology, retrieval toolbox, ops and version dashboards (login required).',          href: HUB_URL },
      { name: 'Pipeline',       tag: 'Pipeline',      desc: 'Upload / OCR / indexing / projection pipeline in one console (login required).',              href: PIPELINE_URL },
    ],
    funnelKicker: 'Commercial funnel',
    funnelTitle: 'From portfolio to engagement, in four steps',
    funnelSubtitle: 'Public proof layer; live systems for hands-on; repository reading for technical due diligence; engagement customized to enterprise context.',
    funnelSteps: [
      { step: '01', title: 'Public proof',          body: 'Landing surfaces the repo matrix, stack and design principles so visitors can quickly judge fit.' },
      { step: '02', title: 'Live experience',       body: 'RAG and BeautyOS demos actually run — proof that the systems ship rather than slide-ware.' },
      { step: '03', title: 'Technical due diligence', body: 'Public repos expose architecture, docs, CI and deployment shape for third-party review.' },
      { step: '04', title: 'Engagement',            body: 'Agent-native + RAG framework, customized to enterprise knowledge, workflow and permission boundaries.' },
    ],
    boundaryKicker: 'Boundary model',
    boundaryTitle: 'Public · System · Agent boundary',
    boundarySubtitle: 'A clear split between what is public proof, what is a runtime entry and what stays inside the agent — flexing capability without leaking strategy.',
    boundaries: [
      { layer: 'Public',  title: 'Public proof layer', body: 'Repository links, stack, positioning and design principles — the proof layer, indexable by search engines.' },
      { layer: 'System',  title: 'Live systems',       body: 'RAG / BeautyOS / Hub / Pipeline — some open to visitors, some behind login, carrying real workflows.' },
      { layer: 'Agent',   title: 'Agent runtime',      body: 'Hermes runtime, scoped tools and audit logs — all writes and external side effects converge here.' },
    ],
    capabilityKicker: 'Capability map',
    capabilityTitle: 'Capability groups',
    capabilitySubtitle: 'Repos grouped by direction, turning the landing into a portfolio overview instead of a single-system page.',
    capabilityGroups: [
      {
        title: 'AI / Agent / RAG',
        description: 'Flagship projects covering knowledge retrieval, evidence recall, structured answers and productized online delivery.',
        items: ['Three Fire Stone Cost Intelligence', 'AI BeautyOS'],
      },
      {
        title: 'Agent runtime',
        description: 'Wrapping Hermes runtime and the upstream agent framework, handling sync and capability integration.',
        items: ['BeautyOS Hermes Runtime', 'Hermes Agent Framework'],
      },
      {
        title: 'Linking strategy',
        description: 'Only real, publicly accessible repos on the landing; private / in-progress work is reached through the GitHub profile and public resume.',
        items: ['Three Fire Stone Cost Intelligence', 'AI BeautyOS', 'BeautyOS Hermes Runtime', 'Hermes Agent Framework'],
      },
    ],
    principlesKicker: 'Why this layout',
    principles: [
      { title: 'Repos as proof',     description: 'The landing skips slogans and uses repo links, stack and project notes as the proof layer.' },
      { title: 'Architecture + ops', description: 'Showcases not just what was built, but how issues are handled, structure converged and systems stabilized.' },
      { title: 'Public surface + private runtime', description: 'Landing surfaces the portfolio; logged-in users reach RAG, pipelines and the ops hub.' },
    ],
    ctaCardKicker: 'System entry',
    ctaCardTitle: 'After the showcase, enter the system',
    ctaCardBody: 'The RAG, data pipeline and ops hub stay available, but at the second level — the landing star is the portfolio itself.',
    ctaCardLinks: [
      { label: 'RAG search',     href: RAG_ENTRY_URL },
      { label: 'BeautyOS demo',  href: BEAUTYOS_ENTRY_URL },
      { label: 'Ops hub',        href: HUB_URL },
      { label: 'Pipeline',       href: PIPELINE_URL },
    ],
    standardsKicker: 'Delivery standards',
    standardsTitle: 'Unified delivery standards',
    standardsSubtitle: 'Every project is delivered under the same engineering bar — readable, verifiable, takeover-friendly.',
    standards: [
      { title: 'Portable deployment',  body: 'Unified Docker / Docker Compose, env examples, health checks, volume strategy and rollback paths.' },
      { title: 'Data enters first',    body: 'Customers, leads, standards, tender docs and knowledge assets are structured into storage before any agent acts on them.' },
      { title: 'Commercial README',    body: 'Each repo states who buys, what pain it solves, how it monetizes, how it deploys and which plan issue owns the next phase.' },
      { title: 'Public export contract', body: 'Public resume and landing only consume "public-safe fields", inheriting no private sales or operational details.' },
    ],
  },
};

const ROUTE_MODULE: [string, string][] = [
  ['/rag',      'library'],
  ['/library',  'library'],
  ['/hub',      'hub'],
  ['/pipeline', 'pipeline'],
  ['/pro',      'library'],
  ['/',         'library'],
];

function getModule(pathname: string): string {
  for (const [prefix, mod] of ROUTE_MODULE) {
    if (pathname === prefix || (prefix !== '/' && pathname.startsWith(prefix + '/'))) {
      return mod;
    }
  }
  return 'library';
}

function Navigation() {
  const location = useLocation();
  const navigate = useNavigate();
  const [scrolled, setScrolled] = useState(false);
  const [auth, setAuth] = useState<AuthState | null>(() => readAuthState());

  useEffect(() => {
    document.documentElement.dataset.module = getModule(location.pathname);
  }, [location.pathname]);

  /* 监听内容区滚动，滚动后 nav 加阴影层次感 */
  useEffect(() => {
    const main = document.querySelector('.app-main');
    if (!main) return;
    const onScroll = () => setScrolled(main.scrollTop > 4);
    main.addEventListener('scroll', onScroll, { passive: true });
    return () => main.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => {
    const onStorage = () => setAuth(readAuthState());
    window.addEventListener('storage', onStorage);
    window.addEventListener('rag-auth-changed', onStorage);
    return () => {
      window.removeEventListener('storage', onStorage);
      window.removeEventListener('rag-auth-changed', onStorage);
    };
  }, []);

  const isActive = (path: string) =>
    path === '/'
      ? location.pathname === '/'
      : location.pathname.startsWith(path);
  const visibleNavItems = auth ? [...PUBLIC_NAV_ITEMS, ...PRIVATE_NAV_ITEMS] : PUBLIC_NAV_ITEMS;

  if (location.pathname === '/' || location.pathname === '/chat') return null;

  return (
    <header className={`app-nav${scrolled ? ' scrolled' : ''}`}>
      <Link className="nav-brand" to="/">
        <span className="nav-mark">3F</span>
        <span className="nav-title">Three Fire Stone</span>
      </Link>

      <nav className="nav-links">
        {visibleNavItems.map(({ path, label, icon }) => (
          <Link
            key={path}
            to={path === '/hub' ? '/hub/runtime' : path}
            className={`nav-link ${isActive(path) ? 'active' : ''}`}
          >
            <span aria-hidden="true" className="nav-icon">
              <ModuleIcon name={icon} size={14} />
            </span>
            {label}
          </Link>
        ))}
      </nav>

      <div className="nav-actions">
        {auth ? (
          <>
            <span className="nav-user">已登录：{auth.user.username}</span>
            <button
              type="button"
              className="nav-auth-button"
              onClick={() => {
                clearAuthState();
                navigate('/login');
              }}
            >
              退出
            </button>
          </>
        ) : (
          <Link className="nav-auth-button primary" to="/login">
            登录
          </Link>
        )}
      </div>
    </header>
  );
}

function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation();
  const auth = readAuthState();

  if (!auth) {
    const from = `${location.pathname}${location.search}${location.hash}`;
    return <Navigate to="/login" replace state={{ from }} />;
  }

  return <>{children}</>;
}

void LANDING;

function LandingPage() {
  const navigate = useNavigate();
  const [lang, setLang] = useState<Lang>(() => {
    if (typeof window === 'undefined') return 'zh';
    const saved = window.localStorage.getItem(LANG_STORAGE_KEY);
    return saved === 'en' ? 'en' : 'zh';
  });
  const [query, setQuery] = useState('');

  useEffect(() => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(LANG_STORAGE_KEY, lang);
      document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
    }
  }, [lang]);

  const toggleLang = () => setLang(lang === 'zh' ? 'en' : 'zh');

  function askHermes(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const q = query.trim();
    const auth = readAuthState();
    if (!auth) {
      const to = q ? `/chat?q=${encodeURIComponent(q)}` : '/chat';
      navigate(`/login?redirect=${encodeURIComponent(to)}`);
      return;
    }
    navigate(q ? `/chat?q=${encodeURIComponent(q)}` : '/chat');
  }

  const copy = lang === 'zh' ? {
    eyebrow: 'Three Fire Stone · 展示入口',
    name: 'Three Fire Stone',
    tagline: 'AI 解决方案与工程作品集',
    intro: '把 RAG、Agent、医美 CRM、课程与简历集中到一个清晰入口；展示优先，运行系统逐步拆分。',
    placeholder: '问 Hermes 任何问题…',
    hint: '展示页无需登录；提交问题会进入 Hermes Chat。',
    enter: '↵',
    primaryCta: { label: '查看完整简历', href: PUBLIC_RESUME_URL, external: false },
    secondaryCta: { label: '进入 RAG 展示', href: RAG_ENTRY_URL, external: false },
    sectionLive: '在线展示',
    sectionWorks: '项目与代码',
    sectionBoundary: '展示边界',
    sectionContact: '联系与资料',
    liveItems: [
      { name: 'RAG 智能检索', desc: '工程造价标准与企业知识库问答', href: RAG_ENTRY_URL, tag: 'RAG', external: false },
      { name: 'BeautyOS 医美 Demo', desc: '医美 CRM 与 Agent-native 工作台展示', href: BEAUTYOS_ENTRY_URL, tag: 'CRM', external: false },
      { name: 'Agent Lecture', desc: 'AI Agent 技术讲义与交互式演示', href: '/lecture/', tag: 'Course', external: false },
      { name: 'Boone Profile', desc: '个人主页、简历与公开项目索引', href: '/boone/', tag: 'Profile', external: false },
    ],
    worksItems: [
      { name: 'Three Fire Stone Cost Intelligence', href: PUBLIC_RAG_REPO_URL, sub: '工程造价 RAG · 检索增强 · 多服务协作', external: true },
      { name: 'AI BeautyOS', href: BEAUTYOS_ENTRY_URL, sub: '医美业务展示 · CRM · Agent 工作台', external: false },
      { name: 'BeautyOS Hermes Runtime', href: PUBLIC_BEAUTYOS_HERMES_URL, sub: 'Hermes runtime 集成与封装', external: true },
      { name: 'Hermes Agent Framework', href: PUBLIC_HERMES_FRAMEWORK_URL, sub: '上游 Agent 框架与运行时', external: true },
    ],
    boundaryItems: [
      { k: '展示', v: '根域只承载公开展示、简历和作品入口，不直接暴露数据库或内部服务。' },
      { k: '系统', v: 'RAG / BeautyOS / Lecture 以路径方式挂载，后续需要再升级为子域名。' },
      { k: 'Agent', v: 'Hermes Chat 入口保留登录边界，副作用工具继续收口到受控服务。' },
    ],
    contactItems: [
      { label: '完整简历', href: PUBLIC_RESUME_URL, external: false },
      { label: 'GitHub', href: GITHUB_OWNER_URL, external: true },
    ],
  } : {
    eyebrow: 'Three Fire Stone · Showcase',
    name: 'Three Fire Stone',
    tagline: 'AI solutions and engineering portfolio',
    intro: 'A clean public entry for RAG, agent systems, BeautyOS, lectures and Boone Liang’s profile.',
    placeholder: 'Ask Hermes anything…',
    hint: 'Showcase pages are public; submitting a question opens Hermes Chat.',
    enter: '↵',
    primaryCta: { label: 'View resume', href: PUBLIC_RESUME_URL, external: false },
    secondaryCta: { label: 'Open RAG showcase', href: RAG_ENTRY_URL, external: false },
    sectionLive: 'Showcases',
    sectionWorks: 'Projects and code',
    sectionBoundary: 'Boundaries',
    sectionContact: 'Contact',
    liveItems: [
      { name: 'RAG Search', desc: 'Cost standards and enterprise knowledge-base Q&A', href: RAG_ENTRY_URL, tag: 'RAG', external: false },
      { name: 'BeautyOS Demo', desc: 'Medical-beauty CRM and agent-native workspace', href: BEAUTYOS_ENTRY_URL, tag: 'CRM', external: false },
      { name: 'Agent Lecture', desc: 'Interactive AI Agent lecture and demos', href: '/lecture/', tag: 'Course', external: false },
      { name: 'Boone Profile', desc: 'Personal homepage, resume and project index', href: '/boone/', tag: 'Profile', external: false },
    ],
    worksItems: [
      { name: 'Three Fire Stone Cost Intelligence', href: PUBLIC_RAG_REPO_URL, sub: 'Cost RAG · retrieval · multi-service architecture', external: true },
      { name: 'AI BeautyOS', href: BEAUTYOS_ENTRY_URL, sub: 'Medical-beauty showcase · CRM · agent workspace', external: false },
      { name: 'BeautyOS Hermes Runtime', href: PUBLIC_BEAUTYOS_HERMES_URL, sub: 'Hermes runtime integration', external: true },
      { name: 'Hermes Agent Framework', href: PUBLIC_HERMES_FRAMEWORK_URL, sub: 'Upstream agent framework and runtime', external: true },
    ],
    boundaryItems: [
      { k: 'Showcase', v: 'The root domain is for public pages, resume and project entry points.' },
      { k: 'Systems', v: 'RAG / BeautyOS / Lecture are mounted as paths and can later move to subdomains.' },
      { k: 'Agent', v: 'Hermes Chat keeps the login boundary; side-effect tools remain scoped and audited.' },
    ],
    contactItems: [
      { label: 'Resume', href: PUBLIC_RESUME_URL, external: false },
      { label: 'GitHub', href: GITHUB_OWNER_URL, external: true },
    ],
  };

  return (
    <section className="landing-min" data-lang={lang}>
      <button
        type="button"
        className="landing-min-lang"
        onClick={toggleLang}
        aria-label="Switch language"
      >
        {lang === 'zh' ? 'EN' : '中'}
      </button>

      <div className="landing-min-inner">
        <header className="landing-min-hero">
          <p className="landing-min-eyebrow">{copy.eyebrow}</p>
          <h1 className="landing-min-name">{copy.name}</h1>
          <p className="landing-min-tagline">{copy.tagline}</p>
          <p className="landing-min-intro">{copy.intro}</p>

          <div className="landing-min-actions">
            <a className="landing-min-cta landing-min-cta-primary" href={copy.primaryCta.href}>
              {copy.primaryCta.label}
            </a>
            <a className="landing-min-cta landing-min-cta-secondary" href={copy.secondaryCta.href}>
              {copy.secondaryCta.label}
            </a>
          </div>

          <form className="landing-min-ask" onSubmit={askHermes} role="search">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={copy.placeholder}
              aria-label={copy.placeholder}
              autoComplete="off"
            />
            <button type="submit" aria-label="Submit">{copy.enter}</button>
          </form>
          <p className="landing-min-hint">{copy.hint}</p>
        </header>

        <main className="landing-min-main">
          <section className="landing-min-panel landing-min-panel-live" aria-labelledby="landing-live-title">
            <div className="landing-min-section-head">
              <span>01</span>
              <h2 id="landing-live-title">{copy.sectionLive}</h2>
            </div>
            <div className="landing-min-card-grid">
              {copy.liveItems.map((it) => (
                <a
                  key={it.name}
                  className="landing-min-card"
                  href={it.href}
                  target={it.external ? '_blank' : undefined}
                  rel={it.external ? 'noreferrer' : undefined}
                >
                  <span className="landing-min-card-tag">{it.tag}</span>
                  <strong>{it.name}</strong>
                  <em>{it.desc}</em>
                </a>
              ))}
            </div>
          </section>

          <section className="landing-min-panel" aria-labelledby="landing-works-title">
            <div className="landing-min-section-head">
              <span>02</span>
              <h2 id="landing-works-title">{copy.sectionWorks}</h2>
            </div>
            <div className="landing-min-list-grid">
              {copy.worksItems.map((it) => (
                <a
                  key={it.name}
                  className="landing-min-list-item"
                  href={it.href}
                  target={it.external ? '_blank' : undefined}
                  rel={it.external ? 'noreferrer' : undefined}
                >
                  <span>{it.name}</span>
                  <em>{it.sub}</em>
                </a>
              ))}
            </div>
          </section>

          <section className="landing-min-panel" aria-labelledby="landing-boundary-title">
            <div className="landing-min-section-head">
              <span>03</span>
              <h2 id="landing-boundary-title">{copy.sectionBoundary}</h2>
            </div>
            <div className="landing-min-boundary-grid">
              {copy.boundaryItems.map((it) => (
                <article key={it.k} className="landing-min-boundary-card">
                  <strong>{it.k}</strong>
                  <p>{it.v}</p>
                </article>
              ))}
            </div>
          </section>
        </main>

        <footer className="landing-min-footer">
          <span>{copy.sectionContact}</span>
          {copy.contactItems.map((it) => (
            <a
              key={it.label}
              href={it.href}
              target={it.external ? '_blank' : undefined}
              rel={it.external ? 'noreferrer' : undefined}
            >
              {it.label}
            </a>
          ))}
        </footer>
      </div>
    </section>
  );
}


function LoginPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const existingAuth = readAuthState();
  const [tab, setTab] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  // 注册字段
  const [regEmail, setRegEmail] = useState('');
  const [regPassword, setRegPassword] = useState('');
  const [regCode, setRegCode] = useState('');
  const [codeSent, setCodeSent] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [loading, setLoading] = useState(false);
  const from =
    new URLSearchParams(location.search).get('redirect') ||
    (location.state as { from?: string } | null)?.from ||
    '/rag';

  if (existingAuth) {
    return <Navigate to={from} replace />;
  }

  function saveAndRedirect(payload: any) {
    const authState: AuthState = {
      token: payload.data.token,
      user: payload.data.user,
    };
    window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(authState));
    window.dispatchEvent(new Event('rag-auth-changed'));
    navigate(from, { replace: true });
  }

  async function submitLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setInfo('');
    setLoading(true);

    const isEmail = /@/.test(username);
    const url = isEmail ? '/api/auth/login-email' : '/api/auth/login';
    const body = isEmail
      ? { email: username, password }
      : { username, password };

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const payload = await response.json();

      if (!response.ok || !payload.success || !payload.data?.token || !payload.data?.user) {
        throw new Error(payload?.error?.message || '登录失败，请检查账号和密码');
      }

      saveAndRedirect(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }

  async function sendEmailCode() {
    if (countdown > 0 || loading) return;
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(regEmail)) {
      setError('请输入有效的邮箱地址');
      return;
    }
    setError('');
    setInfo('');
    setLoading(true);
    try {
      const response = await fetch('/api/auth/send-email-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: regEmail, purpose: 'signup' }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.success) {
        throw new Error(payload?.error?.message || '验证码发送失败');
      }
      setCodeSent(true);
      setInfo('验证码已发送（开发期：请联系管理员查看后端日志获取验证码）');
      setCountdown(60);
      const timer = window.setInterval(() => {
        setCountdown((prev) => {
          if (prev <= 1) {
            window.clearInterval(timer);
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
    } catch (err) {
      setError(err instanceof Error ? err.message : '验证码发送失败');
    } finally {
      setLoading(false);
    }
  }

  async function submitRegister(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setInfo('');
    if (regPassword.length < 8) {
      setError('密码至少 8 位');
      return;
    }
    setLoading(true);
    try {
      const response = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: regEmail, password: regPassword, code: regCode }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.success || !payload.data?.token || !payload.data?.user) {
        throw new Error(payload?.error?.message || '注册失败，请检查验证码与邮箱');
      }
      saveAndRedirect(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : '注册失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="login-page">
      <div className="login-card">
        <div>
          <p className="login-eyebrow">RAG 智库系统</p>
          <h1>{tab === 'login' ? '登录' : '邮箱注册'}</h1>
        </div>

        <div className="login-tabs">
          <button
            type="button"
            className={'login-tab' + (tab === 'login' ? ' active' : '')}
            onClick={() => { setTab('login'); setError(''); setInfo(''); }}
          >
            登录
          </button>
          <button
            type="button"
            className={'login-tab' + (tab === 'register' ? ' active' : '')}
            onClick={() => { setTab('register'); setError(''); setInfo(''); }}
          >
            邮箱注册
          </button>
        </div>

        {tab === 'login' ? (
          <form onSubmit={submitLogin}>
            <label className="login-field">
              <span>账号 / 邮箱</span>
              <input
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="admin 或 your@email.com"
                required
              />
            </label>

            <label className="login-field">
              <span>密码</span>
              <input
                autoComplete="current-password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="请输入密码"
                required
              />
            </label>

            {error && <div className="login-error">{error}</div>}

            <button className="login-submit" type="submit" disabled={loading}>
              {loading ? '登录中…' : '登录'}
            </button>
          </form>
        ) : (
          <form onSubmit={submitRegister}>
            <label className="login-field">
              <span>邮箱</span>
              <div className="login-field-row">
                <input
                  type="email"
                  value={regEmail}
                  onChange={(event) => setRegEmail(event.target.value)}
                  placeholder="your@email.com"
                  required
                />
                <button
                  type="button"
                  className="login-send-code"
                  onClick={sendEmailCode}
                  disabled={loading || countdown > 0}
                >
                  {countdown > 0 ? `${countdown}s` : '获取验证码'}
                </button>
              </div>
            </label>

            <label className="login-field">
              <span>验证码</span>
              <input
                value={regCode}
                onChange={(event) => setRegCode(event.target.value)}
                placeholder="6 位数字验证码"
                maxLength={6}
                required
              />
            </label>

            <label className="login-field">
              <span>密码</span>
              <input
                autoComplete="new-password"
                type="password"
                value={regPassword}
                onChange={(event) => setRegPassword(event.target.value)}
                placeholder="至少 8 位"
                minLength={8}
                required
              />
            </label>

            {codeSent && info && <div className="login-hint">{info}</div>}
            {error && <div className="login-error">{error}</div>}

            <button className="login-submit" type="submit" disabled={loading}>
              {loading ? '提交中…' : '注册并登录'}
            </button>
          </form>
        )}
      </div>
    </section>
  );
}

// ==================== /chat — 访客版 Hermes 聊天 ====================

type ChatMsg = { role: 'user' | 'assistant'; content: string };

function ChatPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const auth = readAuthState();
  const initialQ = new URLSearchParams(location.search).get('q') || '';
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState('');
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const sentInitial = useRef(false);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const send = useCallback(
    async (text: string) => {
      const q = text.trim();
      if (!q || streaming) return;
      setError('');
      const newMsgs: ChatMsg[] = [...messages, { role: 'user', content: q }, { role: 'assistant', content: '' }];
      setMessages(newMsgs);
      setInput('');
      setStreaming(true);

      try {
        const resp = await fetch('/api/hermes/visitor', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${auth?.token || ''}`,
          },
          body: JSON.stringify({
            messages: newMsgs
              .slice(0, -1)
              .filter(m => m.content || m.role === 'user')
              .map(m => ({ role: m.role, content: m.content })),
            stream: true,
          }),
        });

        if (!resp.ok || !resp.body) {
          const t = await resp.text().catch(() => '');
          throw new Error(`HTTP ${resp.status} ${t.slice(0, 200)}`);
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        let acc = '';
        // OpenAI-style SSE: lines starting with "data: ", terminated by "data: [DONE]"
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const parts = buf.split('\n\n');
          buf = parts.pop() || '';
          for (const evt of parts) {
            const line = evt.split('\n').find(l => l.startsWith('data: '));
            if (!line) continue;
            const data = line.slice(6).trim();
            if (data === '[DONE]') continue;
            try {
              const obj = JSON.parse(data);
              const delta = obj.choices?.[0]?.delta?.content ?? obj.choices?.[0]?.message?.content ?? '';
              if (delta) {
                acc += delta;
                setMessages(prev => {
                  const copy = [...prev];
                  copy[copy.length - 1] = { role: 'assistant', content: acc };
                  return copy;
                });
              }
            } catch {
              // ignore malformed chunk
            }
          }
        }
      } catch (e: any) {
        setError(e?.message || String(e));
        setMessages(prev => {
          const copy = [...prev];
          if (copy.length && copy[copy.length - 1].role === 'assistant' && !copy[copy.length - 1].content) {
            copy.pop();
          }
          return copy;
        });
      } finally {
        setStreaming(false);
      }
    },
    [auth, messages, streaming],
  );

  useEffect(() => {
    if (initialQ && !sentInitial.current) {
      sentInitial.current = true;
      void send(initialQ);
    }
  }, [initialQ, send]);

  function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    void send(input);
  }

  return (
    <div className="landing-min" style={{ minHeight: '100vh' }}>
      <div className="landing-min-inner" style={{ maxWidth: 760, paddingTop: '4rem' }}>
        <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
          <button
            type="button"
            onClick={() => navigate('/')}
            style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: '0.95rem' }}
          >
            ← 返回首页
          </button>
          <span style={{ opacity: 0.6, fontSize: '0.85rem' }}>Hermes · 访客</span>
        </header>

        <div
          ref={scrollRef}
          style={{
            minHeight: '50vh',
            maxHeight: '65vh',
            overflowY: 'auto',
            padding: '1rem 0',
            display: 'flex',
            flexDirection: 'column',
            gap: '1rem',
          }}
        >
          {messages.length === 0 && (
            <div style={{ opacity: 0.55, textAlign: 'center', padding: '3rem 0' }}>
              问 Hermes 任何关于这份作品集的问题
            </div>
          )}
          {messages.map((m, i) => (
            <div
              key={i}
              style={{
                alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                maxWidth: '85%',
                padding: '0.75rem 1rem',
                borderRadius: 12,
                background: m.role === 'user' ? 'rgba(0,122,255,0.12)' : 'rgba(120,120,128,0.12)',
                whiteSpace: 'pre-wrap',
                lineHeight: 1.55,
                fontSize: '0.95rem',
              }}
            >
              {m.content || (streaming && i === messages.length - 1 ? '...' : '')}
            </div>
          ))}
          {error && (
            <div style={{ color: '#ff453a', fontSize: '0.85rem' }}>错误：{error}</div>
          )}
        </div>

        <form onSubmit={onSubmit} className="landing-min-ask" style={{ marginTop: '1rem' }}>
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="继续提问…"
            disabled={streaming}
            autoFocus
          />
          <button type="submit" disabled={streaming || !input.trim()}>
            {streaming ? '…' : '↵'}
          </button>
        </form>
      </div>
    </div>
  );
}


export default function App() {
  return (
    <ErrorBoundary>
    <BrowserRouter>
      <div className="app-shell">
        <Navigation />
        <main className="app-main">
          <Routes>
            {/* ── 三大板块 ── */}
            <Route path="/"         element={<LandingPage />} />
            <Route path="/login"    element={<LoginPage />} />
            <Route path="/chat"     element={<RequireAuth><ChatPage /></RequireAuth>} />
            <Route path="/rag"      element={<RequireAuth><LibraryPage /></RequireAuth>} />
            <Route path="/library"  element={<RequireAuth><Navigate to="/rag" replace /></RequireAuth>} />
            <Route path="/pro"      element={<RequireAuth><AgentChat /></RequireAuth>} />
            <Route path="/pipeline" element={<RequireAuth><PipelinePage /></RequireAuth>} />
            <Route path="/hub/:tab" element={<RequireAuth><DashHub /></RequireAuth>} />
            <Route path="/hub"      element={<RequireAuth><Navigate to="/hub/runtime" replace /></RequireAuth>} />

            {/* ── 旧路由重定向（向后兼容） ── */}
            <Route path="/runtime"  element={<RequireAuth><Navigate to="/hub/runtime"  replace /></RequireAuth>} />
            <Route path="/search"   element={<RequireAuth><Navigate to="/hub/search"   replace /></RequireAuth>} />
            <Route path="/ops"      element={<RequireAuth><Navigate to="/hub/ops"      replace /></RequireAuth>} />
            <Route path="/system"   element={<RequireAuth><Navigate to="/hub/system"   replace /></RequireAuth>} />
            <Route path="/learning" element={<RequireAuth><Navigate to="/hub/runtime" replace /></RequireAuth>} />
            <Route path="/agents"   element={<RequireAuth><Navigate to="/hub/runtime" replace /></RequireAuth>} />

            {/* ── 归档页（lazy，避免 DocsReader 的 ?raw 路径导致全局崩溃） ── */}
            <Route path="/archive/deep-dive"      element={<RequireAuth><Suspense fallback={null}><AgentRuntimeDeepDive /></Suspense></RequireAuth>} />
            <Route path="/archive/deep-dive-folk" element={<RequireAuth><Suspense fallback={null}><AgentRuntimeFolk /></Suspense></RequireAuth>} />
            <Route path="/archive/docs"           element={<RequireAuth><Suspense fallback={null}><DocsReader /></Suspense></RequireAuth>} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
    </ErrorBoundary>
  );
}
