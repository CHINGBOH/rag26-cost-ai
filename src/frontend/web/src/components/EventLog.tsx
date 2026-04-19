/**
 * 事件日志
 * 显示实时事件流
 */


import { DashboardEvent } from '@rag/shared';

interface EventLogProps {
  events: DashboardEvent[];
}

const eventTypeLabels: Record<string, string> = {
  state_change: '状态变更',
  recursion_round_start: '开始轮次',
  subquery_complete: '子查询完成',
  retrieval_complete: '检索完成',
  generation_complete: '生成完成',
  evaluation_complete: '评估完成',
  expert_judgment: '专家判断',
  boundary_detected: '边界检测',
  external_query_start: '外部查询开始',
  external_query_complete: '外部查询完成',
  anomaly_alert: '异常警告',
  human_review_required: '需人工审核',
  recursion_complete: '递归完成',
  session_created: '会话创建'
};

export const EventLog: React.FC<EventLogProps> = ({ events }) => {
  return (
    <div className="event-log">
      <h2>事件日志</h2>
      
      <div className="log-container">
        {events.slice(0, 50).map((event, index) => (
          <div key={`${event.timestamp}-${index}`} className="log-entry">
            <span className="timestamp">
              {new Date(event.timestamp).toLocaleTimeString()}
            </span>
            <span className="type">
              {eventTypeLabels[event.type] || event.type}
            </span>
            <span className="session-id">
              {event.sessionId.slice(0, 8)}...
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};
