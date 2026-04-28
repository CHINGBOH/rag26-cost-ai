/**
 * 自学习看板 — 后端分析作业尚未启用，整页显示占位
 */

import { PageHeader } from '../components/common/PageHeader';
import './LearningPage.css';

export const LearningPage: React.FC = () => (
  <div className="learning-page">
    <PageHeader title="自学习看板" subtitle="知识库迭代与评估指标跟踪" />

    <div className="learn-placeholder-card">
      <div className="learn-placeholder-tag">未启用</div>
      <h2 className="learn-placeholder-title">自学习流水线尚未上线</h2>
      <p className="learn-placeholder-desc">
        本看板将在后端日级分析作业接入后展示评估分趋势、反馈分布、知识缺口与待审核片段。
      </p>

      <div className="learn-pipeline-outline">
        <div className="learn-pipeline-step">
          <span className="learn-step-index">01</span>
          <div className="learn-step-text">
            <div className="learn-step-title">采集反馈</div>
            <div className="learn-step-desc">用户点赞 / 点踩与对话记录入库</div>
          </div>
        </div>
        <div className="learn-pipeline-step">
          <span className="learn-step-index">02</span>
          <div className="learn-step-text">
            <div className="learn-step-title">分析知识缺口</div>
            <div className="learn-step-desc">每日凌晨批量扫描负反馈与低置信度问答</div>
          </div>
        </div>
        <div className="learn-pipeline-step">
          <span className="learn-step-index">03</span>
          <div className="learn-step-text">
            <div className="learn-step-title">候选片段审核</div>
            <div className="learn-step-desc">生成补充片段提交人工审核</div>
          </div>
        </div>
        <div className="learn-pipeline-step">
          <span className="learn-step-index">04</span>
          <div className="learn-step-text">
            <div className="learn-step-title">入库与评估</div>
            <div className="learn-step-desc">通过后入库、刷新向量索引、统计满意率变化</div>
          </div>
        </div>
      </div>
    </div>
  </div>
);
