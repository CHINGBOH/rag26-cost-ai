#!/usr/bin/env python3
"""
集成测试脚本 - 验证 Phase 5 服务集成

测试项:
1. 配置系统加载
2. OCR质量验证器可用
3. 查询分析Agent可用
4. 结构化存储可用
5. DocumentProcessor集成
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src" / "backend" / "python-legacy"))

def test_config():
    """测试配置系统"""
    print("\n[1/5] 测试配置系统...")
    try:
        from config.loader import get_config
        config = get_config()
        
        assert config.services.api.port == 8000
        assert config.ocr_quality.confidence_threshold == 0.85
        print(f"  ✅ 配置加载成功")
        print(f"     - API端口: {config.services.api.port}")
        print(f"     - OCR质量阈值: {config.ocr_quality.confidence_threshold}")
        return True
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return False

def test_ocr_validator():
    """测试OCR质量验证器"""
    print("\n[2/5] 测试OCR质量验证器...")
    try:
        from services.ocr_quality_validator import OCRQualityValidator, validate_ocr_quality
        
        validator = OCRQualityValidator()
        
        # 模拟OCR结果
        mock_ocr = {
            "pages": [{
                "page_number": 1,
                "text_blocks": [{"text": "测试", "confidence": 0.95}],
                "tables": []
            }],
            "full_text": "测试"
        }
        
        report = validator.validate(mock_ocr)
        assert report.overall_score > 0
        print(f"  ✅ OCR质量验证器工作正常")
        print(f"     - 质量分数: {report.overall_score:.3f}")
        return True
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return False

def test_query_analysis():
    """测试查询分析Agent"""
    print("\n[3/5] 测试查询分析Agent...")
    try:
        from services.query_analysis_agent import analyze_query
        
        result = analyze_query("2024年钢筋价格")
        
        assert result.primary_intent is not None
        print(f"  ✅ 查询分析Agent工作正常")
        print(f"     - 意图: {result.primary_intent.value}")
        print(f"     - 实体数: {len(result.entities)}")
        return True
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return False

def test_structured_store():
    """测试结构化存储"""
    print("\n[4/5] 测试结构化存储...")
    try:
        from infrastructure.adapters.structured_store import StructuredStoreAdapter
        
        # 只测试初始化，不测试连接
        print(f"  ✅ 结构化存储模块可导入")
        return True
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return False

def test_document_processor():
    """测试DocumentProcessor集成"""
    print("\n[5/5] 测试DocumentProcessor集成...")
    try:
        from services.document_processor import DocumentProcessor
        
        processor = DocumentProcessor()
        
        # 检查集成属性
        assert hasattr(processor, 'ocr_validator')
        assert hasattr(processor, 'structured_store')
        assert hasattr(processor, 'max_ocr_retries')
        
        print(f"  ✅ DocumentProcessor集成完成")
        print(f"     - OCR验证器: {'已启用' if processor.ocr_validator else '未启用'}")
        print(f"     - 结构化存储: {'已启用' if processor.structured_store else '未启用'}")
        print(f"     - 最大重试: {processor.max_ocr_retries}次")
        return True
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return False

def main():
    """主函数"""
    print("=" * 60)
    print("Phase 5 集成测试")
    print("=" * 60)
    
    tests = [
        test_config,
        test_ocr_validator,
        test_query_analysis,
        test_structured_store,
        test_document_processor,
    ]
    
    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"  ❌ 异常: {e}")
            results.append(False)
    
    # 汇总
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print(f"✅ 所有测试通过 ({passed}/{total})")
        return 0
    else:
        print(f"⚠️ 部分测试失败 ({passed}/{total})")
        return 1

if __name__ == "__main__":
    sys.exit(main())
