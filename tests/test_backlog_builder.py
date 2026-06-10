from src.pipelines.mvp_real_run import MvpRealRun
from src.pipelines.vbro_localization_partial_run import VbroLocalizationPartialRun
from src.sheets.backlog_builder import build_backlog_rows


def test_backlog_builder_is_canonical_and_has_ten_rows():
    rows = build_backlog_rows()
    blocks = [row["block"] for row in rows]

    assert len(rows) == 10
    assert blocks == [
        "WB Content API / dim_product",
        "ВБро",
        "Локализация",
        "РК стата",
        "MPStat / Сравнение карточек",
        "Точка вх",
        "Поисковые запросы",
        "Остатки",
        "ИТОГО_FULL",
        "Настройки_артикулы",
    ]


def test_pipeline_backlog_writers_delegate_to_shared_builder():
    assert MvpRealRun()._build_backlog_rows() == build_backlog_rows()
    assert VbroLocalizationPartialRun()._backlog_rows() == build_backlog_rows()
