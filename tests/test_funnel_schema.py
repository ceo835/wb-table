from src.sheets.schema_definitions import USER_SHEET_SCHEMAS


def test_funnel_sheet_starts_with_date():
    columns = USER_SHEET_SCHEMAS["Воронка на день"].columns
    assert columns[:6] == (
        "Дата",
        "Артикул продавца",
        "Артикул WB",
        "Название",
        "Предмет",
        "Бренд",
    )
