/**
 * 专家判断详情卡
 * 展示 LLM 专家的判断结果
 */

import { ExpertJudgmentResponse } from '@rag/shared';

interface ExpertJudgmentCardProps {
  judgment: ExpertJudgmentResponse;
}

const decisionLabels: Record<string, { label: string; color: string }> = {
  satisfy: { label: '满意，停止递归', color: 'var(--color-success)' },
  continue: { label: '继续深挖', color: 'var(--color-primary)' },
  query_external: { label: '查询外部', color: 'var(--color-warning)' },
  human_review: { label: '需人工审核', color: 'var(--color-error)' }
};

const focusLabels: Record<string, string> = {
  deeper: '深入检索',
  broader: '扩大范围',
  clarify_contradiction: '澄清矛盾'
};

export const ExpertJudgmentCard: React.FC<ExpertJudgmentCardProps> = ({ judgment }) => {
  const decision = decisionLabels[judgment.decision] || { label: judgment.decision, color: 'var(--text-muted)' };

  return (
    <div className="expert-judgment-card">
      <div className="judgment-header" style={{ borderColor: decision.color }}>
        <span className="decision-badge" style={{ backgroundColor: decision.color }}>
          {decision.label}
        </span>
        <span className="risk-indicator">
          饱和: {judgment.boundaryAssessment.saturationLevel} | 
          风险: {judgment.boundaryAssessment.riskOfOverthinking}
        </span>
      </div>

      <div className="judgment-reasoning">
        <h4>判断理由</h4>
        <p>{judgment.reasoning}</p>
      </div>

      {judgment.continueStrategy && (
        <div className="continue-strategy">
          <h4>下一步策略</h4>
          <div className="focus-badge">
            {focusLabels[judgment.continueStrategy.focus] || judgment.continueStrategy.focus}
          </div>
          <ul className="suggested-queries">
            {judgment.continueStrategy.suggestedQueries.map((query, idx) => (
              <li key={idx}>{query}</li>
            ))}
          </ul>
        </div>
      )}

      {judgment.externalQuery && (
        <div className="external-query">
          <h4>外部查询</h4>
          <div className="query-target">
            目标: {judgment.externalQuery.target}
          </div>
          <div className="query-text">
            {judgment.externalQuery.query}
          </div>
        </div>
      )}
    </div>
  );
};
