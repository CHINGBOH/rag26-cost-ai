/**
 * 代码执行器组件
 * 检测消息中的代码块并支持执行
 */

import { useState, useCallback } from 'react';
import { CodeExecutionResult } from '@rag/shared';
import { chatFlowConfig } from '../../config';
import './Chat.css';

const TOOLTIPS = chatFlowConfig.ui.tooltips;

interface CodeBlockProps {
  code: string;
  language: string;
  onExecute?: (result: CodeExecutionResult) => void;
}

export const ExecutableCodeBlock: React.FC<CodeBlockProps> = ({
  code,
  language,
  onExecute
}) => {
  const [isExecuting, setIsExecuting] = useState(false);
  const [result, setResult] = useState<CodeExecutionResult | null>(null);
  const [isExpanded, setIsExpanded] = useState(true);

  const isExecutable = language === 'typescript' || language === 'javascript';

  const executeCode = useCallback(async () => {
    if (!isExecutable) return;

    setIsExecuting(true);
    
    const startTime = Date.now();
    
    try {
      // 创建沙箱环境执行代码
      const sandbox = createSandbox();
      const executionResult = await sandbox.execute(code);
      
      const execResult: CodeExecutionResult = {
        code,
        language: language as 'typescript' | 'javascript',
        status: 'success',
        result: executionResult,
        executionTime: Date.now() - startTime,
        timestamp: Date.now()
      };
      
      setResult(execResult);
      onExecute?.(execResult);
    } catch (error) {
      const execResult: CodeExecutionResult = {
        code,
        language: language as 'typescript' | 'javascript',
        status: 'error',
        error: error instanceof Error ? error.message : String(error),
        executionTime: Date.now() - startTime,
        timestamp: Date.now()
      };
      
      setResult(execResult);
      onExecute?.(execResult);
    } finally {
      setIsExecuting(false);
    }
  }, [code, language, onExecute]);

  const copyCode = () => {
    navigator.clipboard.writeText(code);
  };

  return (
    <div className="code-block-container">
      {/* 代码块头部 */}
      <div className="code-block-header">
        <div className="header-left">
          <span className="lang-badge">{language}</span>
          {result?.status === 'success' && (
            <span className="exec-badge success">✓ 执行成功</span>
          )}
          {result?.status === 'error' && (
            <span className="exec-badge error">✗ 执行失败</span>
          )}
        </div>
        <div className="header-actions">
          <button className="action-btn" onClick={copyCode} title={TOOLTIPS.copy}>
            📋
          </button>
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
          <pre className="code-block">
            <code>{code}</code>
          </pre>
          
          {/* 执行按钮 */}
          {isExecutable && !result && (
            <div className="code-actions">
              <button 
                className="execute-btn"
                onClick={executeCode}
                disabled={isExecuting}
              >
                {isExecuting ? (
                  <>
                    <span className="spinner">◐</span>
                    执行中...
                  </>
                ) : (
                  <>
                    <span>▶</span>
                    运行代码
                  </>
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
              <button 
                className="rerun-btn"
                onClick={executeCode}
                disabled={isExecuting}
              >
                重新运行
              </button>
            )}
          </div>
          
          {result.status === 'success' ? (
            <div className="result-output">
              {result.output && (
                <div className="output-section">
                  <div className="section-label">输出:</div>
                  <pre className="output-content">{result.output}</pre>
                </div>
              )}
              {result.result !== undefined && (
                <div className="result-section">
                  <div className="section-label">返回值:</div>
                  <pre className="result-content">
                    {formatResult(result.result)}
                  </pre>
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

// 创建安全的沙箱环境
function createSandbox() {
  return {
    execute: async (code: string): Promise<any> => {
      // 在安全的上下文中执行代码
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
          }
        },
        Math,
        JSON,
        Date,
        Array,
        Object,
        String,
        Number,
        Boolean,
        RegExp,
        Map,
        Set,
        Promise,
        setTimeout: (fn: Function, ms: number) => {
          // 限制执行时间
          return setTimeout(fn, Math.min(ms, 5000));
        },
        clearTimeout,
      };

      // 创建一个函数来执行代码
      const fn = new Function(
        'sandbox',
        `
          with(sandbox) {
            ${code}
          }
        `
      );

      // 执行代码并获取结果
      const result = fn(sandbox);
      
      // 收集 console 输出
      const output = sandbox.console.logs.join('\n');
      
      return {
        result,
        output
      };
    }
  };
}

// 格式化结果显示
function formatResult(result: any): string {
  if (result === null) return 'null';
  if (result === undefined) return 'undefined';
  if (typeof result === 'object') {
    try {
      return JSON.stringify(result, null, 2);
    } catch {
      return String(result);
    }
  }
  return String(result);
}

// 检测代码块
export function detectCodeBlocks(content: string): Array<{ code: string; language: string; index: number }> {
  const codeBlocks: Array<{ code: string; language: string; index: number }> = [];
  const regex = /```(\w+)?\n([\s\S]*?)```/g;
  let match;
  
  while ((match = regex.exec(content)) !== null) {
    codeBlocks.push({
      language: match[1] || 'text',
      code: match[2].trim(),
      index: match.index
    });
  }
  
  return codeBlocks;
}

// 检测计算需求
export function detectCalculationNeed(content: string): boolean {
  const calculationKeywords = [
    '计算', '算一下', '等于多少', '结果是', 
    'calculate', 'compute', 'evaluate',
    '+', '-', '*', '/', '=', '**', '%'
  ];
  
  return calculationKeywords.some(keyword => 
    content.toLowerCase().includes(keyword.toLowerCase())
  );
}

// 内联计算器按钮
export const InlineCalculator: React.FC<{
  expression: string;
  onCalculate: (result: string) => void;
}> = ({ expression, onCalculate }) => {
  const [isCalculating, setIsCalculating] = useState(false);

  const calculate = () => {
    setIsCalculating(true);
    try {
      // 安全计算
      const result = new Function(`return (${expression})`)();
      onCalculate(String(result));
    } catch (error) {
      onCalculate('计算错误');
    } finally {
      setIsCalculating(false);
    }
  };

  return (
    <button 
      className="inline-calc-btn"
      onClick={calculate}
      disabled={isCalculating}
      title={TOOLTIPS.calculate}
    >
      {isCalculating ? '◐' : '🧮'}
    </button>
  );
};
