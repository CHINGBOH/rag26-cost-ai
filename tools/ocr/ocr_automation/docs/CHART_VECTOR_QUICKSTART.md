# Chart Vector Extractor 快速入门

处理 PDF 趋势图数据提取的快速指南。下一个 PDF 只需要三步。

---

## 三步提取数据

### 第 1 步：自动检测子图区域

```bash
cd /home/l/rag-dashboard

.venv-ocr/bin/python -m tools.ocr_automation.engine.chart_vector_cli detect \
  --pdf "path/to/你的文件.pdf" \
  --page 15 \
  --output /tmp/chart_detected.json
```

这会输出一个模板文件，包含检测到的子图 y 边界。你需要手动补充 `series`（系列名）和 `price_range`（价格范围）。

### 第 2 步：编辑配置文件

打开 `/tmp/chart_detected.json`，补充以下内容：

```json
{
  "pdf": "path/to/你的文件.pdf",
  "page": 15,
  "month_start": [2023, 1],
  "subcharts": [
    {
      "y1": 130,
      "y2": 292,
      "name": "热轧钢筋",
      "series": ["热轧光圆钢筋", "热轧带肋钢筋"],
      "price_range": [3000, 5500],
      "x_axis_margin": 45
    }
  ]
}
```

**必填字段**：
- `y1` / `y2`: 子图的上下边界（PDF 坐标）
- `name`: 子图名称
- `series`: 数据线名称列表（1 个或多个）
- `price_range`: [最低价, 最高价]

**可选字段**：
- `x_axis_margin`: X 轴过滤边距（默认 45，X 轴接近数据点时加大到 50）
- `month_start`: 数据起始年月（默认 [2023, 1]）

**如何确定 y1/y2**：
- 方法 A：用 `detect` 命令自动检测（粗略）
- 方法 B：从 PDF 渲染图片，肉眼测量子图边界
- 方法 C：用 pymupdf 遍历 drawing paths 的 y 分布

### 第 3 步：执行提取

```bash
.venv-ocr/bin/python -m tools.ocr_automation.engine.chart_vector_cli extract \
  --pdf "path/to/你的文件.pdf" \
  --page 15 \
  --config /tmp/chart_detected.json \
  --output /tmp/chart_result.json
```

输出格式：

```json
[
  {
    "page": 15,
    "chart_name": "热轧钢筋",
    "series_name": "热轧光圆钢筋",
    "unit": "元/t",
    "point_count": 37,
    "time_range": "2023-01至2026-01",
    "price_range": {"min": 3571, "max": 4820},
    "data_points": [
      {"month": "2023-01", "price": 4496.48, "_y_pixel": 184.2},
      ...
    ]
  }
]
```

---

## 在 Python 代码中使用

### 简单场景

```python
from tools.ocr_automation.engine.chart_vector_extractor import ChartVectorExtractor

extractor = ChartVectorExtractor()

results = extractor.extract_from_pdf(
    pdf_path="input.pdf",
    page_num=15,
    subcharts=[
        {"y1": 130, "y2": 292, "name": "钢筋", "series": ["光圆", "带肋"], "price_range": (3000, 5500)},
    ],
    month_start=(2023, 1),
)

for r in results:
    print(f"{r.series_name}: {len(r.points)} points")
```

### 集成到 OCR 管道

```python
from tools.ocr_automation.engine.chart_extractor import ChartExtractor

chart_ext = ChartExtractor(output_dir=Path("./output"))

# 1. OCR 提取标签
labels = chart_ext.extract_ocr_labels(cells)

# 2. 矢量提取数据点
records = chart_ext.extract_vector_data(
    pdf_path="input.pdf",
    page_num=15,
    subcharts=[{
        "y1": 130, "y2": 292,
        "name": labels["title"],
        "series": labels["legend"],
        "price_range": (3000, 5500),
    }],
)

# 3. records 可直接入库
```

---

## 多页批量处理

如果有多页趋势图，写一个简单的循环：

```python
from tools.ocr_automation.engine.chart_vector_extractor import ChartVectorExtractor
import json

extractor = ChartVectorExtractor()
pdf = "input.pdf"

# 每页的配置
pages_config = {
    15: [
        {"y1": 130, "y2": 292, "name": "钢筋", "series": [...], "price_range": (3000, 5500)},
    ],
    16: [
        {"y1": 130, "y2": 292, "name": "水泥", "series": [...], "price_range": (300, 550)},
    ],
}

all_results = []
for page_num, subcharts in pages_config.items():
    results = extractor.extract_from_pdf(pdf, page_num, subcharts)
    all_results.extend(results)

extractor.save_results(all_results, "all_chart_data.json")
```

---

## 常见问题

**Q: 提取的点数不够 37 个？**
A: 检查 `x_axis_margin` 是否太小，导致 X 轴刻度被误认为数据点；或太大，过滤掉了真实数据点。尝试调整 40~50 之间的值。

**Q: 两条线的数据被交换了？**
A: 检查 `series` 列表的顺序。算法按列表顺序分配线，如果图例中第一条线对应图表中下方的线，需要调整 `series` 顺序。

**Q: 价格绝对值偏差大？**
A: `price_range` 需要准确反映图表 Y 轴范围。可以从 OCR 提取的 Y 轴标签获取，或根据常识调整。
