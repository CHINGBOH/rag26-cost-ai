/**
 * 时间线图组件
 * 用于展示递归过程的时间线
 */

import { useMemo } from 'react';
import './Charts.css';

interface TimelineEvent {
  time: number;
  label: string;
  state: 'pending' | 'running' | 'completed' | 'error';
  duration?: number;
  details?: string;
}

interface TimelineChartProps {
  events: TimelineEvent[];
  height?: number;
  className?: string;
}

export const TimelineChart: React.FC<TimelineChartProps> = ({
  events,
  height = 300,
  className = ''
}) => {
  const sortedEvents = useMemo(() => {
    return [...events].sort((a, b) => a.time - b.time);
  }, [events]);

  const stateColors = {
    pending: 'var(--text-muted)',
    running: 'var(--color-primary)',
    completed: 'var(--color-success)',
    error: 'var(--color-error)'
  };

  const stateIcons = {
    pending: '○',
    running: '◐',
    completed: '●',
    error: '✕'
  };

  if (sortedEvents.length === 0) {
    return <div className={`timeline-chart empty ${className}`}>暂无事件</div>;
  }

  return (
    <div className={`timeline-chart ${className}`} style={{ height }}>
      <div className="timeline-line" />
      
      <div className="timeline-events">
        {sortedEvents.map((event, index) => (
          <div 
            key={index} 
            className={`timeline-event ${event.state}`}
            style={{ animationDelay: `${index * 0.1}s` }}
          >
            <div 
              className="timeline-dot"
              style={{ color: stateColors[event.state] }}
            >
              {stateIcons[event.state]}
            </div>
            
            <div className="timeline-content">
              <div className="timeline-label">{event.label}</div>
              <div className="timeline-time">
                {new Date(event.time).toLocaleTimeString()}
                {event.duration && (
                  <span className="timeline-duration">
                    (+{event.duration}ms)
                  </span>
                )}
              </div>
              {event.details && (
                <div className="timeline-details">{event.details}</div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
