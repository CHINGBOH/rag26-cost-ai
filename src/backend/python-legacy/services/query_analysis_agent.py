"""
查询分析 Agent
负责: 意图识别、实体提取、子查询分解

功能:
- 查询意图分类 (事实查询、数值查询、趋势分析、比较查询等)
- 实体识别与提取 (材料、工程、标准、时间)
- 时间范围解析
- 复杂查询分解为子查询
- 检索策略推荐
"""

import re
import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.loader import get_config, QueryAnalysisConfig

logger = logging.getLogger(__name__)


class QueryIntent(Enum):
    """
    查询意图类型
    
    Attributes:
        FACT_LOOKUP: 事实查询 (是什么)
        NUMERIC_QUERY: 数值查询 (多少钱、多少量)
        TREND_ANALYSIS: 趋势分析 (走势、变化)
        COMPARISON: 比较查询 (对比、区别)
        LIST_ENUMERATION: 列表枚举 (有哪些)
        PROCEDURE: 流程步骤 (如何、怎么做)
        ENTITY_RELATION: 实体关系 (关联、影响)
        TEMPORAL: 时间相关 (何时、最新)
    """
    FACT_LOOKUP = "fact"
    NUMERIC_QUERY = "numeric"
    TREND_ANALYSIS = "trend"
    COMPARISON = "comparison"
    LIST_ENUMERATION = "list"
    PROCEDURE = "procedure"
    ENTITY_RELATION = "relation"
    TEMPORAL = "temporal"


class StorageType(Enum):
    """推荐存储类型"""
    VECTOR = "vector"      # 语义搜索
    KEYWORD = "keyword"    # 精确匹配
    TABLE = "table"        # 结构化表格
    GRAPH = "graph"        # 图谱关系
    HYBRID = "hybrid"      # 混合检索


@dataclass
class ExtractedEntity:
    """提取的实体"""
    name: str
    type: str
    confidence: float = 1.0
    position: Optional[tuple] = None  # (start, end) in query


@dataclass
class TimeRange:
    """时间范围"""
    type: str  # absolute | relative | range
    start: Optional[str] = None  # ISO format date
    end: Optional[str] = None
    description: str = ""  # 原始描述


@dataclass
class SubQuery:
    """
    子查询
    
    Attributes:
        query_id: 子查询ID
        query_text: 查询文本
        intent: 意图类型
        target_storage: 推荐存储类型
        entities: 涉及的实体
        time_range: 时间约束
        priority: 优先级 (1-10)
    """
    query_id: str
    query_text: str
    intent: QueryIntent
    target_storage: StorageType
    entities: List[ExtractedEntity] = field(default_factory=list)
    time_range: Optional[TimeRange] = None
    priority: int = 5


@dataclass
class QueryAnalysisResult:
    """
    查询分析结果
    
    Attributes:
        original_query: 原始查询
        normalized_query: 规范化查询
        primary_intent: 主意图
        secondary_intents: 次要意图
        entities: 提取的实体列表
        time_constraints: 时间约束
        sub_queries: 子查询列表
        suggested_storage: 推荐存储类型
        keywords: 关键词列表
        confidence: 分析置信度
    """
    original_query: str
    normalized_query: str
    primary_intent: QueryIntent
    secondary_intents: List[QueryIntent] = field(default_factory=list)
    entities: List[ExtractedEntity] = field(default_factory=list)
    time_constraints: Optional[TimeRange] = None
    sub_queries: List[SubQuery] = field(default_factory=list)
    suggested_storage: StorageType = StorageType.HYBRID
    keywords: List[str] = field(default_factory=list)
    confidence: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "original_query": self.original_query,
            "normalized_query": self.normalized_query,
            "primary_intent": self.primary_intent.value,
            "secondary_intents": [i.value for i in self.secondary_intents],
            "entities": [
                {"name": e.name, "type": e.type, "confidence": e.confidence}
                for e in self.entities
            ],
            "time_constraints": {
                "type": self.time_constraints.type,
                "start": self.time_constraints.start,
                "end": self.time_constraints.end,
                "description": self.time_constraints.description
            } if self.time_constraints else None,
            "sub_queries": [
                {
                    "query_id": sq.query_id,
                    "query_text": sq.query_text,
                    "intent": sq.intent.value,
                    "target_storage": sq.target_storage.value,
                    "priority": sq.priority
                }
                for sq in self.sub_queries
            ],
            "suggested_storage": self.suggested_storage.value,
            "keywords": self.keywords,
            "confidence": round(self.confidence, 4)
        }


