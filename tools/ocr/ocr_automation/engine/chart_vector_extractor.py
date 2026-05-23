"""
PDF 趋势图矢量数据提取引擎

基于 PDF 矢量绘制路径(drawing paths)提取趋势图数据点，无需 OCR 或视觉模型。
适用场景：PDF 中的矢量趋势图/折线图，数据点由小矩形/标记组成。

核心流程：
1. 从 PDF 提取 drawing paths
2. 几何过滤：筛选数据点标记（小矩形，排除轴刻度等噪声）
3. X 方向聚类：按 x 坐标将同一月份的标记分组
4. X 间距链追踪：基于等间距(~12px)构建连续月份序列
5. Y 轨迹追踪：基于历史趋势将 y 值分配给各数据线
6. 价格映射：y 坐标转换为实际价格

使用示例：
    >>> from chart_vector_extractor import ChartVectorExtractor
    >>> extractor = ChartVectorExtractor()
    >>> result = extractor.extract_from_pdf(
    ...     pdf_path="input.pdf",
    ...     page_num=15,
    ...     subcharts=[
    ...         {"y1": 130, "y2": 292, "name": "热轧钢筋",
    ...          "series": ["光圆钢筋", "带肋钢筋"], "price_range": (3000, 5500)},
    ...     ]
    ... )
"""

import logging
from typing import List, Dict, Optional, Tuple, NamedTuple
from dataclasses import dataclass
from pathlib import Path
import json

import numpy as np

logger = logging.getLogger(__name__)

# 尝试导入 pymupdf，如果不可用则给出友好提示
try:
    import fitz  # pymupdf
except ImportError:
    fitz = None
    logger.warning("pymupdf (fitz) not installed. ChartVectorExtractor will not work.")


@dataclass
class SubchartConfig:
    """单个子图的配置"""
    y1: float                # 子图上边界（PDF y 坐标）
    y2: float                # 子图下边界（PDF y 坐标）
    name: str                # 子图名称/标题
    series: List[str]        # 数据线系列名称列表
    price_range: Tuple[float, float]  # (price_min, price_max)
    x_axis_margin: int = 45  # X 轴过滤边距（px），根据子图调整


@dataclass
class DataPoint:
    """单个数据点"""
    month: str               # 格式：YYYY-MM
    price: float
    y_pixel: float           # 原始 y 坐标（用于调试）


@dataclass
class SeriesResult:
    """单个系列的提取结果"""
    page: int
    chart_name: str
    series_name: str
    unit: str
    points: List[DataPoint]

    def to_dict(self) -> Dict:
        return {
            "page": self.page,
            "chart_name": self.chart_name,
            "series_name": self.series_name,
            "unit": self.unit,
            "point_count": len(self.points),
            "time_range": f"{self.points[0].month}至{self.points[-1].month}" if self.points else "",
            "price_range": {
                "min": round(min(p.price for p in self.points), 2),
                "max": round(max(p.price for p in self.points), 2),
            },
            "data_points": [
                {"month": p.month, "price": p.price, "_y_pixel": round(p.y_pixel, 1)}
                for p in self.points
            ],
        }


