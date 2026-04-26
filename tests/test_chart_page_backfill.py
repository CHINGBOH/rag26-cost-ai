import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, relative_path: str):
    module_path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ocr_json_to_pg = _load_module(
    "ocr_json_to_pg",
    "src/backend/python-legacy/tools/ocr_json_to_pg.py",
)
chart_backfill = _load_module(
    "backfill_chart_page_summaries",
    "src/database/scripts/backfill_chart_page_summaries.py",
)


def test_normalize_price_row_splits_collapsed_unit_price() -> None:
    row = {
        "material": "中砂",
        "spec": "m² 189.00",
        "unit": "",
        "price_tax": "",
        "price": "",
    }

    normalized = ocr_json_to_pg.normalize_price_row(row)

    assert normalized["spec"] == ""
    assert normalized["unit"] == "m³"
    assert normalized["price_tax"] == "189.0"


def test_is_valid_material_label_rejects_malformed_ocr_fragment() -> None:
    assert not ocr_json_to_pg.is_valid_material_label("程，企业管理费")
    assert not ocr_json_to_pg.is_valid_material_label("价格信息")
    assert ocr_json_to_pg.is_valid_material_label("普通硅酸盐水泥P.042.5R散装")


def test_extract_chart_materials_keeps_material_labels() -> None:
    content = (
        "造价信息\n深圳建设工程价格信息\n●部分材料价格变化趋势图\n"
        "部分材料价格变化趋势图（2023-2026年）\n"
        "普通硅酸盐水泥P.042.5R散装\n中砂\n(单位：元/t)\n"
        "碎石5～25\n柴油0号\n"
    )

    materials = chart_backfill.extract_chart_materials(content)

    assert "中砂" in materials
    assert "碎石5～25" in materials
    assert "柴油0号" in materials


def test_normalize_material_name_canonicalizes_diesel_zero() -> None:
    assert chart_backfill.normalize_material_name("柴油") == "柴油0号"
    assert chart_backfill.normalize_material_name("柴油 0号") == "柴油0号"


def test_extract_material_price_reads_text_chunk_page() -> None:
    content = (
        "●建筑材料价格\n(2026年1月价格)\n"
        "4\n中砂\nm²\n187.00\n5\n碎石\n20 ~ 40\nm\n179.00\n"
    )

    parsed = chart_backfill.extract_material_price(content, "中砂")

    assert parsed == ("m³", "187.00")


def test_extract_material_price_ignores_prefixed_sequence_digit() -> None:
    content = "碎石5 ~25m6146.00石粉渣m108.00"

    parsed = chart_backfill.extract_material_price(content, "碎石5～25")

    assert parsed == ("m³", "146.00")