class QueryAnalysisAgent:
    """
    查询分析 Agent
    
    使用方式:
        agent = QueryAnalysisAgent()
        result = agent.analyze("2024年钢筋和混凝土价格对比")
        
        # result.primary_intent = QueryIntent.COMPARISON
        # result.sub_queries = [
        #     SubQuery("2024年钢筋价格", NUMERIC_QUERY, TABLE),
        #     SubQuery("2024年混凝土价格", NUMERIC_QUERY, TABLE),
        #     SubQuery("价格对比分析", COMPARISON, HYBRID)
        # ]
    """
    
    # 意图关键词映射
    INTENT_KEYWORDS = {
        QueryIntent.TREND_ANALYSIS: [
            "走势", "趋势", "变化", "增长", "下降", "涨幅", "跌幅",
            "上升", "降低", "波动", "趋向", "发展"
        ],
        QueryIntent.COMPARISON: [
            "对比", "比较", "vs", "区别", "差异", "哪个更", "优劣",
            "差距", "不同", " versus", "相比", "较之"
        ],
        QueryIntent.NUMERIC_QUERY: [
            "多少", "价格", "费用", "成本", "占比", "比例", "数量",
            "总额", "单价", "合计", "金额", "预算", "造价"
        ],
        QueryIntent.LIST_ENUMERATION: [
            "有哪些", "列表", "所有", "全部", "清单", "目录",
            "包含", "涉及", "相关", "列举"
        ],
        QueryIntent.PROCEDURE: [
            "如何", "怎么", "步骤", "流程", "怎样", "方法",
            "操作", "办理", "申请", "实施"
        ],
        QueryIntent.ENTITY_RELATION: [
            "关联", "影响", "导致", "引起", "关系", "联系",
            "依赖", "基于", "根据", "由...决定"
        ],
        QueryIntent.TEMPORAL: [
            "何时", "什么时候", "最新", "最近", "当前",
            "现在", "过去", "未来", "预计"
        ]
    }
    
    # 实体类型正则模式
    ENTITY_PATTERNS = [
        # 材料
        (r'(?:钢筋|混凝土|水泥|砂石|木材|沥青|钢材|铝材|玻璃|砖|瓦|涂料|防水材料|保温材料|管材|线材|电缆|电气设备|机械)(?:[、,][\u4e00-\u9fa5]+){0,3}', 'material'),
        # 标准编号
        (r'(?:HJ|GB|GB/T|CJ|JC|JGJ|JTG|JTG/T|CECS|T/CECS|DB|Q/)[\s]?\d+(?:\.\d+)?(?:[-]\d{4})?', 'standard_code'),
        # 工程类型
        (r'(?:建筑|市政|公路|桥梁|隧道|水利|电力|通信|园林|装修|安装|土建|结构|基础|主体|屋面|外墙|室内|地下)(?:工程|项目|施工|设计|监理)?', 'engineering_type'),
        # 时间
        (r'20\d{2}年(?:[0-9]{1,2}月?)?', 'time_absolute'),
        (r'(?:近|最近|过去|前|上)(\d+)(个)?(个月|年|季度|周|天)', 'time_relative'),
        (r'(\d{4})[-～到至](\d{4})年?', 'time_range'),
        # 价格单位
        (r'(?:元|万元|亿元)(?:/|每)?(?:吨|立方米|平方米|米|个|套|台)?', 'price_unit'),
        # 规格型号
        (r'(?:HRB|Q|C|HPB)[\s]?\d+(?:[E])?(?:[\s]?Φ\d+)?', 'specification'),
        # 地区
        (r'(?:北京|上海|广州|深圳|杭州|南京|武汉|成都|重庆|天津|西安|苏州|青岛|大连|厦门|宁波|无锡|佛山|东莞|长沙|郑州|济南|福州|沈阳|石家庄|太原|呼和浩特|长春|哈尔滨|合肥|南昌|南宁|贵阳|昆明|拉萨|兰州|西宁|银川|乌鲁木齐)(?:市)?', 'region'),
    ]
    
    def __init__(self, config: Optional[QueryAnalysisConfig] = None):
        """
        初始化查询分析Agent
        
        Args:
            config: 查询分析配置
        """
        self.config = config or get_config().query_analysis
        self.llm_service = None
        
        logger.info("查询分析Agent初始化完成")
        logger.info(f"  意图分类: {self.config.enable_intent_classification}")
        logger.info(f"  实体提取: {self.config.enable_entity_extraction}")
        logger.info(f"  子查询分解: {self.config.enable_subquery_decomposition}")
    
    def analyze(self, query: str, context: Optional[Dict] = None) -> QueryAnalysisResult:
        """
        分析查询 - 增强版带完整埋点
        
        Args:
            query: 用户查询
            context: 可选的上下文信息 (如对话历史)
        
        Returns:
            查询分析结果
        """
        import time
        
        print(f"\n{'='*60}")
        print(f"[QueryAnalysis] 开始分析: '{query[:50]}...'")
        print(f"{'='*60}")
        
        total_start = time.time()
        
        # 1. 规范化查询
        print("\n[Step 1/8] 规范化查询...")
        step_start = time.time()
        normalized = self._normalize_query(query)
        print(f"[Step 1/8] ✓ 规范化完成 (耗时{(time.time()-step_start)*1000:.1f}ms)")
        if normalized != query:
            print(f"  原文: {query}")
            print(f"  规范化: {normalized}")
        
        # 2. 意图识别
        print("\n[Step 2/8] 意图识别...")
        step_start = time.time()
        primary_intent, secondary_intents = self._classify_intent(normalized)
        intent_time = (time.time() - step_start) * 1000
        print(f"[Step 2/8] ✓ 主意图: {primary_intent.value}")
        if secondary_intents:
            print(f"  次要意图: {[i.value for i in secondary_intents]}")
        print(f"  (耗时{intent_time:.1f}ms)")
        
        # 3. 实体提取
        print("\n[Step 3/8] 实体提取...")
        step_start = time.time()
        if self.config.enable_entity_extraction:
            entities = self._extract_entities(normalized)
            print(f"[Step 3/8] ✓ 提取到 {len(entities)} 个实体")
            for e in entities:
                print(f"  - [{e.type}] {e.name}")
        else:
            entities = []
            print("[Step 3/8] ⚠ 实体提取已禁用")
        print(f"  (耗时{(time.time()-step_start)*1000:.1f}ms)")
        
        # 4. 时间解析
        print("\n[Step 4/8] 时间解析...")
        step_start = time.time()
        time_range = self._parse_time(normalized)
        if time_range:
            print(f"[Step 4/8] ✓ 时间约束: {time_range.description} ({time_range.type})")
        else:
            print("[Step 4/8] ⚠ 未检测到时间约束")
        print(f"  (耗时{(time.time()-step_start)*1000:.1f}ms)")
        
        # 5. 关键词提取
        print("\n[Step 5/8] 关键词提取...")
        step_start = time.time()
        keywords = self._extract_keywords(normalized)
        print(f"[Step 5/8] ✓ 关键词: {keywords[:8]}...")
        print(f"  (耗时{(time.time()-step_start)*1000:.1f}ms)")
        
        # 6. 子查询分解
        print("\n[Step 6/8] 子查询分解...")
        step_start = time.time()
        sub_queries = []
        if self.config.enable_subquery_decomposition:
            sub_queries = self._decompose_query(
                normalized, primary_intent, entities, time_range
            )
            print(f"[Step 6/8] ✓ 分解为 {len(sub_queries)} 个子查询")
            for sq in sub_queries:
                print(f"  [{sq.query_id}] {sq.query_text} ({sq.target_storage.value}, P{sq.priority})")
        else:
            print("[Step 6/8] ⚠ 子查询分解已禁用")
        print(f"  (耗时{(time.time()-step_start)*1000:.1f}ms)")
        
        # 7. 推荐存储类型
        print("\n[Step 7/8] 推荐存储类型...")
        step_start = time.time()
        suggested_storage = self._suggest_storage(primary_intent, sub_queries)
        print(f"[Step 7/8] ✓ 推荐: {suggested_storage.value}")
        print(f"  (耗时{(time.time()-step_start)*1000:.1f}ms)")
        
        # 8. 计算置信度
        print("\n[Step 8/8] 计算置信度...")
        step_start = time.time()
        confidence, confidence_breakdown = self._calculate_confidence(
            primary_intent, entities, sub_queries, return_breakdown=True
        )
        print(f"[Step 8/8] ✓ 置信度: {confidence:.3f}")
        print(f"  计算明细: {confidence_breakdown}")
        print(f"  (耗时{(time.time()-step_start)*1000:.1f}ms)")
        
        # 构建结果
        result = QueryAnalysisResult(
            original_query=query,
            normalized_query=normalized,
            primary_intent=primary_intent,
            secondary_intents=secondary_intents,
            entities=entities,
            time_constraints=time_range,
            sub_queries=sub_queries,
            suggested_storage=suggested_storage,
            keywords=keywords,
            confidence=confidence
        )
        
        total_time = (time.time() - total_start) * 1000
        print("\n" + "="*60)
        print("[QueryAnalysis] 分析完成 ✓")
        print(f"  总耗时: {total_time:.1f}ms")
        print(f"  主意图: {primary_intent.value}")
        print(f"  推荐存储: {suggested_storage.value}")
        print(f"  置信度: {confidence:.3f}")
        print(f"{'='*60}\n")
        
        logger.info(f"查询分析完成: '{query[:50]}...' -> intent={primary_intent.value}, "
                   f"entities={len(entities)}, sub_queries={len(sub_queries)}")
        
        return result
    
    def _normalize_query(self, query: str) -> str:
        """
        规范化查询
        
        - 去除多余空格
        - 统一标点
        - 简写展开
        """
        # 去除首尾空格
        query = query.strip()
        
        # 统一空格
        query = re.sub(r'\s+', ' ', query)
        
        # 统一标点
        query = query.replace('？', '?').replace('，', ',').replace('。', '.')
        
        # 简写展开 (示例)
        expansions = {
            '砼': '混凝土',
            ' info ': ' 信息 ',
            ' Info ': ' 信息 ',
        }
        for short, full in expansions.items():
            query = query.replace(short, full)
        
        return query
    
    def _classify_intent(self, query: str) -> tuple:
        """
        意图分类 - 增强版带埋点
        
        Returns:
            (primary_intent, [secondary_intents])
        """
        scores = {}
        matched_keywords = {}
        
        for intent, keywords in self.INTENT_KEYWORDS.items():
            score = 0
            matched = []
            for keyword in keywords:
                if keyword in query:
                    score += 1
                    matched.append(keyword)
                    # 关键词位置权重 (越靠前权重越高)
                    pos = query.find(keyword)
                    if pos >= 0:
                        score += max(0, 1 - pos / len(query))
            scores[intent] = score
            if matched:
                matched_keywords[intent.value] = matched[:3]  # 最多记录3个
        
        # 排序
        sorted_intents = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        
        if not sorted_intents or sorted_intents[0][1] == 0:
            print("    [Intent] 未匹配到意图关键词，默认 FACT_LOOKUP")
            return QueryIntent.FACT_LOOKUP, []
        
        primary = sorted_intents[0][0]
        # 次要意图 (分数 > 0 且与主意图差距不大)
        secondary = [
            intent for intent, score in sorted_intents[1:]
            if score > 0 and score >= sorted_intents[0][1] * 0.5
        ]
        
        print(f"    [Intent] 意图得分: {[(i.value, round(s, 2)) for i, s in sorted_intents[:3]]}")
        if matched_keywords.get(primary.value):
            print(f"    [Intent] 匹配关键词: {matched_keywords[primary.value]}")
        
        return primary, secondary
    
    def _extract_entities(self, query: str) -> List[ExtractedEntity]:
        """提取实体 - 增强版带匹配反馈"""
        entities = []
        seen = set()
        
        print("    [Entity] 开始实体提取...")
        
        for pattern, entity_type in self.ENTITY_PATTERNS:
            matches = list(re.finditer(pattern, query, re.IGNORECASE))
            if matches:
                print(f"    [Entity] 类型 '{entity_type}' 匹配到 {len(matches)} 个")
            for match in matches:
                name = match.group(0)
                if name not in seen:
                    seen.add(name)
                    entities.append(ExtractedEntity(
                        name=name,
                        type=entity_type,
                        position=(match.start(), match.end())
                    ))
                    print(f"      ✓ [{entity_type}] {name}")
        
        if not entities:
            print("    [Entity] ⚠ 未提取到任何实体")
        
        return entities
    
    def _parse_time(self, query: str) -> Optional[TimeRange]:
        """解析时间范围"""
        # 绝对时间: "2024年", "2024年1月"
        abs_match = re.search(r'(20\d{2})年(?:([0-9]{1,2})月?)?', query)
        if abs_match:
            year = abs_match.group(1)
            month = abs_match.group(2)
            return TimeRange(
                type="absolute",
                start=f"{year}-{month.zfill(2) if month else '01'}-01",
                end=f"{year}-{month.zfill(2) if month else '12'}-31",
                description=abs_match.group(0)
            )
        
        # 相对时间: "近3个月", "最近一年"
        rel_match = re.search(r'(?:近|最近|过去|前)(\d+)?个?(个月|年|季度|周)', query)
        if rel_match:
            count = int(rel_match.group(1)) if rel_match.group(1) else 1
            unit = rel_match.group(2)
            return TimeRange(
                type="relative",
                description=f"{count}{unit}"
            )
        
        # 时间范围: "2023到2024年", "2023-2024"
        range_match = re.search(r'(20\d{2})[-～到至](20\d{2})年?', query)
        if range_match:
            start_year = range_match.group(1)
            end_year = range_match.group(2)
            return TimeRange(
                type="range",
                start=f"{start_year}-01-01",
                end=f"{end_year}-12-31",
                description=range_match.group(0)
            )
        
        return None
    
    def _extract_keywords(self, query: str) -> List[str]:
        """提取关键词"""
        # 简单的关键词提取 (去除停用词)
        stopwords = {'的', '了', '和', '是', '在', '有', '我', '都', '个', '与', '也', '为', '能'}
        
        words = []
        # 基于实体提取的结果
        for match in re.finditer(r'[\u4e00-\u9fa5]{2,}|[a-zA-Z]+', query):
            word = match.group(0)
            if word not in stopwords and len(word) >= 2:
                words.append(word)
        
        return list(set(words))  # 去重
    
    def _decompose_query(self, query: str, intent: QueryIntent,
                         entities: List[ExtractedEntity],
                         time_range: Optional[TimeRange]) -> List[SubQuery]:
        """
        分解复杂查询为子查询
        
        示例:
        "2024年深圳信息价中钢筋和混凝土的价格涨幅对比"
        ↓
        Q1: "2024年深圳钢筋信息价" (数值查询 → 表格)
        Q2: "2024年深圳混凝土信息价" (数值查询 → 表格)
        Q3: "钢筋混凝土价格涨幅对比" (比较查询 → 混合)
        """
        sub_queries = []
        
        # 比较查询分解
        if intent == QueryIntent.COMPARISON:
            material_entities = [e for e in entities if e.type == 'material']
            
            if len(material_entities) >= 2:
                # 为每个材料创建子查询
                for i, entity in enumerate(material_entities[:2]):
                    # 构建子查询文本
                    sub_text = f"{entity.name}"
                    if time_range:
                        sub_text = f"{time_range.description}{sub_text}"
                    
                    sub_queries.append(SubQuery(
                        query_id=f"sub_{i+1}",
                        query_text=sub_text,
                        intent=QueryIntent.NUMERIC_QUERY,
                        target_storage=StorageType.TABLE,
                        entities=[entity],
                        time_range=time_range,
                        priority=8
                    ))
                
                # 添加比较子查询
                sub_queries.append(SubQuery(
                    query_id="sub_compare",
                    query_text=f"{material_entities[0].name}与{material_entities[1].name}对比",
                    intent=QueryIntent.COMPARISON,
                    target_storage=StorageType.HYBRID,
                    entities=material_entities[:2],
                    priority=10
                ))
        
        # 趋势查询分解
        elif intent == QueryIntent.TREND_ANALYSIS:
            material_entities = [e for e in entities if e.type == 'material']
            
            for entity in material_entities:
                sub_queries.append(SubQuery(
                    query_id=f"sub_trend_{entity.name}",
                    query_text=f"{entity.name}价格时间序列",
                    intent=QueryIntent.NUMERIC_QUERY,
                    target_storage=StorageType.TABLE,
                    entities=[entity],
                    time_range=time_range,
                    priority=9
                ))
        
        # 如果没有分解，返回单个查询
        if not sub_queries:
            storage = self._intent_to_storage(intent)
            sub_queries.append(SubQuery(
                query_id="sub_1",
                query_text=query,
                intent=intent,
                target_storage=storage,
                entities=entities,
                time_range=time_range,
                priority=5
            ))
        
        # 限制子查询数量
        return sub_queries[:self.config.max_subqueries]
    
    def _intent_to_storage(self, intent: QueryIntent) -> StorageType:
        """意图映射到存储类型"""
        mapping = {
            QueryIntent.NUMERIC_QUERY: StorageType.TABLE,
            QueryIntent.TREND_ANALYSIS: StorageType.TABLE,
            QueryIntent.COMPARISON: StorageType.HYBRID,
            QueryIntent.FACT_LOOKUP: StorageType.HYBRID,
            QueryIntent.LIST_ENUMERATION: StorageType.KEYWORD,
            QueryIntent.PROCEDURE: StorageType.VECTOR,
            QueryIntent.ENTITY_RELATION: StorageType.GRAPH,
            QueryIntent.TEMPORAL: StorageType.TABLE,
        }
        return mapping.get(intent, StorageType.HYBRID)
    
    def _suggest_storage(self, intent: QueryIntent, 
                          sub_queries: List[SubQuery]) -> StorageType:
        """推荐存储类型"""
        if intent in [QueryIntent.NUMERIC_QUERY, QueryIntent.TREND_ANALYSIS]:
            return StorageType.TABLE
        elif intent == QueryIntent.COMPARISON:
            return StorageType.HYBRID
        elif intent == QueryIntent.ENTITY_RELATION:
            return StorageType.GRAPH
        return StorageType.HYBRID
    
    def _calculate_confidence(self, intent: QueryIntent,
                               entities: List[ExtractedEntity],
                               sub_queries: List[SubQuery],
                               return_breakdown: bool = False) -> float | tuple:
        """计算分析置信度 - 增强版带明细"""
        confidence = 0.5  # 基础置信度
        breakdown = {"base": 0.5}
        
        # 意图明确的加分
        if intent != QueryIntent.FACT_LOOKUP:
            intent_bonus = 0.2
            confidence += intent_bonus
            breakdown["intent_clear"] = intent_bonus
        else:
            breakdown["intent_clear"] = 0.0
        
        # 提取到实体的加分
        if entities:
            entity_bonus = min(0.3, len(entities) * 0.1)
            confidence += entity_bonus
            breakdown["entities"] = round(entity_bonus, 2)
        else:
            breakdown["entities"] = 0.0
        
        # 子查询分解的加分
        if sub_queries and len(sub_queries) > 1:
            decomp_bonus = 0.1
            confidence += decomp_bonus
            breakdown["decomposition"] = decomp_bonus
        else:
            breakdown["decomposition"] = 0.0
        
        final = min(1.0, confidence)
        breakdown["final"] = round(final, 3)
        
        if return_breakdown:
            return final, breakdown
        return final


