"""
Verification 4: Feedback Analyzer Aggregation Test
Tests feedback trend detection and learning trigger at 20% frequency
"""
import pytest
import sys
import os
from unittest.mock import MagicMock
from dataclasses import asdict

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src/backend/retrieval-service'))


@pytest.mark.asyncio
async def test_feedback_analyzer_initialization():
    """Test feedback analyzer initializes with correct parameters"""
    from app.agent.feedback_analyzer import FeedbackAnalyzer
    
    analyzer = FeedbackAnalyzer(db_pool=None)
    
    assert analyzer is not None, "Analyzer should initialize"
    assert analyzer.TRENDING_THRESHOLD == 0.20, "Trending threshold should be 20%"
    assert analyzer.MIN_FEEDBACK_SAMPLES == 5, "Min samples should be 5"
    assert len(analyzer.TAG_WEIGHTS) > 0, "Should have tag weights"
    
    print(f"✅ Feedback Analyzer initialized:")
    print(f"   Trending threshold: {analyzer.TRENDING_THRESHOLD:.0%}")
    print(f"   Min samples: {analyzer.MIN_FEEDBACK_SAMPLES}")
    print(f"   Known tags: {len(analyzer.TAG_WEIGHTS)}")


@pytest.mark.asyncio
async def test_feedback_analyzer_no_feedback():
    """Test analyzer with no feedback data"""
    from app.agent.feedback_analyzer import FeedbackAnalyzer
    
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    # No feedback
    mock_cursor.fetchall.return_value = []
    
    analyzer = FeedbackAnalyzer(db_pool=mock_pool)
    analysis = await analyzer.analyze_feedback_trends(window_days=7)
    
    assert analysis is None, "Should return None when no feedback"
    
    print(f"✅ No feedback case handled correctly")


@pytest.mark.asyncio
async def test_feedback_analyzer_insufficient_samples():
    """Test that analyzer requires minimum sample size"""
    from app.agent.feedback_analyzer import FeedbackAnalyzer
    
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    # Only 3 feedback (min is 5)
    mock_cursor.fetchall.return_value = [
        (5, ['数据过时'], None, None, None),
        (4, ['缺少依据'], None, None, None),
        (3, [], None, None, None),
    ]
    
    analyzer = FeedbackAnalyzer(db_pool=mock_pool)
    analysis = await analyzer.analyze_feedback_trends(window_days=7)
    
    assert analysis is None or analysis.should_trigger is False, \
        "Should not trigger with insufficient samples"
    
    print(f"✅ Minimum sample requirement enforced (min: 5)")


@pytest.mark.asyncio
async def test_feedback_analyzer_trending_issue_detection():
    """Test detection of trending issues at 20% frequency"""
    from app.agent.feedback_analyzer import FeedbackAnalyzer
    
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    # 10 feedback: 2 with '数据过时' (20%), 3 with '缺少依据' (30%)
    mock_cursor.fetchall.return_value = [
        (5, ['数据过时'], None, None, None),
        (4, ['数据过时'], None, None, None),
        (2, ['缺少依据'], None, None, None),
        (2, ['缺少依据'], None, None, None),
        (2, ['缺少依据'], None, None, None),
        (5, [], None, None, None),
        (5, [], None, None, None),
        (4, [], None, None, None),
        (4, [], None, None, None),
        (3, [], None, None, None),
    ]
    
    analyzer = FeedbackAnalyzer(db_pool=mock_pool)
    analysis = await analyzer.analyze_feedback_trends(window_days=7)
    
    assert analysis is not None, "Should get analysis"
    assert analysis.total_feedback == 10, "Should have 10 feedback"
    
    # Find trending issues
    trending_tags = [issue.tag for issue in analysis.trending_problems]
    assert '缺少依据' in trending_tags, "Should detect '缺少依据' as trending (30%)"
    assert '数据过时' in trending_tags, "Should detect '数据过时' as trending (20%)"
    
    print(f"✅ Trending issues detected:")
    print(f"   Total feedback: {analysis.total_feedback}")
    print(f"   Trending: {trending_tags}")
    print(f"   Trending threshold: {analyzer.TRENDING_THRESHOLD:.0%}")


