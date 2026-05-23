# 趋势图矢量提取方法总结

> 适用场景：PDF 中的趋势图/折线图包含大量数据点，OCR 无法识别、视觉模型无法精确定位的情况。
>
> 成功案例：《深圳建设工程价格信息》2026年1月 P15/P16，11 个材料系列，37 个月，407 个数据点。

---

## 一、核心原理：解析 PDF 矢量绘制指令

PDF 中的图表数据点不是文本，也不是像素图像，而是**矢量绘制路径**（drawing paths）。通过 `pymupdf` 的 `page.get_drawings()` 可以获取每个绘制对象的原始指令。

每个数据点标记在 PDF 中表现为一个小矩形（`"re"` 指令）：

```python
import fitz

doc = fitz.open("input.pdf")
page = doc[page_num - 1]
drawings = page.get_drawings()

for d in drawings:
    items = d.get("items", [])
    for item in items:
        if item[0] == "re":  # 矩形
            rect = item[1]
            # rect.x0, rect.y0, rect.x1, rect.y1
```

### 数据点标记的特征

| 特征 | 值 | 说明 |
|------|-----|------|
| 宽度 | 4~6 px | 小矩形标记的宽 |
| 高度 | 4~6 px | 小矩形标记的高 |
| path items | 4 或 15 | 矩形或填充路径的指令数 |
| 中心 x 范围 | 80~530 | 在图表绘图区域内 |
| 中心 y 范围 | 子图内 | 根据子图位置确定 |
| 重复次数 | 2 次/点 | 同一位置绘制两次（深浅色或描边+填充）|

P15 单页 1957 个 paths 中，数据点标记约占 150 个（4 个子图 × 37 月 × 2 线 × 2 次绘制 ≈ 592，加上 X/Y 轴标记约 150 个）。

---

## 二、三层噪声过滤

原始 paths 包含大量噪声，必须逐层过滤。

### 第一层：几何特征过滤

```python
if not (2 <= width <= 12 and 2 <= height <= 12):
    continue           # 过滤线条、填充区域
if cx < 80:
    continue           # 过滤 Y 轴刻度标记
if cy > y2 - 45:
    continue           # 过滤 X 轴刻度标记（子图底部 45px）
if not (70 <= cx <= 540):
    continue           # 过滤图例、标题区域的标记
```

### 第二层：X 间距链追踪（关键创新）

月份在 X 轴上是**等间距排列**的，正常间距约 12px。噪声 cluster 的间距异常（如 5px、单点孤立）。

**算法**：从左侧开始贪婪构建月份链，每一步在 `预期位置 ±6px` 内搜索下一个 cluster。

```python
MEDIAN_SPACING = 12.0  # 月份间距中位数

def build_chain(start_idx, clusters):
    chain = [start_idx]
    i = start_idx + 1
    while i < len(clusters) and len(chain) < 40:
        expected_x = clusters[chain[-1]][0].x + MEDIAN_SPACING
        best_idx = None
        best_dist = float("inf")
        for j in range(i, min(i + 4, len(clusters))):
            dist = abs(clusters[j][0].x - expected_x)
            if dist < best_dist and dist < 6:
                best_dist = dist
                best_idx = j
        if best_idx is not None:
            chain.append(best_idx)
            i = best_idx + 1
        else:
            i += 1
    return chain
```

**为什么有效**：
- X 轴刻度标记虽然在正确的 x 位置，但 y 已在第一层过滤掉
- Y 轴刻度标记（x < 80）已被过滤
- 网格线交叉点通常是单点且 x 位置偏离月份序列

### 第三层：Y 值轨迹追踪（解决线条重叠）

同一月份有多个 y 值候选（2 条线 × 2 次绘制 = 最多 4 个 y 值，加上噪声可能更多）。**不能简单排序取前 N 个**，因为：

1. 噪声 y 值可能比真实数据更小（更高价格位置）
2. 两条线可能相交或非常接近

**解决方案**：基于历史趋势预测当前位置，最近邻匹配。

```python
def predict_y(history):
    """基于前 2-3 个月的斜率线性外推"""
    ys = [y for y in history if y is not None]
    if len(ys) == 0:
        return 200  # 初始默认值
    if len(ys) == 1:
        return ys[-1]
    if len(ys) == 2:
        return ys[-1] + (ys[-1] - ys[-2])
    # 三阶差分外推
    dy1 = ys[-1] - ys[-2]
    dy2 = ys[-2] - ys[-3]
    return ys[-1] + (dy1 + dy2) / 2


# 每个月份：将候选 y 值分配给各条线
for month_idx in chain:
    candidates = get_y_values(clusters[month_idx])
    predictions = [predict_y(line.history) for line in lines]

    # 贪心：每条线找最近的未分配候选点
    for line_idx in sorted(range(n_lines), key=lambda i: predictions[i]):
        best = min(unassigned_candidates,
                   key=lambda y: abs(y - predictions[line_idx]))
        lines[line_idx].history.append(best)
```

**为什么有效**：即使两条线在某月相交（y 值相同），下一个月它们会分开。算法根据各自的历史轨迹预测，不会混淆。

---

## 三、价格映射

从 PDF y 坐标到实际价格的映射：