# 便捷函数
def analyze_query(query: str, 
                  context: Optional[Dict] = None,
                  config: Optional[QueryAnalysisConfig] = None) -> QueryAnalysisResult:
    """
    便捷函数: 分析查询
    
    Args:
        query: 用户查询
        context: 可选上下文
        config: 可选配置
    
    Returns:
        分析结果
    """
    agent = QueryAnalysisAgent(config)
    return agent.analyze(query, context)


if __name__ == "__main__":
    # 测试代码
    print("=" * 70)
    print("查询分析 Agent 测试")
    print("=" * 70)
    
    test_queries = [
        "2024年钢筋价格是多少？",
        "2024年深圳信息价中钢筋和混凝土的价格涨幅对比",
        "建设工程造价管理规定的最新版本",
        "如何申请建设工程规划许可证？",
        "钢筋HRB400 Φ12的规格参数",
        "近三个月混凝土价格走势",
        "GB/T 50204标准的主要内容有哪些？"
    ]
    
    for query in test_queries:
        print(f"\n{'='*70}")
        print(f"查询: {query}")
        print('='*70)
        
        result = analyze_query(query)
        
        print(f"  主意图: {result.primary_intent.value}")
        print(f"  推荐存储: {result.suggested_storage.value}")
        print(f"  置信度: {result.confidence:.2f}")
        
        if result.entities:
            print(f"\n  实体:")
            for e in result.entities:
                print(f"    - {e.name} ({e.type})")
        
        if result.time_constraints:
            print(f"\n  时间约束: {result.time_constraints.description}")
        
        if result.sub_queries:
            print(f"\n  子查询 ({len(result.sub_queries)}个):")
            for sq in result.sub_queries:
                print(f"    [{sq.query_id}] {sq.query_text}")
                print(f"      intent={sq.intent.value}, storage={sq.target_storage.value}, priority={sq.priority}")
    
    print("\n" + "=" * 70)
    print("测试完成!")
    print("=" * 70)
