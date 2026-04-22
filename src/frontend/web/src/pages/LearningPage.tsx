/**
 * Learning Dashboard — self-learning pipeline overview
 * Data will come from learning endpoints once implemented.
 */

import './LearningPage.css';

export const LearningPage: React.FC = () => {
  const statsCards = [
    { label: '总对话数', value: '—', icon: '💬' },
    { label: '平均评估分', value: '—', icon: '📊' },
    { label: '满意率', value: '—', icon: '😊' },
    { label: '知识缺口', value: '0', icon: '🔍' },
    { label: '待审核', value: '0', icon: '📝' },
    { label: '已批准片段', value: '0', icon: '✅' },
  ];

  return (
    <div className="learning-page">
      <h1>自学习看板</h1>
      <p className="page-subtitle">知识库迭代与评估指标跟踪</p>

      {/* Stats cards */}
      <div className="learn-stats-grid">
        {statsCards.map((card) => (
          <div key={card.label} className="learn-stat-card">
            <span className="learn-stat-icon">{card.icon}</span>
            <div className="learn-stat-value">{card.value}</div>
            <div className="learn-stat-label">{card.label}</div>
          </div>
        ))}
      </div>

      {/* Charts placeholder row */}
      <div className="learn-charts-row">
        <div className="learn-chart-card">
          <h3>评估分趋势</h3>
          <div className="learn-empty-chart">
            <span className="learn-empty-icon">📈</span>
            <p>暂无数据，分析作业每日 02:00 运行</p>
          </div>
        </div>
        <div className="learn-chart-card">
          <h3>反馈分布（👍 / 👎）</h3>
          <div className="learn-empty-chart">
            <span className="learn-empty-icon">📉</span>
            <p>暂无反馈数据</p>
          </div>
        </div>
      </div>

      {/* Knowledge gaps */}
      <div className="learn-card">
        <div className="learn-card-header">
          <h3>知识缺口</h3>
          <span className="learn-badge">0</span>
        </div>
        <div className="learn-empty-state">
          <span>🔍</span>
          <p>暂无数据，分析作业每日 02:00 运行</p>
        </div>
      </div>

      {/* Pending review */}
      <div className="learn-card">
        <div className="learn-card-header">
          <h3>待审核片段</h3>
          <span className="learn-badge">0</span>
        </div>
        <div className="learn-empty-state">
          <span>📝</span>
          <p>无待审核内容</p>
        </div>
      </div>

      {/* Pipeline info */}
      <div className="learn-info-box">
        <h4>🔄 自学习流水线</h4>
        <ol className="learn-pipeline-steps">
          <li>收集用户反馈（👍/👎）和对话记录</li>
          <li>每日凌晨 02:00 自动分析知识缺口</li>
          <li>生成候选补充片段并提交人工审核</li>
          <li>审核通过后自动入库并更新向量索引</li>
          <li>统计满意率变化，评估知识库改善效果</li>
        </ol>
      </div>
    </div>
  );
};
