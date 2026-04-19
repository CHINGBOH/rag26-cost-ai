import React, { useState, useEffect } from 'react'
import { getTheme, toggleTheme } from '../../config/theme'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, BarChart, Bar, Legend,
} from 'recharts'

/* ===================================================================
   Agent Runtime 深度调研 —— 村头办事处版（基于 Gemini.md 对话整理）
   用「村头办事处」模型讲清楚 Channel / Checkpoint / Reducer / RAG
   =================================================================== */

const CodeBlock: React.FC<{ children: string }> = ({ children }) => (
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

const Card: React.FC<{ title: string; children: React.ReactNode; color?: string; icon?: string }> = ({
  title,
  children,
  color = '#4f46e5',
  icon = '📦',
}) => (
  <div
    style={{
      background: 'var(--bg-elevated)',
      borderRadius: 12,
      border: '1px solid var(--border-default)',
      padding: 20,
      boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
    }}
  >
    <h3 style={{ fontSize: 17, fontWeight: 600, marginBottom: 12, color, display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ fontSize: 20 }}>{icon}</span>
      {title}
    </h3>
    <div style={{ fontSize: 14, lineHeight: 1.7, color: 'var(--text-secondary)' }}>{children}</div>
  </div>
)

const SectionTitle: React.FC<{ children: React.ReactNode; subtitle?: string }> = ({
  children,
  subtitle,
}) => (
  <div style={{ marginBottom: 24, marginTop: 48 }}>
    <h2
      style={{
        fontSize: 26,
        fontWeight: 700,
        color: 'var(--text-primary)',
        marginBottom: subtitle ? 8 : 0,
        borderLeft: '4px solid #f59e0b',
        paddingLeft: 12,
      }}
    >
      {children}
    </h2>
    {subtitle && <p style={{ fontSize: 15, color: 'var(--text-muted)', margin: 0 }}>{subtitle}</p>}
  </div>
)

const Alert: React.FC<{ type: 'danger' | 'warning' | 'tip'; children: React.ReactNode }> = ({
  type,
  children,
}) => {
  const colors = {
    danger: { bg: '#fef2f2', border: '#ef4444', text: '#991b1b' },
    warning: { bg: '#fffbeb', border: '#f59e0b', text: '#92400e' },
    tip: { bg: '#ecfdf5', border: '#10b981', text: '#065f46' },
  }
  const c = colors[type]
  return (
    <div
      style={{
        background: c.bg + '30',
        borderLeft: `4px solid ${c.border}`,
        padding: '12px 16px',
        borderRadius: 8,
        margin: '12px 0',
        fontSize: 14,
        color: c.text,
      }}
    >
      {children}
    </div>
  )
}

// ===================== 动态演示：村头办事处 =====================

function VillageOfficeDemo() {
  const [step, setStep] = useState(0)

  const steps = [
    {
      title: '村民进门办事',
      desc: '王大爷走进村头办事处，说："我要给娃办入学！"',
      action: '值班员在大黑板上写下：【任务：办入学。版本：1.0】',
      visual: (
        <div style={{ textAlign: 'center', padding: 20 }}>
          <div style={{ fontSize: 48, marginBottom: 8 }}>👴</div>
          <div style={{ background: '#dbeafe', padding: '10px 16px', borderRadius: 12, display: 'inline-block', color: '#1e40af', fontWeight: 600 }}>
            "我要给娃办入学！"
          </div>
        </div>
      ),
      board: [
        { line: '【任务：办入学】', fresh: true },
        { line: '【状态：待处理】', fresh: true },
        { line: '【版本：1.0】', fresh: true },
        { line: '——————————————', fresh: false },
        { line: '（空白）', fresh: false },
      ],
      who: '值班员（Runtime）',
    },
    {
      title: '摇铃喊村长',
      desc: '值班员一看黑板有新字，摇铃！村长过来瞅一眼',
      action: 'Runtime 检测到 Channel 变化 → 唤醒 LLM 决策',
      visual: (
        <div style={{ textAlign: 'center', padding: 20 }}>
          <div style={{ fontSize: 48, marginBottom: 8 }}>🔔</div>
          <div style={{ background: '#fef3c7', padding: '10px 16px', borderRadius: 12, display: 'inline-block', color: '#92400e', fontWeight: 600 }}>
            "黑板有新字了！村长来看！"
          </div>
        </div>
      ),
      board: [
        { line: '【任务：办入学】', fresh: false },
        { line: '【状态：待处理】', fresh: false },
        { line: '【版本：1.0】', fresh: false },
        { line: '——————————————', fresh: false },
        { line: '（空白）', fresh: false },
      ],
      who: '值班员（Runtime）',
    },
    {
      title: '村长出主意',
      desc: '村长见多识广，看了黑板说："先让会计查社保交够没"',
      action: 'LLM 分析 Channel → 输出 Thought + Action',
      visual: (
        <div style={{ textAlign: 'center', padding: 20 }}>
          <div style={{ fontSize: 48, marginBottom: 8 }}>👨‍💼</div>
          <div style={{ background: '#fce7f3', padding: '10px 16px', borderRadius: 12, display: 'inline-block', color: '#9d174d', fontWeight: 600 }}>
            🧠 "先查社保！"
          </div>
        </div>
      ),
      board: [
        { line: '【任务：办入学】', fresh: false },
        { line: '【状态：待处理】', fresh: false },
        { line: '【版本：1.0】', fresh: false },
        { line: '——————————————', fresh: false },
        { line: '【村长指令：查社保】', fresh: true },
      ],
      who: '村长（LLM）',
    },
    {
      title: '派活给会计',
      desc: '值班员去隔壁喊会计来查账',
      action: 'Runtime 根据 LLM 决策 → 调用 Tool（会计）',
      visual: (
        <div style={{ textAlign: 'center', padding: 20 }}>
          <div style={{ fontSize: 48, marginBottom: 8 }}>🏃‍♂️</div>
          <div style={{ background: '#d1fae5', padding: '10px 16px', borderRadius: 12, display: 'inline-block', color: '#065f46', fontWeight: 600 }}>
            "会计！查一下王家的社保！"
          </div>
        </div>
      ),
      board: [
        { line: '【任务：办入学】', fresh: false },
        { line: '【状态：查社保中...】', fresh: true },
        { line: '【版本：1.0】', fresh: false },
        { line: '——————————————', fresh: false },
        { line: '【村长指令：查社保】', fresh: false },
      ],
      who: '值班员（Runtime）',
    },
    {
      title: '会计写回黑板',
      desc: '会计查完账，在黑板上写：【社保交够了】',
      action: 'Tool 返回结果 → 写入 Channel → 版本自动 +1',
      visual: (
        <div style={{ textAlign: 'center', padding: 20 }}>
          <div style={{ fontSize: 48, marginBottom: 8 }}>📝</div>
          <div style={{ background: '#dbeafe', padding: '10px 16px', borderRadius: 12, display: 'inline-block', color: '#1e40af', fontWeight: 600 }}>
            【会计回复：社保交够了 ✅】
          </div>
        </div>
      ),
      board: [
        { line: '【任务：办入学】', fresh: false },
        { line: '【状态：查社保中...】', fresh: false },
        { line: '【版本：2.0】 ⬆️', fresh: true },
        { line: '——————————————', fresh: false },
        { line: '【会计回复：社保交够了】', fresh: true },
      ],
      who: '会计（Tool）',
    },
    {
      title: '再喊村长',
      desc: '值班员又摇铃："黑板又更新了！"村长再看',
      action: 'Runtime 再次检测版本变化 → 唤醒 LLM',
      visual: (
        <div style={{ textAlign: 'center', padding: 20 }}>
          <div style={{ fontSize: 48, marginBottom: 8 }}>🔔🔔</div>
          <div style={{ background: '#fef3c7', padding: '10px 16px', borderRadius: 12, display: 'inline-block', color: '#92400e', fontWeight: 600 }}>
            "版本变了（1.0→2.0）！村长再看！"
          </div>
        </div>
      ),
      board: [
        { line: '【任务：办入学】', fresh: false },
        { line: '【状态：待下一步】', fresh: true },
        { line: '【版本：2.0】', fresh: false },
        { line: '——————————————', fresh: false },
        { line: '【会计回复：社保交够了】', fresh: false },
      ],
      who: '值班员（Runtime）',
    },
    {
      title: '村长结案',
      desc: '村长看社保够了，写下："可以去开入学证明了！"',
      action: 'LLM 判断任务完成 → 输出 FINAL_ANSWER',
      visual: (
        <div style={{ textAlign: 'center', padding: 20 }}>
          <div style={{ fontSize: 48, marginBottom: 8 }}>✅</div>
          <div style={{ background: '#d1fae5', padding: '10px 16px', borderRadius: 12, display: 'inline-block', color: '#065f46', fontWeight: 600 }}>
            【村长指令：开入学证明，结案！】
          </div>
        </div>
      ),
      board: [
        { line: '【任务：办入学】', fresh: false },
        { line: '【状态：已结案 ✅】', fresh: true },
        { line: '【版本：3.0】 ⬆️', fresh: true },
        { line: '——————————————', fresh: false },
        { line: '【村长指令：开入学证明】', fresh: true },
      ],
      who: '村长（LLM）',
    },
  ]

  const s = steps[step]

  return (
    <div
      style={{
        background: 'var(--bg-elevated)',
        borderRadius: 12,
        border: '1px solid var(--border-default)',
        padding: 24,
        marginBottom: 32,
      }}
    >
      <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
        {steps.map((_, i) => (
          <button
            key={i}
            onClick={() => setStep(i)}
            style={{
              padding: '6px 10px',
              borderRadius: 20,
              border: 'none',
              fontSize: 11,
              fontWeight: 600,
              cursor: 'pointer',
              background: step === i ? '#f59e0b' : step > i ? '#10b981' : 'var(--bg-hover)',
              color: step === i || step > i ? '#fff' : 'var(--text-muted)',
            }}
          >
            {step > i ? '✓' : ''} {i + 1}
          </button>
        ))}
      </div>

      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 4 }}>{s.title}</div>
        <div style={{ fontSize: 14, color: 'var(--text-secondary)', marginBottom: 6 }}>{s.desc}</div>
        <div style={{ fontSize: 12, color: '#f59e0b', fontWeight: 500 }}>🔧 {s.action}</div>
      </div>

      {s.visual}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 16,
          marginTop: 20,
        }}
      >
        {/* 大黑板 */}
        <div
          style={{
            background: '#1f2937',
            borderRadius: 10,
            padding: 16,
            border: '2px solid #334155',
          }}
        >
          <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 10, textAlign: 'center' }}>
            📋 大黑板（Channel）
          </div>
          {s.board.map((line, i) => (
            <div
              key={i}
              style={{
                fontSize: 13,
                fontFamily: 'monospace',
                color: line.fresh ? '#fbbf24' : '#64748b',
                marginBottom: 4,
                transition: 'color 0.3s',
              }}
            >
              {line.fresh ? '▶ ' : '  '}{line.line}
            </div>
          ))}
        </div>

        {/* 角色说明 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div
            style={{
              background: s.who.includes('值班员') ? '#dbeafe' : s.who.includes('村长') ? '#fce7f3' : '#d1fae5',
              padding: 12,
              borderRadius: 8,
              fontSize: 13,
              color: s.who.includes('值班员') ? '#1e40af' : s.who.includes('村长') ? '#9d174d' : '#065f46',
            }}
          >
            <div style={{ fontWeight: 700, marginBottom: 4 }}>当前行动者</div>
            <div>{s.who}</div>
          </div>
          <div style={{ background: 'var(--bg-hover)', padding: 12, borderRadius: 8, fontSize: 12, color: 'var(--text-muted)' }}>
            <div style={{ fontWeight: 600, marginBottom: 4, color: 'var(--text-secondary)' }}>技术映射</div>
            {s.who.includes('值班员') && 'Runtime：监控 Channel 变化，调度节点执行'}
            {s.who.includes('村长') && 'LLM：读取 Channel，输出决策（Thought + Action）'}
            {s.who.includes('会计') && 'Tool：执行外部操作，返回结果写入 Channel'}
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 20 }}>
        <button
          onClick={() => setStep(Math.max(0, step - 1))}
          disabled={step === 0}
          style={{
            padding: '8px 16px',
            borderRadius: 8,
            border: '1px solid var(--border-default)',
            background: 'var(--bg-elevated)',
            color: step === 0 ? 'var(--text-muted)' : 'var(--text-primary)',
            cursor: step === 0 ? 'not-allowed' : 'pointer',
            fontSize: 13,
          }}
        >
          ← 上一步
        </button>
        <button
          onClick={() => setStep(Math.min(steps.length - 1, step + 1))}
          disabled={step === steps.length - 1}
          style={{
            padding: '8px 16px',
            borderRadius: 8,
            border: 'none',
            background: step === steps.length - 1 ? 'var(--bg-hover)' : '#4f46e5',
            color: step === steps.length - 1 ? 'var(--text-muted)' : '#fff',
            cursor: step === steps.length - 1 ? 'not-allowed' : 'pointer',
            fontSize: 13,
            fontWeight: 500,
          }}
        >
          {step === steps.length - 1 ? '已结案 ✅' : '下一步 →'}
        </button>
      </div>
    </div>
  )
}

// ===================== 主页面 =====================

export default function AgentRuntimeFolk() {
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

  // ===================== 全局共享状态：沙箱 ↔ 监控面板联动 =====================
  const [segments, setSegments] = useState([
    { id: 'seg-001', collection: 'documents', status: 'green', docs: 124000, size: '1.2GB', sizeBytes: 1.2, progress: 100, quantized: true },
    { id: 'seg-002', collection: 'documents', status: 'merging', docs: 98000, size: '0.9GB', sizeBytes: 0.9, progress: 67, quantized: true },
    { id: 'seg-003', collection: 'documents', status: 'green', docs: 156000, size: '1.5GB', sizeBytes: 1.5, progress: 100, quantized: true },
    { id: 'seg-004', collection: 'images', status: 'yellow', docs: 45000, size: '2.1GB', sizeBytes: 2.1, progress: 92, quantized: false },
    { id: 'seg-005', collection: 'images', status: 'green', docs: 62000, size: '1.8GB', sizeBytes: 1.8, progress: 100, quantized: false },
  ])
  const [quantization, setQuantization] = useState<'FP32' | 'INT8' | 'Binary'>('INT8')
  const [memoryPercent, setMemoryPercent] = useState(72)
  const [searchLatency, setSearchLatency] = useState(45)
  const [alerts, setAlerts] = useState<Array<{ id: number; time: string; level: 'info' | 'warning' | 'critical'; message: string }>>([
    { id: 1, time: '10:23', level: 'info', message: 'Segment seg-002 开始合并' },
    { id: 2, time: '10:25', level: 'warning', message: 'seg-004 文档数超过阈值 (45k/40k)' },
  ])
  const [totalDocs] = useState(485000)
  const [iopsHistory, setIopsHistory] = useState([
    { time: '00:00', read: 120, write: 45 },
    { time: '04:00', read: 80, write: 200 },
    { time: '08:00', read: 340, write: 120 },
    { time: '12:00', read: 560, write: 180 },
    { time: '16:00', read: 480, write: 90 },
    { time: '20:00', read: 210, write: 60 },
    { time: '23:59', read: 150, write: 40 },
  ])
  const [hotCold] = useState([
    { name: '热数据 (内存)', value: 20, color: '#f59e0b' },
    { name: '温数据 (SSD)', value: 45, color: '#4f46e5' },
    { name: '冷数据 (磁盘)', value: 35, color: '#06b6d4' },
  ])
  const alertIdRef = React.useRef(3)

  const addAlert = (level: 'info' | 'warning' | 'critical', message: string) => {
    const now = new Date()
    const time = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
    const id = alertIdRef.current++
    setAlerts((prev) => [{ id, time, level, message }, ...prev].slice(0, 50))
  }

  // ===================== 交互式 Python 沙箱（增强版：诊断挑战 + qdrant_client 模拟）=====================
  const InteractivePythonSandbox: React.FC = () => {
    const [code, setCode] = useState('# 试试在「村头办事处」里跑段 Python\nprint("王大爷的入学材料整理完毕！")\nprint(f"共处理 {3+2} 份文件")')
    const [output, setOutput] = useState('')
    const [isRunning, setIsRunning] = useState(false)
    const [execTime, setExecTime] = useState(0)
    const [memUsed, setMemUsed] = useState(0)
    const [mode, setMode] = useState<'free' | 'challenge'>('free')
    const [challengeIndex, setChallengeIndex] = useState(0)
    const [challengeSolved, setChallengeSolved] = useState<boolean[]>([false, false, false, false])

    const challenges = [
      {
        title: '🔥 挑战一：检索延迟飙升',
        scenario: '用户投诉检索从 45ms 变成 900ms。查看监控发现 seg-002 正在合并，且内存占用 95%。\n请用 Python 诊断并给出优化建议。',
        hint: '试试 print(segments) 查看状态，或者计算内存占用率',
        check: (out: string) => out.includes('合并') || out.includes('内存') || out.includes('INT8') || out.includes('量化'),
        solution: 'Segment 合并期间 IOPS 飙升导致延迟增加。建议：1) 避开高峰期合并 2) 启用 INT8 量化降低内存 3) 增加 shard 数量',
      },
      {
        title: '🔥 挑战二：冷数据过多',
        scenario: '分析发现 80% 的数据 30 天内没被访问过，但全部驻留在内存中。内存即将耗尽。\n请用 Python 分析冷热分布并给出迁移方案。',
        hint: '计算冷热比例，考虑 on_disk=True 配置',
        check: (out: string) => out.includes('冷') || out.includes('磁盘') || out.includes('on_disk') || out.includes('迁移'),
        solution: '80% 冷数据应迁移到磁盘集合。建议：1) 冷数据设置 on_disk=True 2) 热数据保留内存索引 3) 按访问频率自动分级',
      },
      {
        title: '🔥 挑战三：向量维度升级',
        scenario: '业务需要从 768 维升级到 1536 维。当前 1TB 数据全部使用旧维度。\n请估算重新索引的时间和资源成本。',
        hint: '数据量 × 新维度 × 4字节 = ? 每天能处理多少？',
        check: (out: string) => out.includes('维') || out.includes('索引') || out.includes('天') || out.includes('TB'),
        solution: '1TB FP32 768维 → 1536维 约需 2TB 空间。重新 Embedding 速度约 1000 docs/s，485k 文档约需 8 分钟 × 批次数。实际需数天（含网络、验证）。务必先备份！',
      },
      {
        title: '🔥 挑战四：批量导入 OOM',
        scenario: '一次性导入 100 万条向量时进程被 Killed。当前 batch_size=10000。\n请用 Python 计算合理的 batch_size 和内存预算。',
        hint: '每条 1536 维 FP32 = 6KB。batch_size × 6KB + 索引开销 = ?',
        check: (out: string) => out.includes('batch') || out.includes('OOM') || out.includes('内存') || out.includes('1000'),
        solution: '1536维 FP32 ≈ 6KB/条 + 索引开销 ≈ 10KB/条。100万条约 10GB。建议 batch_size=500-1000，分 1000-2000 批导入，每批间隔 1s 让 GC 回收。',
      },
    ]

    const presets = [
      {
        label: '📊 数据处理',
        code: `# 模拟王大爷的材料分类
files = ["户口本", "房产证", "疫苗本", "出生证明", "照片"]
hot = [f for f in files if "证" in f]  # 热数据：证件类
cold = [f for f in files if f not in hot]  # 冷数据
print(f"热数据: {hot}")
print(f"冷数据: {cold}")
print(f"分类完成，共 {len(files)} 份")`,
      },
      {
        label: '🔍 向量检索模拟',
        code: `# 模拟向量相似度搜索（余弦相似度）
import math

def cosine_sim(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    norm = math.sqrt(sum(x*x for x in a)) * math.sqrt(sum(x*x for x in b))
    return dot / norm

query = [0.1, 0.3, 0.5]
docs = {
    "入学政策": [0.2, 0.4, 0.6],
    "疫苗接种": [0.9, 0.1, 0.0],
    "房产证明": [0.1, 0.1, 0.1],
}

for name, vec in docs.items():
    score = cosine_sim(query, vec)
    print(f"{name}: {score:.3f}")
`,
      },
      {
        label: '📈 统计分析',
        code: `# 统计 7 天内的检索延迟（毫秒）
latencies = [45, 52, 38, 120, 41, 39, 900]  # 第 4 天 merge，第 7 天 OOM
avg = sum(latencies) / len(latencies)
p95 = sorted(latencies)[int(len(latencies)*0.95)]

print(f"平均延迟: {avg:.1f}ms")
print(f"P95 延迟: {p95}ms")
print(f"⚠️ 检测到异常: 第 7 天延迟 {latencies[-1]}ms，疑似 OOM")
`,
      },
      {
        label: '🗃️ Qdrant 诊断',
        code: `# 模拟 Qdrant 生产诊断脚本
print("=== Qdrant 集群诊断 ===")
print(f"总文档数: {485000}")
print(f"当前量化: {quantization}")
print(f"内存占用: {memoryPercent}%")
print(f"搜索延迟: {searchLatency}ms")
print("\nSegment 状态:")
for seg in segments:
    status = "🟢" if seg.status == "green" else "🔵" if seg.status == "merging" else "🟡"
    print(f"  {status} {seg.id}: {seg.docs} docs, {seg.size}, {seg.progress}%")
print("\n建议: 如果内存 > 80% 且延迟 > 100ms，考虑启用 INT8 量化或增加 shard")
`,
      },
      {
        label: '🧪 批量导入计算',
        code: `# 计算批量导入的内存预算
dim = 1536  # 向量维度
bytes_per_float = 4  # FP32
overhead = 1.5  # 索引开销倍数
doc_size_kb = dim * bytes_per_float / 1024 * overhead

batch_size = 1000
total_docs = 1_000_000
batches = total_docs // batch_size
memory_per_batch_mb = batch_size * doc_size_kb / 1024

print(f"单条向量: {doc_size_kb:.1f} KB")
print(f"每批内存: {memory_per_batch_mb:.1f} MB")
print(f"总批次数: {batches}")
print(f"建议: batch_size={batch_size}, 批次间隔 1s")
print(f"预估总时间: {batches // 60} 分钟（1000 docs/s）")
`,
      },
    ]

    const runCode = () => {
      setIsRunning(true)
      setOutput('')
      const start = performance.now()
      setTimeout(() => {
        const raw = code.trim()
        const lines: string[] = []
        let mem = 0

        // 通用 print 模拟
        if (raw.includes('print(')) {
          const prints = raw.match(/print\((.*)\)/g) || []
          prints.forEach((p) => {
            const inner = p.slice(6, -1)
            if (inner.startsWith('f"') || inner.startsWith("f'")) {
              let txt = inner.slice(2, -1)
              txt = txt.replace(/\{([^}]+)\}/g, (_m, expr) => {
                try {
                  // eslint-disable-next-line no-new-func
                  return String(new Function('math', 'files', 'hot', 'cold', 'query', 'docs', 'latencies', 'avg', 'p95', 'segments', 'quantization', 'memoryPercent', 'searchLatency', `return (${expr})`)(Math, [], [], [], [], {}, [], 0, 0, segments, quantization, memoryPercent, searchLatency))
                } catch {
                  return `{${expr}}`
                }
              })
              lines.push(txt)
            } else if (inner.startsWith('"') || inner.startsWith("'")) {
              lines.push(inner.slice(1, -1))
            } else {
              lines.push(inner)
            }
          })
          mem = lines.join('').length * 2 + 1024
        }

        // 向量检索模拟
        if (raw.includes('cosine_sim')) {
          lines.push('入学政策: 0.991')
          lines.push('疫苗接种: 0.378')
          lines.push('房产证明: 0.577')
          mem = 4096
        }

        // 统计分析
        if (raw.includes('latencies')) {
          lines.push('平均延迟: 176.4ms')
          lines.push('P95 延迟: 900ms')
          lines.push('⚠️ 检测到异常: 第 7 天延迟 900ms，疑似 OOM')
          mem = 2048
        }

        // Qdrant 诊断模拟
        if (raw.includes('Qdrant') || raw.includes('segment') || raw.includes(' Segment ')) {
          lines.push('=== Qdrant 集群诊断 ===')
          lines.push(`总文档数: ${totalDocs.toLocaleString()}`)
          lines.push(`当前量化: ${quantization}`)
          lines.push(`内存占用: ${memoryPercent}%`)
          lines.push(`搜索延迟: ${searchLatency}ms`)
          lines.push('')
          lines.push('Segment 状态:')
          segments.forEach((seg) => {
            const st = seg.status === 'green' ? '🟢' : seg.status === 'merging' ? '🔵' : '🟡'
            lines.push(`  ${st} ${seg.id}: ${seg.docs.toLocaleString()} docs, ${seg.size}, ${seg.progress}%`)
          })
          mem = 8192
        }

        // 批量导入计算
        if (raw.includes('batch_size') || raw.includes('memory_per_batch')) {
          lines.push('单条向量: 9.0 KB')
          lines.push('每批内存: 8.8 MB')
          lines.push('总批次数: 1000')
          lines.push('建议: batch_size=1000, 批次间隔 1s')
          lines.push('预估总时间: 16 分钟（1000 docs/s）')
          mem = 2048
        }

        if (lines.length === 0) {
          lines.push('>>> 代码执行完成（无输出）')
          lines.push('💡 提示：用 print() 把结果打出来，王大爷才能看见')
        }

        const out = lines.join('\n')
        setOutput(out)
        setExecTime(Number((performance.now() - start).toFixed(1)))
        setMemUsed(mem || 512)
        setIsRunning(false)

        // 诊断挑战检查
        if (mode === 'challenge') {
          const ch = challenges[challengeIndex]
          if (ch.check(out)) {
            setChallengeSolved((prev) => {
              const next = [...prev]
              next[challengeIndex] = true
              return next
            })
          }
        }
      }, 600 + Math.random() * 400)
    }

    return (
      <div>
        {/* 模式切换 */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          <button
            onClick={() => setMode('free')}
            style={{
              padding: '6px 16px', borderRadius: 8, border: '1px solid var(--border-default)',
              background: mode === 'free' ? '#4f46e5' : 'var(--bg-surface)',
              color: mode === 'free' ? '#fff' : 'var(--text-secondary)',
              fontSize: 13, cursor: 'pointer', fontWeight: 600,
            }}
          >
            🧪 自由模式
          </button>
          <button
            onClick={() => setMode('challenge')}
            style={{
              padding: '6px 16px', borderRadius: 8, border: '1px solid var(--border-default)',
              background: mode === 'challenge' ? '#ef4444' : 'var(--bg-surface)',
              color: mode === 'challenge' ? '#fff' : 'var(--text-secondary)',
              fontSize: 13, cursor: 'pointer', fontWeight: 600,
            }}
          >
            🔥 诊断挑战 ({challengeSolved.filter(Boolean).length}/{challenges.length})
          </button>
        </div>

        {mode === 'challenge' ? (
          <div style={{ background: 'var(--bg-elevated)', borderRadius: 12, border: '1px solid var(--border-default)', padding: 20, marginBottom: 16 }}>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
              {challenges.map((_c, i) => (
                <button
                  key={i}
                  onClick={() => { setChallengeIndex(i); setOutput('') }}
                  style={{
                    padding: '6px 12px', borderRadius: 6, border: '1px solid var(--border-default)',
                    background: challengeIndex === i ? '#ef4444' : challengeSolved[i] ? '#10b981' : 'var(--bg-surface)',
                    color: challengeIndex === i || challengeSolved[i] ? '#fff' : 'var(--text-secondary)',
                    fontSize: 12, cursor: 'pointer', fontWeight: 600,
                  }}
                >
                  {challengeSolved[i] ? '✅' : '🔒'} 挑战 {i + 1}
                </button>
              ))}
            </div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#ef4444', marginBottom: 8 }}>
              {challenges[challengeIndex].title}
            </div>
            <pre style={{ background: '#1e1e2e', color: '#cdd6f4', padding: 12, borderRadius: 8, fontSize: 13, lineHeight: 1.6, margin: '0 0 12px 0', whiteSpace: 'pre-wrap', fontFamily: 'ui-monospace, monospace' }}>
              {challenges[challengeIndex].scenario}
            </pre>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>
              💡 提示：{challenges[challengeIndex].hint}
            </div>
            {challengeSolved[challengeIndex] && (
              <div style={{ background: 'rgba(16, 185, 129, 0.1)', border: '1px solid #10b981', borderRadius: 8, padding: 12, fontSize: 13, color: '#10b981', lineHeight: 1.6 }}>
                <strong>🎉 挑战完成！</strong><br/>{challenges[challengeIndex].solution}
              </div>
            )}
          </div>
        ) : null}

        <div style={{ background: 'var(--bg-elevated)', borderRadius: 12, border: '1px solid var(--border-default)', padding: 20 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
            {presets.map((p) => (
              <button
                key={p.label}
                onClick={() => setCode(p.code)}
                style={{
                  padding: '6px 12px', borderRadius: 6, border: '1px solid var(--border-default)',
                  background: 'var(--bg-surface)', color: 'var(--text-secondary)', fontSize: 12, cursor: 'pointer',
                }}
              >
                {p.label}
              </button>
            ))}
          </div>
          <textarea
            value={code}
            onChange={(e) => setCode(e.target.value)}
            rows={mode === 'challenge' ? 10 : 8}
            style={{
              width: '100%', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
              fontSize: 13, lineHeight: 1.6, padding: 12, borderRadius: 8,
              border: '1px solid var(--border-default)', background: '#1e1e2e', color: '#cdd6f4',
              resize: 'vertical', boxSizing: 'border-box',
            }}
          />
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 12, flexWrap: 'wrap' }}>
            <button
              onClick={runCode}
              disabled={isRunning}
              style={{
                padding: '8px 20px', borderRadius: 8, border: 'none', background: mode === 'challenge' ? '#ef4444' : '#4f46e5', color: '#fff',
                fontSize: 14, fontWeight: 600, cursor: isRunning ? 'not-allowed' : 'pointer', opacity: isRunning ? 0.7 : 1,
              }}
            >
              {isRunning ? '⏳ 执行中...' : mode === 'challenge' ? '▶ 提交诊断' : '▶ 运行代码'}
            </button>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              {mode === 'challenge' ? '🔥 诊断正确即可解锁下一关' : '✅ 纯前端模拟，不会真执行代码'}
            </span>
          </div>
          {(output || isRunning) && (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6, display: 'flex', justifyContent: 'space-between' }}>
                <span>🖥️ 输出</span>
                {execTime > 0 && <span>⏱ {execTime}ms · 🧠 {memUsed}KB</span>}
              </div>
              <pre
                style={{
                  background: '#0f0f1a', color: '#a6e3a1', padding: 14, borderRadius: 8, fontSize: 13,
                  lineHeight: 1.6, overflowX: 'auto', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
                  minHeight: 60, margin: 0,
                }}
              >
                {isRunning ? '正在模拟执行...' : output}
              </pre>
            </div>
          )}
        </div>
      </div>
    )
  }

  // ===================== Qdrant 1TB 监控面板（增强版：运维操作 + 故障注入 + 告警流）=====================
  const QdrantMonitor: React.FC = () => {
    const [tick, setTick] = useState(0)
    const [selectedSeg, setSelectedSeg] = useState<string | null>(null)
    const [injecting, setInjecting] = useState<string | null>(null)

    useEffect(() => {
      const timer = setInterval(() => {
        setTick((t) => t + 1)
        setSegments((prev) =>
          prev.map((s) => {
            if (s.status === 'merging') {
              const next = Math.min(100, s.progress + Math.random() * 4)
              const done = next >= 100
              if (done && s.progress < 100) {
                addAlert('info', `Segment ${s.id} 合并完成`)
              }
              return { ...s, progress: Number(next.toFixed(1)), status: done ? 'green' : 'merging' }
            }
            return s
          })
        )
      }, 1500)
      return () => clearInterval(timer)
    }, [])

    const triggerMerge = () => {
      setSegments((prev) => {
        const yellow = prev.find((s) => s.status === 'yellow')
        if (yellow) {
          addAlert('warning', `手动触发 Segment ${yellow.id} 合并`)
          return prev.map((s) => s.id === yellow.id ? { ...s, status: 'merging' as const, progress: 10 } : s)
        }
        const green = prev.find((s) => s.status === 'green' && s.docs > 100000)
        if (green) {
          addAlert('warning', `手动触发 Segment ${green.id} 合并`)
          return prev.map((s) => s.id === green.id ? { ...s, status: 'merging' as const, progress: 10 } : s)
        }
        addAlert('info', '没有需要合并的 Segment')
        return prev
      })
    }

    const switchQuantization = (q: 'FP32' | 'INT8' | 'Binary') => {
      setQuantization(q)
      const ratios = { FP32: 100, INT8: 25, Binary: 3.1 }
      const mems = { FP32: 92, INT8: 72, Binary: 45 }
      setMemoryPercent(mems[q])
      addAlert('info', `切换量化策略为 ${q}，内存占用 ${mems[q]}%，压缩比 ${ratios[q]}%`)
    }

    const expandShard = () => {
      const newId = `seg-${String(segments.length + 1).padStart(3, '0')}`
      setSegments((prev) => [...prev, {
        id: newId, collection: 'documents', status: 'green',
        docs: 0, size: '0GB', sizeBytes: 0, progress: 100, quantized: true,
      }])
      addAlert('info', `扩容 Shard：新增 ${newId}`)
    }

    const injectOOM = () => {
      setInjecting('oom')
      addAlert('critical', '🚨 模拟 OOM：内存瞬间飙升至 98%！')
      setMemoryPercent(98)
      setSearchLatency(850)
      setTimeout(() => {
        addAlert('critical', '进程被系统 OOM Killer 终止！服务重启中...')
        setTimeout(() => {
          setMemoryPercent(72)
          setSearchLatency(45)
          setInjecting(null)
          addAlert('info', '服务已恢复，内存回到 72%')
        }, 2000)
      }, 1500)
    }

    const injectDiskFull = () => {
      setInjecting('disk')
      addAlert('critical', '🚨 模拟磁盘满：写入 IOPS 降为 0！')
      setIopsHistory((prev) => prev.map((d, i) => i === prev.length - 1 ? { ...d, write: 0 } : d))
      setTimeout(() => {
        addAlert('warning', 'Segment 合并失败：磁盘空间不足')
        setTimeout(() => {
          setIopsHistory((prev) => prev.map((d, i) => i === prev.length - 1 ? { ...d, write: 40 } : d))
          setInjecting(null)
          addAlert('info', '磁盘清理完成，写入恢复')
        }, 2000)
      }, 1500)
    }

    const injectLatency = () => {
      setInjecting('latency')
      addAlert('warning', '模拟网络抖动：搜索延迟波动 200-800ms')
      setSearchLatency(520)
      setTimeout(() => {
        setSearchLatency(45)
        setInjecting(null)
        addAlert('info', '网络恢复，延迟回到正常')
      }, 3000)
    }

    const clearAlerts = () => setAlerts([])

    const memoryData = [
      { name: '向量索引', value: Math.round(memoryPercent * 0.58), fill: '#4f46e5' },
      { name: 'Payload', value: Math.round(memoryPercent * 0.25), fill: '#10b981' },
      { name: '系统缓存', value: Math.round(memoryPercent * 0.17), fill: '#f59e0b' },
      { name: '空闲', value: 100 - memoryPercent, fill: 'var(--border-default)' },
    ]

    const statusColor: Record<string, string> = {
      green: '#10b981',
      yellow: '#f59e0b',
      merging: '#4f46e5',
      red: '#ef4444',
    }

    return (
      <div style={{ display: 'grid', gap: 16 }}>
        {/* 操作按钮栏 + 指标卡 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12 }}>
          <div style={{ background: 'var(--bg-elevated)', borderRadius: 10, border: '1px solid var(--border-default)', padding: 14, textAlign: 'center' }}>
            <div style={{ fontSize: 24, fontWeight: 800, color: memoryPercent > 90 ? '#ef4444' : memoryPercent > 75 ? '#f59e0b' : '#10b981' }}>{memoryPercent}%</div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>🧠 内存占用</div>
          </div>
          <div style={{ background: 'var(--bg-elevated)', borderRadius: 10, border: '1px solid var(--border-default)', padding: 14, textAlign: 'center' }}>
            <div style={{ fontSize: 24, fontWeight: 800, color: searchLatency > 200 ? '#ef4444' : '#4f46e5' }}>{searchLatency}<span style={{ fontSize: 14 }}>ms</span></div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>🔍 搜索延迟</div>
          </div>
          <div style={{ background: 'var(--bg-elevated)', borderRadius: 10, border: '1px solid var(--border-default)', padding: 14, textAlign: 'center' }}>
            <div style={{ fontSize: 24, fontWeight: 800, color: '#4f46e5' }}>{totalDocs.toLocaleString()}</div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>🗂️ 总文档数</div>
          </div>
          <div style={{ background: 'var(--bg-elevated)', borderRadius: 10, border: '1px solid var(--border-default)', padding: 14, textAlign: 'center' }}>
            <div style={{ fontSize: 24, fontWeight: 800, color: '#06b6d4' }}>{quantization}</div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>🗜️ 量化策略</div>
          </div>
        </div>

        {/* 运维操作按钮 */}
        <div style={{ background: 'var(--bg-elevated)', borderRadius: 12, border: '1px solid var(--border-default)', padding: 16 }}>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 10 }}>🎮 运维控制台</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button onClick={triggerMerge} style={{ padding: '6px 12px', borderRadius: 6, border: 'none', background: '#4f46e5', color: '#fff', fontSize: 12, cursor: 'pointer' }}>🧩 触发合并</button>
            <button onClick={() => switchQuantization('INT8')} style={{ padding: '6px 12px', borderRadius: 6, border: '1px solid #f59e0b', background: quantization === 'INT8' ? '#f59e0b' : 'var(--bg-surface)', color: quantization === 'INT8' ? '#fff' : '#f59e0b', fontSize: 12, cursor: 'pointer' }}>INT8</button>
            <button onClick={() => switchQuantization('Binary')} style={{ padding: '6px 12px', borderRadius: 6, border: '1px solid #10b981', background: quantization === 'Binary' ? '#10b981' : 'var(--bg-surface)', color: quantization === 'Binary' ? '#fff' : '#10b981', fontSize: 12, cursor: 'pointer' }}>Binary</button>
            <button onClick={() => switchQuantization('FP32')} style={{ padding: '6px 12px', borderRadius: 6, border: '1px solid #ef4444', background: quantization === 'FP32' ? '#ef4444' : 'var(--bg-surface)', color: quantization === 'FP32' ? '#fff' : '#ef4444', fontSize: 12, cursor: 'pointer' }}>FP32</button>
            <button onClick={expandShard} style={{ padding: '6px 12px', borderRadius: 6, border: 'none', background: '#06b6d4', color: '#fff', fontSize: 12, cursor: 'pointer' }}>➕ 扩容 Shard</button>
            <button onClick={injectOOM} disabled={injecting !== null} style={{ padding: '6px 12px', borderRadius: 6, border: 'none', background: injecting === 'oom' ? '#7f1d1d' : '#ef4444', color: '#fff', fontSize: 12, cursor: injecting ? 'not-allowed' : 'pointer', opacity: injecting ? 0.6 : 1 }}>💥 注入 OOM</button>
            <button onClick={injectDiskFull} disabled={injecting !== null} style={{ padding: '6px 12px', borderRadius: 6, border: 'none', background: injecting === 'disk' ? '#7f1d1d' : '#ef4444', color: '#fff', fontSize: 12, cursor: injecting ? 'not-allowed' : 'pointer', opacity: injecting ? 0.6 : 1 }}>💾 磁盘满</button>
            <button onClick={injectLatency} disabled={injecting !== null} style={{ padding: '6px 12px', borderRadius: 6, border: 'none', background: injecting === 'latency' ? '#7f1d1d' : '#ef4444', color: '#fff', fontSize: 12, cursor: injecting ? 'not-allowed' : 'pointer', opacity: injecting ? 0.6 : 1 }}>📡 网络抖动</button>
          </div>
        </div>

        {/* Segment 合并状态 + 告警流 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
          {/* Segment 表格 */}
          <div style={{ background: 'var(--bg-elevated)', borderRadius: 12, border: '1px solid var(--border-default)', padding: 20 }}>
            <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
              <span>🧩</span> Segment 合并状态
              <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-muted)', fontWeight: 400 }}>⏱ {tick}s</span>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border-default)' }}>
                    <th style={{ padding: '8px 4px' }}>Segment</th>
                    <th style={{ padding: '8px 4px' }}>Collection</th>
                    <th style={{ padding: '8px 4px' }}>状态</th>
                    <th style={{ padding: '8px 4px' }}>文档数</th>
                    <th style={{ padding: '8px 4px', width: 120 }}>进度</th>
                  </tr>
                </thead>
                <tbody>
                  {segments.map((s) => (
                    <tr key={s.id} style={{ borderBottom: '1px solid var(--border-default)', cursor: 'pointer' }} onClick={() => setSelectedSeg(selectedSeg === s.id ? null : s.id)}>
                      <td style={{ padding: '8px 4px', fontFamily: 'monospace' }}>{s.id}</td>
                      <td style={{ padding: '8px 4px' }}>{s.collection}</td>
                      <td style={{ padding: '8px 4px' }}>
                        <span style={{ color: statusColor[s.status] || '#888', fontWeight: 600 }}>
                          {s.status === 'green' ? '🟢' : s.status === 'yellow' ? '🟡' : s.status === 'merging' ? '🔵' : '🔴'}
                        </span>
                      </td>
                      <td style={{ padding: '8px 4px' }}>{s.docs.toLocaleString()}</td>
                      <td style={{ padding: '8px 4px' }}>
                        <div style={{ background: 'var(--bg-surface)', borderRadius: 4, height: 8, overflow: 'hidden' }}>
                          <div style={{ width: `${s.progress}%`, background: statusColor[s.status] || '#888', height: '100%', borderRadius: 4, transition: 'width 0.5s ease' }} />
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{s.progress}%</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {selectedSeg && (
              <div style={{ marginTop: 12, padding: 12, background: 'var(--bg-surface)', borderRadius: 8, fontSize: 12, lineHeight: 1.8 }}>
                <strong>📋 {selectedSeg} 详情</strong><br/>
                {(() => {
                  const s = segments.find((x) => x.id === selectedSeg)
                  if (!s) return null
                  return (
                    <>
                      大小: {s.size} · 量化: {s.quantized ? '✅' : '❌'} ·
                      建议: {s.status === 'yellow' ? '文档数接近上限，建议触发合并' : s.status === 'merging' ? '合并期间避免大量写入' : '状态正常'}
                    </>
                  )
                })()}
              </div>
            )}
          </div>

          {/* 实时告警流 */}
          <div style={{ background: 'var(--bg-elevated)', borderRadius: 12, border: '1px solid var(--border-default)', padding: 20, display: 'flex', flexDirection: 'column', maxHeight: 320 }}>
            <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>🚨 实时告警流</span>
              <button onClick={clearAlerts} style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border-default)', background: 'var(--bg-surface)', color: 'var(--text-muted)', cursor: 'pointer' }}>清空</button>
            </div>
            <div style={{ overflowY: 'auto', flex: 1, fontSize: 12, lineHeight: 1.6 }}>
              {alerts.length === 0 && <div style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 20 }}>暂无告警 🎉</div>}
              {alerts.map((a) => (
                <div key={a.id} style={{ padding: '6px 0', borderBottom: '1px solid var(--border-default)', display: 'flex', gap: 8 }}>
                  <span style={{ color: a.level === 'critical' ? '#ef4444' : a.level === 'warning' ? '#f59e0b' : '#06b6d4', fontWeight: 600, whiteSpace: 'nowrap' }}>{a.time}</span>
                  <span style={{ color: 'var(--text-secondary)' }}>{a.message}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* 图表区 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
          {/* IOPS */}
          <div style={{ background: 'var(--bg-elevated)', borderRadius: 12, border: '1px solid var(--border-default)', padding: 16 }}>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8 }}>📈 磁盘 IOPS（24h）</div>
            <ResponsiveContainer width="100%" height={180}>
              <AreaChart data={iopsHistory}>
                <defs>
                  <linearGradient id="colorRead" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#4f46e5" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#4f46e5" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="colorWrite" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" />
                <XAxis dataKey="time" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
                <YAxis tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
                <Tooltip contentStyle={{ background: 'var(--bg-elevated)', border: '1px solid var(--border-default)', fontSize: 12 }} />
                <Area type="monotone" dataKey="read" stroke="#4f46e5" fill="url(#colorRead)" strokeWidth={2} name="读取" />
                <Area type="monotone" dataKey="write" stroke="#f59e0b" fill="url(#colorWrite)" strokeWidth={2} name="写入" />
                <Legend wrapperStyle={{ fontSize: 12 }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* 内存分布 */}
          <div style={{ background: 'var(--bg-elevated)', borderRadius: 12, border: '1px solid var(--border-default)', padding: 16 }}>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8 }}>🧠 内存使用分布</div>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={memoryData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" />
                <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 11, fill: 'var(--text-muted)' }} unit="%" />
                <YAxis dataKey="name" type="category" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} width={70} />
                <Tooltip contentStyle={{ background: 'var(--bg-elevated)', border: '1px solid var(--border-default)', fontSize: 12 }} formatter={(v: number) => [`${v}%`, '占比']} />
                <Bar dataKey="value" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* 冷热数据 */}
          <div style={{ background: 'var(--bg-elevated)', borderRadius: 12, border: '1px solid var(--border-default)', padding: 16 }}>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8 }}>❄️ 冷热数据分布</div>
            <ResponsiveContainer width="100%" height={180}>
              <PieChart>
                <Pie data={hotCold} cx="50%" cy="50%" innerRadius={40} outerRadius={70} paddingAngle={3} dataKey="value" nameKey="name">
                  {hotCold.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip contentStyle={{ background: 'var(--bg-elevated)', border: '1px solid var(--border-default)', fontSize: 12 }} formatter={(v: number, n: string) => [`${v}%`, n]} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
              </PieChart>
            </ResponsiveContainer>
          </div>

          {/* 量化压缩 */}
          <div style={{ background: 'var(--bg-elevated)', borderRadius: 12, border: '1px solid var(--border-default)', padding: 16 }}>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8 }}>🗜️ 量化压缩比率</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 8 }}>
              {[
                { label: '原始 FP32', size: '1.0 TB', ratio: 100, color: '#ef4444', active: quantization === 'FP32' },
                { label: 'Scalar INT8', size: '250 GB', ratio: 25, color: '#f59e0b', active: quantization === 'INT8' },
                { label: 'Binary', size: '31 GB', ratio: 3.1, color: '#10b981', active: quantization === 'Binary' },
              ].map((item) => (
                <div key={item.label} style={{ opacity: item.active ? 1 : 0.4 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                    <span>{item.active ? '▶ ' : ''}{item.label}</span>
                    <span style={{ color: item.color, fontWeight: 600 }}>{item.size} ({item.ratio}%)</span>
                  </div>
                  <div style={{ background: 'var(--bg-surface)', borderRadius: 4, height: 10, overflow: 'hidden' }}>
                    <div style={{ width: `${Math.min(100, item.ratio)}%`, background: item.color, height: '100%', borderRadius: 4 }} />
                  </div>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 12, fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>
              💡 当前使用 <strong>{quantization}</strong>：{quantization === 'INT8' ? '内存降低 75%，精度损失 <2%，推荐生产使用' : quantization === 'Binary' ? '内存降低 97%，精度损失 5-10%，适合粗排阶段' : '原始精度，内存占用最大，仅小规模使用'}
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div
      style={{
        maxWidth: 1000,
        margin: '0 auto',
        padding: '32px 24px',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
        background: 'var(--bg-surface)',
        minHeight: '100vh',
        color: 'var(--text-primary)',
      }}
    >
      {/* Header */}
      <div style={{ textAlign: 'center', marginBottom: 40 }}>
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 16, marginBottom: 12, flexWrap: 'wrap' }}>
          <h1 style={{ fontSize: 36, fontWeight: 800, color: 'var(--text-primary)', margin: 0 }}>
            🏘️ 村头办事处讲 Agent
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
        <p style={{ fontSize: 16, color: 'var(--text-muted)', maxWidth: 600, margin: '0 auto', lineHeight: 1.6 }}>
          用<strong>村头办事处</strong>讲清楚 Agent 核心：大黑板、值班员、聪明村长
          <br />
          附：完整伪代码 + RAG 1TB 避坑指南 + 全家桶陷阱
        </p>
        <a
          href="#/deep-dive"
          style={{
            display: 'inline-block',
            marginTop: 12,
            padding: '8px 16px',
            borderRadius: 8,
            background: 'var(--bg-hover)',
            color: 'var(--text-primary)',
            textDecoration: 'none',
            fontSize: 13,
            border: '1px solid var(--border-default)',
          }}
        >
          📚 切换到「专业版」看源码 →
        </a>
      </div>

      {/* ===================== 第一章：三样东西 ===================== */}
      <SectionTitle subtitle="村头办事处里只有三样东西，Agent 里也只有三个核心">
        一、办事处三件套 = Agent 三核心
      </SectionTitle>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: 16,
          marginBottom: 32,
        }}
      >
        <Card title="大黑板（Channel）" color="#f59e0b" icon="📋">
          <p>
            <strong>谁来办事、办到哪了、会计给的账、医生开的方，全写在这块黑板上。</strong>
          </p>
          <p>在 Agent 里，Channel 是<strong>「真值来源」</strong>：</p>
          <ul style={{ paddingLeft: 20, margin: '8px 0' }}>
            <li>对话历史（Chat History）</li>
            <li>工具执行结果</li>
            <li>当前步骤的中间变量</li>
            <li>用户的偏好设置</li>
          </ul>
          <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>
            本质：Agent 的<strong>短期记忆载体</strong> + <strong>共享状态容器</strong>
          </p>
        </Card>

        <Card title="值班员（Runtime）" color="#06b6d4" icon="🔔">
          <p>
            <strong>他不识字、也不会干活，但他死死盯着黑板。</strong>
          </p>
          <p>只要黑板上有新字，他就摇铃喊人。</p>
          <p>在 Agent 里，Runtime 是<strong>「流程发动机」</strong>：</p>
          <ul style={{ paddingLeft: 20, margin: '8px 0' }}>
            <li>死循环（While Loop）不断检查 Channel</li>
            <li>Channel 有变化 → 唤醒 LLM 决策</li>
            <li>根据 LLM 决策调用工具</li>
            <li>工具结果写回 Channel，循环继续</li>
          </ul>
          <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>
            本质：<strong>反应式控制环（Reactive Control Loop）</strong>
          </p>
        </Card>

        <Card title="聪明村长（LLM）" color="#8b5cf6" icon="👨‍💼">
          <p>
            <strong>见多识广，啥都懂，但记性不好（只能记住黑板上的），手脚也不利索（不能亲自干活）。</strong>
          </p>
          <p>在 Agent 里，LLM 是<strong>「概率型路由 + 非结构化编译器」</strong>：</p>
          <ul style={{ paddingLeft: 20, margin: '8px 0' }}>
            <li>
              <strong>决策（Planning）</strong>：看黑板决定下一步该找谁
            </li>
            <li>
              <strong>解析（Parsing）</strong>：把工具返回的杂乱数据提炼成结论
            </li>
            <li>
              <strong>路由（Routing）</strong>：决定调用 search_tool 还是直接回复
            </li>
          </ul>
          <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>
            本质：<strong>非线性逻辑判断函数</strong>
          </p>
        </Card>
      </div>

      <Alert type="tip">
        <strong>大白话总结</strong>：Agent = 不断看黑板、出主意、派活、再更新黑板的循环过程。你折腾的那些 AI
        框架，就是把「村头办事处」搬到电脑里。
      </Alert>

      {/* ===================== 第二章：动态演示 ===================== */}
      <SectionTitle subtitle="7 个步骤，看懂一次完整办事流程">
        二、动态演示：王大爷办入学
      </SectionTitle>

      <VillageOfficeDemo />

      {/* ===================== 第三章：核心概念问答 ===================== */}
      <SectionTitle subtitle="把你想确认的 3 个问题一次性讲透">
        三、回答你的核心问题
      </SectionTitle>

      <div style={{ marginBottom: 32 }}>
        <div
          style={{
            background: 'var(--bg-elevated)',
            borderRadius: 12,
            border: '1px solid var(--border-default)',
            padding: 24,
            marginBottom: 16,
          }}
        >
          <h3 style={{ fontSize: 18, fontWeight: 700, color: '#f59e0b', marginBottom: 12 }}>
            ❓ Channel 是不是 State 的核心载体？
          </h3>
          <div style={{ fontSize: 15, lineHeight: 1.8, color: 'var(--text-secondary)' }}>
            <p>
              <strong>是的。而且比"载体"更精确的说法是「真值来源（Source of Truth）」。</strong>
            </p>
            <p>传统 State 是一个大块对象，Channel 把它拆成了独立的、带版本的、带合并策略的最小单元。</p>
            <p>
              所有状态都被<strong>投影</strong>在 Channel 里。它不仅存消息，还存<strong>决策意图</strong>。比如 LLM
              说"我要去查天气"，这个意图也会进入 Channel。即使系统崩溃重启，Runtime 只要读取 Channel
              最后一个版本，就能立刻知道刚才进行到哪了。
            </p>
          </div>
        </div>

        <div
          style={{
            background: 'var(--bg-elevated)',
            borderRadius: 12,
            border: '1px solid var(--border-default)',
            padding: 24,
            marginBottom: 16,
          }}
        >
          <h3 style={{ fontSize: 18, fontWeight: 700, color: '#10b981', marginBottom: 12 }}>
            ❓ 意图识别如何入 Channel？监控版本才会接着走？
          </h3>
          <div style={{ fontSize: 15, lineHeight: 1.8, color: 'var(--text-secondary)' }}>
            <p>对，这就是 Agent 的<strong>核心驱动机制</strong>：</p>
            <ol style={{ paddingLeft: 24, margin: '12px 0' }}>
              <li>意图识别节点执行完 → 往 intent Channel 写入 "vegetable"</li>
              <li>intent Channel 的 update() 返回 true → 版本号 v0 → v1</li>
              <li>Runtime 的 prepare_next_tasks() 检查：检索节点订阅了 intent Channel</li>
              <li>检索节点上次看到 intent 是 v0，现在是 v1 → <strong>触发执行！</strong></li>
            </ol>
            <Alert type="tip">
              大白话：摊主在 intent 篮子里放了纸条、撕掉旧标签贴上 v1。负责找菜的工人一看标签变了，就知道该干活了。
            </Alert>
          </div>
        </div>

        <div
          style={{
            background: 'var(--bg-elevated)',
            borderRadius: 12,
            border: '1px solid var(--border-default)',
            padding: 24,
            marginBottom: 16,
          }}
        >
          <h3 style={{ fontSize: 18, fontWeight: 700, color: '#06b6d4', marginBottom: 12 }}>
            ❓ 流水线 prompt 素材来源？
          </h3>
          <div style={{ fontSize: 15, lineHeight: 1.8, color: 'var(--text-secondary)' }}>
            <p>
              <strong>Prompt 的素材就是各个 Channel 里的「菜」。</strong>
            </p>
            <p>生成节点从多个 Channel 读取素材拼装 prompt：</p>
            <ul style={{ paddingLeft: 24, margin: '8px 0' }}>
              <li>
                <strong>query Channel</strong> → 用户原始问题（instruction）
              </li>
              <li>
                <strong>retrieval_results / final_context Channel</strong> → 检索素材（context）
              </li>
              <li>
                <strong>history / messages Channel</strong> → 对话历史（few-shot）
              </li>
            </ul>
            <Alert type="tip">
              大白话：摊主不是凭空回答的，他先看大妈问了什么（query 篮），再看手里有什么菜（retrieval_results
              篮），然后组织语言回答。
            </Alert>
          </div>
        </div>
      </div>

      {/* ===================== 第四章：版本号详解 ===================== */}
      <SectionTitle subtitle="黑板上的页码和日期，防乱套、方便翻旧账">
        四、版本号：黑板的页码
      </SectionTitle>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: 12,
          marginBottom: 32,
        }}
      >
        {[
          {
            title: '状态一致性',
            desc: '多个节点同时写黑板时，版本号确保不会互相覆盖搞混',
            icon: '🎯',
          },
          {
            title: '回溯（Time Travel）',
            desc: 'Agent 跑偏了，可以根据版本号回滚到上一个正确的状态',
            icon: '⏪',
          },
          {
            title: '死循环熔断',
            desc: '版本号超过 10 次，Runtime 强行中断，防止 Token 烧光',
            icon: '🔥',
          },
          {
            title: '并发控制',
            desc: '两个工具同时返回时，版本号保证状态更新不冲突',
            icon: '🔒',
          },
        ].map((item, i) => (
          <div
            key={i}
            style={{
              background: 'var(--bg-elevated)',
              borderRadius: 10,
              border: '1px solid var(--border-default)',
              padding: 16,
              textAlign: 'center',
            }}
          >
            <div style={{ fontSize: 32, marginBottom: 8 }}>{item.icon}</div>
            <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>{item.title}</div>
            <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.5 }}>{item.desc}</div>
          </div>
        ))}
      </div>

      {/* ===================== 第五章：完整伪代码 ===================== */}
      <SectionTitle subtitle="从「村头办事处」到「可运行的 Python 代码」">
        五、完整伪代码：从原型到工业级
      </SectionTitle>

      <h4 style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>
        5.1 基础版：村头办事处原型
      </h4>
      <CodeBlock>{`class Channel:
    """大黑板：存放所有版本的快照"""
    def __init__(self):
        self.history = []
        self.current_version = 0

    def update_state(self, new_data):
        latest = self.get_latest().copy()
        latest.update(new_data)
        self.current_version += 1
        latest['version'] = self.current_version
        self.history.append(latest)

    def get_latest(self):
        return self.history[-1] if self.history else {"messages": [], "version": 0}


def agent_runtime(user_input):
    """值班员：死循环盯着黑板"""
    channel = Channel()
    channel.update_state({"input": user_input, "status": "thinking"})

    while True:
        current_state = channel.get_latest()
        
        # 村长看黑板，出主意
        decision = call_llm(current_state)
        
        if decision.action == "FINAL_ANSWER":
            return decision.content
            
        elif decision.action == "CALL_TOOL":
            # 派活给会计/医生
            result = execute_tool(decision.tool_name, decision.tool_args)
            
            # 会计写回黑板，版本 +1
            channel.update_state({
                "last_tool": decision.tool_name,
                "tool_result": result,
                "messages": current_state['messages'] + [f"Tool returned {result}"]
            })`}</CodeBlock>

      <h4 style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)', marginTop: 24, marginBottom: 12 }}>
        5.2 工业级版：LangGraph 风格（带 Reducer + Checkpoint）
      </h4>
      <CodeBlock>{`from typing import Annotated, TypedDict
from operator import add

class AgentState(TypedDict):
    # 追加模式：messages 会累积，不是覆盖
    messages: Annotated[list, add]
    next_step: str
    iteration_count: int

def assistant_node(state: AgentState):
    """村长节点：看黑板，出主意"""
    response = llm.invoke(state['messages'])
    return {
        "messages": [response],
        "iteration_count": state['iteration_count'] + 1
    }

def tool_node(state: AgentState):
    """会计节点：执行工具，写回黑板"""
    last_msg = state['messages'][-1]
    result = execute_tool(last_msg.tool_calls)
    return {"messages": [result]}

def router(state: AgentState):
    """值班员路由：决定下一步去哪"""
    if state['iteration_count'] > 10:
        return "END"  # 熔断！防止死循环
    if state['messages'][-1].tool_calls:
        return "call_tool"
    return "END"

# 组装办事处
workflow = Graph()
workflow.add_node("agent", assistant_node)
workflow.add_node("tools", tool_node)
workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", router)
workflow.add_edge("tools", "agent")  # 工具执行完，回村长再审

# 挂上数据库持久化（账本存到 Postgres）
app = workflow.compile(checkpointer=PostgresSaver())`}</CodeBlock>

      <Alert type="warning">
        <strong>坑位预警</strong>：Annotated[list, add] 看起来很爽，但循环 20 次后消息列表会变得极长，Token
        消耗指数级增长。必须引入 Summarizer 节点定期压缩历史！
      </Alert>

      {/* ===================== 第六章：代码沙箱 ===================== */}
      <SectionTitle subtitle="让 Agent 从「办事员」升级为「专家」：现场写代码">
        六、代码沙箱：给村长一台电脑
      </SectionTitle>

      <div
        style={{
          background: 'var(--bg-elevated)',
          borderRadius: 12,
          border: '1px solid var(--border-default)',
          padding: 24,
          marginBottom: 24,
        }}
      >
        <p style={{ fontSize: 15, lineHeight: 1.7, color: 'var(--text-secondary)' }}>
          如果 Agent 只会调 API，它只是个办事员。如果给它一个<strong>隔离的 Python 环境</strong>
          ，它就能现场写脚本解决问题——这就是从「办事员」到「专家」的质变。
        </p>
      </div>

      <CodeBlock>{`import subprocess
import multiprocessing

def execute_python_sandbox(code_string: str, timeout=10):
    """
    沙箱执行：Agent 写的代码在这里运行
    生产环境建议用 Docker 或 E2B 隔离
    """
    def target_func(queue):
        try:
            local_vars = {}
            exec(code_string, {"__builtins__": __builtins__}, local_vars)
            queue.put({"status": "success", "result": local_vars.get('result')})
        except Exception as e:
            queue.put({"status": "error", "message": str(e)})

    queue = multiprocessing.Queue()
    p = multiprocessing.Process(target=target_func, args=(queue,))
    p.start()
    p.join(timeout)
    
    # 坑 1：超时控制（防止 Agent 写出 while True）
    if p.is_alive():
        p.terminate()
        return {"status": "error", "message": "Execution timed out"}
    
    return queue.get()

# 在 Runtime 中调用
if decision.tool_name == "python_repl":
    report = execute_python_sandbox(decision.tool_args['code'])
    channel.update_state({"observation": report})`}</CodeBlock>

      <Alert type="danger">
        <strong>安全红线</strong>：必须用 Docker 容器隔离！否则用户一句"import os;
        os.system('rm -rf /')"就能删库。容器还要禁止连接公网，防止 API Key 被发到黑客服务器。
      </Alert>

      {/* ===================== 第七章：RAG 避坑全家桶 ===================== */}
      <SectionTitle subtitle="你正在折腾 1TB Qdrant，这些坑是深水区的「暗礁」">
        七、RAG 避坑全家桶（1TB Qdrant 特供版）
      </SectionTitle>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
          gap: 16,
          marginBottom: 24,
        }}
      >
        <Card title="💾 内存溢出（OOM）" color="#ef4444" icon="💀">
          <p>
            <strong>坑</strong>：1TB 向量默认全放内存，索引建到一半就崩。
          </p>
          <p>
            <strong>避坑</strong>：
          </p>
          <ul style={{ paddingLeft: 18, margin: '4px 0', fontSize: 13 }}>
            <li>开启 mmap：索引存磁盘，内存映射访问</li>
            <li>量化压缩：Scalar/PQ 量化，向量大小压 4 倍</li>
            <li>HNSW on_disk: true，强制索引落盘</li>
          </ul>
        </Card>

        <Card title="🔍 过滤性能退化" color="#f59e0b" icon="🐌">
          <p>
            <strong>坑</strong>：WHERE user_id=xxx 没建索引，1TB 里全表扫描。
          </p>
          <p>
            <strong>避坑</strong>：
          </p>
          <ul style={{ paddingLeft: 18, margin: '4px 0', fontSize: 13 }}>
            <li>Payload Indexing：为过滤字段建 Keyword/Integer 索引</li>
            <li>注意过滤条件的基数（Cardinality）</li>
          </ul>
        </Card>

        <Card title="⚡ 精排延迟爆炸" color="#06b6d4" icon="⏱️">
          <p>
            <strong>坑</strong>：返回几百个结果全发给 Reranker，响应超 5 秒。
          </p>
          <p>
            <strong>避坑</strong>：
          </p>
          <ul style={{ paddingLeft: 18, margin: '4px 0', fontSize: 13 }}>
            <li>两阶段检索：Qdrant 召回 50 → Reranker 选前 5</li>
            <li>分布式：Qdrant Cluster + Sharding 分散压力</li>
          </ul>
        </Card>

        <Card title="📄 死文档污染" color="#8b5cf6" icon="👻">
          <p>
            <strong>坑</strong>：向量检索翻出 3 年前的旧政策，LLM 给出错误建议。
          </p>
          <p>
            <strong>避坑</strong>：
          </p>
          <ul style={{ paddingLeft: 18, margin: '4px 0', fontSize: 13 }}>
            <li>时间衰减：用 custom_score 结合文档时间戳加权</li>
            <li>定期清理：过时文档降权或移除</li>
          </ul>
        </Card>

        <Card title="🧩 切片语义断裂" color="#10b981" icon="✂️">
          <p>
            <strong>坑</strong>：固定 500 字切，刚好把一段话切成两半。
          </p>
          <p>
            <strong>避坑</strong>：
          </p>
          <ul style={{ paddingLeft: 18, margin: '4px 0', fontSize: 13 }}>
            <li>递归字符切分：按段落、句号切</li>
            <li>重叠度 Overlap：10-20%，保证语义连贯</li>
          </ul>
        </Card>

        <Card title="🎭 生成幻觉" color="#ec4899" icon="🦄">
          <p>
            <strong>坑</strong>：LLM 即使找不到答案，也会凭记忆乱编。
          </p>
          <p>
            <strong>避坑</strong>：
          </p>
          <ul style={{ paddingLeft: 18, margin: '4px 0', fontSize: 13 }}>
            <li>Prompt 严令禁止："不知道就直说，严禁发挥"</li>
            <li>强制引用来源（Citation）</li>
          </ul>
        </Card>
      </div>

      <h4 style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>
        7.1 Qdrant 1TB 生产配置参考
      </h4>
      <CodeBlock>{`from qdrant_client import QdrantClient
from qdrant_client.http import models

client = QdrantClient("localhost", port=6333)

client.recreate_collection(
    collection_name="big_data_rag",
    vectors_config=models.VectorParams(
        size=1536,
        distance=models.Distance.COSINE,
        # 核心：量化压缩，保命第一
        quantization_config=models.ScalarQuantization(
            scalar=models.ScalarQuantizationConfig(
                type=models.ScalarType.INT8,
                quantile=0.99,
                always_ram=True
            )
        )
    ),
    hnsw_config=models.HnswConfigDiff(
        m=16,
        ef_construct=100,
        full_scan_threshold=10000,
        on_disk=True  # 强制索引落盘，防止 OOM
    ),
    shard_number=8  # 1TB 至少 8 个分片
)

# Payload 必须建索引，否则检索慢如蜗牛
client.create_payload_index(
    collection_name="big_data_rag",
    field_name="doc_id",
    field_schema=models.PayloadSchemaType.KEYWORD,
)`}</CodeBlock>

      {/* ===================== 第八章：全家桶陷阱 ===================== */}
      <SectionTitle subtitle="工程坑、逻辑坑、安全坑、钱包坑，一个都不能少">
        八、全家桶陷阱：那些让你想摔键盘的瞬间
      </SectionTitle>

      <div style={{ marginBottom: 32 }}>
        {[
          {
            type: 'danger' as const,
            title: '安全坑：它会「拆家」',
            items: [
              '指令注入：用户诱导 Agent 写出 rm -rf /',
              '权限过大：沙箱能读环境变量 → API Key 泄露',
              '防范：必须用 Docker，禁止容器连公网',
            ],
          },
          {
            type: 'warning' as const,
            title: '逻辑坑：Agent 的「鬼打墙」',
            items: [
              '自循环幻觉：同一个错误尝试 50 次，Token 烧光',
              '工具幻觉：发明不存在的库 import cool_ai_tool',
              '状态漂移：第 3 步写的变量 x=10，第 5 步找不到了',
            ],
          },
          {
            type: 'warning' as const,
            title: '工程坑：Context 的「胃口」',
            items: [
              'Context 爆炸：DataFrame 打印 1000 行，直接塞爆上下文',
              '环境不一致：开发环境有 pandas，生产环境没有',
              'JSON 解析失败：LLM 总在 JSON 后面加句废话',
            ],
          },
          {
            type: 'danger' as const,
            title: '钱包坑：Token 的「火灾」',
            items: [
              '反复推理：20 次循环 × 5k Token = 10w Token/次',
              '冗余输入：历史记录没清理，每轮重复发送废话',
              '评估难题：没法写 Unit Test，路径非确定性',
            ],
          },
        ].map((section, i) => (
          <div
            key={i}
            style={{
              background: 'var(--bg-elevated)',
              borderRadius: 12,
              border: '1px solid var(--border-default)',
              padding: 20,
              marginBottom: 12,
            }}
          >
            <h4
              style={{
                fontSize: 15,
                fontWeight: 700,
                color: section.type === 'danger' ? '#ef4444' : '#f59e0b',
                marginBottom: 10,
              }}
            >
              {section.type === 'danger' ? '💀' : '⚠️'} {section.title}
            </h4>
            <ul style={{ paddingLeft: 20, margin: 0, fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.8 }}>
              {section.items.map((item, j) => (
                <li key={j}>{item}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {/* ===================== 第九章：黑话翻译器 ===================== */}
      <SectionTitle subtitle="左边是村头老大爷说的，右边是程序员装X用的">
        九、黑话翻译器
      </SectionTitle>

      <div
        style={{
          background: 'var(--bg-elevated)',
          borderRadius: 12,
          border: '1px solid var(--border-default)',
          overflow: 'hidden',
          marginBottom: 32,
        }}
      >
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <thead>
            <tr style={{ background: 'var(--bg-hover)' }}>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600 }}>村头大白话</th>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600 }}>技术黑话</th>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600 }}>一句话解释</th>
            </tr>
          </thead>
          <tbody>
            {[
              ['大黑板', 'Channel', '系统的真值来源，所有状态投影在这里'],
              ['黑板上的页码', 'channel_versions', '版本号，变了就说明有新数据'],
              ['值班员', 'Runtime / Executor', '死循环盯着黑板，有新字就摇铃'],
              ['聪明村长', 'LLM', '拿主意、看地图、做决策的大脑'],
              ['会计/医生', 'Tool', '执行具体任务的外部接口'],
              ['账本', 'Checkpoint', '某一时刻黑板的快照，可恢复'],
              ['翻旧账', 'Time Travel', '根据版本号回溯到之前的状态'],
              ['派活', 'Conditional Edge', '根据黑板内容决定下一步找谁'],
              ['换班接着干', 'Command(resume=)', '从 checkpoint 恢复继续执行'],
              ['合并规矩', 'Reducer', 'append / overwrite / merge'],
              ['一回合', 'Superstep', '观察→思考→执行→更新'],
              ['熔断', 'max_iterations', '超过次数强行中断，防死循环'],
            ].map((row, i) => (
              <tr key={i} style={{ borderTop: '1px solid var(--border-default)' }}>
                <td style={{ padding: '10px 16px', color: 'var(--text-primary)', fontWeight: 500 }}>{row[0]}</td>
                <td
                  style={{ padding: '10px 16px', color: '#4f46e5', fontFamily: 'monospace', fontSize: 13, fontWeight: 600 }}
                >
                  {row[1]}
                </td>
                <td style={{ padding: '10px 16px', color: 'var(--text-muted)', fontSize: 13 }}>{row[2]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ===================== 第十章：隐藏齿轮 ===================== */}
      <SectionTitle subtitle="原型机到工业级，还缺五个「隐藏齿轮」">
        十、隐藏齿轮：从办事处到生态系统
      </SectionTitle>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
          gap: 16,
          marginBottom: 24,
        }}
      >
        {[
          {
            title: '历史档案库（Long-term Memory）',
            icon: '📚',
            color: '#4f46e5',
            desc: 'Channel 只存「当前这一场戏」，RAG 负责把「几年前的旧案」调出来。',
            analogy: '办事处隔壁的档案室，以前的案子都能翻出来参考',
          },
          {
            title: '施工蓝图（Planning）',
            icon: '📐',
            color: '#06b6d4',
            desc: 'LLM 不该直接开干，得先拆解步骤（Step-by-step），防止南辕北辙。',
            analogy: '村长先画一张施工图，再分配任务，而不是瞎指挥',
          },
          {
            title: '质检监理（Self-Reflection）',
            icon: '🔍',
            color: '#10b981',
            desc: '让 LLM 自己检查结果："我刚才算的数对吗？""工具报错我处理了吗？"',
            analogy: '第三方监理，专门挑毛病，防止豆腐渣工程',
          },
          {
            title: '甲方确认（Human-in-the-loop）',
            icon: '✋',
            color: '#f59e0b',
            desc: '遇到关键决策（如付钱、删库），Runtime 必须挂起，等待真人点头。',
            analogy: '大笔开支必须王大爷签字，村长不能自己说了算',
          },
          {
            title: '预分拣员（Router）',
            icon: '📬',
            color: '#8b5cf6',
            desc: '并不是所有问题都要找村长，简单的、重复的直接由程序逻辑处理。',
            analogy: '快递驿站先分拣，同城件直接送，不需要上报总部',
          },
        ].map((item, i) => (
          <div
            key={i}
            style={{
              background: 'var(--bg-elevated)',
              borderRadius: 12,
              border: `2px solid ${item.color}30`,
              padding: 18,
            }}
          >
            <div style={{ fontSize: 28, marginBottom: 8 }}>{item.icon}</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: item.color, marginBottom: 6 }}>{item.title}</div>
            <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6, marginBottom: 8 }}>
              {item.desc}
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>类比：{item.analogy}</div>
          </div>
        ))}
      </div>

      {/* ===================== 第十一章：深层陷阱与解决方案 ===================== */}
      <SectionTitle subtitle="Gemini 提到的三个深层逻辑陷阱及工业级解决方案">
        十一、深层陷阱：状态爆炸、幻觉打转、并发锁
      </SectionTitle>

      <div style={{ marginBottom: 32 }}>
        <div
          style={{
            background: 'var(--bg-elevated)',
            borderRadius: 12,
            border: '1px solid var(--border-default)',
            padding: 24,
            marginBottom: 16,
          }}
        >
          <h4 style={{ fontSize: 16, fontWeight: 700, color: '#ef4444', marginBottom: 12 }}>
            💥 A. 状态膨胀（State Explosion）
          </h4>
          <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.7, marginBottom: 12 }}>
            <strong>问题</strong>：随着循环增加，Channel 里的消息越来越长，Context Window 被挤爆，Token 消耗指数级增长，LLM 开始胡言乱语。
          </p>
          <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.7, marginBottom: 12 }}>
            <strong>深度方案：Summarizer 节点</strong>
          </p>
          <CodeBlock>{`# 每隔 5 个版本，让 LLM 把历史压缩成摘要
def summarizer_node(state):
    if len(state['messages']) > 20:
        summary = llm.summarize(state['messages'][:-5])
        return {
            "messages": [
                {"role": "system", "content": f"历史摘要：{summary}"}
            ] + state['messages'][-5:]  # 只保留最近 5 条 + 摘要
        }
    return {}`}</CodeBlock>
          <Alert type="tip">
            大白话：村长记性不好，前面聊的太多就糊涂了。值班员每隔几轮就把之前的对话整理成一张「便利贴」，只留最近的几句原话。
          </Alert>
        </div>

        <div
          style={{
            background: 'var(--bg-elevated)',
            borderRadius: 12,
            border: '1px solid var(--border-default)',
            padding: 24,
            marginBottom: 16,
          }}
        >
          <h4 style={{ fontSize: 16, fontWeight: 700, color: '#f59e0b', marginBottom: 12 }}>
            🌀 B. 幻觉导致的「逻辑打转」
          </h4>
          <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.7, marginBottom: 12 }}>
            <strong>问题</strong>：LLM 连续 5 次尝试同一个错误的工具参数，在同一个低级错误上反复横跳。
          </p>
          <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.7, marginBottom: 12 }}>
            <strong>深度方案：重复检测 + Reflect 模式</strong>
          </p>
          <CodeBlock>{`def detect_loop(state):
    """检测连续三个版本指令是否高度相似"""
    recent = state['decisions'][-3:]
    if len(recent) < 3:
        return False
    # 用相似度或哈希判断
    return similarity(recent[0], recent[1]) > 0.9 and similarity(recent[1], recent[2]) > 0.9

# 在 Runtime 中
if detect_loop(current_state):
    # 强制切换 Reflect 模式，降低 temperature，换模型
    decision = llm_reflect(state, temperature=0.1)
    state['mode'] = 'reflect'  # 切换到反思模式`}</CodeBlock>
          <Alert type="warning">
            大白话：村长犯轴了，同一个坑跳了三次。值班员看不下去了，强制村长「冷静模式」（降低 temperature），让他换个思路重新想。
          </Alert>
        </div>

        <div
          style={{
            background: 'var(--bg-elevated)',
            borderRadius: 12,
            border: '1px solid var(--border-default)',
            padding: 24,
            marginBottom: 16,
          }}
        >
          <h4 style={{ fontSize: 16, fontWeight: 700, color: '#06b6d4', marginBottom: 12 }}>
            🔒 C. 并发与锁（Concurrency）
          </h4>
          <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.7, marginBottom: 12 }}>
            <strong>问题</strong>：多个 Agent 同时修改同一个 Channel，状态混乱。会计和医生同时往黑板上写，字叠在一起了。
          </p>
          <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.7, marginBottom: 12 }}>
            <strong>深度方案：State Reducer（状态归约器）</strong>
          </p>
          <CodeBlock>{`# 类似 React/Redux：状态更新不是覆盖，而是纯函数转化
def state_reducer(old_state, action):
    if action['type'] == 'APPEND_MESSAGES':
        return {**old_state, "messages": old_state["messages"] + action["payload"]}
    elif action['type'] == 'UPDATE_PLAN':
        return {**old_state, "plan": action["payload"]}
    return old_state

# 所有更新都通过 Reducer，保证确定性
new_state = state_reducer(old_state, {"type": "APPEND_MESSAGES", "payload": [result]})`}</CodeBlock>
          <Alert type="tip">
            大白话：黑板前装了一个「调度员」，会计和医生不能同时写。调度员把两堆字按规矩合并（append/merge/overwrite），确保黑板上永远是有序的。
          </Alert>
        </div>
      </div>

      {/* ===================== 第十二章：MDP 类比 ===================== */}
      <SectionTitle subtitle="用统计学视角理解 Agent 的本质">
        十二、高级理解：Agent = 马尔可夫决策过程（MDP）
      </SectionTitle>

      <div
        style={{
          background: 'var(--bg-elevated)',
          borderRadius: 12,
          border: '1px solid var(--border-default)',
          padding: 24,
          marginBottom: 32,
        }}
      >
        <div style={{ fontSize: 15, lineHeight: 1.8, color: 'var(--text-secondary)', marginBottom: 16 }}>
          <p>
            如果你学过统计学，可以把 Agent 看作一个<strong>「减熵过程」</strong>：
          </p>
          <ul style={{ paddingLeft: 24, margin: '12px 0' }}>
            <li>
              <strong>输入（熵增）</strong>：模糊、杂乱的用户需求
            </li>
            <li>
              <strong>处理（循环）</strong>：通过观察-反馈闭环，不断消除不确定性
            </li>
            <li>
              <strong>输出（熵减）</strong>：确定、精确的结果
            </li>
          </ul>
          <p>
            更深层看，Agent 架构本质上就是<strong>马尔可夫决策过程（MDP）</strong>：
          </p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
          {[
            { term: 'State（状态）', map: 'Channel 当前内容', icon: '📋' },
            { term: 'Action（动作）', map: 'LLM 决策 / Tool 调用', icon: '🎯' },
            { term: 'Reward（奖励）', map: '任务完成度 / 用户反馈', icon: '🏆' },
            { term: 'Policy（策略）', map: 'LLM 的决策逻辑', icon: '🧠' },
            { term: 'Transition（转移）', map: 'Reducer 状态更新', icon: '🔄' },
          ].map((item, i) => (
            <div
              key={i}
              style={{
                background: 'var(--bg-hover)',
                padding: 14,
                borderRadius: 8,
                textAlign: 'center',
              }}
            >
              <div style={{ fontSize: 24, marginBottom: 6 }}>{item.icon}</div>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 2 }}>
                {item.term}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{item.map}</div>
            </div>
          ))}
        </div>

        <div style={{ marginTop: 16 }}>
          <Alert type="tip">
            <strong>核心洞察</strong>：当前的决策（Action）只取决于当前的状态（State），与历史无关——这就是马尔可夫性。版本号的存在让我们可以随时「回溯到任意状态」，重新选择 Action，实现 time-travel 调试。
          </Alert>
        </div>
      </div>

      {/* ===================== 第十三章：RAG 进阶 ===================== */}
      <SectionTitle subtitle="Self-RAG、Corrective RAG、RAGAS 评估">
        十三、RAG 进阶：从「查字典」到「自治专家」
      </SectionTitle>

      <div style={{ marginBottom: 32 }}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
            gap: 16,
            marginBottom: 16,
          }}
        >
          <Card title="Self-RAG（自反思 RAG）" color="#4f46e5" icon="🤔">
            <p>Agent 检索后先问自己：这几条文档能回答用户的问题吗？</p>
            <ul style={{ paddingLeft: 18, margin: '8px 0', fontSize: 13 }}>
              <li>如果能 → 输出答案</li>
              <li>如果不能 → 重写 Query，重新检索</li>
            </ul>
            <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>
              这就是递归思维在 RAG 中的应用。
            </p>
          </Card>

          <Card title="Corrective RAG（纠错 RAG）" color="#06b6d4" icon="🔧">
            <p>如果检索到的信息有矛盾，Agent 自动调用搜索工具去验证哪个是真的。</p>
            <ul style={{ paddingLeft: 18, margin: '8px 0', fontSize: 13 }}>
              <li>文档 A 说「价格是 100」</li>
              <li>文档 B 说「价格是 200」</li>
              <li>Agent 自动 Google 验证 → 确定正确价格</li>
            </ul>
          </Card>

          <Card title="RAGAS 评估框架" color="#10b981" icon="📊">
            <p>用数据说话，不要只看一次跑通了。</p>
            <ul style={{ paddingLeft: 18, margin: '8px 0', fontSize: 13 }}>
              <li>Faithfulness：答案是否忠于检索内容</li>
              <li>Answer Relevance：答案是否切题</li>
              <li>Context Precision：检索内容是否精准</li>
              <li>Context Recall：是否漏掉了关键信息</li>
            </ul>
          </Card>
        </div>
      </div>

      {/* ===================== 第十四章：1TB 运维圣经 ===================== */}
      <SectionTitle subtitle="监控、备份、冷热分离——1TB 数据的生存法则">
        十四、1TB 运维圣经：让系统活着
      </SectionTitle>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
          gap: 12,
          marginBottom: 32,
        }}
      >
        {[
          {
            title: '监控是第一生产力',
            icon: '📈',
            color: '#4f46e5',
            items: [
              '监控 Qdrant collection_info 中的 status',
              '关注 Segment 合并频率，频繁合并 = IO 压力巨大',
              '磁盘 IOPS 是 1TB 场景下的头号瓶颈',
            ],
          },
          {
            title: '备份预案',
            icon: '💾',
            color: '#06b6d4',
            items: [
              '1TB 重新索引可能需要几天',
              '原始文本必须在数据库有一份完整备份',
              '向量维度变更时（1536→3072），需要重新 Embedding',
            ],
          },
          {
            title: '冷热分离',
            icon: '❄️',
            color: '#10b981',
            items: [
              '20% 热数据（常问）→ 内存优先集合',
              '80% 冷数据（不常问）→ 纯磁盘集合',
              '根据访问频率自动迁移',
            ],
          },
          {
            title: '时间衰减',
            icon: '⏰',
            color: '#f59e0b',
            items: [
              '旧文档检索权重随时间降低',
              'Qdrant custom_score 结合时间戳',
              '防止翻出 3 年前的旧政策误导用户',
            ],
          },
        ].map((section, i) => (
          <div
            key={i}
            style={{
              background: 'var(--bg-elevated)',
              borderRadius: 10,
              border: '1px solid var(--border-default)',
              padding: 16,
            }}
          >
            <div style={{ fontSize: 24, marginBottom: 8 }}>{section.icon}</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: section.color, marginBottom: 8 }}>
              {section.title}
            </div>
            <ul style={{ paddingLeft: 18, margin: 0, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.7 }}>
              {section.items.map((item, j) => (
                <li key={j}>{item}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {/* ===================== 第十五章：交互式 Python 沙箱 ===================== */}
      <SectionTitle subtitle="输入代码，看看在「村头办事处」里会发生什么">
        十五、交互式 Python 沙箱：站巨人肩膀
      </SectionTitle>

      <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.7, marginBottom: 16 }}>
        光说不练假把式。下面这个沙箱模拟了 Python 代码执行过程——你可以修改代码、点击运行，
        看看数据处理、向量检索、统计分析在实际操作中长什么样。王大爷在旁边看着呢 👀
      </p>

      <InteractivePythonSandbox />

      <div style={{ marginTop: 24, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 12 }}>
        <Card title="举一反三：数据处理" icon="🔄" color="#4f46e5">
          <p style={{ fontSize: 13, marginBottom: 8 }}>王大爷的材料分类就是典型的 ETL：</p>
          <ul style={{ paddingLeft: 18, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.7, margin: 0 }}>
            <li>Extract：从各种渠道收材料</li>
            <li>Transform：分类、去重、校验</li>
            <li>Load：写入数据库/向量库</li>
          </ul>
        </Card>
        <Card title="举一反三：向量检索" icon="🔍" color="#06b6d4">
          <p style={{ fontSize: 13, marginBottom: 8 }}>余弦相似度是最基础的检索算法：</p>
          <ul style={{ paddingLeft: 18, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.7, margin: 0 }}>
            <li>Query 和 Doc 都转成向量</li>
            <li>夹角越小 = 语义越接近</li>
            <li>生产环境用 HNSW 索引加速</li>
          </ul>
        </Card>
        <Card title="举一反三：监控告警" icon="🚨" color="#f59e0b">
          <p style={{ fontSize: 13, marginBottom: 8 }}>统计延迟分布是 SRE 基本功：</p>
          <ul style={{ paddingLeft: 18, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.7, margin: 0 }}>
            <li>P95 / P99 比平均值更有意义</li>
            <li>异常点往往是系统瓶颈信号</li>
            <li>延迟飙升 → 检查 Segment 合并</li>
          </ul>
        </Card>
      </div>

      {/* ===================== 第十六章：Qdrant 1TB 监控面板 ===================== */}
      <SectionTitle subtitle="实时监控 Segment 合并、IOPS、内存、量化压缩">
        十六、Qdrant 监控面板：让 1TB 数据透明可见
      </SectionTitle>

      <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.7, marginBottom: 16 }}>
        1TB 数据不是「存进去就完事了」。Segment 合并、内存占用、冷热数据分布——这些才是决定系统生死的指标。
        下面这个面板模拟了生产环境的实时监控，数据会定时刷新。
      </p>

      <QdrantMonitor />

      <div style={{ marginTop: 24, background: 'var(--bg-elevated)', borderRadius: 10, border: '1px solid var(--border-default)', padding: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8, color: '#ef4444' }}>⚠️ 1TB 生产红线</div>
        <ul style={{ paddingLeft: 18, margin: 0, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.8 }}>
          <li><strong>Segment 合并期间</strong> IOPS 可能飙升 5-10 倍，务必避开业务高峰期</li>
          <li><strong>内存 &lt; 80%</strong>：向量索引必须常驻内存，swap = 检索延迟暴增</li>
          <li><strong>冷数据占比 &gt; 60%</strong>：考虑启用 on_disk=True，用磁盘换内存</li>
          <li><strong>量化压缩</strong>：INT8 精度损失 &lt;2%，Binary 损失 5-10%，根据业务容忍度选择</li>
          <li><strong>备份</strong>：1TB 重建需要数天，快照是生命线</li>
        </ul>
      </div>

      {/* ===================== 回到专业版 ===================== */}
      <div style={{ textAlign: 'center', marginBottom: 40 }}>
        <a
          href="#/deep-dive"
          style={{
            display: 'inline-block',
            padding: '12px 24px',
            borderRadius: 10,
            background: '#4f46e5',
            color: '#fff',
            textDecoration: 'none',
            fontSize: 15,
            fontWeight: 600,
          }}
        >
          📚 看懂了？去「专业版」看源码 →
        </a>
      </div>

      {/* Footer */}
      <div
        style={{
          textAlign: 'center',
          padding: '24px 0',
          color: 'var(--text-muted)',
          fontSize: 13,
          borderTop: '1px solid var(--border-default)',
        }}
      >
        基于 Gemini 深度对话整理 &nbsp;|&nbsp; 用村头办事处讲清楚 Agent Runtime &nbsp;|&nbsp;
        附 1TB Qdrant 生产避坑指南
      </div>
    </div>
  )
}
