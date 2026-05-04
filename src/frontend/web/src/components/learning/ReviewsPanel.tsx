import React, { useState } from 'react';
import { ImprovementEvent, approveFix, rejectFix } from '../../services/metricsApi';
import { fmtDateTime } from '../../utils/dateUtils';
import './ReviewsPanel.css';

interface ReviewsPanelProps {
  reviews: ImprovementEvent[];
  onApprove: (eventId: number) => void;
  onReject: (eventId: number, reason: string) => void;
}

export const ReviewsPanel: React.FC<ReviewsPanelProps> = ({ reviews, onApprove, onReject }) => {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [rejectReason, setRejectReason] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState<number | null>(null);

  const handleApprove = async (eventId: number) => {
    setLoading(eventId);
    try {
      await approveFix(eventId);
      onApprove(eventId);
    } finally {
      setLoading(null);
    }
  };

  const handleReject = async (eventId: number) => {
    setLoading(eventId);
    try {
      const reason = rejectReason[eventId] || 'No reason provided';
      await rejectFix(eventId, reason);
      onReject(eventId, reason);
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="reviews-panel">
      <h3>待人工审核的修复建议 ({reviews.length})</h3>

      {reviews.length === 0 ? (
        <div className="empty">
          <p>✅ 没有待审核项</p>
          <p>所有修复建议均已自动应用或被拒绝</p>
        </div>
      ) : (
        <div className="review-items">
          {reviews.map((review) => (
            <div key={review.event_id} className="review-card">
              <div
                className="header"
                onClick={() => setExpandedId(expandedId === review.event_id ? null : review.event_id)}
              >
                <span className="timestamp">{fmtDateTime(review.timestamp)}</span>
                <span className="action">{review.action}</span>
                <span className={`risk mid`}>⚠️ 中风险</span>
                <span className="toggle">{expandedId === review.event_id ? '▼' : '▶'}</span>
              </div>

              {expandedId === review.event_id && (
                <div className="content">
                  <p className="description">{review.action}</p>

                  <div className="impact">
                    <div className="metric">
                      <span>修改前成功率</span>
                      <strong>{(review.before_rate * 100).toFixed(1)}%</strong>
                    </div>
                    <span className="arrow">→</span>
                    <div className="metric">
                      <span>修改后成功率</span>
                      <strong>{(review.after_rate * 100).toFixed(1)}%</strong>
                    </div>
                    <div className="delta">
                      <span>预期改进</span>
                      <strong className="positive">+{(review.delta * 100).toFixed(1)}%</strong>
                    </div>
                  </div>

                  {/* 拒绝原因输入 */}
                  <div className="actions">
                    <textarea
                      placeholder="如选择拒绝，请输入原因..."
                      value={rejectReason[review.event_id] || ''}
                      onChange={(e) => setRejectReason({ ...rejectReason, [review.event_id]: e.target.value })}
                    />
                    <div className="buttons">
                      <button
                        className="approve"
                        onClick={() => handleApprove(review.event_id)}
                        disabled={loading === review.event_id}
                      >
                        {loading === review.event_id ? '⏳...' : '✅ 批准'}
                      </button>
                      <button
                        className="reject"
                        onClick={() => handleReject(review.event_id)}
                        disabled={loading === review.event_id}
                      >
                        {loading === review.event_id ? '⏳...' : '❌ 拒绝'}
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
