from src.db.active_products_backfill import _build_reference_indexes, _chunked


def test_chunked_splits_values_without_loss():
    chunks = _chunked([1, 2, 3, 4, 5], 2)

    assert chunks == [[1, 2], [3, 4], [5]]


def test_build_reference_indexes_maps_int_and_string_keys():
    int_index, str_index = _build_reference_indexes(
        [
            {
                "nm_id": 197330807,
                "supplier_article": "BlackWOM5",
                "title": "Трусы комплект",
                "subject": "Трусы",
                "brand": "PALEY",
            }
        ]
    )

    assert int_index[197330807]["supplier_article"] == "BlackWOM5"
    assert str_index["197330807"]["brand"] == "PALEY"
