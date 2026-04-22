/**
 * 代码执行器组件
 * 检测消息中的代码块并支持执行
 * - JS/TS: 浏览器内沙箱
 * - Python: 后端 Docker 沙箱 /api/v1/sandbox/execute
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import { CodeExecutionResult } from '@rag/shared';
import { chatFlowConfig } from '../../config';
import './Chat.css';

const TOOLTIPS = chatFlowConfig.ui.tooltips;
const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

interface CodeBlockProps {
  code: string;
  language: string;
  autoRun?: boolean;
  onExecute?: (result: CodeExecutionResult) => void;
}

export const ExecutableCodeBlock: React.FC<CodeBlockProps> = ({
  code,
  language,
  autoRun = false,
  onExecute
}) => {
  const [isExecuting, setIsExecuting] = useState(false);
  const [result, setResult] = useState<CodeExecutionResult | null>(null);
  const [isExpanded, setIsExpanded] = useState(true);
  const hasAutoRun = useRef(false);

  const isPython = language === 'python' || language === 'py';
  const isJsTs = language === 'typescript' || language === 'javascript';
  const isExecutable = isPython || isJsTs;

  const executeCode = useCallback(async () => {
    if (!isExecutable) return;
    setIsExecuting(true);
    const startTime = Date.now();
    try {
      let execResult: CodeExecutionResult;

      if (isPython) {
        // 后端 Docker 沙箱
        const resp = await fetch(`${API_BASE}/api/v1/sandbox/execute`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code }),
        });
        const data = await resp.json();
        execResult = {
          code,
          language: 'python',
          status: data.status === 'success' ? 'success' : 'error',
          result: data.result,
          output: data.output,
          error: data.error,
          executionTime: Date.now() - startTime,
          timestamp: Date.now(),
        };
      } else {
        // 浏览器内 JS/TS 沙箱
        const sandbox = createJsSandbox();
        const sandboxResult = await sandbox.execute(code);
        execResult = {
          code,
          language: language as 'typescript' | 'javascript',
          status: 'success',
          result: sandboxResult.result,
          output: sandboxResult.output,
          executionTime: Date.now() - startTime,
          timestamp: Date.now(),
        };
      }

      setResult(execResult);
      onExecute?.(execResult);
    } catch (error) {
      const execResult: CodeExecutionResult = {
        code,
        language: language as 'typescript' | 'javascript',
        status: 'error',
        error: error instanceof Error ? error.message : String(error),
        executionTime: Date.now() - startTime,
        timestamp: Date.now(),
      };
      setResult(execResult);
      onExecute?.(execResult);
    } finally {
      setIsExecuting(false);
    }
  }, [code, language, isPython, isExecutable, onExecute]);

  // Auto-run Python blocks when the AI injects calculation code.
  // Guard with hasAutoRun inside the timer so StrictMode double-invocation doesn't skip it.
  useEffect(() => {
    if (!autoRun || !isPython) return;
    const timer = setTimeout(() => {
      if (!hasAutoRun.current) {
        hasAutoRun.current = true;
        executeCode();
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [autoRun, isPython, executeCode]);

  const copyCode = () => navigator.clipboard.writeText(code);

  return (
    <div className="code-block-container">
      {/* 头部 */}
      <div className="code-block-header">
        <div className="header-left">
          <span className={`lang-badge ${isPython ? 'python' : ''}`}>{language}</span>
          {isPython && <span className="sandbox-badge">🐳 Docker沙箱</span>}
          {isPython && autoRun && !result && !isExecuting && <span className="sandbox-badge auto">⚡ 自动运行</span>}
          {isExecuting && <span className="sandbox-badge running">⏳ 计算中...</span>}
          {result?.status === 'success' && <span className="exec-badge success">✓ 执行成功</span>}
          {result?.status === 'error' && <span className="exec-badge error">✗ 执行失败</span>}
        </div>
        <div className="header-actions">
          <button className="action-btn" onClick={copyCode} title={TOOLTIPS.copy}>📋</button>
          <button
            className="action-btn"
            onClick={() => setIsExpanded(!isExpanded)}
            title={isExpanded ? TOOLTIPS.collapse : TOOLTIPS.expand}
          >
            {isExpanded ? '▼' : '▶'}
          </button>
        </div>
      </div>

      {/* 代码内容 */}
      {isExpanded && (
        <div className="code-content-wrapper">
          <pre className="code-block"><code>{code}</code></pre>

          {isExecutable && !result && !autoRun && (
            <div className="code-actions">
              <button className="execute-btn" onClick={executeCode} disabled={isExecuting}>
                {isExecuting ? (
                  <><span className="spinner">◐</span> 执行中...</>
                ) : (
                  <><span>▶</span> {isPython ? '在沙箱中运行' : '运行代码'}</>
                )}
              </button>
            </div>
          )}
        </div>
      )}

      {/* 执行结果 */}
      {result && (
        <div className={`execution-result ${result.status}`}>
          <div className="result-header">
            <span>执行结果</span>
            <span className="exec-time">{result.executionTime}ms</span>
            {result.status === 'success' && (
              <button className="rerun-btn" onClick={executeCode} disabled={isExecuting}>重新运行</button>
            )}
          </div>

          {result.status === 'success' ? (
            <div className="result-output">
              {result.output && (
                <div className="output-section">
                  <div className="section-label">输出:</div>
                  <SandboxOutput output={result.output} />
                </div>
              )}
              {result.result !== undefined && result.result !== '' && (
                <div className="result-section">
                  <div className="section-label">返回值:</div>
                  <pre className="result-content">{formatResult(result.result)}</pre>
                </div>
              )}
            </div>
          ) : (
            <div className="error-output">
              <div className="error-label">错误:</div>
              <pre className="error-content">{result.error}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// 智能输出渲染：检测 Markdown 表格后渲染为 HTML 表格
const SandboxOutput: React.FC<{ output: string }> = ({ output }) => {
  const lines = output.trim().split('\n');
  const isMarkdownTable = lines.length >= 2 && lines[0].startsWith('|') && lines[1].includes('---');

  if (isMarkdownTable) {
    const headers = lines[0].split('|').map(s => s.trim()).filter(Boolean);
    const rows = lines.slice(2).filter(l => l.startsWith('|')).map(
      l => l.split('|').map(s => s.trim()).filter(Boolean)
    );
    return (
      <div className="sandbox-table-wrapper">
        <table className="sandbox-result-table">
          <thead>
            <tr>{headers.map((h, i) => <th key={i} dangerouslySetInnerHTML={{ __html: bold(h) }} />)}</tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri} className={ri % 2 === 0 ? 'even' : 'odd'}>
                {row.map((cell, ci) => <td key={ci} dangerouslySetInnerHTML={{ __html: bold(cell) }} />)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return <pre className="output-content">{output}</pre>;
};

function bold(s: string) {
  return s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
}

// 浏览器内 JS/TS 沙箱（保持原有逻辑）
function createJsSandbox() {
  return {
    execute: async (code: string): Promise<{ result: any; output: string }> => {
      const sandbox = {
        console: {
          logs: [] as string[],
          log: (...args: any[]) => {
            sandbox.console.logs.push(args.map(a =>
              typeof a === 'object' ? JSON.stringify(a, null, 2) : String(a)
            ).join(' '));
          },
          error: (...args: any[]) => {
            sandbox.console.logs.push('ERROR: ' + args.map(a => String(a)).join(' '));
          },
        },
        Math, JSON, Date, Array, Object, String, Number, Boolean, RegExp, Map, Set, Promise,
        setTimeout: (fn: Function, ms: number) => setTimeout(fn, Math.min(ms, 5000)),
        clearTimeout,
      };
      const fn = new Function('sandbox', `with(sandbox) { ${code} }`);
      const result = fn(sandbox);
      return { result, output: sandbox.console.logs.join('\n') };
    },
  };
}

function formatResult(result: any): string {
  if (result === null) return 'null';
  if (result === undefined) return 'undefined';
  if (typeof result === 'object') {
    try { return JSON.stringify(result, null, 2); } catch { return String(result); }
  }
  return String(result);
}

export function detectCodeBlocks(content: string): Array<{ code: string; language: string; index: number }> {
  const codeBlocks: Array<{ code: string; language: string; index: number }> = [];
  const regex = /```(\w+)?\n([\s\S]*?)```/g;
  let match;
  while ((match = regex.exec(content)) !== null) {
    codeBlocks.push({ language: match[1] || 'text', code: match[2].trim(), index: match.index });
  }
  return codeBlocks;
}

export function detectCalculationNeed(content: string): boolean {
  const keywords = ['计算', '算一下', '等于多少', '结果是', 'calculate', 'compute', 'evaluate', '+', '-', '*', '/', '=', '**', '%'];
  return keywords.some(k => content.toLowerCase().includes(k.toLowerCase()));
}

export const InlineCalculator: React.FC<{ expression: string; onCalculate: (result: string) => void }> = ({ expression, onCalculate }) => {
  const [isCalculating, setIsCalculating] = useState(false);
  const calculate = () => {
    setIsCalculating(true);
    try {
      const result = new Function(`return (${expression})`)();
      onCalculate(String(result));
    } catch { onCalculate('计算错误'); }
    finally { setIsCalculating(false); }
  };
  return (
    <button className="inline-calc-btn" onClick={calculate} disabled={isCalculating} title={TOOLTIPS.calculate}>
      {isCalculating ? '◐' : '🧮'}
    </button>
  );
};
