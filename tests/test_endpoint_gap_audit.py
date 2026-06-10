from src.reports.endpoint_gap_audit import FieldSpec, _find_download_id, _field_result, first_list_length, has_path_anywhere


def test_has_path_anywhere_finds_nested_values() -> None:
    payload = {
        "data": {
            "items": [
                {
                    "openCard": {"current": 6, "dynamics": 100, "percentile": 100},
                    "addToCart": {"current": 0, "dynamics": 0, "percentile": 100},
                }
            ]
        }
    }

    assert has_path_anywhere(payload, ("openCard", "percentile"))
    assert has_path_anywhere(payload, ("addToCart", "percentile"))
    assert not has_path_anywhere(payload, ("orders", "percentile"))


def test_first_list_length_works_for_nested_lists() -> None:
    payload = {"data": {"items": [1, 2, 3]}}
    assert first_list_length(payload, ("data", "items")) == 3
    assert first_list_length(payload, ("missing",)) == 3


def test_find_download_id_prefers_first_valid_id() -> None:
    payload = {"data": [{"name": "one"}, {"id": "abc-123"}, {"id": "zzz"}]}
    assert _find_download_id(payload) == "abc-123"


def test_field_result_marks_found_and_missing_correctly() -> None:
    payload = {"data": {"items": [{"nmId": 197330807, "frequency": {"current": 4, "dynamics": 1}}]}}
    spec_found = FieldSpec(
        field="nm_id",
        paths=(("nmId",),),
        source_type="WB",
        missing_status="PARTIAL",
        next_step="keep live request",
        employee_question="",
    )
    spec_missing = FieldSpec(
        field="order_conversion",
        paths=(),
        source_type="WB",
        missing_status="CSV_ONLY",
        next_step="need export",
        employee_question="",
        found_status="NEEDS_FORMULA",
    )

    found = _field_result("Test block", "/x", "200", [payload], spec_found)
    missing = _field_result("Test block", "/x", "200", [payload], spec_missing)

    assert found.status == "FOUND"
    assert found.evidence_short.startswith("found path")
    assert missing.status == "CSV_ONLY"
    assert missing.evidence_short == "not found in tested response"
