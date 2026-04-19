"""
OCR质量验证器
负责: 评估OCR结果质量、触发重试循环、生成质量报告

功能:
- 字符级置信度评估
- 表格结构完整性检查
- 版面一致性检测
- LLM辅助校验
- 重试策略管理
"""

import re
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import sys

# 将项目根目录加入路径
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.loader import get_config, OCRQualityConfig

logger = logging.getLogger(__name__)


class QualityGrade(Enum):
    """质量等级"""
    EXCELLENT = "excellent"    # >= 0.95
    GOOD = "good"              # >= 0.85
    ACCEPTABLE = "acceptable"  # >= 0.70
    POOR = "poor"              # < 0.70


class RetryStrategy(Enum):
    """重试策略"""
    INCREASE_CONTRAST = "increase_contrast"
    DESKEW_CORRECTION = "deskew_correction"
    ENHANCE_TABLE_DETECTION = "enhance_table_detection"
    BINARIZATION = "binarization"
    NOISE_REDUCTION = "noise_reduction"


@dataclass
class TextQualityMetrics:
    """文本质量指标"""
    avg_confidence: float = 0.0
    min_confidence: float = 0.0
    low_confidence_blocks: List[Dict] = field(default_factory=list)
    char_count: int = 0
    garbled_ratio: float = 0.0  # 乱码比例


@dataclass
class TableQualityMetrics:
    """表格质量指标"""
    table_count: int = 0
    valid_tables: int = 0
    avg_rows_per_table: float = 0.0
    headers_detected: bool = False
    structure_integrity: float = 0.0  # 0-1


@dataclass
class LayoutQualityMetrics:
    """版面质量指标"""
    overlapping_blocks: int = 0
    out_of_bounds_blocks: int = 0
    reading_order_valid: bool = True
    avg_line_spacing: float = 0.0


@dataclass
class OCRQualityReport:
    """
    OCR质量报告
    
    Attributes:
        overall_score: 综合质量分数 (0-1)
        grade: 质量等级
        text_metrics: 文本质量指标
        table_metrics: 表格质量指标
        layout_metrics: 版面质量指标
        needs_retry: 是否需要重试
        retry_strategies: 推荐的重试策略
        verified: 是否通过LLM校验
        issues: 发现的问题列表
        suggestions: 改进建议
    """
    overall_score: float = 0.0
    grade: QualityGrade = QualityGrade.POOR
    text_metrics: TextQualityMetrics = field(default_factory=TextQualityMetrics)
    table_metrics: TableQualityMetrics = field(default_factory=TableQualityMetrics)
    layout_metrics: LayoutQualityMetrics = field(default_factory=LayoutQualityMetrics)
    needs_retry: bool = False
    retry_strategies: List[RetryStrategy] = field(default_factory=list)
    verified: bool = False
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "overall_score": round(self.overall_score, 4),
            "grade": self.grade.value,
            "needs_retry": self.needs_retry,
            "verified": self.verified,
            "text_metrics": {
                "avg_confidence": round(self.text_metrics.avg_confidence, 4),
                "min_confidence": round(self.text_metrics.min_confidence, 4),
                "char_count": self.text_metrics.char_count,
                "garbled_ratio": round(self.text_metrics.garbled_ratio, 4),
                "low_confidence_count": len(self.text_metrics.low_confidence_blocks)
            },
            "table_metrics": {
                "table_count": self.table_metrics.table_count,
                "valid_tables": self.table_metrics.valid_tables,
                "structure_integrity": round(self.table_metrics.structure_integrity, 4)
            },
            "layout_metrics": {
                "overlapping_blocks": self.layout_metrics.overlapping_blocks,
                "reading_order_valid": self.layout_metrics.reading_order_valid
            },
            "retry_strategies": [s.value for s in self.retry_strategies],
            "issues": self.issues,
            "suggestions": self.suggestions
        }


