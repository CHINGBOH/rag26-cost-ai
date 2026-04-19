import React, { useState, useEffect } from 'react'
import { getTheme, toggleTheme } from '../../config/theme'
import MarkdownRenderer from './MarkdownRenderer'

// Vite ?raw 导入 markdown 文件
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore
import creativeArch from '../../../../../../docs/rag-agent-creative-architecture.md?raw'
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore
import observability from '../../../../../../docs/rag-architecture-observability.md?raw'
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore
import enhancement from '../../../../../../docs/rag-agent-architecture-enhancement.md?raw'
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore
import archImpl from '../../../../../../docs/ARCHITECTURE_IMPLEMENTATION.md?raw'
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore
import xstateDeepDive from '../../../../../../docs/xstate-v5-deep-dive.md?raw'
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore
import dataPipeline from '../../../../../../docs/DATA_PIPELINE.md?raw'

interface DocItem {
  id: string
  title: string
  icon: string
  category: string
  source: string
}

const docs: DocItem[] = [
  {
    id: 'creative',
    title: 'RAG × Agent 发散式架构进化图谱',
    icon: '🧠',
    category: '架构设计',
    source: creativeArch as string,
  },
  {
    id: 'observability',
    title: 'RAG 架构健康度观测与自检体系',
    icon: '🔭',
    category: '观测工具',
    source: observability as string,
  },
  {
    id: 'enhancement',
    title: 'RAG Agent 架构增强方案',
    icon: '🚀',
    category: '架构设计',
    source: enhancement as string,
  },
  {
    id: 'arch-impl',
    title: '架构实现文档',
    icon: '🏗️',
    category: '工程实现',
    source: archImpl as string,
  },
  {
    id: 'xstate',
    title: 'XState v5 深度调研',
    icon: '⚙️',
    category: '状态机',
    source: xstateDeepDive as string,
  },
  {
    id: 'pipeline',
    title: '数据管道设计',
    icon: '📊',
    category: '工程实现',
    source: dataPipeline as string,
  },
]

const categories = Array.from(new Set(docs.map((d) => d.category)))

