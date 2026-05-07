"""
Layer 2 - Feedback Aggregation and Analysis
Analyzes user feedback trends to identify systemic issues
Issue #96
"""

import logging
import asyncio
from typing import Dict, List, Optional
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class FeedbackIssue:
    """Represents a feedback-based issue"""
    tag: str
    frequency: float  # 0-1, proportion of feedback mentioning this tag
    count: int  # absolute count
    weight: int  # frequency * weight from TAG_WEIGHTS
    
    def __repr__(self):
        return f"{self.tag}: {self.frequency:.1%} ({self.count}x, weight={self.weight})"


@dataclass
class FeedbackAnalysis:
    """Complete feedback analysis result"""
    window_days: int
    total_feedback: int
    negative_rate: float  # proportion with rating <= 2
    top_issues: List[FeedbackIssue]  # sorted by weight
    trending_problems: List[FeedbackIssue]  # issues with frequency >= 20%
    suggested_improvements: List[str]
    should_trigger: bool


class FeedbackAnalyzer:
    """
    Analyzes user feedback to identify systemic problems.
    Generates improvement suggestions and determines if learning should be triggered.
    """
    
    # Tag importance weights
    TAG_WEIGHTS = {
        '逻辑错误': 15,
        '工具失效': 12,
        '数据过时': 10,
        '缺少依据': 8,
        '返回缺失': 7,
        '理解不足': 6,
        '格式错误': 5,
    }
    
    # Thresholds
    TRENDING_THRESHOLD = 0.20  # 20% of feedback
    MIN_FEEDBACK_SAMPLES = 5  # Need at least 5 feedback to analyze
    TRIGGER_WEIGHT_THRESHOLD = 30  # Total weight > 30 to trigger
    
    def __init__(self, db_pool=None):
        """
        Initialize feedback analyzer.
        
        Args:
            db_pool: psycopg2.ThreadedConnectionPool or None
        """
        self.db_pool = db_pool

    @staticmethod
    def _feedback_ts_expression(data_type: Optional[str]) -> str:
        normalized = (data_type or "").lower()
        if normalized in {"double precision", "real", "numeric", "integer", "bigint", "smallint"}:
            return "to_timestamp(ts)"
        if normalized in {"timestamp with time zone", "timestamp without time zone"}:
            return "ts"
        return "created_at"

    def _detect_feedback_ts_expression(self, cursor) -> str:
        cursor.execute(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_name = 'rag_feedback' AND column_name = 'ts'
            """
        )
        row = cursor.fetchone()
        return self._feedback_ts_expression(row[0] if row else None)
    
    async def analyze_feedback_trends(self, window_days: int = 7) -> Optional[FeedbackAnalysis]:
        """
        Analyze feedback trends over a time window.
        
        Args:
            window_days: lookback period in days
            
        Returns:
            FeedbackAnalysis with trends and suggestions
        """
        if not self.db_pool:
            logger.warning("No DB pool, cannot analyze feedback")
            return None
        
        try:
            conn = self.db_pool.getconn()
            try:
                with conn.cursor() as cur:
                    ts_expr = self._detect_feedback_ts_expression(cur)
                    # Fetch recent feedback
                    cur.execute(
                        f"""
                        SELECT rating, tags, praise, criticism, suggestion
                        FROM rag_feedback
                        WHERE {ts_expr} > NOW() - (%s * INTERVAL '1 day')
                        ORDER BY {ts_expr} DESC
                        """,
                        (window_days,)
                    )
                    rows = cur.fetchall()
            finally:
                self.db_pool.putconn(conn)
            
            if not rows:
                logger.info(f"No feedback in last {window_days} days")
                return None
            
            # Analyze feedback
            tag_counter = Counter()
            negative_count = 0
            
            for rating, tags, praise, criticism, suggestion in rows:
                # Runtime semantics treat ratings <= 2 as negative feedback.
                if rating is not None and rating <= 2:
                    negative_count += 1
                
                # Count tags
                if tags:
                    for tag in tags:
                        tag_counter[tag] += 1
            
            negative_rate = negative_count / len(rows) if rows else 0
            
            # Compute weighted issues
            top_issues = []
            for tag, count in tag_counter.most_common():
                frequency = count / len(rows)
                weight = count * self.TAG_WEIGHTS.get(tag, 1)
                top_issues.append(FeedbackIssue(
                    tag=tag,
                    frequency=frequency,
                    count=count,
                    weight=weight
                ))
            
            # Identify trending problems (freq >= threshold)
            trending = [issue for issue in top_issues if issue.frequency >= self.TRENDING_THRESHOLD]
            
            # Generate suggestions
            suggestions = self._generate_suggestions(trending)
            
            # Decide if should trigger learning
            total_weight = sum(issue.weight for issue in trending)
            should_trigger = (len(rows) >= self.MIN_FEEDBACK_SAMPLES and 
                             total_weight > self.TRIGGER_WEIGHT_THRESHOLD)
            
            analysis = FeedbackAnalysis(
                window_days=window_days,
                total_feedback=len(rows),
                negative_rate=negative_rate,
                top_issues=sorted(top_issues, key=lambda x: x.weight, reverse=True),
                trending_problems=trending,
                suggested_improvements=suggestions,
                should_trigger=should_trigger
            )
            
            logger.info(f"📊 Feedback analysis: {len(rows)} feedback, "
                       f"{negative_rate:.1%} negative, {len(trending)} trending issues")
            
            return analysis
            
        except Exception as e:
            logger.error(f"Failed to analyze feedback: {e}")
            return None
    
    def _generate_suggestions(self, trending_issues: List[FeedbackIssue]) -> List[str]:
        """Generate improvement suggestions based on trending issues"""
        suggestions = []
        seen_tags = set()
        
        for issue in trending_issues:
            if issue.tag in seen_tags:
                continue
            seen_tags.add(issue.tag)
            
            if issue.tag == '逻辑错误':
                suggestions.append(
                    "审视推理流程和 prompt 设计，可能需要调整工具选择或路由策略"
                )
            elif issue.tag == '工具失效':
                suggestions.append(
                    "检查工具链路健康度，确认所有工具都在线，验证参数配置是否正确"
                )
            elif issue.tag == '数据过时':
                suggestions.append(
                    "检查数据源更新频率，考虑增加爬取频率或切换到实时 API"
                )
            elif issue.tag == '缺少依据':
                suggestions.append(
                    "增强检索策略，扩大检索范围或调整重排权重以获取更多源文档"
                )
            elif issue.tag == '返回缺失':
                suggestions.append(
                    "检查数据库连接和查询过滤逻辑，确保所有相关数据都被返回"
                )
            elif issue.tag == '理解不足':
                suggestions.append(
                    "改进查询理解模块，补充更多样本进行 few-shot 学习"
                )
            elif issue.tag == '格式错误':
                suggestions.append(
                    "审视输出格式化逻辑，确保符合用户期望的结构和可读性"
                )
        
        return suggestions
    
    async def trigger_if_needed(self) -> Optional[str]:
        """
        Analyze feedback and trigger learning loop if conditions met.
        
        Sprint 3: Routes through AdaptiveRetestScheduler if Feature Flag enabled.
        
        Returns:
            run_id if triggered, None otherwise
        """
        analysis = await self.analyze_feedback_trends()
        
        if not analysis or not analysis.should_trigger:
            return None
        
        try:
            # Sprint 3: Feature Flag control (#117)
            from config.feature_flags import is_feature_enabled
            from main import get_adaptive_retest_scheduler
            
            adaptive_scheduler = get_adaptive_retest_scheduler()
            trending_tags = [issue.tag for issue in analysis.trending_problems]
            
            if is_feature_enabled("LEARNING_USE_ADAPTIVE_SCHEDULER") and adaptive_scheduler:
                # 新路径：通过 AdaptiveRetestScheduler
                from app.agent.adaptive_retest_scheduler import RetestRequest, RetestPriority
                from datetime import datetime, timezone
                
                try:
                    question = f"Feedback analysis: {', '.join(trending_tags[:3])}"
                    question_hash = await adaptive_scheduler.request_retest(RetestRequest(
                        question=question,
                        source="feedback",
                        priority=RetestPriority.USER_FEEDBACK,
                        metadata={
                            "trigger": "feedback_analysis",
                            "trending_tags": trending_tags,
                            "total_feedback": analysis.total_feedback,
                            "negative_rate": analysis.negative_rate,
                            "top_issues": [{"tag": i.tag, "count": i.count, "frequency": i.frequency} for i in analysis.top_issues[:5]],
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    ))
                    
                    logger.info(f"✅ Feedback trigger queued via AdaptiveRetestScheduler: {question[:50]}... (hash={question_hash[:8]}...)")
                    return f"queued_{question_hash[:8]}"
                    
                except Exception as e:
                    logger.warning(f"Failed to queue via AdaptiveRetestScheduler, falling back to direct trigger: {e}")
            
            # 旧路径：直接触发（fallback）
            from app.agent.scheduler import get_scheduler
            
            scheduler = get_scheduler()
            if not scheduler:
                logger.warning("Scheduler not initialized, cannot trigger learning loop")
                return None
            
            reason = f"feedback_analysis_{'_'.join(trending_tags[:3])}"
            run_id = await scheduler.trigger_manual(reason=reason)
            
            logger.info(f"✅ Learning loop triggered via feedback analysis (direct): {run_id}")
            return run_id
            
        except Exception as e:
            logger.error(f"Failed to trigger learning loop: {e}")
            return None
    
    async def get_insights(self, window_days: int = 7) -> Optional[Dict]:
        """Get human-readable insights from feedback analysis"""
        analysis = await self.analyze_feedback_trends(window_days)
        
        if not analysis:
            return None
        
        return {
            'period_days': window_days,
            'total_feedback_count': analysis.total_feedback,
            'negative_feedback_rate': f"{analysis.negative_rate:.1%}",
            'top_issues': [
                {
                    'tag': issue.tag,
                    'frequency': f"{issue.frequency:.1%}",
                    'count': issue.count,
                    'weight': issue.weight
                }
                for issue in analysis.top_issues[:5]
            ],
            'trending_problems': [issue.tag for issue in analysis.trending_problems],
            'improvement_suggestions': analysis.suggested_improvements,
            'should_trigger_learning': analysis.should_trigger
        }


# Global instance
_analyzer = None


def init_feedback_analyzer(db_pool=None) -> FeedbackAnalyzer:
    """Initialize the feedback analyzer"""
    global _analyzer
    _analyzer = FeedbackAnalyzer(db_pool=db_pool)
    logger.info("✅ FeedbackAnalyzer initialized")
    return _analyzer


def get_feedback_analyzer() -> Optional[FeedbackAnalyzer]:
    """Get the global feedback analyzer instance"""
    return _analyzer


def shutdown_feedback_analyzer():
    """Reset the global feedback analyzer instance."""
    global _analyzer
    _analyzer = None
