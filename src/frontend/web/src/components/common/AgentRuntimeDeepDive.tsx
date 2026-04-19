import React, { useState, useEffect } from 'react'
import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
} from 'recharts'
import { getTheme, toggleTheme } from '../../config/theme'

/* ===================================================================
   Agent Runtime 深度调研展示页
   包含：大比分对比、多层架构、流程流线、伪代码、RAG 设计模式
   =================================================================== */

// ------------------- 数据定义 -------------------

const radarData = [
  { subject: '状态持久化', XState: 40, LangGraph: 95, CrewAI: 50, AutoGen: 60 },
  { subject: '崩溃恢复', XState: 20, LangGraph: 95, CrewAI: 30, AutoGen: 40 },
  { subject: 'Human-in-loop', XState: 60, LangGraph: 90, CrewAI: 40, AutoGen: 50 },
  { subject: '多 Agent 协作', XState: 70, LangGraph: 85, CrewAI: 90, AutoGen: 95 },
  { subject: '学习曲线', XState: 85, LangGraph: 50, CrewAI: 80, AutoGen: 65 },
  { subject: 'TypeScript 原生', XState: 95, LangGraph: 30, CrewAI: 20, AutoGen: 30 },
  { subject: '生产验证', XState: 60, LangGraph: 95, CrewAI: 60, AutoGen: 70 },
  { subject: '流式输出', XState: 75, LangGraph: 90, CrewAI: 50, AutoGen: 60 },
]

const barData = [
  { name: 'GitHub Stars', XState: 25000, LangGraph: 25000, CrewAI: 20000, AutoGen: 50000 },
  { name: '月下载量(万)', XState: 80, LangGraph: 3450, CrewAI: 120, AutoGen: 200 },
  { name: '生产案例', XState: 30, LangGraph: 400, CrewAI: 50, AutoGen: 80 },
]

const layerColors = [
  '#4f46e5', // 应用层
  '#06b6d4', // 编排层
  '#10b981', // 状态层
  '#f59e0b', // 持久层
  '#ef4444', // 观测层
]

// ------------------- 子组件 -------------------

const SectionTitle: React.FC<{ children: React.ReactNode; subtitle?: string }> = ({
  children,
  subtitle,
}) => (
  <div style={{ marginBottom: 24 }}>
    <h2
      style={{
        fontSize: 28,
        fontWeight: 700,
        color: '#1f2937',
        marginBottom: subtitle ? 8 : 0,
        borderLeft: '4px solid #4f46e5',
        paddingLeft: 12,
      }}
    >
      {children}
    </h2>
    {subtitle && (
      <p style={{ fontSize: 15, color: '#6b7280', margin: 0 }}>{subtitle}</p>
    )}
  </div>
)

const Card: React.FC<{ title: string; children: React.ReactNode; color?: string }> = ({
  title,
  children,
  color = '#4f46e5',
}) => (
  <div
    style={{
      background: '#fff',
      borderRadius: 12,
      border: '1px solid #e5e7eb',
      padding: 20,
      boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
    }}
  >
    <h3
      style={{
        fontSize: 17,
        fontWeight: 600,
        marginBottom: 12,
        color,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}
    >
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: color,
          display: 'inline-block',
        }}
      />
      {title}
    </h3>
    <div style={{ fontSize: 14, lineHeight: 1.7, color: '#374151' }}>{children}</div>
  </div>
)

const CodeBlock: React.FC<{ lang?: string; children: string }> = ({ children }) => (
  <pre
    style={{
      background: '#1e1e2e',
      color: '#cdd6f4',
      padding: 16,
      borderRadius: 10,
      fontSize: 13,
      lineHeight: 1.6,
      overflowX: 'auto',
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
      margin: '12px 0',
    }}
  >
    <code>{children}</code>
  </pre>
)

const FlowStep: React.FC<{
  num: number
  title: string
  desc: string
  active?: boolean
}> = ({ num, title, desc, active }) => (
  <div
    style={{
      display: 'flex',
      alignItems: 'flex-start',
      gap: 14,
      padding: 14,
      borderRadius: 10,
      background: active ? '#eef2ff' : '#f9fafb',
      border: `2px solid ${active ? '#4f46e5' : 'transparent'}`,
      transition: 'all 0.3s',
      marginBottom: 10,
    }}
  >
    <div
      style={{
        width: 32,
        height: 32,
        borderRadius: '50%',
        background: active ? '#4f46e5' : '#d1d5db',
        color: '#fff',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontWeight: 700,
        fontSize: 14,
        flexShrink: 0,
      }}
    >
      {num}
    </div>
    <div>
      <div style={{ fontWeight: 600, fontSize: 14, color: '#1f2937', marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: 13, color: '#6b7280' }}>{desc}</div>
    </div>
  </div>
)

// ------------------- 主页面 -------------------

