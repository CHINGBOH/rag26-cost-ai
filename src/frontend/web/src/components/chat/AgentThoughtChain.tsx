/**
 * AgentThoughtChain — 使用 Ant Design X 的 Think + ThoughtChain
 * 将 RAG Agent 执行步骤可视化展示在对话框中
 */

import React, { useMemo } from 'react';
import { Think, ThoughtChain } from '@ant-design/x';
import type { ThoughtChainItemType } from '@ant-design/x/es/thought-chain/index';
import type { RagProcessStep } from '@rag/shared';

interface AgentThoughtChainProps {
  steps: RagProcessStep[];
  isStreaming?: boolean;
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

  return (
    <Think
      loading={!!isStreaming}
      defaultExpanded
    >
      <ThoughtChain items={items} />
    </Think>
  );
};

export default AgentThoughtChain;