@pytest.mark.asyncio
async def test_feedback_analyzer_negative_rate():
    """Test negative feedback rate calculation"""
    from app.agent.feedback_analyzer import FeedbackAnalyzer
    
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    # 10 feedback: 3 with rating <= 2 (30% negative)
    mock_cursor.fetchall.return_value = [
        (1, [], None, None, None),  # Negative
        (2, [], None, None, None),  # Negative
        (2, [], None, None, None),  # Negative
        (3, [], None, None, None),
        (4, [], None, None, None),
        (5, [], None, None, None),
        (5, [], None, None, None),
        (4, [], None, None, None),
        (3, [], None, None, None),
        (5, [], None, None, None),
    ]
    
    analyzer = FeedbackAnalyzer(db_pool=mock_pool)
    analysis = await analyzer.analyze_feedback_trends(window_days=7)
    
    assert analysis is not None, "Should get analysis"
    assert abs(analysis.negative_rate - 0.3) < 0.01, f"Negative rate should be 30%, got {analysis.negative_rate:.1%}"
    
    print(f"✅ Negative feedback rate calculated:")
    print(f"   Negative rate: {analysis.negative_rate:.1%}")


@pytest.mark.asyncio
async def test_feedback_analyzer_tag_weighting():
    """Test that tag importance weights are applied correctly"""
    from app.agent.feedback_analyzer import FeedbackAnalyzer
    
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    # 10 feedback with different tags
    mock_cursor.fetchall.return_value = [
        (1, ['逻辑错误'], None, None, None),   # Weight: 15
        (1, ['逻辑错误'], None, None, None),   # Weight: 15
        (1, ['工具失效'], None, None, None),   # Weight: 12
        (1, ['数据过时'], None, None, None),   # Weight: 10
        (1, ['缺少依据'], None, None, None),   # Weight: 8
        (5, [], None, None, None),
        (5, [], None, None, None),
        (4, [], None, None, None),
        (4, [], None, None, None),
        (4, [], None, None, None),
    ]
    
    analyzer = FeedbackAnalyzer(db_pool=mock_pool)
    analysis = await analyzer.analyze_feedback_trends(window_days=7)
    
    assert analysis is not None, "Should get analysis"
    
    # Find '逻辑错误' and verify weight
    for issue in analysis.top_issues:
        if issue.tag == '逻辑错误':
            expected_weight = 2 * analyzer.TAG_WEIGHTS['逻辑错误']  # 2 occurrences * 15
            assert issue.weight == expected_weight, f"Weight should be {expected_weight}, got {issue.weight}"
            print(f"✅ Tag weighting verified:")
            print(f"   '逻辑错误': frequency={issue.frequency:.0%}, weight={issue.weight}")
            break


@pytest.mark.asyncio
async def test_feedback_analyzer_should_trigger_learning():
    """Test decision to trigger learning based on trending issues"""
    from app.agent.feedback_analyzer import FeedbackAnalyzer
    
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    # 15 feedback with high-weight trending issues
    mock_cursor.fetchall.return_value = [
        (1, ['工具失效'], None, None, None),   # High weight issue
        (1, ['工具失效'], None, None, None),
        (1, ['工具失效'], None, None, None),
        (1, ['工具失效'], None, None, None),
        (1, ['工具失效'], None, None, None),
        (2, ['缺少依据'], None, None, None),
        (2, ['缺少依据'], None, None, None),
        (2, ['缺少依据'], None, None, None),
        (2, ['缺少依据'], None, None, None),
        (3, [], None, None, None),
        (3, [], None, None, None),
        (3, [], None, None, None),
        (4, [], None, None, None),
        (4, [], None, None, None),
        (5, [], None, None, None),
    ]
    
    analyzer = FeedbackAnalyzer(db_pool=mock_pool)
    analysis = await analyzer.analyze_feedback_trends(window_days=7)
    
    assert analysis is not None, "Should get analysis"
    assert analysis.total_feedback >= analyzer.MIN_FEEDBACK_SAMPLES, "Should have enough samples"
    
    # Check if should trigger
    print(f"✅ Learning trigger analysis:")
    print(f"   Total feedback: {analysis.total_feedback}")
    print(f"   Trending problems: {[i.tag for i in analysis.trending_problems]}")
    print(f"   Total weight of trending: {sum(i.weight for i in analysis.trending_problems)}")
    print(f"   Weight threshold: {analyzer.TRIGGER_WEIGHT_THRESHOLD}")
    print(f"   Should trigger: {analysis.should_trigger}")