class ChartVectorExtractor:
    """
    PDF 趋势图矢量数据提取器

    不依赖 OCR/视觉模型，直接从 PDF 矢量路径中提取数据点。
    """

    # 默认参数
    DEFAULT_MARKER_WH_RANGE = (2.0, 12.0)   # marker 宽/高范围
    DEFAULT_X_CLUSTER_THRESH = 3.0          # X 方向聚类阈值（px）
    DEFAULT_MONTH_SPACING = (8, 16)         # 正常月份间距范围（px）
    DEFAULT_SPACING_TOLERANCE = 6.0         # 间距搜索容忍度（px）
    DEFAULT_Y_PREDICT_TOLERANCE = 30.0      # Y 预测偏差容忍度（px）
    DEFAULT_MARGIN_RATIO = 0.12             # Y 轴边距占子图高度比例
    DEFAULT_X_MIN = 70.0                    # 数据点最小 x 坐标（过滤 Y 轴）
    DEFAULT_X_MAX = 540.0                   # 数据点最大 x 坐标

    def __init__(self):
        if fitz is None:
            raise ImportError("pymupdf (fitz) is required. Install with: pip install pymupdf")

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def extract_from_pdf(
        self,
        pdf_path: str,
        page_num: int,
        subcharts: List[Dict],
        month_start: Tuple[int, int] = (2023, 1),
    ) -> List[SeriesResult]:
        """
        从 PDF 指定页面提取趋势图数据

        Args:
            pdf_path: PDF 文件路径
            page_num: 页码（从 1 开始）
            subcharts: 子图配置列表，每个元素为 dict：
                {
                    "y1": 130, "y2": 292,
                    "name": "热轧钢筋",
                    "series": ["光圆钢筋", "带肋钢筋"],
                    "price_range": (3000, 5500),
                    "x_axis_margin": 45,  # 可选
                }
            month_start: 起始年月 (year, month)，默认 (2023, 1)

        Returns:
            List[SeriesResult]
        """
        configs = [self._dict_to_config(c) for c in subcharts]
        doc = fitz.open(pdf_path)
        page = doc[page_num - 1]
        drawings = page.get_drawings()
        doc.close()

        results = []
        for cfg in configs:
            series_results = self._extract_subchart(
                drawings, page_num, cfg, month_start
            )
            results.extend(series_results)

        return results

    def extract_auto_detect(
        self,
        pdf_path: str,
        page_num: int,
    ) -> Dict:
        """
        自动检测子图区域和系列名（实验性功能）

        基于 drawing paths 的分布自动推断：
        - 子图边界：y 坐标聚类
        - 系列名：需要 OCR 配合（返回 y 坐标供后续匹配）

        Returns:
            {
                "subcharts": [
                    {"y1": 130, "y2": 292, "estimated_series_count": 2},
                    ...
                ],
                "raw_markers": [...],  # 原始标记坐标供调试
            }
        """
        doc = fitz.open(pdf_path)
        page = doc[page_num - 1]
        drawings = page.get_drawings()
        doc.close()

        markers = self._collect_markers(drawings, (0, 9999), 0)
        # Y 坐标聚类检测子图边界
        ys = [m["y"] for m in markers]
        subcharts = self._detect_subchart_regions(ys)

        return {
            "subcharts": subcharts,
            "marker_count": len(markers),
        }

    def save_results(self, results: List[SeriesResult], output_path: str):
        """将提取结果保存为 JSON"""
        data = [r.to_dict() for r in results]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(data)} series to {output_path}")

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _dict_to_config(self, d: Dict) -> SubchartConfig:
        """将 dict 转为 SubchartConfig"""
        return SubchartConfig(
            y1=d["y1"],
            y2=d["y2"],
            name=d["name"],
            series=d["series"],
            price_range=tuple(d["price_range"]),
            x_axis_margin=d.get("x_axis_margin", 45),
        )

    def _extract_subchart(
        self,
        drawings: List[Dict],
        page_num: int,
        cfg: SubchartConfig,
        month_start: Tuple[int, int],
    ) -> List[SeriesResult]:
        """提取单个子图"""
        logger.info(f"Extracting subchart '{cfg.name}' y=[{cfg.y1}, {cfg.y2}]")

        # 1. 收集 markers
        markers = self._collect_markers(drawings, (cfg.y1, cfg.y2), cfg.x_axis_margin)
        if len(markers) < 20:
            logger.warning(f"Too few markers ({len(markers)}) in subchart {cfg.name}")
            return []

        # 2. X 方向聚类
        clusters = self._cluster_by_x(markers, self.DEFAULT_X_CLUSTER_THRESH)
        logger.debug(f"  Clusters: {len(clusters)}")

        # 3. X 间距链追踪
        chain = self._build_month_chain(clusters)
        if len(chain) > 37:
            chain = chain[:37]
        logger.info(f"  Month chain: {len(chain)} months")

        # 4. Y 轨迹追踪
        line_y_values = self._track_y_trajectory(clusters, chain, len(cfg.series))

        # 5. 价格映射
        results = self._map_to_prices(
            line_y_values, cfg, page_num, month_start, chain
        )

        for r in results:
            logger.info(
                f"  {r.series_name}: {len(r.points)} pts, "
                f"price=[{r.points[0].price:.0f}, {r.points[-1].price:.0f}]"
            )

        return results

    def _collect_markers(
        self,
        drawings: List[Dict],
        y_region: Tuple[float, float],
        x_axis_margin: int,
    ) -> List[Dict]:
        """
        从 drawing paths 中收集数据点标记

        过滤条件：
        - 宽/高在范围内（小矩形标记）
        - 中心在子图区域内
        - 不在 Y 轴（x < 80）或 X 轴（y > y2 - margin）附近
        """
        y1, y2 = y_region
        x_axis_threshold = y2 - x_axis_margin
        wh_min, wh_max = self.DEFAULT_MARKER_WH_RANGE
        markers = []

        for d in drawings:
            items = d.get("items", [])
            if not items:
                continue

            xs, ys = [], []
            for item in items:
                if item[0] == "l":
                    xs.extend([item[1].x, item[2].x])
                    ys.extend([item[1].y, item[2].y])
                elif item[0] == "c":
                    xs.extend([item[1].x, item[4].x])
                    ys.extend([item[1].y, item[4].y])
                elif item[0] == "re":
                    r = item[1]
                    xs.extend([r.x0, r.x1])
                    ys.extend([r.y0, r.y1])

            if not xs:
                continue

            w = max(xs) - min(xs)
            h = max(ys) - min(ys)
            cx = (min(xs) + max(xs)) / 2
            cy = (min(ys) + max(ys)) / 2

            if not (wh_min <= w <= wh_max and wh_min <= h <= wh_max):
                continue
            if not (y1 <= cy <= y2):
                continue
            if cx < self.DEFAULT_X_MIN:
                continue
            if cy > x_axis_threshold:
                continue
            if not (self.DEFAULT_X_MIN <= cx <= self.DEFAULT_X_MAX):
                continue

            markers.append({"x": cx, "y": cy, "w": w, "h": h})

        markers.sort(key=lambda m: m["x"])
        return markers

    def _cluster_by_x(self, markers: List[Dict], threshold: float) -> List[List[Dict]]:
        """按 x 坐标聚类（同一月份的标记）"""
        clusters = []
        for m in markers:
            if clusters and abs(m["x"] - clusters[-1][0]["x"]) < threshold:
                clusters[-1].append(m)
            else:
                clusters.append([m])
        return clusters

    def _build_month_chain(self, clusters: List[List[Dict]]) -> List[int]:
        """
        构建月份链：基于等间距假设追踪连续月份

        算法：
        1. 计算相邻 cluster 间距的中位数（正常月份间距）
        2. 从左侧候选起点开始，贪婪搜索下一个 cluster
        3. 要求下一个 cluster 在预期位置 ±tolerance 内
        """
        if len(clusters) < 2:
            return list(range(len(clusters)))

        spacings = [
            clusters[i + 1][0]["x"] - clusters[i][0]["x"]
            for i in range(len(clusters) - 1)
        ]
        valid = [s for s in spacings if self.DEFAULT_MONTH_SPACING[0] <= s <= self.DEFAULT_MONTH_SPACING[1]]
        median_spacing = float(np.median(valid)) if valid else 12.0

        best_chain = []
        for start in range(min(4, len(clusters))):
            chain = self._build_chain_from(start, clusters, median_spacing)
            if len(chain) > len(best_chain):
                best_chain = chain

        return best_chain

    def _build_chain_from(
        self, start: int, clusters: List[List[Dict]], median_spacing: float
    ) -> List[int]:
        """从指定起点构建月份链"""
        chain = [start]
        i = start + 1
        tol = self.DEFAULT_SPACING_TOLERANCE

        while i < len(clusters) and len(chain) < 40:
            expected_x = clusters[chain[-1]][0]["x"] + median_spacing
            best_idx = None
            best_dist = float("inf")

            for j in range(i, min(i + 4, len(clusters))):
                dist = abs(clusters[j][0]["x"] - expected_x)
                if dist < best_dist and dist < tol:
                    best_dist = dist
                    best_idx = j

            if best_idx is not None:
                chain.append(best_idx)
                i = best_idx + 1
            else:
                i += 1

        return chain

    def _track_y_trajectory(
        self, clusters: List[List[Dict]], chain: List[int], n_lines: int
    ) -> List[List[float]]:
        """
        轨迹追踪：将每个月份的候选 y 值分配给各条线

        核心逻辑：
        1. 对每条线，基于历史 y 值预测当前位置
        2. 将候选 y 值按最近邻原则分配给各线
        3. 优先处理预测位置更"极端"的线（离均值更远的）
        """
        line_values: List[List[float]] = [[] for _ in range(n_lines)]

        for cluster_idx in chain:
            c = clusters[cluster_idx]
            ys = sorted(set(round(m["y"], 1) for m in c))
            preds = [self._predict_y(line_values[i]) for i in range(n_lines)]

            if len(ys) < n_lines:
                # 候选点不足，用预测值补充
                used = [False] * len(ys)
                for line_idx in sorted(range(n_lines), key=lambda i: preds[i]):
                    best_yi = None
                    best_dist = float("inf")
                    for yi, y in enumerate(ys):
                        if used[yi]:
                            continue
                        dist = abs(y - preds[line_idx])
                        if dist < best_dist:
                            best_dist = dist
                            best_yi = yi
                    if best_yi is not None and best_dist < self.DEFAULT_Y_PREDICT_TOLERANCE:
                        line_values[line_idx].append(ys[best_yi])
                        used[best_yi] = True
                    else:
                        line_values[line_idx].append(preds[line_idx])
            else:
                # 候选点足够（或过多），贪心匹配
                assigned = [False] * len(ys)
                mean_y = sum(ys) / len(ys)
                # 优先处理离均值更远的线（更确定的分配）
                order = sorted(range(n_lines), key=lambda i: abs(preds[i] - mean_y), reverse=True)
                for line_idx in order:
                    pred = preds[line_idx]
                    best_yi = None
                    best_dist = float("inf")
                    for yi, y in enumerate(ys):
                        if assigned[yi]:
                            continue
                        dist = abs(y - pred)
                        if dist < best_dist:
                            best_dist = dist
                            best_yi = yi
                    if best_yi is not None:
                        line_values[line_idx].append(ys[best_yi])
                        assigned[best_yi] = True
                    else:
                        line_values[line_idx].append(pred)

        return line_values

    @staticmethod
    def _predict_y(history: List[float]) -> float:
        """基于历史 y 值预测下一个位置（线性外推）"""
        ys = [y for y in history]
        if not ys:
            return 200.0
        if len(ys) == 1:
            return ys[-1]
        if len(ys) == 2:
            return ys[-1] + (ys[-1] - ys[-2])
        dy1 = ys[-1] - ys[-2]
        dy2 = ys[-2] - ys[-3]
        return ys[-1] + (dy1 + dy2) / 2.0

    def _map_to_prices(
        self,
        line_y_values: List[List[float]],
        cfg: SubchartConfig,
        page_num: int,
        month_start: Tuple[int, int],
        chain: List[int],
    ) -> List[SeriesResult]:
        """将 y 坐标映射为实际价格"""
        price_min, price_max = cfg.price_range
        all_ys = [y for line in line_y_values for y in line]
        if not all_ys:
            return []

        y_min = min(all_ys)
        y_max = max(all_ys)
        margin = (cfg.y2 - cfg.y1) * self.DEFAULT_MARGIN_RATIO
        y_pixel_top = y_min - margin
        y_pixel_bottom = y_max + margin
        y_range = y_pixel_bottom - y_pixel_top
        if y_range == 0:
            y_range = 1.0

        start_year, start_month = month_start
        results = []

        for line_idx, series_name in enumerate(cfg.series):
            points = []
            for i, y_pixel in enumerate(line_y_values[line_idx]):
                ratio = (y_pixel_bottom - y_pixel) / y_range
                ratio = max(0.0, min(1.0, ratio))
                price = price_min + ratio * (price_max - price_min)

                # 计算月份
                total_months = (start_year - 2023) * 12 + (start_month - 1) + i
                year = 2023 + total_months // 12
                month = (total_months % 12) + 1
                ym = f"{year}-{month:02d}"

                points.append(DataPoint(month=ym, price=round(price, 2), y_pixel=y_pixel))

            unit = "元/L" if "柴油" in cfg.name else "元/t"
            results.append(
                SeriesResult(
                    page=page_num,
                    chart_name=cfg.name,
                    series_name=series_name,
                    unit=unit,
                    points=points,
                )
            )

        return results

    # ------------------------------------------------------------------
    # 自动检测（实验性）
    # ------------------------------------------------------------------

    def _detect_subchart_regions(self, ys: List[float]) -> List[Dict]:
        """
        基于 y 坐标分布自动检测子图区域

        原理：数据点在 y 方向上是分层的，每个子图的数据点形成一个密集的 band
        """
        if not ys:
            return []

        # 简单的直方图聚类
        y_bins: Dict[int, int] = {}
        for y in ys:
            b = int(y / 20) * 20  # 20px 一个 bin
            y_bins[b] = y_bins.get(b, 0) + 1

        # 找连续的 dense bin
        sorted_bins = sorted(y_bins.items())
        regions = []
        current_start = None
        current_count = 0

        for b, count in sorted_bins:
            if count >= 3:  # dense bin
                if current_start is None:
                    current_start = b
                current_count += count
            else:
                if current_start is not None:
                    regions.append({
                        "y1": current_start,
                        "y2": b,
                        "marker_count": current_count,
                    })
                    current_start = None
                    current_count = 0

        if current_start is not None:
            regions.append({
                "y1": current_start,
                "y2": sorted_bins[-1][0] + 20,
                "marker_count": current_count,
            })

        # 合并接近的区域
        merged = []
        for r in regions:
            if merged and r["y1"] - merged[-1]["y2"] < 30:
                merged[-1]["y2"] = r["y2"]
                merged[-1]["marker_count"] += r["marker_count"]
            else:
                merged.append(r.copy())

        # 估算系列数（根据 marker 密度）
        for r in merged:
            # 粗略估算：每个系列每月 2 个 marker，37 个月
            estimated = max(1, round(r["marker_count"] / 74))
            r["estimated_series_count"] = estimated

        return merged
