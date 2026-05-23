"""
ChartVectorExtractor 使用示例

演示如何从 PDF 趋势图中提取时间序列数据。
"""

from chart_vector_extractor import ChartVectorExtractor


def example_manual_config():
    """
    示例 1：手动配置子图区域（推荐，精度最高）

    适用于已知图表布局的情况。通过查看 PDF 或图片确定各子图的 y 坐标范围。
    """
    extractor = ChartVectorExtractor()

    pdf_path = "/path/to/《深圳建设工程价格信息》2026年1月.pdf"

    # P15 配置：4 个子图，每个子图包含 1~2 条数据线
    p15_subcharts = [
        {
            "y1": 130, "y2": 292,
            "name": "热轧钢筋",
            "series": ["热轧光圆钢筋HP300 Φ8盘卷", "热轧带肋钢筋HRB400E Φ16"],
            "price_range": (3000, 5500),
            "x_axis_margin": 45,
        },
        {
            "y1": 292, "y2": 446,
            "name": "角钢Q235B",
            "series": ["角钢Q235B"],
            "price_range": (3500, 5500),
            "x_axis_margin": 45,
        },
        {
            "y1": 446, "y2": 605,
            "name": "钢板镀锌钢板",
            "series": ["钢板Q235B δ=8", "镀锌钢板δ=0.5"],
            "price_range": (3500, 6500),
            "x_axis_margin": 50,  # X 轴更接近数据点，需要更严格的过滤
        },
        {
            "y1": 605, "y2": 763,
            "name": "无缝钢管焊接钢管",
            "series": ["无缝钢管", "焊接钢管"],
            "price_range": (3500, 6500),
            "x_axis_margin": 45,
        },
    ]

    results = extractor.extract_from_pdf(
        pdf_path=pdf_path,
        page_num=15,
        subcharts=p15_subcharts,
        month_start=(2023, 1),  # 数据从 2023-01 开始
    )

    print(f"P15 提取了 {len(results)} 个系列")
    for r in results:
        print(f"  {r.chart_name}/{r.series_name}: {len(r.points)} 点, "
              f"价格范围 [{r.points[0].price:.0f}, {r.points[-1].price:.0f}] {r.unit}")

    # 保存为 JSON
    extractor.save_results(results, "chart_data_p15.json")


def example_auto_detect():
    """
    示例 2：自动检测子图区域（实验性，用于辅助确定配置）

    当不确定子图边界时，先用自动检测获取大致区域，再手动微调。
    """
    extractor = ChartVectorExtractor()

    pdf_path = "/path/to/input.pdf"

    detect_result = extractor.extract_auto_detect(pdf_path, page_num=15)
    print("自动检测到的子图区域：")
    for sub in detect_result["subcharts"]:
        print(f"  y=[{sub['y1']}, {sub['y2']}], "
              f"markers={sub['marker_count']}, "
              f"estimated_series={sub['estimated_series_count']}")

    # 基于检测结果手动配置
    # ...


def example_single_series():
    """
    示例 3：单个子图、单条数据线（最简单场景）
    """
    extractor = ChartVectorExtractor()

    results = extractor.extract_from_pdf(
        pdf_path="input.pdf",
        page_num=16,
        subcharts=[
            {
                "y1": 605, "y2": 763,
                "name": "柴油0号",
                "series": ["柴油0号"],
                "price_range": (7, 10),
                "x_axis_margin": 45,
            },
        ],
        month_start=(2023, 1),
    )

    for r in results:
        for p in r.points[:3]:
            print(f"  {p.month}: {p.price} {r.unit}")
        print("  ...")
        for p in r.points[-3:]:
            print(f"  {p.month}: {p.price} {r.unit}")


def example_integration_with_ocr_pipeline():
    """
    示例 4：集成到现有 OCR 管道

    在 classify_page 检测到 chart 类型后，调用矢量提取器补充数据点。
    """
    from chart_vector_extractor import ChartVectorExtractor

    extractor = ChartVectorExtractor()

    # 假设这是 OCR 管道的某个步骤
    def process_chart_page(page_data, pdf_path, page_num):
        # 先进行 OCR 提取标签（标题、系列名、单位）
        ocr_labels = extract_ocr_labels(page_data["cells"])

        # 再调用矢量提取器获取数据点
        subcharts = build_subchart_config_from_ocr(ocr_labels)
        vector_results = extractor.extract_from_pdf(
            pdf_path, page_num, subcharts
        )

        # 合并 OCR 标签和矢量数据
        for series in vector_results:
            series_dict = series.to_dict()
            series_dict["extraction_method"] = "pdf_vector_paths"
            series_dict["chart_title"] = ocr_labels.get("title", "")
            series_dict["unit"] = ocr_labels.get("unit", series.unit)
            # 存入数据库或 JSON
            save_to_db(series_dict)


def build_subchart_config_from_ocr(ocr_labels):
    """
    从 OCR 标签自动生成子图配置（简化示例）

    实际实现需要根据 OCR 结果解析系列名、推断价格范围等。
    """
    # 这里只是一个占位示例
    return [
        {
            "y1": 130, "y2": 292,
            "name": ocr_labels.get("title", "趋势图"),
            "series": ocr_labels.get("legend", ["系列1"]),
            "price_range": (3000, 5500),
        }
    ]


def extract_ocr_labels(cells):
    """占位：从 OCR cells 提取标签"""
    return {"title": "", "legend": [], "unit": ""}


def save_to_db(record):
    """占位：保存到数据库"""
    pass


if __name__ == "__main__":
    example_manual_config()