class OCRQualityValidator:
    """
    OCR质量验证器
    
    使用方式:
        validator = OCRQualityValidator()
        report = validator.validate(ocr_result)
        
        if report.needs_retry:
            strategies = report.retry_strategies
            # 应用重试策略
    """
    
    def __init__(self, config: Optional[OCRQualityConfig] = None):
        """
        初始化验证器
        
        Args:
            config: OCR质量配置，默认从全局配置加载
        """
        self.config = config or get_config().ocr_quality
        self.llm_service = None  # 延迟初始化
        
        logger.info(f"OCR质量验证器初始化完成")
        logger.info(f"  置信度阈值: {self.config.confidence_threshold}")
        logger.info(f"  表格完整性阈值: {self.config.table_integrity_threshold}")
        logger.info(f"  最大重试次数: {self.config.max_retries}")
    
    def validate(self, ocr_result: Dict[str, Any], attempt: int = 1) -> OCRQualityReport:
        """
        验证OCR结果质量
        
        Args:
            ocr_result: OCR服务返回的结果
            attempt: 当前尝试次数 (1-based)
        
        Returns:
            OCRQualityReport 质量报告
        """
        report = OCRQualityReport()
        
        # 1. 评估文本质量
        report.text_metrics = self._evaluate_text_quality(ocr_result)
        
        # 2. 评估表格质量
        report.table_metrics = self._evaluate_table_quality(ocr_result)
        
        # 3. 评估版面质量
        report.layout_metrics = self._evaluate_layout_quality(ocr_result)
        
        # 4. 计算综合得分
        report.overall_score = self._calculate_overall_score(report)
        report.grade = self._score_to_grade(report.overall_score)
        
        # 5. 判断是否需要重试
        report.needs_retry = (
            report.overall_score < self.config.confidence_threshold 
            and attempt < self.config.max_retries
        )
        
        # 6. 生成重试策略
        if report.needs_retry:
            report.retry_strategies = self._generate_retry_strategies(report)
            report.suggestions = self._generate_suggestions(report)
        
        # 7. 识别问题
        report.issues = self._identify_issues(report)
        
        logger.info(f"OCR质量评估完成: score={report.overall_score:.3f}, "
                   f"grade={report.grade.value}, needs_retry={report.needs_retry}")
        
        return report
    
    def validate_with_llm(self, ocr_result: Dict[str, Any], 
                          original_query: Optional[str] = None) -> bool:
        """
        使用LLM辅助校验OCR结果
        
        校验内容:
        - 数值合理性 (价格>0, 百分比<100%)
        - 日期格式正确性
        - 专业术语拼写
        - 上下文逻辑一致性
        
        Args:
            ocr_result: OCR结果
            original_query: 原始查询上下文 (可选)
        
        Returns:
            是否通过LLM校验
        """
        if not self.config.enable_llm_verify:
            return True
        
        # 延迟加载LLM服务
        if self.llm_service is None:
            self.llm_service = self._init_llm_service()
        
        if self.llm_service is None:
            logger.warning("LLM服务不可用，跳过LLM校验")
            return True
        
        try:
            # 提取样本文本
            sample_text = self._extract_sample_text(ocr_result)
            
            # 构建校验提示
            prompt = f"""请校验以下OCR识别结果的合理性。只需回答"VALID"或"INVALID:问题描述"。

文本片段:
{sample_text}

请检查:
1. 数值是否在合理范围 (如价格>0, 百分比<100%)
2. 日期格式是否正确 (如2024年1月, 2024-01-01)
3. 专业术语是否常见
4. 是否存在明显的乱码或识别错误

回答格式:
- 如果合理: VALID
- 如果有问题: INVALID:具体问题描述"""

            response = self.llm_service.quick_ask(prompt)
            
            is_valid = "VALID" in response and "INVALID" not in response
            
            if not is_valid:
                logger.warning(f"LLM校验发现问题: {response}")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"LLM校验失败: {e}")
            # 校验失败时返回False，由调用方决定如何处理
            # 生产环境可配置为：strict(失败即拒) / lenient(失败通过)
            return False
    
    def _evaluate_text_quality(self, ocr_result: Dict) -> TextQualityMetrics:
        """评估文本质量"""
        metrics = TextQualityMetrics()
        
        pages = ocr_result.get("pages", [])
        all_confidences = []
        all_text = []
        
        for page in pages:
            for block in page.get("text_blocks", []):
                conf = block.get("confidence", 0)
                text = block.get("text", "")
                
                all_confidences.append(conf)
                all_text.append(text)
                
                # 记录低置信度块
                if conf < self.config.confidence_threshold:
                    metrics.low_confidence_blocks.append({
                        "text": text[:50],  # 截断
                        "confidence": conf,
                        "page": page.get("page_number", 0)
                    })
        
        if all_confidences:
            metrics.avg_confidence = sum(all_confidences) / len(all_confidences)
            metrics.min_confidence = min(all_confidences)
        
        # 统计字符数和乱码比例
        full_text = "\n".join(all_text)
        metrics.char_count = len(full_text)
        metrics.garbled_ratio = self._calculate_garbled_ratio(full_text)
        
        return metrics
    
    def _evaluate_table_quality(self, ocr_result: Dict) -> TableQualityMetrics:
        """评估表格质量"""
        metrics = TableQualityMetrics()
        
        pages = ocr_result.get("pages", [])
        all_tables = []
        
        for page in pages:
            tables = page.get("tables", [])
            all_tables.extend(tables)
        
        metrics.table_count = len(all_tables)
        
        if metrics.table_count == 0:
            return metrics
        
        valid_count = 0
        total_rows = 0
        headers_detected_count = 0
        
        for table in all_tables:
            html = table.get("html", "")
            markdown = table.get("markdown", "")
            
            # 检查基本结构
            has_table_tag = "<table>" in html
            has_tr_tag = "<tr>" in html
            has_td_tag = "<td>" in html or "<th>" in html
            
            if has_table_tag and has_tr_tag and has_td_tag:
                valid_count += 1
            
            # 统计行数
            row_count = html.count("<tr>")
            total_rows += row_count
            
            # 检查表头
            has_headers = "<th>" in html or "|" in markdown
            if has_headers:
                headers_detected_count += 1
        
        metrics.valid_tables = valid_count
        metrics.avg_rows_per_table = total_rows / metrics.table_count if metrics.table_count > 0 else 0
        metrics.headers_detected = headers_detected_count > 0
        metrics.structure_integrity = valid_count / metrics.table_count if metrics.table_count > 0 else 0
        
        return metrics
    
    def _evaluate_layout_quality(self, ocr_result: Dict) -> LayoutQualityMetrics:
        """评估版面质量"""
        metrics = LayoutQualityMetrics()
        
        # 简化实现：检查文本块是否有异常
        # 在实际生产环境中，可以添加更复杂的版面分析
        
        pages = ocr_result.get("pages", [])
        overlapping_count = 0
        
        for page in pages:
            blocks = page.get("text_blocks", [])
            bboxes = []
            
            for block in blocks:
                bbox = block.get("bbox", {})
                if bbox:
                    bboxes.append(bbox)
            
            # 检查重叠
            for i, bbox1 in enumerate(bboxes):
                for bbox2 in bboxes[i+1:]:
                    if self._check_bbox_overlap(bbox1, bbox2):
                        overlapping_count += 1
        
        metrics.overlapping_blocks = overlapping_count
        metrics.reading_order_valid = overlapping_count < 5  # 简单阈值
        
        return metrics
    
    def _calculate_overall_score(self, report: OCRQualityReport) -> float:
        """计算综合质量分数"""
        text_score = report.text_metrics.avg_confidence
        table_score = report.table_metrics.structure_integrity if report.table_metrics.table_count > 0 else 1.0
        layout_score = 1.0 if report.layout_metrics.reading_order_valid else 0.5
        
        # 如果有表格，表格质量权重更高
        if report.table_metrics.table_count > 0:
            overall = text_score * 0.4 + table_score * 0.4 + layout_score * 0.2
        else:
            overall = text_score * 0.7 + layout_score * 0.3
        
        # 乱码惩罚
        if report.text_metrics.garbled_ratio > 0.1:
            overall *= 0.8
        
        return max(0.0, min(1.0, overall))
    
    def _score_to_grade(self, score: float) -> QualityGrade:
        """分数转换为等级"""
        if score >= 0.95:
            return QualityGrade.EXCELLENT
        elif score >= 0.85:
            return QualityGrade.GOOD
        elif score >= 0.70:
            return QualityGrade.ACCEPTABLE
        else:
            return QualityGrade.POOR
    
    def _generate_retry_strategies(self, report: OCRQualityReport) -> List[RetryStrategy]:
        """生成重试策略"""
        strategies = []
        
        # 根据质量问题选择策略
        if report.text_metrics.avg_confidence < 0.8:
            strategies.append(RetryStrategy.INCREASE_CONTRAST)
        
        if report.text_metrics.garbled_ratio > 0.05:
            strategies.append(RetryStrategy.NOISE_REDUCTION)
        
        if report.table_metrics.structure_integrity < 0.9:
            strategies.append(RetryStrategy.ENHANCE_TABLE_DETECTION)
        
        if report.layout_metrics.overlapping_blocks > 3:
            strategies.append(RetryStrategy.DESKEW_CORRECTION)
        
        # 按优先级排序，去重
        unique_strategies = list(dict.fromkeys(strategies))
        
        return unique_strategies[:3]  # 最多3个策略
    
    def _generate_suggestions(self, report: OCRQualityReport) -> List[str]:
        """生成改进建议"""
        suggestions = []
        
        if report.text_metrics.avg_confidence < 0.8:
            suggestions.append("建议增强图像对比度以提高文字识别准确率")
        
        if report.text_metrics.min_confidence < 0.5:
            suggestions.append("部分区域识别置信度极低，建议人工复核")
        
        if report.table_metrics.table_count > 0 and report.table_metrics.valid_tables < report.table_metrics.table_count:
            suggestions.append("部分表格结构识别不完整，建议检查表格边界")
        
        if report.text_metrics.garbled_ratio > 0.05:
            suggestions.append("检测到较多乱码，建议清理图像噪声或检查扫描质量")
        
        return suggestions
    
    def _identify_issues(self, report: OCRQualityReport) -> List[str]:
        """识别问题"""
        issues = []
        
        if report.text_metrics.avg_confidence < self.config.confidence_threshold:
            issues.append(f"平均置信度偏低 ({report.text_metrics.avg_confidence:.2f} < {self.config.confidence_threshold})")
        
        if len(report.text_metrics.low_confidence_blocks) > 10:
            issues.append(f"大量低置信度文本块 ({len(report.text_metrics.low_confidence_blocks)}个)")
        
        if report.table_metrics.table_count > 0 and report.table_metrics.structure_integrity < self.config.table_integrity_threshold:
            issues.append(f"表格结构不完整 ({report.table_metrics.structure_integrity:.2f} < {self.config.table_integrity_threshold})")
        
        if report.layout_metrics.overlapping_blocks > 0:
            issues.append(f"检测到 {report.layout_metrics.overlapping_blocks} 处文本块重叠")
        
        if report.text_metrics.garbled_ratio > 0.1:
            issues.append(f"乱码比例过高 ({report.text_metrics.garbled_ratio:.1%})")
        
        return issues
    
    def _calculate_garbled_ratio(self, text: str) -> float:
        """计算乱码比例"""
        if not text:
            return 0.0
        
        # 定义乱码特征
        # 包含：控制字符、私有Unicode区、未分配字符
        # 排除：常用标点、全角字符、特殊行业符号
        garbled_patterns = [
            r'[\x00-\x08\x0b-\x0c\x0e-\x1f]',  # 控制字符
            r'[\ud800-\udfff]',  # 代理对（非法UTF-16）
            r'[\ue000-\uf8ff]',  # 私有使用区
            r'[^\u4e00-\u9fff\u3000-\u303f\uff00-\uffef'  # CJK + 全角标点
            r'a-zA-Z0-9\s\.,;:!?"\'()\-/%￥$€°Φ㎡±×÷²³'  # ASCII + 行业符号
            r'，。！？《》（）【】、：；"''\.\-\[\]·｜│]',  # 中文标点
        ]
        
        garbled_count = 0
        for pattern in garbled_patterns:
            garbled_count += len(re.findall(pattern, text))
        
        # 去重（一个字符可能匹配多个模式）
        return min(garbled_count / len(text), 1.0) if text else 0.0
    
    def _check_bbox_overlap(self, bbox1: Dict, bbox2: Dict, epsilon: float = 1.0) -> bool:
        """检查两个bbox是否重叠
        
        Args:
            bbox1, bbox2: 边界框字典，包含 x, y, width, height
            epsilon: 容差像素，用于处理浮点精度问题
        """
        # 安全获取边界值
        def get_bounds(bbox: Dict) -> tuple:
            x = bbox.get("x") or 0
            y = bbox.get("y") or 0
            w = bbox.get("width") or 0
            h = bbox.get("height") or 0
            return float(x), float(y), float(x) + float(w), float(y) + float(h)
        
        x1_min, y1_min, x1_max, y1_max = get_bounds(bbox1)
        x2_min, y2_min, x2_max, y2_max = get_bounds(bbox2)
        
        # 检查是否重叠（含容差）
        overlap_x = not (x1_max < x2_min - epsilon or x2_max < x1_min - epsilon)
        overlap_y = not (y1_max < y2_min - epsilon or y2_max < y1_min - epsilon)
        
        return overlap_x and overlap_y
    
    def _extract_sample_text(self, ocr_result: Dict, max_length: int = 1000) -> str:
        """提取样本文本用于LLM校验"""
        pages = ocr_result.get("pages", [])
        texts = []
        
        for page in pages[:3]:  # 最多3页
            for block in page.get("text_blocks", [])[:20]:  # 每页最多20块
                texts.append(block.get("text", ""))
                if sum(len(t) for t in texts) > max_length:
                    break
        
        sample = "\n".join(texts)
        return sample[:max_length]
    
    def _init_llm_service(self) -> Optional[Any]:
        """初始化LLM服务
        
        TODO: 生产环境需要接入真实LLM服务
        当前返回Mock服务用于开发和测试
        """
        try:
            # 检查是否有配置的LLM服务
            try:
                from config.loader import get_config
                config = get_config()
                
                # 如果有配置，尝试加载真实服务
                if hasattr(config, 'llm') and getattr(config.llm, 'api_key', None):
                    # TODO: 接入真实LLM服务
                    # if getattr(config.llm, 'provider', None) == 'openai':
                    #     return OpenAILLMService(api_key=config.llm.api_key)
                    # if getattr(config.llm, 'provider', None) == 'local':
                    #     return LocalLLMService(endpoint=config.llm.endpoint)
                    logger.warning("LLM配置存在但未实现，回退到Mock")
            except Exception:
                pass  # 配置加载失败，回退到Mock
            
            # Mock服务（仅用于开发测试）
            logger.warning("使用Mock LLM服务，生产环境请配置真实LLM")
            
            class MockLLMService:
                def quick_ask(self, prompt: str) -> str:
                    # 简单启发式：如果提示中包含明显错误关键词，返回INVALID
                    invalid_keywords = ['乱码', '错误', 'invalid', 'error', 'undefined']
                    if any(kw in prompt.lower() for kw in invalid_keywords):
                        return "INVALID: 检测到异常内容"
                    return "VALID"
            
            return MockLLMService()
            
        except Exception as e:
            logger.error(f"初始化LLM服务失败: {e}")
            return None


