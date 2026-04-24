"""
视觉LLM图表理解引擎
使用Ollama LLaVA模型理解图表图片并提取数据点
"""

import json
import logging
import base64
from typing import List, Dict, Optional
from pathlib import Path

import requests
from PIL import Image

logger = logging.getLogger(__name__)


class VisionLLMEngine:
    """视觉LLM引擎（Ollama LLaVA）"""

    def __init__(self, base_url: str = "http://localhost:11434/api/generate",
                 model: str = "llava"):
        self.base_url = base_url
        self.model = model
        self._available = self._check_model()

    def _check_model(self) -> bool:
        """检查模型是否可用"""
        try:
            resp = requests.get("http://localhost:11434/api/tags", timeout=5)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                for m in models:
                    if self.model in m.get("name", ""):
                        logger.info(f"✅ Vision LLM model '{self.model}' available")
                        return True
            logger.warning(f"⚠️ Vision LLM model '{self.model}' not found in Ollama")
            return False
        except Exception as e:
            logger.warning(f"⚠️ Ollama check failed: {e}")
            return False

    def extract_chart_data(self, image_path: Path, chart_type: str = "line") -> List[Dict]:
        """
        从图表图片中提取数据点
        
        Args:
            image_path: 图表图片路径
            chart_type: 图表类型 line/bar/pie
        
        Returns:
            List of {'series_name': str, 'x_value': str, 'y_value': float}
        """
        if not self._available:
            logger.warning("Vision LLM not available")
            return []
        
        # 读取图片并编码
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        
        # 构建提示词
        prompt = self._build_chart_prompt(chart_type)
        
        try:
            resp = requests.post(
                self.base_url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "images": [img_b64],
                    "stream": False,
                },
                timeout=120
            )
            
            if resp.status_code != 200:
                logger.error(f"LLM error: {resp.status_code} {resp.text[:200]}")
                return []
            
            result = resp.json().get("response", "")
            return self._parse_llm_response(result)
            
        except Exception as e:
            logger.error(f"Vision LLM request failed: {e}")
            return []

    def _build_chart_prompt(self, chart_type: str) -> str:
        """构建图表提取提示词"""
        return f"""You are a data extraction assistant. Analyze this {chart_type} chart image carefully.

Extract ALL data points and return them as a JSON array. Format:
[
  {{"series_name": "name of data series", "x_value": "x-axis label", "y_value": numeric_value}},
  ...
]

Rules:
- Read all axis labels carefully
- Include every data point visible on the chart
- y_value must be a number (not string)
- If there are multiple series, include series_name for each
- If x-axis shows dates, use format like "2024-01" or "2024年1月"
- Return ONLY the JSON array, no explanation
"""

    def _parse_llm_response(self, text: str) -> List[Dict]:
        """解析LLM返回的JSON"""
        # 尝试从文本中提取JSON
        try:
            # 找方括号包裹的内容
            start = text.find('[')
            end = text.rfind(']')
            if start != -1 and end != -1 and end > start:
                json_str = text[start:end+1]
                data = json.loads(json_str)
                if isinstance(data, list):
                    return data
        except json.JSONDecodeError:
            pass
        
        # 尝试解析整个文本
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
        except Exception:
            pass
        
        logger.warning(f"Failed to parse LLM response as JSON: {text[:200]}")
        return []

    def describe_image(self, image_path: Path) -> str:
        """获取图片的文字描述"""
        if not self._available:
            return ""
        
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        
        try:
            resp = requests.post(
                self.base_url,
                json={
                    "model": self.model,
                    "prompt": "Describe this image in detail, including all text, numbers, and visual elements.",
                    "images": [img_b64],
                    "stream": False,
                },
                timeout=60
            )
            return resp.json().get("response", "")
        except Exception as e:
            logger.error(f"Image description failed: {e}")
            return ""