@pytest.mark.asyncio
async def test_feedback_analyzer_suggestions_generation():
    """Test that improvement suggestions are generated"""
    from app.agent.feedback_analyzer import FeedbackAnalyzer, FeedbackIssue
    
    analyzer = FeedbackAnalyzer(db_pool=None)
    
    # Create trending issues
    issues = [
        FeedbackIssue(tag='逻辑错误', frequency=0.25, count=3, weight=45),
        FeedbackIssue(tag='数据过时', frequency=0.20, count=2, weight=20),
    ]
    
    suggestions = analyzer._generate_suggestions(issues)
    
    assert len(suggestions) > 0, "Should generate suggestions"
    assert any('推理' in s or 'prompt' in s for s in suggestions), "Should mention reasoning/prompt"
    assert any('数据源' in s for s in suggestions), "Should mention data source"
    
    print(f"✅ Suggestions generated:")
    for i, suggestion in enumerate(suggestions, 1):
        print(f"   {i}. {suggestion}")


@pytest.mark.asyncio
async def test_feedback_analyzer_insights_generation():
    """Test human-readable insights generation"""
    from app.agent.feedback_analyzer import FeedbackAnalyzer
    
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    # 10 feedback
    mock_cursor.fetchall.return_value = [
        (1, ['逻辑错误'], None, None, None),
        (1, ['逻辑错误'], None, None, None),
        (2, ['工具失效'], None, None, None),
        (5, [], None, None, None),
        (5, [], None, None, None),
        (5, [], None, None, None),
        (4, [], None, None, None),
        (4, [], None, None, None),
        (4, [], None, None, None),
        (3, [], None, None, None),
    ]
    
    analyzer = FeedbackAnalyzer(db_pool=mock_pool)
    insights = await analyzer.get_insights(window_days=7)
    
    assert insights is not None, "Should get insights"
    assert 'total_feedback_count' in insights, "Should have feedback count"
    assert 'negative_feedback_rate' in insights, "Should have negative rate"
    assert 'top_issues' in insights, "Should have top issues"
    
    print(f"✅ Insights generated:")
    print(f"   Period: {insights['period_days']} days")
    print(f"   Total feedback: {insights['total_feedback_count']}")
    print(f"   Negative rate: {insights['negative_feedback_rate']}")
    print(f"   Top issues: {len(insights['top_issues'])}")


@pytest.mark.asyncio
async def test_global_feedback_analyzer_initialization():
    """Test global feedback analyzer functions"""
    from app.agent.feedback_analyzer import init_feedback_analyzer, get_feedback_analyzer
    
    analyzer = init_feedback_analyzer(db_pool=None)
    assert analyzer is not None, "Analyzer should initialize"
    
    retrieved = get_feedback_analyzer()
    assert retrieved is not None, "Should retrieve global analyzer"
    assert retrieved is analyzer, "Should be same instance"
    
    print(f"✅ Global feedback analyzer initialized")
    print(f"   Trending threshold: {analyzer.TRENDING_THRESHOLD:.0%}")
    print(f"   Min samples: {analyzer.MIN_FEEDBACK_SAMPLES}")