export default function AgentRuntimeDeepDive() {
  const [activeSuperstep, setActiveSuperstep] = useState(0)
  const [selectedFramework, setSelectedFramework] = useState<string | null>(null)
  const [theme, setThemeState] = useState(getTheme())

  useEffect(() => {
    const handler = () => setThemeState(getTheme())
    window.addEventListener('storage', handler)
    const interval = setInterval(handler, 500)
    return () => {
      window.removeEventListener('storage', handler)
      clearInterval(interval)
    }
  }, [])

  const supersteps = [
    {
      title: '输入映射 (map_input)',
      desc: '将外部输入转换为 Channel 更新。例如：用户查询写入 query Channel。',
    },
    {
      title: '准备任务 (prepare_next_tasks)',
      desc: '检查每个 Channel 的版本号。如果某 Channel 自上次执行后版本递增，订阅它的节点被标记为可执行。',
    },
    {
      title: '并发执行 (PregelRunner.tick)',
      desc: '所有就绪节点并行执行。每个节点签名：State -> Partial<State>。节点间不直接通信，只通过写入 Channel 表达输出。',
    },
    {
      title: '合并 writes (apply_writes)',
      desc: '收集所有节点的 writes，按 Channel 分组。每个 Channel 调用自己的 update() + reducer 合并。生成 updated_channels 集合。',
    },
    {
      title: '保存 Checkpoint',
      desc: '将当前所有 Channel 值序列化为快照。形成链表：id -> parent_id。支持崩溃恢复和 time-travel。',
    },
    {
      title: '检查中断 (should_interrupt)',
      desc: '如果 interrupt_before/after 匹配当前节点，抛出 GraphInterrupt。状态已保存，可安全暂停。',
    },
  ]

  return (
    <div
      style={{
        maxWidth: 1200,
        margin: '0 auto',
        padding: '32px 24px',
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
        background: '#f8fafc',
        minHeight: '100vh',
      }}
    >
      {/* ===================== Hero ===================== */}
      <div style={{ textAlign: 'center', marginBottom: 48 }}>
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 16, marginBottom: 16 }}>
          <h1 style={{ fontSize: 40, fontWeight: 800, color: 'var(--text-primary)', margin: 0 }}>
            Agent Runtime 深度调研
          </h1>
          <button
            onClick={() => { toggleTheme(); setThemeState(getTheme()) }}
            style={{
              padding: '8px 14px',
              borderRadius: 20,
              border: '1px solid var(--border-default)',
              background: 'var(--bg-elevated)',
              color: 'var(--text-primary)',
              fontSize: 13,
              cursor: 'pointer',
            }}
          >
            {theme === 'dark' ? '☀️ 亮色' : '🌙 暗黑'}
          </button>
        </div>
        <p style={{ fontSize: 17, color: 'var(--text-muted)', maxWidth: 700, margin: '0 auto', lineHeight: 1.6 }}>
          基于 LangGraph / XState / CrewAI / AutoGen 的多维度技术拆解。
          <br />
          涵盖架构对比、Runtime 核心机制、RAG 设计模式与源码映射。
        </p>
      </div>

      {/* ===================== 1. 大比分对比 ===================== */}
      <SectionTitle subtitle="从 8 个维度横向对比主流 Agent 框架">
        一、大比分：谁的状态机最强？
      </SectionTitle>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          gap: 20,
          marginBottom: 32,
        }}
      >
        <Card title="能力雷达图" color="#4f46e5">
          <div style={{ height: 320 }}>
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart cx="50%" cy="50%" outerRadius="70%" data={radarData}>
                <PolarGrid />
                <PolarAngleAxis dataKey="subject" tick={{ fontSize: 12 }} />
                <PolarRadiusAxis angle={30} domain={[0, 100]} tick={{ fontSize: 10 }} />
                <Radar name="XState" dataKey="XState" stroke="#f59e0b" fill="#f59e0b" fillOpacity={0.15} />
                <Radar name="LangGraph" dataKey="LangGraph" stroke="#4f46e5" fill="#4f46e5" fillOpacity={0.25} />
                <Radar name="CrewAI" dataKey="CrewAI" stroke="#10b981" fill="#10b981" fillOpacity={0.15} />
                <Legend />
              </RadarChart>
            </ResponsiveContainer>
          </div>
          <p style={{ fontSize: 12, color: '#9ca3af', marginTop: 8, textAlign: 'center' }}>
            数据来源：GitHub stars、生产案例、官方文档、社区基准测试（2025Q2）
          </p>
        </Card>

        <Card title="生态规模对比" color="#06b6d4">
          <div style={{ height: 280 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={barData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend />
                <Bar dataKey="XState" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                <Bar dataKey="LangGraph" fill="#4f46e5" radius={[4, 4, 0, 0]} />
                <Bar dataKey="CrewAI" fill="#10b981" radius={[4, 4, 0, 0]} />
                <Bar dataKey="AutoGen" fill="#ef4444" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      {/* 通俗解释 */}
      <div
        style={{
          background: '#fff',
          borderRadius: 12,
          border: '1px solid #e5e7eb',
          padding: 24,
          marginBottom: 40,
        }}
      >
        <h3 style={{ fontSize: 18, fontWeight: 600, marginBottom: 16, color: '#1f2937' }}>
          通俗解读
        </h3>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
            gap: 16,
          }}
        >
          {[
            {
              fw: 'LangGraph',
              tag: '生产首选',
              color: '#4f46e5',
              text: '像一台带「黑匣子」的飞机——每一步都自动记录快照（checkpoint），坠机后能从任意时刻恢复。被 Klarna、Uber 生产验证。缺点是 TS 支持弱、学习曲线陡。',
            },
            {
              fw: 'XState',
              tag: '前端/TS 最强',
              color: '#f59e0b',
              text: '像一台精密的机械表——event-driven、类型安全、可视化完美。但缺持久化和分布式状态合并。适合已有 TS 团队「借鉴设计、自研扩展」。',
            },
            {
              fw: 'CrewAI',
              tag: '原型最快',
              color: '#10b981',
              text: '像一支临时剧组——角色（Role）定义清晰，50 行代码跑起来。但 state 控制弱，不适合复杂状态机和长流程。',
            },
            {
              fw: 'AutoGen',
              tag: '对话最强',
              color: '#ef4444',
              text: '像一群在群聊里讨论的顾问——conversational pattern 丰富。但 token 消耗高、状态隐式、生产稳定性待验证。',
            },
          ].map((item) => (
            <div
              key={item.fw}
              style={{
                padding: 16,
                borderRadius: 10,
                background: '#f9fafb',
                border: `2px solid ${selectedFramework === item.fw ? item.color : 'transparent'}`,
                cursor: 'pointer',
              }}
              onClick={() =>
                setSelectedFramework(selectedFramework === item.fw ? null : item.fw)
              }
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <strong style={{ fontSize: 15, color: '#111827' }}>{item.fw}</strong>
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    padding: '2px 8px',
                    borderRadius: 12,
                    background: item.color + '15',
                    color: item.color,
                  }}
                >
                  {item.tag}
                </span>
              </div>
              <p style={{ fontSize: 13, color: '#4b5563', lineHeight: 1.6, margin: 0 }}>{item.text}</p>
            </div>
          ))}
        </div>
      </div>

      {/* ===================== 2. 多层架构 ===================== */}
      <SectionTitle subtitle="LangGraph Runtime 的五层架构 vs 你的现有架构映射">
        二、多层架构：五层拆解
      </SectionTitle>

      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
          marginBottom: 40,
        }}
      >
        {[
          {
            name: '应用层 (Application)',
            color: layerColors[0],
            left: 'FastAPI Routes / React UI',
            center: 'Graph.invoke() / Graph.stream()',
            right: '用户查询输入、答案输出、流式推送',
          },
          {
            name: '编排层 (Orchestration)',
            color: layerColors[1],
            left: 'XState Machine + EventBus',
            center: 'StateGraph.compile() -> PregelLoop',
            right: '节点调度、条件路由、中断恢复、子图嵌套',
          },
          {
            name: '状态层 (State)',
            color: layerColors[2],
            left: 'Zustand + XState Context',
            center: 'Channel + Reducer + TypedDict',
            right: '状态合并策略、版本号追踪、增量更新',
          },
          {
            name: '持久层 (Persistence)',
            color: layerColors[3],
            left: 'Redis / PostgreSQL (自定义)',
            center: 'BaseCheckpointSaver + Checkpoint',
            right: '快照链表、time-travel、崩溃恢复、thread 隔离',
          },
          {
            name: '观测层 (Observability)',
            color: layerColors[4],
            left: 'WebSocket + EventLog',
            center: 'LangSmith / StreamProtocol',
            right: '执行轨迹、状态 diff、调试回放、成本监控',
          },
        ].map((layer, i) => (
          <div
            key={i}
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1.4fr 1fr',
              gap: 12,
              alignItems: 'center',
              background: '#fff',
              borderRadius: 10,
              borderLeft: `5px solid ${layer.color}`,
              padding: '14px 18px',
              boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
            }}
          >
            <div>
              <div style={{ fontWeight: 700, fontSize: 14, color: layer.color, marginBottom: 4 }}>
                {layer.name}
              </div>
              <div style={{ fontSize: 12, color: '#6b7280' }}>你现在的实现</div>
              <div style={{ fontSize: 13, color: '#374151', fontWeight: 500 }}>{layer.left}</div>
            </div>
            <div
              style={{
                textAlign: 'center',
                background: layer.color + '08',
                borderRadius: 8,
                padding: '10px 14px',
              }}
            >
              <div style={{ fontSize: 11, color: '#9ca3af', marginBottom: 2 }}>LangGraph 对标</div>
              <div style={{ fontSize: 14, fontWeight: 600, color: '#1f2937' }}>{layer.center}</div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 12, color: '#6b7280' }}>核心职责</div>
              <div style={{ fontSize: 13, color: '#374151' }}>{layer.right}</div>
            </div>
          </div>
        ))}
      </div>

      {/* ===================== 3. Runtime 核心概念 ===================== */}
      <SectionTitle subtitle="LangGraph 的四大核心抽象，也是你自研时需要复现的基石">
        三、Runtime 心脏：四大核心概念
      </SectionTitle>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
          gap: 16,
          marginBottom: 40,
        }}
      >
        <Card title="Checkpoint（快照）" color="#f59e0b">
          <p>
            每个超步结束后自动保存的<strong>不可变状态快照</strong>。包含：
          </p>
          <ul style={{ paddingLeft: 18, margin: '8px 0' }}>
            <li>id：UUID，单调递增</li>
            <li>channel_values：各 Channel 的序列化值</li>
            <li>channel_versions：版本号（向量时钟简化版）</li>
            <li>versions_seen：每个节点已看到的版本</li>
          </ul>
          <p style={{ margin: 0, fontSize: 12, color: '#6b7280' }}>
            类比：游戏的存档点，随时加载、分叉、回溯。
          </p>
        </Card>

        <Card title="Channel（状态通道）" color="#10b981">
          <p>
            每个 State Key 底层对应一个 Channel，负责<strong>状态合并策略</strong>：
          </p>
          <ul style={{ paddingLeft: 18, margin: '8px 0' }}>
            <li>LastValue — 覆盖（默认）</li>
            <li>BinaryOperatorAggregate — 累积（如 operator.add）</li>
            <li>Topic — 发布订阅，consume 后清空</li>
            <li>EphemeralValue — 一步存活</li>
          </ul>
          <p style={{ margin: 0, fontSize: 12, color: '#6b7280' }}>
            类比：每个字段配一个「合并规则」，并行节点写同一段数据时不冲突。
          </p>
        </Card>

        <Card title="Superstep（超步循环）" color="#4f46e5">
          <p>
            Pregel 执行模型的核心循环，每步三件事：
          </p>
          <ol style={{ paddingLeft: 18, margin: '8px 0' }}>
            <li>收集所有可执行节点（入边满足）</li>
            <li>并行执行，收集 Partial State</li>
            <li>通过 Reducer 合并，决定下一批节点</li>
          </ol>
          <p style={{ margin: 0, fontSize: 12, color: '#6b7280' }}>
            类比：一回合制游戏，所有角色同时出招，然后结算。
          </p>
        </Card>

        <Card title="Reducer（合并器）" color="#06b6d4">
          <p>
            控制多个节点同时更新同一字段时的合并行为：
          </p>
          <CodeBlock lang="python">
{`class State(TypedDict):
    messages: Annotated[list, operator.add]  # 累积
    confidence: float                         # 覆盖
    metadata: Annotated[dict, lambda o,n: {**o,**n}]  # 合并`}
          </CodeBlock>
          <p style={{ margin: 0, fontSize: 12, color: '#6b7280' }}>
            类比：Git 的 merge strategy —— 有的字段用 rebase，有的用 squash。
          </p>
        </Card>
      </div>

      {/* ===================== 4. 流程流线 ===================== */}
      <SectionTitle subtitle="点击步骤查看 Pregel 超步循环的完整细节">
        四、流程流线：Pregel Superstep 循环
      </SectionTitle>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1.2fr',
          gap: 24,
          marginBottom: 40,
        }}
      >
        <div>
          {supersteps.map((s, i) => (
            <div key={i} onClick={() => setActiveSuperstep(i)} style={{ cursor: 'pointer' }}>
              <FlowStep num={i + 1} title={s.title} desc={s.desc} active={activeSuperstep === i} />
            </div>
          ))}
          <div
            style={{
              marginTop: 12,
              padding: 14,
              borderRadius: 10,
              background: '#eef2ff',
              border: '1px dashed #4f46e5',
              fontSize: 13,
              color: '#4f46e5',
              fontWeight: 500,
            }}
          >
            🔁 循环条件：updated_channels 能触发新节点，且未到达 END，且未触发 interrupt
          </div>
        </div>

        <div>
          <div
            style={{
              background: '#fff',
              borderRadius: 12,
              border: '1px solid #e5e7eb',
              padding: 20,
              height: '100%',
            }}
          >
            <h4 style={{ margin: '0 0 12px 0', fontSize: 15, color: '#1f2937' }}>
              步骤 {activeSuperstep + 1} 详解
            </h4>
            <p style={{ fontSize: 14, color: '#4b5563', lineHeight: 1.7, marginBottom: 16 }}>
              {supersteps[activeSuperstep].desc}
            </p>

            {activeSuperstep === 0 && (
              <CodeBlock>
{`// 用户输入被映射为 Channel 更新
const inputWrites = [{ channel: 'query', value: '什么是 RAG？' }]

// 同时触发版本号递增
checkpoint.channel_versions['query'] = nextVersion`}
              </CodeBlock>
            )}

            {activeSuperstep === 1 && (
              <CodeBlock>
{`// 检查每个节点的订阅 Channel 是否更新
for (const node of nodes) {
  for (const trigger of node.triggers) {
    const seen = checkpoint.versions_seen[node.name][trigger]
    const current = checkpoint.channel_versions[trigger]
    if (current > seen) {
      readyTasks.push(node)  // 版本号推进 = 需要重新执行
    }
  }
}`}
              </CodeBlock>
            )}

            {activeSuperstep === 2 && (
              <CodeBlock>
{`// 并行执行所有就绪节点
const results = await Promise.all(
  readyTasks.map(task => runNode(task, currentState))
)

// 每个节点返回 Partial State
// 例如 retrieveNode 返回 { retrieval_results: [...] }
// 例如 rerankNode 返回 { retrieval_results: [...] }`}
              </CodeBlock>
            )}

            {activeSuperstep === 3 && (
              <CodeBlock>
{`// 按 Channel 分组 writes
const byChannel = groupBy(writes, w => w.channel)

for (const [chan, vals] of byChannel) {
  // 由 Channel 自己的 update() 合并
  const changed = channels[chan].update(vals)
  if (changed) {
    checkpoint.channel_versions[chan] = nextVersion
    updatedChannels.add(chan)
  }
}`}
              </CodeBlock>
            )}

            {activeSuperstep === 4 && (
              <CodeBlock>
{`const newCheckpoint = {
  id: uuid6(),           // 新 UUID
  parent_id: old.id,     // 链表指针
  channel_values: serialize(channels),
  channel_versions: { ...checkpoint.channel_versions },
  versions_seen: { ...checkpoint.versions_seen },
}

await saver.put(config, newCheckpoint, metadata, newVersions)`}
              </CodeBlock>
            )}

            {activeSuperstep === 5 && (
              <CodeBlock>
{`// Human-in-the-loop
if (interruptNodes.includes(currentNodeName)) {
  // 状态已保存，安全暂停
  throw new GraphInterrupt({
    value: state.proposal,
    resume: null,
  })
}

// 恢复时：Command(resume="Approved")
// 从上一个 checkpoint 继续执行`}
              </CodeBlock>
            )}
          </div>
        </div>
      </div>

      {/* ===================== 5. 伪代码区 ===================== */}
      <SectionTitle subtitle="LangGraph 最核心的三个函数，以及映射到你的 XState 实现">
        五、核心伪代码： tick / apply_writes / compile
      </SectionTitle>

      <div style={{ marginBottom: 40 }}>
        <h4 style={{ fontSize: 16, fontWeight: 600, color: '#1f2937', marginBottom: 12 }}>
          5.1 PregelLoop.tick() — 超步调度器
        </h4>
        <CodeBlock>
{`function tick(): boolean {
  // 1. 步数保护
  if (step > maxSteps) { status = "out_of_steps"; return false; }

  // 2. 根据 Channel 版本号计算就绪节点
  tasks = prepareNextTasks({
    checkpoint, channels, nodes, updatedChannels
  });

  // 3. 无任务 -> 结束
  if (tasks.isEmpty()) { status = "done"; return false; }

  // 4. 恢复之前保存的 pending writes（用于崩溃恢复）
  if (!isReplaying && checkpointPendingWrites) {
    matchWritesToTasks(tasks, checkpointPendingWrites);
  }

  // 5. Human-in-the-loop 检查
  if (shouldInterrupt(checkpoint, interruptBefore, tasks)) {
    status = "interrupt_before";
    throw new GraphInterrupt();  // 安全暂停，状态已保存
  }

  return true;  // 让 Runner 去执行 tasks
}`}
        </CodeBlock>

        <h4
          style={{
            fontSize: 16,
            fontWeight: 600,
            color: '#1f2937',
            marginBottom: 12,
            marginTop: 24,
          }}
        >
          5.2 apply_writes() — 状态合并引擎
        </h4>
        <CodeBlock>
{`function applyWrites(checkpoint, channels, tasks, getNextVersion) {
  const updatedChannels = new Set<string>();

  // 1. 更新 versions_seen（每个节点记录它看到的版本）
  for (const task of tasks) {
    checkpoint.versions_seen[task.name] = {
      ...checkpoint.versions_seen[task.name],
      ...Object.fromEntries(
        task.triggers.map(t => [t, checkpoint.channel_versions[t]])
      )
    };
  }

  // 2. 计算下一个全局版本号
  const nextVersion = getNextVersion(
    Math.max(...Object.values(checkpoint.channel_versions))
  );

  // 3. 按 Channel 分组收集 writes
  const writesByChannel = groupBy(
    tasks.flatMap(t => t.writes),
    w => w.channel
  );

  // 4. 对每个 Channel 调用 update()（内部用 reducer 合并）
  for (const [channelName, values] of writesByChannel) {
    const changed = channels[channelName].update(values);
    if (changed) {
      checkpoint.channel_versions[channelName] = nextVersion;
      if (channels[channelName].isAvailable()) {
        updatedChannels.add(channelName);
      }
    }
  }

  return updatedChannels;  // 决定下一步触发哪些节点
}`}
        </CodeBlock>

        <h4
          style={{
            fontSize: 16,
            fontWeight: 600,
            color: '#1f2937',
            marginBottom: 12,
            marginTop: 24,
          }}
        >
          {'5.3 StateGraph.compile() — 编译器（Builder -> Runtime）'}
        </h4>
        <CodeBlock>
{`function compile(stateGraph, checkpointer) {
  // 1. 验证图结构
  validateGraph(stateGraph.nodes, stateGraph.edges);

  // 2. 将 StateSchema 映射为 Channel 实例
  const channels = {};
  for (const [key, type] of Object.entries(stateGraph.schema)) {
    if (type.reducer) {
      channels[key] = new BinaryOperatorAggregate(type.baseType, type.reducer);
    } else {
      channels[key] = new LastValue(type.baseType);
    }
  }

  // 3. 将每个 node 包装为 PregelNode
  const nodes = {};
  for (const [name, fn] of Object.entries(stateGraph.nodes)) {
    nodes[name] = new PregelNode({
      triggers: fn.inputChannels,   // 订阅的 Channel
      writes: fn.outputChannels,    // 写入的 Channel
      bound: wrapRunnable(fn),      // 实际的节点函数
    });
  }

  // 4. 组装 Pregel 实例（包含 Loop + Runner）
  return new Pregel({
    nodes, channels, checkpointer,
    inputChannels: stateGraph.inputSchema,
    outputChannels: stateGraph.outputSchema,
  });
}`}
        </CodeBlock>
      </div>

      {/* ===================== 6. RAG 设计模式 ===================== */}
      <SectionTitle subtitle="从用户查询到最终答案的完整 RAG 流程，映射到 Pregel 图节点">
        {'六、RAG 设计模式：查询 -> 检索 -> 精排 -> 生成'}
      </SectionTitle>

      <div
        style={{
          background: '#fff',
          borderRadius: 12,
          border: '1px solid #e5e7eb',
          padding: 28,
          marginBottom: 40,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: 8,
          }}
        >
          {[
            { label: '用户查询', sub: 'query Channel', color: '#4f46e5' },
            { label: '→', sub: '', color: 'transparent' },
            { label: '理解意图', sub: 'decompose node', color: '#06b6d4' },
            { label: '→', sub: '', color: 'transparent' },
            { label: '多路召回', sub: 'retrieve node', color: '#10b981' },
            { label: '→', sub: '', color: 'transparent' },
            { label: 'Cross-Encoder 精排', sub: 'rerank node', color: '#f59e0b' },
            { label: '→', sub: '', color: 'transparent' },
            { label: '分数融合', sub: 'fuse node', color: '#ef4444' },
            { label: '→', sub: '', color: 'transparent' },
            { label: '生成答案', sub: 'generate node', color: '#8b5cf6' },
            { label: '→', sub: '', color: 'transparent' },
            { label: '评估/中断', sub: 'evaluate node', color: '#ec4899' },
          ].map((item, i) => (
            <div key={i} style={{ textAlign: 'center' }}>
              {item.color === 'transparent' ? (
                <span style={{ fontSize: 20, color: '#9ca3af' }}>→</span>
              ) : (
                <>
                  <div
                    style={{
                      background: item.color + '12',
                      color: item.color,
                      padding: '10px 16px',
                      borderRadius: 8,
                      fontWeight: 600,
                      fontSize: 14,
                      border: `1px solid ${item.color}30`,
                    }}
                  >
                    {item.label}
                  </div>
                  <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 4 }}>{item.sub}</div>
                </>
              )}
            </div>
          ))}
        </div>

        <div
          style={{
            marginTop: 24,
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: 12,
          }}
        >
          {[
            {
              title: 'decompose node',
              in: 'query: string',
              out: 'sub_queries: string[]',
              note: '把复杂查询拆成多个子查询，写入 sub_queries Channel（Topic）',
            },
            {
              title: 'retrieve node',
              in: 'sub_queries: string[]',
              out: 'retrieval_results: Chunk[]',
              note: '并行检索，results 用 reducer append 累积',
            },
            {
              title: 'rerank node',
              in: 'retrieval_results: Chunk[]',
              out: 'retrieval_results: Chunk[]',
              note: '精排后覆盖原 Channel（LastValue）',
            },
            {
              title: 'evaluate node',
              in: 'answer: string, confidence: number',
              out: 'decision: "continue" | "finalize" | "escalate"',
              note: '设置 interrupt_after，低置信度时暂停等待人工审核',
            },
          ].map((n, i) => (
            <div
              key={i}
              style={{
                background: '#f9fafb',
                borderRadius: 8,
                padding: 12,
                fontSize: 12,
                lineHeight: 1.6,
              }}
            >
              <div style={{ fontWeight: 700, color: '#1f2937', marginBottom: 4 }}>{n.title}</div>
              <div style={{ color: '#059669' }}>in: {n.in}</div>
              <div style={{ color: '#d97706' }}>out: {n.out}</div>
              <div style={{ color: '#6b7280', marginTop: 4 }}>{n.note}</div>
            </div>
          ))}
        </div>
      </div>

      {/* ===================== 7. 源码映射表 ===================== */}
      <SectionTitle subtitle="LangGraph 源码文件 -> 你的 XState 实现对应关系">
        七、源码映射：抄设计，不抄依赖
      </SectionTitle>

      <div
        style={{
          background: '#fff',
          borderRadius: 12,
          border: '1px solid #e5e7eb',
          overflow: 'hidden',
          marginBottom: 40,
        }}
      >
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <thead>
            <tr style={{ background: '#f3f4f6' }}>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600, color: '#374151' }}>
                LangGraph 源码文件
              </th>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600, color: '#374151' }}>
                核心机制
              </th>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600, color: '#374151' }}>
                你的 XState 映射
              </th>
            </tr>
          </thead>
          <tbody>
            {[
              {
                file: 'checkpoint/base/__init__.py',
                mech: 'Checkpoint / CheckpointMetadata / BaseCheckpointSaver',
                map: 'Redis/Postgres 中的 thread_id + snapshot 表结构',
              },
              {
                file: 'channels/base.py',
                mech: 'BaseChannel (update/get/checkpoint)',
                map: 'context 字段配 mergeStrategy: lastWriteWins / append / sum',
              },
              {
                file: 'pregel/_algo.py',
                mech: 'apply_writes() + prepare_next_tasks()',
                map: 'XState assign() 的批量合并 + transition guard',
              },
              {
                file: 'pregel/_loop.py',
                mech: 'PregelLoop.tick() + after_tick()',
                map: 'interpret(machine).onTransition() + checkpointService.save()',
              },
              {
                file: 'pregel/_runner.py',
                mech: 'PregelRunner.tick() 并发执行',
                map: 'Promise.all() 并行执行独立 actions',
              },
              {
                file: 'pregel/_checkpoint.py',
                mech: 'create_checkpoint() / channels_from_checkpoint()',
                map: 'JSON.stringify(context) + 从 Redis 恢复初始 context',
              },
              {
                file: 'graph/state.py',
                mech: 'StateGraph.compile()',
                map: 'createMachine() + 状态转换表',
              },
              {
                file: 'types.py',
                mech: 'interrupt() / Command(resume=)',
                map: 'XState 等待外部 RESUME 事件 + 合并 payload',
              },
            ].map((row, i) => (
              <tr key={i} style={{ borderTop: '1px solid var(--border-default)' }}>
                <td style={{ padding: '10px 16px', fontFamily: 'monospace', fontSize: 12, color: '#4f46e5' }}>
                  {row.file}
                </td>
                <td style={{ padding: '10px 16px', color: '#374151' }}>{row.mech}</td>
                <td style={{ padding: '10px 16px', color: '#059669', fontWeight: 500 }}>{row.map}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ===================== 8. 可交互 RAG 节点详情 ===================== */}
      <SectionTitle subtitle="点击节点查看输入输出契约、Channel 配置和示例代码">
        八、RAG 节点解剖室
      </SectionTitle>

      <RagNodeAnatomy />

      {/* ===================== 9. 性能基准 ===================== */}
      <SectionTitle subtitle="社区公开基准测试数据（环境不同仅供参考）">
        九、性能基准：谁跑得最快？
      </SectionTitle>

      <div
        style={{
          background: '#fff',
          borderRadius: 12,
          border: '1px solid #e5e7eb',
          overflow: 'hidden',
          marginBottom: 40,
        }}
      >
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <thead>
            <tr style={{ background: '#f3f4f6' }}>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600 }}>指标</th>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600 }}>LangGraph</th>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600 }}>XState + 自研</th>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600 }}>CrewAI</th>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600 }}>AutoGen</th>
            </tr>
          </thead>
          <tbody>
            {[
              ['p99 延迟（单 Agent）', '< 2.1s', '取决于实现', '2.5s', '1.8s'],
              ['吞吐量（req/s）', '8.5', '取决于实现', '10.1', '12.2'],
              ['内存占用', '4.2GB', '最小', '5.1GB', '3.8GB'],
              ['Checkpoint 序列化', '~1ms（小状态）', '自定义', '无原生支持', '无原生支持'],
              ['崩溃恢复时间', '< 100ms', '取决于存储', 'N/A', 'N/A'],
              ['Human-in-loop 延迟', '< 50ms 恢复', '取决于实现', 'N/A', 'N/A'],
              ['并发节点数', '无上限（线程池）', 'Promise.all', 'Python 线程', 'Python 异步'],
            ].map((row, i) => (
              <tr key={i} style={{ borderTop: '1px solid var(--border-default)' }}>
                {row.map((cell, j) => (
                  <td
                    key={j}
                    style={{
                      padding: '10px 16px',
                      fontWeight: j === 0 ? 500 : 400,
                      color: j === 0 ? '#111827' : '#4b5563',
                      fontFamily: j === 0 ? 'inherit' : 'monospace',
                      fontSize: j === 0 ? 14 : 13,
                    }}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ padding: '10px 16px', fontSize: 12, color: '#9ca3af', background: '#f9fafb' }}>
          注：LangGraph/CrewAI/AutoGen 数据来自 2025 社区基准（AWS/GCP 中等实例），XState
          行表示「如果自研实现」的理论下限。
        </div>
      </div>

      {/* ===================== 10. 配置生成器 ===================== */}
      <SectionTitle subtitle="基于调研结论，一键生成你的 XState + RAG 配置骨架">
        十、配置生成器：从调研到代码
      </SectionTitle>

      <ConfigGenerator />

      {/* ===================== 11. 源码导航 ===================== */}
      <SectionTitle subtitle="直接跳转到 GitHub 源码阅读">
        十一、源码导航：在哪看原始代码？
      </SectionTitle>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: 12,
          marginBottom: 40,
        }}
      >
        {[
          {
            title: 'LangGraph Runtime 核心',
            url: 'https://github.com/langchain-ai/langgraph/tree/main/libs/langgraph/langgraph/pregel',
            desc: 'PregelLoop、PregelRunner、apply_writes、StateGraph',
            color: '#4f46e5',
          },
          {
            title: 'LangGraph Checkpoint',
            url: 'https://github.com/langchain-ai/langgraph/tree/main/libs/checkpoint/langgraph/checkpoint',
            desc: 'Checkpoint 结构、BaseCheckpointSaver、Postgres/Redis 实现',
            color: '#f59e0b',
          },
          {
            title: 'LangGraph Channels',
            url: 'https://github.com/langchain-ai/langgraph/tree/main/libs/langgraph/langgraph/channels',
            desc: 'BaseChannel、LastValue、Topic、BinaryOperatorAggregate',
            color: '#10b981',
          },
          {
            title: 'LangGraph 文档（Agentic RAG）',
            url: 'https://github.com/langchain-ai/langgraph/tree/main/docs/docs',
            desc: 'Agentic RAG、Memory、Persistence、Subgraphs 教程',
            color: '#06b6d4',
          },
          {
            title: 'LangChain 文档仓库',
            url: 'https://github.com/langchain-ai/docs',
            desc: 'RAG、Retrieval、Knowledge Base 完整文档（已 copy 到本地）',
            color: '#ef4444',
          },
          {
            title: 'XState 官方文档',
            url: 'https://github.com/statelyai/xstate',
            desc: '状态机、Actor Model、TypeScript 类型推导',
            color: '#8b5cf6',
          },
        ].map((item, i) => (
          <a
            key={i}
            href={item.url}
            target="_blank"
            rel="noreferrer"
            style={{
              display: 'block',
              background: '#fff',
              borderRadius: 10,
              border: '1px solid #e5e7eb',
              padding: 16,
              textDecoration: 'none',
              transition: 'transform 0.2s, box-shadow 0.2s',
            }}
            onMouseEnter={(e) => {
              ;(e.currentTarget as HTMLElement).style.transform = 'translateY(-2px)'
              ;(e.currentTarget as HTMLElement).style.boxShadow = '0 4px 12px rgba(0,0,0,0.08)'
            }}
            onMouseLeave={(e) => {
              ;(e.currentTarget as HTMLElement).style.transform = 'translateY(0)'
              ;(e.currentTarget as HTMLElement).style.boxShadow = 'none'
            }}
          >
            <div style={{ fontWeight: 600, fontSize: 14, color: item.color, marginBottom: 6 }}>
              {item.title}
            </div>
            <div style={{ fontSize: 13, color: '#4b5563', lineHeight: 1.5 }}>{item.desc}</div>
            <div style={{ fontSize: 12, color: '#9ca3af', marginTop: 8, fontFamily: 'monospace' }}>
              {item.url.replace('https://', '')}
            </div>
          </a>
        ))}
      </div>

      {/* ===================== 12. 操作栏 ===================== */}
      <div
        style={{
          position: 'sticky',
          bottom: 20,
          display: 'flex',
          justifyContent: 'center',
          gap: 12,
          marginBottom: 24,
          zIndex: 50,
        }}
      >
        <button
          onClick={() => window.print()}
          style={{
            padding: '10px 20px',
            borderRadius: 24,
            border: 'none',
            background: '#1f2937',
            color: '#fff',
            fontSize: 14,
            fontWeight: 500,
            cursor: 'pointer',
            boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          🖨️ 打印 / 导出 PDF
        </button>
        <button
          onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
          style={{
            padding: '10px 20px',
            borderRadius: 24,
            border: 'none',
            background: '#4f46e5',
            color: '#fff',
            fontSize: 14,
            fontWeight: 500,
            cursor: 'pointer',
            boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          ⬆️ 回到顶部
        </button>
      </div>

      {/* ===================== Footer ===================== */}
      <div
        style={{
          textAlign: 'center',
          padding: '24px 0',
          color: '#9ca3af',
          fontSize: 13,
          borderTop: '1px solid var(--border-default)',
        }}
      >
        数据来源：langchain-ai/langgraph @ GitHub &nbsp;|&nbsp; langchain-ai/docs &nbsp;|&nbsp; 外部调研综合整理
      </div>
    </div>
  )
}

// ===================== 子组件：RAG 节点解剖 =====================

function RagNodeAnatomy() {
  const [expanded, setExpanded] = useState<string | null>('retrieve')

  const nodes = [
    {
      id: 'decompose',
      title: 'decompose（查询拆解）',
      color: '#06b6d4',
      inputs: 'query: string',
      outputs: 'sub_queries: string[]',
      channel: 'Topic<string>（发布订阅，消费后清空）',
      code: `function decomposeNode(state) {
  const query = state.query
  const subQueries = llm.generate(
    \`拆解以下查询为子查询：\${query}\`
  )
  return { sub_queries: subQueries }  // Topic Channel，自动广播
}`,
    },
    {
      id: 'retrieve',
      title: 'retrieve（多路召回）',
      color: '#10b981',
      inputs: 'sub_queries: string[]',
      outputs: 'retrieval_results: Chunk[]',
      channel: 'BinaryOperatorAggregate<Chunk[], append>（累积）',
      code: `function retrieveNode(state) {
  const allResults = []
  for (const q of state.sub_queries) {
    const vector = vectorStore.search(q, 30)
    const keyword = es.search(q, 20)
    const graph = neo4j.expand(q, 10)
    allResults.push(...vector, ...keyword, ...graph)
  }
  return { retrieval_results: allResults }  // append reducer
}`,
    },
    {
      id: 'rerank',
      title: 'rerank（Cross-Encoder 精排）',
      color: '#f59e0b',
      inputs: 'retrieval_results: Chunk[]',
      outputs: 'retrieval_results: Chunk[]（覆盖）',
      channel: 'LastValue<Chunk[]>（覆盖）',
      code: `function rerankNode(state) {
  const scored = crossEncoder.score(
    state.query,
    state.retrieval_results
  )
  const topK = scored.sort((a,b) => b.score - a.score).slice(0, 10)
  return { retrieval_results: topK }  // LastValue，覆盖旧值
}`,
    },
    {
      id: 'fuse',
      title: 'fuse（分数融合）',
      color: '#ef4444',
      inputs: 'retrieval_results: Chunk[]（精排后）',
      outputs: 'final_context: string',
      channel: 'LastValue<string>',
      code: `function fuseNode(state) {
  const weights = { rerank: 0.4, vector: 0.3, keyword: 0.2, graph: 0.05, time: 0.05 }
  const fused = weightedFusion(state.retrieval_results, weights)
  const context = buildContext(fused, { maxLength: 2000, window: 2 })
  return { final_context: context }
}`,
    },
    {
      id: 'generate',
      title: 'generate（答案生成）',
      color: '#8b5cf6',
      inputs: 'final_context: string, query: string',
      outputs: 'answer: string, confidence: number',
      channel: 'LastValue<string> + LastValue<number>',
      code: `function generateNode(state) {
  const { answer, confidence } = llm.generate({
    system: '基于上下文回答问题',
    context: state.final_context,
    query: state.query,
  })
  return { answer, confidence }
}`,
    },
    {
      id: 'evaluate',
      title: 'evaluate（评估 + 中断）',
      color: '#ec4899',
      inputs: 'answer: string, confidence: number, depth: number',
      outputs: 'decision: "continue" | "finalize" | "escalate"',
      channel: 'LastValue<string>',
      code: `function evaluateNode(state) {
  if (state.confidence > 0.85 || state.depth >= 5) {
    return { decision: 'finalize' }
  }
  if (state.confidence < 0.5) {
    return { decision: 'escalate' }  // 触发 interrupt_after
  }
  return { decision: 'continue' }  // 回到 decompose
}`,
    },
  ]

  return (
    <div style={{ marginBottom: 40 }}>
      <div
        style={{
          display: 'flex',
          gap: 8,
          marginBottom: 16,
          flexWrap: 'wrap',
        }}
      >
        {nodes.map((n) => (
          <button
            key={n.id}
            onClick={() => setExpanded(expanded === n.id ? null : n.id)}
            style={{
              padding: '8px 14px',
              borderRadius: 8,
              border: 'none',
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
              background: expanded === n.id ? n.color : n.color + '15',
              color: expanded === n.id ? '#fff' : n.color,
              transition: 'all 0.2s',
            }}
          >
            {n.title.split('（')[0]}
          </button>
        ))}
      </div>

      {expanded && (
        <div
          style={{
            background: '#fff',
            borderRadius: 12,
            border: '1px solid #e5e7eb',
            padding: 24,
            animation: 'fadeIn 0.3s ease',
          }}
        >
          {nodes
            .filter((n) => n.id === expanded)
            .map((n) => (
              <div key={n.id}>
                <div
                  style={{
                    fontSize: 18,
                    fontWeight: 700,
                    color: n.color,
                    marginBottom: 16,
                  }}
                >
                  {n.title}
                </div>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                    gap: 12,
                    marginBottom: 16,
                  }}
                >
                  <div style={{ background: '#f0fdf4', padding: 12, borderRadius: 8 }}>
                    <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>输入 Channel</div>
                    <div style={{ fontSize: 13, color: '#111827', fontFamily: 'monospace' }}>{n.inputs}</div>
                  </div>
                  <div style={{ background: '#fffbeb', padding: 12, borderRadius: 8 }}>
                    <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>输出 Channel</div>
                    <div style={{ fontSize: 13, color: '#111827', fontFamily: 'monospace' }}>{n.outputs}</div>
                  </div>
                  <div style={{ background: '#eff6ff', padding: 12, borderRadius: 8 }}>
                    <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>Channel 类型</div>
                    <div style={{ fontSize: 13, color: '#111827' }}>{n.channel}</div>
                  </div>
                </div>
                <CodeBlock>{n.code}</CodeBlock>
              </div>
            ))}
        </div>
      )}
    </div>
  )
}

// ===================== 子组件：配置生成器 =====================

function ConfigGenerator() {
  const [config, setConfig] = useState({
    enableCheckpoint: true,
    checkpointStore: 'redis' as 'redis' | 'postgres' | 'memory',
    enableInterrupt: true,
    interruptNodes: 'evaluate',
    maxDepth: 5,
    mergeStrategy: 'reducer' as 'reducer' | 'lastWriteWins',
    vectorTopK: 30,
    keywordTopK: 20,
    graphTopK: 10,
    enableRerank: true,
    enableFusion: true,
    rerankWeight: 0.4,
    vectorWeight: 0.3,
    keywordWeight: 0.2,
    graphWeight: 0.05,
    timeWeight: 0.05,
  })

  const generateCode = () => {
    return `// 由「Agent Runtime 深度调研」配置生成器自动生成
// 基于 LangGraph 设计模式 + XState 实现

import { createMachine, assign, interpret } from 'xstate'

interface AgentState {
  query: string
  sub_queries: string[]
  retrieval_results: RetrievalChunk[]
  final_context: string
  answer: string
  confidence: number
  decision: 'continue' | 'finalize' | 'escalate'
  depth: number
}

// ==================== 1. Reducer 配置 ====================
const mergeStrategy = {
  // ${config.mergeStrategy === 'reducer' ? '使用 Reducer 合并（推荐）' : '使用 LastWriteWins'}
${config.mergeStrategy === 'reducer' ? `
  retrieval_results: (a: any[], b: any[]) => [...a, ...b],  // append
  messages: (a: any[], b: any[]) => [...a, ...b],           // append
  metadata: (a: object, b: object) => ({ ...a, ...b }),      // merge` : `
  // 所有字段默认 LastWriteWins（简单但不支持并行节点写同字段）`}
}

// ==================== 2. Checkpoint 服务 ====================
class CheckpointService {
  async save(threadId: string, state: AgentState, step: number) {
    ${config.checkpointStore === 'redis' ? `
    await redis.hset(\`checkpoint:\${threadId}\`, String(step), JSON.stringify(state))
    ` : config.checkpointStore === 'postgres' ? `
    await db.query(
      'INSERT INTO checkpoints (thread_id, step, state) VALUES ($1, $2, $3)',
      [threadId, step, JSON.stringify(state)]
    )
    ` : `
    // Memory 模式：仅用于开发和测试
    this._memory[threadId] = state
    `}
  }

  async load(threadId: string): Promise<AgentState | null> {
    ${config.checkpointStore === 'redis' ? `
    const latest = await redis.hgetall(\`checkpoint:\${threadId}\`)
    const maxStep = Math.max(...Object.keys(latest).map(Number))
    return JSON.parse(latest[maxStep])
    ` : config.checkpointStore === 'postgres' ? `
    const row = await db.query(
      'SELECT state FROM checkpoints WHERE thread_id = $1 ORDER BY step DESC LIMIT 1',
      [threadId]
    )
    return row ? JSON.parse(row.state) : null
    ` : `
    return this._memory[threadId] || null
    `}
  }
}

// ==================== 3. XState 机器定义 ====================
const agentMachine = createMachine({
  id: 'rag-agent',
  initial: 'decomposing',
  context: {
    query: '',
    sub_queries: [],
    retrieval_results: [],
    final_context: '',
    answer: '',
    confidence: 0,
    decision: 'continue',
    depth: 0,
  } as AgentState,
  states: {
    decomposing: {
      entry: assign({ depth: (ctx) => ctx.depth + 1 }),
      invoke: {
        src: async (ctx) => {
          const subQueries = await llm.decompose(ctx.query)
          return { sub_queries: subQueries }
        },
        onDone: { target: 'retrieving', actions: assign({ sub_queries: (_, e) => e.data.sub_queries }) },
      },
    },
    retrieving: {
      invoke: {
        src: async (ctx) => {
          const all = []
          for (const q of ctx.sub_queries) {
            const [v, k, g] = await Promise.all([
              vectorStore.search(q, ${config.vectorTopK}),
              es.search(q, ${config.keywordTopK}),
              neo4j.expand(q, ${config.graphTopK}),
            ])
            all.push(...v, ...k, ...g)
          }
          return { retrieval_results: all }
        },
        onDone: { target: 'reranking', actions: assign({ retrieval_results: (_, e) => e.data.retrieval_results }) },
      },
    },
    reranking: {
      invoke: {
        src: async (ctx) => {
          ${config.enableRerank ? `
          const scored = await crossEncoder.rerank(ctx.query, ctx.retrieval_results)
          return { retrieval_results: scored.slice(0, 10) }
          ` : `
          return { retrieval_results: ctx.retrieval_results.slice(0, 10) }
          `}
        },
        onDone: { target: 'fusing', actions: assign({ retrieval_results: (_, e) => e.data.retrieval_results }) },
      },
    },
    fusing: {
      invoke: {
        src: async (ctx) => {
          ${config.enableFusion ? `
          const weights = {
            rerank: ${config.rerankWeight},
            vector: ${config.vectorWeight},
            keyword: ${config.keywordWeight},
            graph: ${config.graphWeight},
            time: ${config.timeWeight},
          }
          const fused = weightedFusion(ctx.retrieval_results, weights)
          ` : `
          const fused = ctx.retrieval_results
          `}
          const context = buildContext(fused, { maxLength: 2000 })
          return { final_context: context }
        },
        onDone: { target: 'generating', actions: assign({ final_context: (_, e) => e.data.final_context }) },
      },
    },
    generating: {
      invoke: {
        src: async (ctx) => {
          const { answer, confidence } = await llm.generate({
            context: ctx.final_context,
            query: ctx.query,
          })
          return { answer, confidence }
        },
        onDone: { target: 'evaluating', actions: assign({ answer: (_, e) => e.data.answer, confidence: (_, e) => e.data.confidence }) },
      },
    },
    evaluating: {
      ${config.enableInterrupt ? `
      entry: ['checkpoint', 'emitForHumanReview'],  // 保存 + 可能中断
      ` : ''}
      invoke: {
        src: async (ctx) => {
          if (ctx.confidence > 0.85 || ctx.depth >= ${config.maxDepth}) return { decision: 'finalize' }
          if (ctx.confidence < 0.5) return { decision: 'escalate' }
          return { decision: 'continue' }
        },
        onDone: [
          { target: 'decomposing', guard: (ctx: any, e: any) => e.data.decision === 'continue', actions: assign({ decision: (_, e) => e.data.decision }) },
          { target: 'finalized', guard: (ctx: any, e: any) => e.data.decision === 'finalize', actions: assign({ decision: (_, e) => e.data.decision }) },
          { target: 'escalated', guard: (ctx: any, e: any) => e.data.decision === 'escalate', actions: assign({ decision: (_, e) => e.data.decision }) },
        ],
      },
      on: {
        RESUME: { target: 'generating', actions: assign({ human_feedback: (_, e) => e.feedback }) },
      },
    },
    finalized: { type: 'final' },
    escalated: { type: 'final' },
  },
})

// ==================== 4. 启动 ====================
const service = interpret(agentMachine)
  .onTransition((state) => {
    console.log('[Agent]', state.value, state.context)
    ${config.enableCheckpoint ? `
    checkpointService.save('thread-1', state.context, state.context.depth)
    ` : ''}
  })
  .start()

// 触发查询
service.send({ type: 'START', query: '什么是 RAG？' })
`
  }

  const Checkbox = ({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) => (
    <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer' }}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  )

  const NumberInput = ({ label, value, onChange, min, max, step = 1 }: any) => (
    <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
      {label}
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ width: 60, padding: '4px 8px', borderRadius: 6, border: '1px solid #d1d5db' }}
      />
    </label>
  )

  return (
    <div style={{ marginBottom: 40 }}>
      <div
        style={{
          background: '#fff',
          borderRadius: 12,
          border: '1px solid #e5e7eb',
          padding: 24,
          marginBottom: 16,
        }}
      >
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: 16,
          }}
        >
          <div>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 10, color: '#1f2937' }}>架构选项</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <Checkbox label="启用 Checkpoint" checked={config.enableCheckpoint} onChange={(v) => setConfig({ ...config, enableCheckpoint: v })} />
              {config.enableCheckpoint && (
                <select
                  value={config.checkpointStore}
                  onChange={(e) => setConfig({ ...config, checkpointStore: e.target.value as any })}
                  style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #d1d5db', fontSize: 13 }}
                >
                  <option value="redis">Redis</option>
                  <option value="postgres">PostgreSQL</option>
                  <option value="memory">Memory（仅开发）</option>
                </select>
              )}
              <Checkbox label="启用 Human-in-loop" checked={config.enableInterrupt} onChange={(v) => setConfig({ ...config, enableInterrupt: v })} />
              <label style={{ fontSize: 13 }}>
                合并策略
                <select
                  value={config.mergeStrategy}
                  onChange={(e) => setConfig({ ...config, mergeStrategy: e.target.value as any })}
                  style={{ marginLeft: 8, padding: '4px 8px', borderRadius: 6, border: '1px solid #d1d5db' }}
                >
                  <option value="reducer">Reducer（推荐）</option>
                  <option value="lastWriteWins">LastWriteWins</option>
                </select>
              </label>
              <NumberInput label="最大递归深度" value={config.maxDepth} onChange={(v: number) => setConfig({ ...config, maxDepth: v })} min={1} max={20} />
            </div>
          </div>

          <div>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 10, color: '#1f2937' }}>召回配置</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <NumberInput label="向量召回 Top-K" value={config.vectorTopK} onChange={(v: number) => setConfig({ ...config, vectorTopK: v })} min={1} max={100} />
              <NumberInput label="关键词召回 Top-K" value={config.keywordTopK} onChange={(v: number) => setConfig({ ...config, keywordTopK: v })} min={1} max={100} />
              <NumberInput label="图谱召回 Top-K" value={config.graphTopK} onChange={(v: number) => setConfig({ ...config, graphTopK: v })} min={1} max={100} />
            </div>
          </div>

          <div>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 10, color: '#1f2937' }}>精排与融合</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <Checkbox label="启用精排" checked={config.enableRerank} onChange={(v) => setConfig({ ...config, enableRerank: v })} />
              <Checkbox label="启用分数融合" checked={config.enableFusion} onChange={(v) => setConfig({ ...config, enableFusion: v })} />
              {config.enableFusion && (
                <>
                  <NumberInput label="精排权重" value={config.rerankWeight} onChange={(v: number) => setConfig({ ...config, rerankWeight: v })} min={0} max={1} step={0.05} />
                  <NumberInput label="向量权重" value={config.vectorWeight} onChange={(v: number) => setConfig({ ...config, vectorWeight: v })} min={0} max={1} step={0.05} />
                  <NumberInput label="关键词权重" value={config.keywordWeight} onChange={(v: number) => setConfig({ ...config, keywordWeight: v })} min={0} max={1} step={0.05} />
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 10, marginBottom: 12, justifyContent: 'flex-end' }}>
        <button
          onClick={() => {
            navigator.clipboard.writeText(generateCode())
            alert('代码已复制到剪贴板')
          }}
          style={{
            padding: '8px 16px',
            borderRadius: 8,
            border: '1px solid #d1d5db',
            background: '#fff',
            fontSize: 13,
            cursor: 'pointer',
            color: '#374151',
          }}
        >
          📋 复制代码
        </button>
        <button
          onClick={() => {
            const blob = new Blob([generateCode()], { type: 'text/typescript' })
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = 'rag-agent-machine.ts'
            a.click()
            URL.revokeObjectURL(url)
          }}
          style={{
            padding: '8px 16px',
            borderRadius: 8,
            border: 'none',
            background: '#4f46e5',
            color: '#fff',
            fontSize: 13,
            cursor: 'pointer',
            fontWeight: 500,
          }}
        >
          ⬇️ 下载 .ts 文件
        </button>
      </div>
      <CodeBlock>{generateCode()}</CodeBlock>
    </div>
  )
}
