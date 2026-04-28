/**
 * AgentThoughtChain — 轻量本地渲染，不依赖 Ant Design X
 * 将 RAG Agent 执行步骤可视化展示在对话框中
 */

import React, { useMemo } from 'react';
import type { RagProcessStep } from '@rag/shared';

interface AgentThoughtChainProps {
  steps: RagProcessStep[];
  isStreaming?: boolean;
}

type ThoughtChainStatus = 'loading' | 'success' | 'error' | undefined;

interface ThoughtChainItemType {
  key: string;
  title: string;
  status?: ThoughtChainStatus;
  description?: string;
  content?: React.ReactNode;
}

const STEP_TITLES: Record<string, string> = {
  intent_recognition: '理解问题',
  task_decomposition: '制定计划',
  query_generation: '生成查询',
  vector_retrieval: '向量检索',
  knowledge_retrieval: '知识检索',
  graph_retrieval: '图谱检索',
  reranking: '精排结果',
  prompt_assembly: '组装上下文',
  llm_generation: '综合分析',
  answer_formatting: '回答完成',
};

function stepToItem(step: RagProcessStep, index: number): ThoughtChainItemType {
  const tcStatus =
    step.status === 'running' ? 'loading' :
    step.status === 'completed' ? 'success' :
    step.status === 'failed' ? 'error' :
    undefined;

  const title = (step.data as Record<string, any>)?.label || STEP_TITLES[step.type] || step.type;

  // plan steps as a numbered list
  const planSteps = (step.data as Record<string, any>)?.planSteps as string[] | undefined;
  const content = planSteps && planSteps.length > 0
    ? (
      <ol style={{ margin: '4px 0 0', paddingLeft: 20, lineHeight: 1.7 }}>
        {planSteps.map((s, i) => <li key={i}>{s}</li>)}
      </ol>
    )
    : undefined;

  // latency badge
  const latencyMs = step.latency ?? (
    step.startTime && step.endTime ? step.endTime - step.startTime : undefined
  );
  const description = latencyMs !== undefined && step.status === 'completed'
    ? `${latencyMs}ms`
    : undefined;

  return {
    key: `${step.type}-${index}`,
    title,
    status: tcStatus,
    description,
    content,
  };
}

const AgentThoughtChain: React.FC<AgentThoughtChainProps> = ({ steps, isStreaming }) => {
  const items = useMemo((): ThoughtChainItemType[] => steps.map(stepToItem), [steps]);

  if (!steps.length) return null;

  const statusDot = (status?: ThoughtChainStatus) => {
    if (status === 'loading') return '⏳';
    if (status === 'success') return '✅';
    if (status === 'error') return '❌';
    return '•';
  };

  return (
    <div
      style={{
        border: '1px solid #e5e7eb',
        borderRadius: 8,
        padding: 12,
        marginTop: 8,
        background: '#fff',
      }}
    >
      <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 8 }}>
        {isStreaming ? '推理中…' : '推理过程'}
      </div>
      <div style={{ display: 'grid', gap: 8 }}>
        {items.map((item) => (
          <div key={item.key} style={{ border: '1px solid #f1f5f9', borderRadius: 6, padding: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
              <div style={{ fontSize: 13 }}>
                <span style={{ marginRight: 6 }}>{statusDot(item.status)}</span>
                {item.title}
              </div>
              {item.description && (
                <div style={{ fontSize: 12, color: '#6b7280' }}>{item.description}</div>
              )}
            </div>
            {item.content && <div style={{ marginTop: 6, fontSize: 13 }}>{item.content}</div>}
          </div>
        ))}
      </div>
    </div>
  );
};

export default AgentThoughtChain;
