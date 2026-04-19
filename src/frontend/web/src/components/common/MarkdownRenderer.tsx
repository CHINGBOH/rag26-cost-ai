import React from 'react'

interface Props {
  source: string
}

/* 简易 Markdown → React 渲染器（支持 GFM 常用语法） */
const MarkdownRenderer: React.FC<Props> = ({ source }) => {
  const lines = source.split('\n')
  const elements: React.ReactNode[] = []
  let i = 0
  let key = 0

  const nextKey = () => `md-${key++}`

  // 行内样式解析
  const parseInline = (text: string): React.ReactNode => {
    const parts: React.ReactNode[] = []
    let remaining = text
    let pid = 0

    const push = (node: React.ReactNode) => parts.push(<React.Fragment key={`inline-${pid++}`}>{node}</React.Fragment>)

    while (remaining.length > 0) {
      // 粗体 **text**
      const boldMatch = remaining.match(/^(.*?)\*\*(.+?)\*\*(.*)$/)
      if (boldMatch) {
        if (boldMatch[1]) push(parseInline(boldMatch[1]))
        push(<strong key={`b-${pid++}`} style={{ color: 'var(--text-primary)' }}>{boldMatch[2]}</strong>)
        remaining = boldMatch[3]
        continue
      }
      // 斜体 *text*（避开已处理的 **）
      const emMatch = remaining.match(/^(.*?)\*(.+?)\*(.*)$/)
      if (emMatch) {
        if (emMatch[1]) push(parseInline(emMatch[1]))
        push(<em key={`em-${pid++}`}>{emMatch[2]}</em>)
        remaining = emMatch[3]
        continue
      }
      // 行内代码 `text`
      const codeMatch = remaining.match(/^(.*?)`(.+?)`(.*)$/)
      if (codeMatch) {
        if (codeMatch[1]) push(parseInline(codeMatch[1]))
        push(
          <code
            key={`ic-${pid++}`}
            style={{
              background: 'var(--bg-surface)',
              padding: '2px 6px',
              borderRadius: 4,
              fontSize: '0.9em',
              fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
              color: '#f59e0b',
            }}
          >
            {codeMatch[2]}
          </code>
        )
        remaining = codeMatch[3]
        continue
      }
      // 链接 [text](url)
      const linkMatch = remaining.match(/^(.*?)\[(.+?)\]\((.+?)\)(.*)$/)
      if (linkMatch) {
        if (linkMatch[1]) push(parseInline(linkMatch[1]))
        push(
          <a
            key={`a-${pid++}`}
            href={linkMatch[3]}
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: '#4f46e5', textDecoration: 'underline' }}
          >
            {linkMatch[2]}
          </a>
        )
        remaining = linkMatch[4]
        continue
      }
      // 纯文本
      push(remaining)
      break
    }
    return <>{parts}</>
  }

  while (i < lines.length) {
    const line = lines[i]

    // 空行
    if (line.trim() === '') {
      i++
      continue
    }

    // 分隔线
    if (/^\s*---+\s*$/.test(line) || /^\s*\*\*\*+\s*$/.test(line)) {
      elements.push(
        <hr
          key={nextKey()}
          style={{ border: 'none', borderTop: '1px solid var(--border-default)', margin: '24px 0' }}
        />
      )
      i++
      continue
    }

    // 代码块
    if (line.startsWith('```')) {
      const lang = line.slice(3).trim()
      const codeLines: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) {
        codeLines.push(lines[i])
        i++
      }
      i++ // skip ```
      elements.push(
        <pre
          key={nextKey()}
          style={{
            background: '#1e1e2e',
            color: '#cdd6f4',
            padding: 16,
            borderRadius: 10,
            fontSize: 13,
            lineHeight: 1.6,
            overflowX: 'auto',
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
            margin: '16px 0',
          }}
        >
          {lang && (
            <div style={{ fontSize: 11, color: '#6c7086', marginBottom: 8, textTransform: 'uppercase' }}>
              {lang}
            </div>
          )}
          <code>{codeLines.join('\n')}</code>
        </pre>
      )
      continue
    }

    // 表格
    if (line.startsWith('|')) {
      const tableRows: string[][] = []
      while (i < lines.length && lines[i].startsWith('|')) {
        const cells = lines[i]
          .split('|')
          .map((c) => c.trim())
          .filter((c, idx, arr) => idx > 0 && idx < arr.length - 1 || (idx === 0 && c !== '') || (idx === arr.length - 1 && c !== ''))
        // 跳过表头分隔行 |---|---|
        if (!cells.every((c) => /^[-:]+$/.test(c))) {
          tableRows.push(cells)
        }
        i++
      }
      if (tableRows.length > 0) {
        elements.push(
          <div key={nextKey()} style={{ overflowX: 'auto', margin: '16px 0' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--border-default)' }}>
                  {tableRows[0].map((cell, idx) => (
                    <th
                      key={idx}
                      style={{
                        padding: '10px 12px',
                        textAlign: 'left',
                        fontWeight: 700,
                        color: 'var(--text-primary)',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {parseInline(cell)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tableRows.slice(1).map((row, ridx) => (
                  <tr key={ridx} style={{ borderBottom: '1px solid var(--border-default)' }}>
                    {row.map((cell, cidx) => (
                      <td
                        key={cidx}
                        style={{
                          padding: '8px 12px',
                          color: 'var(--text-secondary)',
                          lineHeight: 1.6,
                        }}
                      >
                        {parseInline(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      }
      continue
    }

    // 引用块
    if (line.startsWith('>')) {
      const quoteLines: string[] = []
      while (i < lines.length && lines[i].startsWith('>')) {
        quoteLines.push(lines[i].slice(1).trim())
        i++
      }
      elements.push(
        <blockquote
          key={nextKey()}
          style={{
            borderLeft: '4px solid #4f46e5',
            padding: '12px 16px',
            margin: '16px 0',
            background: 'var(--bg-surface)',
            borderRadius: '0 8px 8px 0',
            color: 'var(--text-secondary)',
            fontStyle: 'italic',
          }}
        >
          {parseInline(quoteLines.join(' '))}
        </blockquote>
      )
      continue
    }

    // 标题
    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/)
    if (headingMatch) {
      const level = headingMatch[1].length
      const text = headingMatch[2].trim()
      const sizes = [28, 24, 20, 18, 16, 14]
      const margins = [32, 24, 20, 16, 14, 12]
      const Tag = `h${level}` as keyof JSX.IntrinsicElements
      elements.push(
        <Tag
          key={nextKey()}
          style={{
            fontSize: sizes[level - 1],
            fontWeight: 800,
            color: 'var(--text-primary)',
            marginTop: margins[level - 1],
            marginBottom: 12,
            lineHeight: 1.3,
          }}
        >
          {parseInline(text)}
        </Tag>
      )
      i++
      continue
    }

    // 无序列表
    if (/^(\s*)[-*+]\s+/.test(line)) {
      const indent = line.match(/^(\s*)/)![1].length
      const listItems: { text: string; children: string[] }[] = []
      let current: { text: string; children: string[] } | null = null

      while (i < lines.length) {
        const match = lines[i].match(/^(\s*)[-*+]\s+(.+)$/)
        if (!match) break
        const itemIndent = match[1].length
        if (itemIndent !== indent) break
        current = { text: match[2], children: [] }
        listItems.push(current)
        i++
        // 收集后续缩进行作为子内容（简化处理）
        while (i < lines.length && lines[i].startsWith(' ') && !lines[i].match(/^\s*[-*+]\s+/)) {
          current.children.push(lines[i].trim())
          i++
        }
      }
      elements.push(
        <ul key={nextKey()} style={{ paddingLeft: 20, margin: '12px 0', color: 'var(--text-secondary)', lineHeight: 1.8 }}>
          {listItems.map((item, idx) => (
            <li key={idx}>
              {parseInline(item.text)}
              {item.children.length > 0 && (
                <div style={{ marginTop: 4, fontSize: '0.95em', opacity: 0.85 }}>
                  {item.children.map((c, cidx) => (
                    <div key={cidx}>{parseInline(c)}</div>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )
      continue
    }

    // 有序列表
    if (/^(\s*)\d+\.\s+/.test(line)) {
      const listItems: string[] = []
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        listItems.push(lines[i].replace(/^\s*\d+\.\s+/, ''))
        i++
      }
      elements.push(
        <ol key={nextKey()} style={{ paddingLeft: 24, margin: '12px 0', color: 'var(--text-secondary)', lineHeight: 1.8 }}>
          {listItems.map((item, idx) => (
            <li key={idx}>{parseInline(item)}</li>
          ))}
        </ol>
      )
      continue
    }

    // 普通段落（支持多行合并）
    const paraLines: string[] = [line]
    i++
    while (i < lines.length && lines[i].trim() !== '' && !lines[i].startsWith('#') && !lines[i].startsWith('-') && !lines[i].startsWith('*') && !lines[i].startsWith('>') && !lines[i].startsWith('|') && !lines[i].startsWith('```') && !/^\s*---+\s*$/.test(lines[i]) && !/^\s*\d+\.\s+/.test(lines[i])) {
      paraLines.push(lines[i])
      i++
    }
    elements.push(
      <p key={nextKey()} style={{ lineHeight: 1.8, color: 'var(--text-secondary)', margin: '12px 0' }}>
        {parseInline(paraLines.join(' '))}
      </p>
    )
  }

  return <div style={{ fontSize: 15 }}>{elements}</div>
}

export default MarkdownRenderer
