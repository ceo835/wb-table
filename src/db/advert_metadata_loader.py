from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

import requests
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.db.models import FactAdvertMetadata
from src.db.session import session_scope, upsert_rows


WB_ADVERT_API_BASE = "https://advert-api.wildberries.ru"
WB_ADVERT_METADATA_ENDPOINT = f"{WB_ADVERT_API_BASE}/api/advert/v2/adverts"
FACT_ADVERT_METADATA_CONFLICT_COLUMNS = ("advert_id",)


class AdvertMetadataRequesterResult(dict):
    pass


AdvertMetadataRequester = Callable[[], tuple[str, Any, str]]


def _headers() -> dict[str, str]:
    if not settings.wb_token:
        raise RuntimeError("WB_TOKEN is missing")
    return {
        "Authorization": settings.wb_token,
        "Accept": "application/json",
    }


def _default_requester(timeout_seconds: int = 60) -> AdvertMetadataRequester:
    session = requests.Session()

    def _request() -> tuple[str, Any, str]:
        try:
            response = session.get(
                WB_ADVERT_METADATA_ENDPOINT,
                headers=_headers(),
                timeout=timeout_seconds,
            )
        except requests.RequestException as exc:
            return "REQUEST_ERROR", None, str(exc)
        if response.status_code != 200:
            return str(response.status_code), None, response.text[:1000]
        try:
            return str(response.status_code), response.json(), ""
        except ValueError:
            return str(response.status_code), None, "invalid_json_response"

    return _request


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _extract_nm_ids(payload: Mapping[str, Any]) -> list[int]:
    raw_nm_settings = _coalesce(payload.get("nmSettings"), payload.get("nm_settings"), {})
    if isinstance(raw_nm_settings, Mapping):
        raw_nm_ids = _coalesce(raw_nm_settings.get("nmIds"), raw_nm_settings.get("nm_ids"), [])
    else:
        raw_nm_ids = []
    nm_ids: list[int] = []
    if isinstance(raw_nm_ids, Sequence) and not isinstance(raw_nm_ids, (str, bytes)):
        for value in raw_nm_ids:
            try:
                nm_ids.append(int(value))
            except (TypeError, ValueError):
                continue
    return nm_ids


def _extract_placements(payload: Mapping[str, Any]) -> list[str] | dict[str, Any] | None:
    placements = _coalesce(payload.get("placements"), payload.get("placement"), payload.get("place"))
    if placements is None:
        return None
    if isinstance(placements, Mapping):
        return dict(placements)
    if isinstance(placements, Sequence) and not isinstance(placements, (str, bytes)):
        return [str(value) for value in placements]
    return [str(placements)]


def _list_adverts(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "adverts", "items", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested_items = value.get("items") or value.get("adverts")
                if isinstance(nested_items, list):
                    return [item for item in nested_items if isinstance(item, dict)]
    return []


def normalize_advert_metadata_rows(
    payload: Any,
    *,
    loaded_at: datetime | None = None,
    source_status: str = "REAL_API",
    advert_ids: Sequence[int] | None = None,
) -> list[dict[str, Any]]:
    loaded_at_value = loaded_at or datetime.now().astimezone()
    allowed_ids = {int(advert_id) for advert_id in advert_ids} if advert_ids else None
    normalized_rows: list[dict[str, Any]] = []
    for advert in _list_adverts(payload):
        advert_id_raw = _coalesce(advert.get("advertId"), advert.get("advert_id"), advert.get("id"))
        try:
            advert_id = int(advert_id_raw)
        except (TypeError, ValueError):
            continue
        if allowed_ids is not None and advert_id not in allowed_ids:
            continue
        linked_nm_ids = _extract_nm_ids(advert)
        normalized_rows.append(
            {
                "advert_id": advert_id,
                "campaign_name": _coalesce(advert.get("name"), advert.get("campaignName"), advert.get("campaign_name")),
                "status": None if advert.get("status") in (None, "") else str(advert.get("status")),
                "payment_type": _coalesce(advert.get("paymentType"), advert.get("payment_type")),
                "primary_nm_id": linked_nm_ids[0] if linked_nm_ids else None,
                "linked_nm_ids_json": linked_nm_ids or None,
                "placements_json": _extract_placements(advert),
                "raw_payload_json": dict(advert),
                "source_status": source_status,
                "loaded_at": loaded_at_value,
            }
        )
    return normalized_rows


def prepare_fact_advert_metadata_upsert_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduplicated: dict[int, dict[str, Any]] = {}
    for row in rows:
        advert_id_raw = row.get("advert_id")
        try:
            advert_id = int(advert_id_raw)
        except (TypeError, ValueError):
            continue
        mapped = {
            "advert_id": advert_id,
            "campaign_name": row.get("campaign_name") or None,
            "status": None if row.get("status") in (None, "") else str(row.get("status")),
            "payment_type": row.get("payment_type") or None,
            "primary_nm_id": row.get("primary_nm_id"),
            "linked_nm_ids_json": row.get("linked_nm_ids_json") or None,
            "placements_json": row.get("placements_json") or None,
            "raw_payload_json": row.get("raw_payload_json"),
            "source_status": row.get("source_status") or None,
            "loaded_at": row.get("loaded_at"),
        }
        deduplicated[advert_id] = mapped
    return list(deduplicated.values())


def upsert_fact_advert_metadata(session: Session, rows: Sequence[Mapping[str, Any]]) -> int:
    prepared_rows = prepare_fact_advert_metadata_upsert_rows(rows)
    return upsert_rows(
        session=session,
        model=FactAdvertMetadata,
        rows=prepared_rows,
        conflict_columns=FACT_ADVERT_METADATA_CONFLICT_COLUMNS,
    )


def load_advert_metadata_to_db(
    *,
    advert_ids: Sequence[int] | None = None,
    requester: AdvertMetadataRequester | None = None,
    loaded_at: datetime | None = None,
) -> dict[str, Any]:
    request = requester or _default_requester()
    status_code, payload, error = request()
    normalized_rows = normalize_advert_metadata_rows(
        payload,
        loaded_at=loaded_at,
        source_status="REAL_API" if status_code == "200" else "API_ERROR",
        advert_ids=advert_ids,
    )
    rows_upserted = 0
    if status_code == "200" and normalized_rows:
        with session_scope() as session:
            rows_upserted = upsert_fact_advert_metadata(session, normalized_rows)
    return {
        "status": status_code,
        "error": error,
        "rows_fetched": len(normalized_rows),
        "rows_upserted": rows_upserted,
        "advert_ids_requested": sorted({int(advert_id) for advert_id in advert_ids}) if advert_ids else [],
        "advert_ids_loaded": [row["advert_id"] for row in normalized_rows],
    }