# 便捷函数
def validate_ocr_quality(ocr_result: Dict[str, Any], 
                         attempt: int = 1,
                         config: Optional[OCRQualityConfig] = None) -> OCRQualityReport:
    """
    便捷函数: 验证OCR质量
    
    Args:
        ocr_result: OCR结果
        attempt: 尝试次数
        config: 可选配置
    
    Returns:
        质量报告
    """
    validator = OCRQualityValidator(config)
    return validator.validate(ocr_result, attempt)


if __name__ == "__main__":
    # 测试代码
    print("=" * 60)
    print("OCR质量验证器测试")
    print("=" * 60)
    
    # 模拟OCR结果
    mock_ocr_result = {
        "pages": [
            {
                "page_number": 1,
                "text_blocks": [
                    {"text": "2024年钢筋价格表", "confidence": 0.95, "bbox": {"x": 100, "y": 100, "width": 200, "height": 30}},
                    {"text": "HRB400 Φ12 3850元/吨", "confidence": 0.88, "bbox": {"x": 100, "y": 150, "width": 250, "height": 25}},
                    {"text": "HRB500 Φ16 4200元/吨", "confidence": 0.92, "bbox": {"x": 100, "y": 185, "width": 250, "height": 25}},
                ],
                "tables": [
                    {
                        "html": "<table><tr><th>规格</th><th>价格</th></tr><tr><td>HRB400</td><td>3850</td></tr></table>",
                        "markdown": "| 规格 | 价格 |\n|------|------|\n| HRB400 | 3850 |"
                    }
                ]
            }
        ],
        "full_text": "2024年钢筋价格表\nHRB400 Φ12 3850元/吨\nHRB500 Φ16 4200元/吨"
    }
    
    # 验证
    report = validate_ocr_quality(mock_ocr_result)
    
    print(f"\n✅ 质量报告:")
    print(f"   综合得分: {report.overall_score:.3f}")
    print(f"   质量等级: {report.grade.value}")
    print(f"   平均置信度: {report.text_metrics.avg_confidence:.3f}")
    print(f"   表格数量: {report.table_metrics.table_count}")
    print(f"   是否需要重试: {report.needs_retry}")
    
    if report.issues:
        print(f"\n⚠️ 发现问题:")
        for issue in report.issues:
            print(f"   - {issue}")
    
    if report.suggestions:
        print(f"\n💡 改进建议:")
        for suggestion in report.suggestions:
            print(f"   - {suggestion}")
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)