```python
# 从该子图所有数据点的 y 范围推断 Y 轴边界
all_y = [y for line in lines for y in line.history]
y_min = min(all_y)
y_max = max(all_y)

margin = (y2 - y1) * 0.12  # 子图高度的 12% 作为边距
y_pixel_top    = y_min - margin   # 对应 price_max（图表顶部）
y_pixel_bottom = y_max + margin   # 对应 price_min（图表底部）

ratio = (y_pixel_bottom - y_pixel) / (y_pixel_bottom - y_pixel_top)
ratio = max(0, min(1, ratio))
price = price_min + ratio * (price_max - price_min)
```

`price_min` 和 `price_max` 根据图表 Y 轴刻度确定（可从 OCR 提取的 Y 轴标签获取，或根据材料常识设定）。

---

## 四、完整流程图

```
PDF page
  ↓ get_drawings() — 获取 1957 个矢量路径
  ↓
几何过滤（宽/高/x范围/y范围）— 过滤大区域、Y轴、X轴
  ↓
X 方向聚类（3px 阈值）— 将同一月份的 markers 分组
  ↓
X 间距链追踪 — 构建 37 个月的连续序列，跳过噪声 cluster
  ↓
Y 值轨迹追踪 — 逐月将候选 y 值分配给各条数据线
  ↓
Y 轴价格映射 — 将 y 坐标转换为实际价格
  ↓
输出：series_name → [{month, price}, ...]
```

---

## 五、关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| marker 宽/高范围 | 2~12 px | 过滤非数据标记 |
| X 聚类阈值 | 3 px | 同一月份的 markers 中心 x 差 |
| 月份间距 | 10~16 px | 正常月份间距范围 |
| 间距搜索窗口 | ±6 px | 链追踪时允许的位置偏差 |
| X 轴过滤阈值 | `y2 - 40~50` | 根据子图底部位置调整 |
| Y 轴过滤阈值 | `x < 80` | 过滤 Y 轴刻度 |
| 轨迹预测偏差容忍 | < 30 px | 候选点与预测位置的最大偏差 |
| Y 轴边距比例 | 12~15% | 数据点范围之外的边距 |

---

## 六、使用方法

### 方式 1：直接使用 ChartVectorExtractor（推荐）

```python
from ocr_automation.engine.chart_vector_extractor import ChartVectorExtractor

extractor = ChartVectorExtractor()

results = extractor.extract_from_pdf(
    pdf_path="input.pdf",
    page_num=15,
    subcharts=[
        {
            "y1": 130, "y2": 292,
            "name": "热轧钢筋",
            "series": ["光圆钢筋", "带肋钢筋"],
            "price_range": (3000, 5500),
        },
    ],
    month_start=(2023, 1),
)

# results 是 List[SeriesResult]
for r in results:
    print(f"{r.series_name}: {len(r.points)} points")
    for p in r.points[:3]:
        print(f"  {p.month}: {p.price}")

# 保存为 JSON
extractor.save_results(results, "chart_data.json")
```

### 方式 2：通过 ChartExtractor 集成到现有管道

```python
from ocr_automation.engine.chart_extractor import ChartExtractor

chart_extractor = ChartExtractor(output_dir=Path("./output"))

# 先提取 OCR 标签
labels = chart_extractor.extract_ocr_labels(cells)

# 再提取矢量数据点
records = chart_extractor.extract_vector_data(
    pdf_path="input.pdf",
    page_num=15,
    subcharts=[
        {
            "y1": 130, "y2": 292,
            "name": "热轧钢筋",
            "series": labels["legend"][:2],  # 从 OCR 获取系列名
            "price_range": (3000, 5500),
        },
    ],
)

# records 与 extract_from_image 输出格式兼容
for rec in records:
    print(f"{rec['series_name']} {rec['year_month']}: {rec['price_value']}")
```

### 方式 3：自动检测辅助配置

```python
# 当不确定子图边界时
detect_result = chart_extractor.auto_detect_subcharts("input.pdf", page_num=15)
print(detect_result)
# 输出：{"subcharts": [{"y1": 130, "y2": 292, "estimated_series_count": 2}, ...]}
```

---

## 七、验证方法

1. **点数验证**：每个系列应为 37 点（2023-01 至 2026-01）
2. **月份连续性验证**：检查是否缺少某个月份
3. **价格合理性验证**：与同期价格表中的实际价格对比
4. **趋势合理性验证**：价格应从 2023 到 2026 总体呈下降趋势（符合当时市场环境）

---

## 八、适用限制

| 限制 | 说明 |
|------|------|
| PDF 必须是矢量图 | 如果图表是栅格图片嵌入 PDF，则无法提取 |
| 数据点必须是独立路径 | 如果数据点被合并为一个复合路径，需要额外解析 |
| 子图必须水平排列 | 当前方法假设月份沿 X 轴等间距排列 |
| 需要已知 price_range | Y 轴价格范围需从 OCR 标签或外部知识获取 |

---

## 九、代码文件

| 文件 | 说明 |
|------|------|
| `engine/chart_vector_extractor.py` | 核心提取器（独立可复用） |
| `engine/chart_extractor.py` | 封装集成（与现有管道兼容） |
| `engine/chart_vector_example.py` | 使用示例 |
| `docs/CHART_VECTOR_EXTRACTION.md` | 本文档 |