const DocsReader: React.FC = () => {
  const [activeId, setActiveId] = useState<string>('creative')
  const [theme, setThemeState] = useState(getTheme())
  const [search, setSearch] = useState('')
  const [toc, setToc] = useState<Array<{ level: number; text: string }>>([])

  const activeDoc = docs.find((d) => d.id === activeId) || docs[0]

  useEffect(() => {
    const handler = () => setThemeState(getTheme())
    window.addEventListener('storage', handler)
    const interval = setInterval(handler, 500)
    return () => {
      window.removeEventListener('storage', handler)
      clearInterval(interval)
    }
  }, [])

  // 自动提取目录（heading）
  useEffect(() => {
    const headings: Array<{ level: number; text: string }> = []
    const lines = activeDoc.source.split('\n')
    for (const line of lines) {
      const match = line.match(/^(#{1,3})\s+(.+)$/)
      if (match) {
        headings.push({ level: match[1].length, text: match[2].trim() })
      }
    }
    setToc(headings)
  }, [activeDoc])

  const filteredDocs = docs.filter(
    (d) =>
      d.title.toLowerCase().includes(search.toLowerCase()) ||
      d.category.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div
      style={{
        display: 'flex',
        height: '100vh',
        background: 'var(--bg-surface)',
        color: 'var(--text-primary)',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
      }}
    >
      {/* 左侧目录栏 */}
      <div
        style={{
          width: 280,
          minWidth: 280,
          borderRight: '1px solid var(--border-default)',
          display: 'flex',
          flexDirection: 'column',
          background: 'var(--bg-primary)',
        }}
      >
        {/* Header */}
        <div style={{ padding: '20px 16px 12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <span style={{ fontSize: 22 }}>📚</span>
            <span style={{ fontSize: 16, fontWeight: 700 }}>技术文档库</span>
            <button
              onClick={() => { toggleTheme(); setThemeState(getTheme()) }}
              style={{
                marginLeft: 'auto',
                padding: '4px 10px',
                borderRadius: 12,
                border: '1px solid var(--border-default)',
                background: 'var(--bg-elevated)',
                color: 'var(--text-secondary)',
                fontSize: 12,
                cursor: 'pointer',
              }}
            >
              {theme === 'dark' ? '☀️' : '🌙'}
            </button>
          </div>
          <input
            type="text"
            placeholder="搜索文档..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              width: '100%',
              padding: '8px 12px',
              borderRadius: 8,
              border: '1px solid var(--border-default)',
              background: 'var(--bg-surface)',
              color: 'var(--text-primary)',
              fontSize: 13,
              outline: 'none',
              boxSizing: 'border-box',
            }}
          />
        </div>

        {/* 文档列表 */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px 16px' }}>
          {categories.map((cat) => {
            const catDocs = filteredDocs.filter((d) => d.category === cat)
            if (catDocs.length === 0) return null
            return (
              <div key={cat} style={{ marginBottom: 8 }}>
                <div
                  style={{
                    padding: '8px 12px',
                    fontSize: 11,
                    fontWeight: 700,
                    color: 'var(--text-muted)',
                    textTransform: 'uppercase',
                    letterSpacing: 0.5,
                  }}
                >
                  {cat}
                </div>
                {catDocs.map((doc) => (
                  <button
                    key={doc.id}
                    onClick={() => setActiveId(doc.id)}
                    style={{
                      width: '100%',
                      textAlign: 'left',
                      padding: '10px 12px',
                      borderRadius: 8,
                      border: 'none',
                      background: activeId === doc.id ? 'var(--bg-hover)' : 'transparent',
                      color: activeId === doc.id ? 'var(--text-primary)' : 'var(--text-secondary)',
                      fontSize: 13,
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      transition: 'all 0.15s',
                      fontWeight: activeId === doc.id ? 600 : 400,
                    }}
                  >
                    <span>{doc.icon}</span>
                    <span style={{ lineHeight: 1.4 }}>{doc.title}</span>
                  </button>
                ))}
              </div>
            )
          })}
        </div>

        {/* 底部信息 */}
        <div
          style={{
            padding: '12px 16px',
            borderTop: '1px solid var(--border-default)',
            fontSize: 11,
            color: 'var(--text-muted)',
          }}
        >
          共 {docs.length} 篇文档 · 实时渲染
        </div>
      </div>

      {/* 中间内容区 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* 顶部标题栏 */}
        <div
          style={{
            padding: '16px 24px',
            borderBottom: '1px solid var(--border-default)',
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            background: 'var(--bg-primary)',
          }}
        >
          <span style={{ fontSize: 20 }}>{activeDoc.icon}</span>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: 'var(--text-primary)' }}>
            {activeDoc.title}
          </h1>
          <span
            style={{
              marginLeft: 'auto',
              fontSize: 12,
              padding: '4px 10px',
              borderRadius: 12,
              background: 'var(--bg-hover)',
              color: 'var(--text-muted)',
            }}
          >
            {activeDoc.category}
          </span>
        </div>

        {/* 内容 + 右侧目录 */}
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          <div
            style={{
              flex: 1,
              overflowY: 'auto',
              padding: '24px 32px',
              maxWidth: 800,
            }}
          >
            <MarkdownRenderer source={activeDoc.source} />
            <div style={{ height: 60 }} />
          </div>

          {/* 右侧 TOC 快速导航 */}
          {toc.length > 0 && (
            <div
              style={{
                width: 220,
                minWidth: 220,
                borderLeft: '1px solid var(--border-default)',
                padding: '20px 16px',
                overflowY: 'auto',
                background: 'var(--bg-primary)',
              }}
            >
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 700,
                  color: 'var(--text-muted)',
                  marginBottom: 12,
                  textTransform: 'uppercase',
                  letterSpacing: 0.5,
                }}
              >
                目录
              </div>
              {toc.map((h, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: '4px 0',
                    paddingLeft: (h.level - 1) * 12,
                    fontSize: h.level === 1 ? 13 : 12,
                    fontWeight: h.level === 1 ? 600 : 400,
                    color: 'var(--text-secondary)',
                    lineHeight: 1.5,
                    cursor: 'pointer',
                    borderRadius: 4,
                  }}
                  onClick={() => {
                    // 简单滚动到对应内容（通过heading文本匹配）
                    const el = document.querySelector(`[data-heading="${encodeURIComponent(h.text)}"]`)
                    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
                  }}
                >
                  {h.text}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default DocsReader
