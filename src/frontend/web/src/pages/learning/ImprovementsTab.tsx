import React from 'react';
import { ReviewsPanel } from '../../components/learning/ReviewsPanel';
import { ImprovementHistoryPanel } from '../../components/learning/ImprovementHistoryPanel';
import { ImprovementEvent } from '../../services/metricsApi';

interface ImprovementsTabProps {
  historyEvents: ImprovementEvent[];
  historySummary: any;
  onApprove: (eventId: number) => void;
  onReject: (eventId: number, reason: string) => void;
}

export const ImprovementsTab: React.FC<ImprovementsTabProps> = ({
  historyEvents,
  historySummary,
  onApprove,
  onReject,
}) => (
  <>
    <ReviewsPanel
      reviews={historyEvents.filter((e) => e.status === 'pending_review')}
      onApprove={onApprove}
      onReject={onReject}
    />
    <ImprovementHistoryPanel
      events={historyEvents}
      stats={{ summary: historySummary, effectiveness: historySummary }}
    />
  </>
);

export default ImprovementsTab;
