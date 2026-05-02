/**
 * FeedbackModal — 详细打分弹窗
 * 触发方式：点击 👍/👎 立即提交基础 rating，同时弹出此模态框收集详情（可选）。
 */

import { useState } from 'react';
import './FeedbackModal.css';

export interface FeedbackDetail {
  overall_rating: number;   // 1-5
  rating_relevance?: number;
  rating_accuracy?: number;
  rating_completeness?: number;
  praise?: string;
  criticism?: string;
  suggestion?: string;
  tags?: string[];
}

interface Props {
  initialRating: 1 | -1;   // from thumb click
  onSubmit: (detail: FeedbackDetail) => void;
  onClose: () => void;
}

const QUICK_TAGS_NEGATIVE = ['答非所问', '数据过时', '缺少依据', '回答太短', '格式混乱', '计算错误'];
const QUICK_TAGS_POSITIVE = ['准确详细', '有计算过程', '引用来源清晰', '图表清晰', '推荐收藏'];

function StarRow({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div className="fm-star-row">
      <span className="fm-star-label">{label}</span>
      <div className="fm-stars">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            className={`fm-star ${n <= value ? 'filled' : ''}`}
            onClick={() => onChange(n)}
            aria-label={`${n}星`}
          >★</button>
        ))}
      </div>
      <span className="fm-star-num">{value > 0 ? value : '—'}</span>
    </div>
  );
}

export function FeedbackModal({ initialRating, onSubmit, onClose }: Props) {
  const [overall, setOverall] = useState<number>(initialRating === 1 ? 5 : 1);
  const [relevance, setRelevance] = useState(0);
  const [accuracy, setAccuracy] = useState(0);
  const [completeness, setCompleteness] = useState(0);
  const [praise, setPraise] = useState('');
  const [criticism, setCriticism] = useState('');
  const [suggestion, setSuggestion] = useState('');
  const [tags, setTags] = useState<string[]>([]);

  const allTags = initialRating === 1 ? QUICK_TAGS_POSITIVE : QUICK_TAGS_NEGATIVE;

  const toggleTag = (t: string) => {
    setTags((prev) => prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]);
  };

  const handleSubmit = () => {
    onSubmit({
      overall_rating: overall,
      rating_relevance: relevance || undefined,
      rating_accuracy: accuracy || undefined,
      rating_completeness: completeness || undefined,
      praise: praise.trim() || undefined,
      criticism: criticism.trim() || undefined,
      suggestion: suggestion.trim() || undefined,
      tags: tags.length > 0 ? tags : undefined,
    });
  };

  return (
    <div className="fm-overlay" onClick={onClose}>
      <div className="fm-panel" onClick={(e) => e.stopPropagation()}>
        <div className="fm-header">
          <span>{initialRating === 1 ? '👍 好评点评' : '👎 差评点评'}</span>
          <button className="fm-close" onClick={onClose}>✕</button>
        </div>

        <div className="fm-body">
          <div className="fm-section">
            <div className="fm-section-title">总体评分</div>
            <StarRow label="总体" value={overall} onChange={setOverall} />
            <StarRow label="相关性" value={relevance} onChange={setRelevance} />
            <StarRow label="准确性" value={accuracy} onChange={setAccuracy} />
            <StarRow label="完整性" value={completeness} onChange={setCompleteness} />
          </div>

          <div className="fm-section">
            <div className="fm-section-title">快速标签</div>
            <div className="fm-tags">
              {allTags.map((t) => (
                <button
                  key={t}
                  type="button"
                  className={`fm-tag ${tags.includes(t) ? 'active' : ''}`}
                  onClick={() => toggleTag(t)}
                >{t}</button>
              ))}
            </div>
          </div>

          <div className="fm-section">
            <div className="fm-section-title">文字点评（可选）</div>
            <textarea
              className="fm-textarea"
              placeholder="好在哪里？"
              value={praise}
              onChange={(e) => setPraise(e.target.value)}
              rows={2}
            />
            <textarea
              className="fm-textarea"
              placeholder="差在哪里？"
              value={criticism}
              onChange={(e) => setCriticism(e.target.value)}
              rows={2}
            />
            <textarea
              className="fm-textarea"
              placeholder="建议如何改进？"
              value={suggestion}
              onChange={(e) => setSuggestion(e.target.value)}
              rows={2}
            />
          </div>
        </div>

        <div className="fm-footer">
          <button className="fm-btn-skip" onClick={onClose}>跳过</button>
          <button className="fm-btn-submit" onClick={handleSubmit}>提交点评</button>
        </div>
      </div>
    </div>
  );
}
