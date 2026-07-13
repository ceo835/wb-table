from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.clients.ozon_chats_client import OzonChatsClient
from src.config.settings import settings
from src.db.base import Base
from src.db.communications_models import CampaignRecipient, ChatRegistry, SendLog
from src.db.models import FactOzonPriceSnapshot
from src.services.communications.audience_service import AudienceService
from src.services.communications.campaign_service import CampaignService
from src.services.communications.providers import OzonChatProvider, serialize_ozon_registry_meta
from src.services.communications.ui import (
    OZON_CHAT_REGISTRY_DISPLAY_COLUMNS,
    OZON_MAIN_SECTIONS,
    OZON_TECHNICAL_EXPANDER_LABEL,
    _build_campaign_registry_empty_message,
    _build_ozon_chat_registry_dataframe,
    _build_ozon_registry_sync_message,
    _filter_ozon_chat_registry_dataframe,
    _prepare_diagnostics_dataframe,
)


class FakeOzonChatsClient:
    def __init__(self) -> None:
        self.last_known_good_result = {"status_code": 200}
        self.last_chat_list_result = None
        self.last_history_results = []
        self.known_good_calls = 0
        self.client_id = "cid"
        self.base_url = "https://api-seller.ozon.ru"

    def has_credentials(self) -> bool:
        return True

    def validate_known_good_access(self):
        self.known_good_calls += 1
        return {
            "operation": "known_good_readonly_check",
            "endpoint": "/v3/product/list",
            "status_code": 200,
            "elapsed_ms": 10,
            "payload_sent": {"filter": {"visibility": "ALL"}, "limit": 1, "last_id": ""},
            "payload": {"result": {"items": [{"offer_id": "x"}], "last_id": ""}},
            "response_top_level_type": "object",
            "response_top_level_keys": ["result"],
            "item_count": 1,
            "pagination": {"keys_found": ["result.last_id"], "values": {"result.last_id": ""}, "has_pagination_signals": True},
            "rate_limit_headers": {},
            "error": "",
            "is_success": True,
            "is_role_error": False,
            "is_not_found": False,
            "is_bad_request": False,
            "is_auth_error": False,
        }

    def _chat_rows(self):
        return [
            {
                "chat": {
                    "chat_id": "oz-1",
                    "chat_status": "Opened",
                    "created_at": "2026-07-01T10:00:00Z",
                    "chat_type": "BUYER_TO_SELLER",
                },
                "sku": 501,
                "offer_id": "offer-1",
                "vendor_code": "art-1",
                "updated_at": "2026-07-10T10:00:00Z",
                "senderType": "buyer",
                "can_reply": True,
                "posting_number": "P-1",
                "unread_count": 2,
                "last_message_id": "m-10",
                "first_unread_message_id": "m-09",
            },
            {
                "chat": {
                    "chat_id": "oz-2",
                    "chat_status": "Closed",
                    "created_at": "2026-07-02T10:00:00Z",
                    "chat_type": "ORDER",
                },
                "product_id": 777,
                "updated_at": "2026-07-11T10:00:00Z",
                "senderType": "seller",
                "unread_count": 0,
            },
        ]

    def list_chats(self):
        result = {
            "operation": "chat_list",
            "endpoint": "/v3/chat/list",
            "attempts": [
                {
                    "operation": "chat_list",
                    "endpoint": "/v3/chat/list",
                    "status_code": 200,
                    "elapsed_ms": 15,
                    "payload_sent": {"limit": 100},
                    "payload": {"chats": self._chat_rows(), "has_next": False},
                    "response_text_preview": '{"chats":[{"chat":{"chat_id":"oz-1"}}]}',
                    "response_top_level_type": "object",
                    "response_top_level_keys": ["chats", "has_next"],
                    "item_count": 2,
                    "pagination": {"keys_found": ["has_next"], "values": {"has_next": False}, "has_pagination_signals": True},
                    "rate_limit_headers": {},
                    "error": "",
                    "is_success": True,
                    "is_role_error": False,
                    "is_not_found": False,
                    "is_bad_request": False,
                    "is_auth_error": False,
                }
            ],
        }
        result["result"] = result["attempts"][0]
        self.last_chat_list_result = result
        return result

    def list_all_chats(self, *, max_pages=50, limit=100, sleep_seconds=0.1):
        result = self.list_chats()
        items = list(result["result"]["payload"]["chats"])
        summary = {
            **result,
            "items": items,
            "fetched_pages": 1,
            "fetched_chats_raw": len(items),
            "unique_chats": len(items),
            "stop_reason": "has_next_false",
            "repeated_cursor": False,
        }
        self.last_chat_list_result = summary
        return summary

    def get_chat_history(self, chat_id: str, context=None):
        payload = {
            "result": {
                "messages": [
                    {
                        "chat_id": chat_id,
                        "product_id": 501 if chat_id == "oz-1" else 777,
                        "created_at": "2026-07-01T09:00:00Z" if chat_id == "oz-1" else "2026-07-02T09:00:00Z",
                        "updated_at": "2026-07-10T11:00:00Z" if chat_id == "oz-1" else "2026-07-11T11:00:00Z",
                        "senderType": "seller" if chat_id == "oz-1" else "buyer",
                    }
                ]
            }
        }
        result = {
            "operation": "chat_history",
            "endpoint": "/v1/chat/history",
            "attempts": [
                {
                    "operation": "chat_history",
                    "endpoint": "/v1/chat/history",
                    "status_code": 200,
                    "elapsed_ms": 12,
                    "payload_sent": {"chat_id": chat_id},
                    "payload": payload,
                    "response_top_level_type": "object",
                    "response_top_level_keys": ["result"],
                    "item_count": 1,
                    "pagination": {"keys_found": [], "values": {}, "has_pagination_signals": False},
                    "rate_limit_headers": {},
                    "error": "",
                    "is_success": True,
                    "is_role_error": False,
                    "is_not_found": False,
                    "is_bad_request": False,
                    "is_auth_error": False,
                }
            ],
        }
        result["result"] = result["attempts"][0]
        self.last_history_results.append(result)
        return result


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_list_all_chats_paginates_and_deduplicates(monkeypatch) -> None:
    client = OzonChatsClient(client_id="cid", api_key="key")

    first_result = {
        "status_code": 200,
        "payload": {
            "chats": [
                {"chat": {"chat_id": "oz-1"}},
                {"chat": {"chat_id": "oz-2"}},
            ],
            "cursor": "cursor-1",
            "has_next": True,
        },
        "payload_sent": {"limit": 100},
        "response_text_preview": "{}",
    }
    next_result = {
        "status_code": 200,
        "payload": {
            "chats": [
                {"chat": {"chat_id": "oz-2"}},
                {"chat": {"chat_id": "oz-3"}},
            ],
            "has_next": False,
        },
        "payload_sent": {"limit": 100, "cursor": "cursor-1"},
        "response_text_preview": "{}",
    }

    monkeypatch.setattr(
        client,
        "_run_payload_variants",
        lambda **kwargs: {"operation": "chat_list", "endpoint": "/v3/chat/list", "attempts": [first_result], "result": first_result},
    )
    page_results = [next_result]
    monkeypatch.setattr(client, "_post_json", lambda **kwargs: page_results.pop(0))

    summary = client.list_all_chats(max_pages=5, sleep_seconds=0)

    assert summary["fetched_pages"] == 2
    assert summary["fetched_chats_raw"] == 4
    assert summary["unique_chats"] == 3
    assert [item["chat"]["chat_id"] for item in summary["items"]] == ["oz-1", "oz-2", "oz-3"]
    assert summary["stop_reason"] == "has_next_false"


def test_chat_history_payloads_include_context_variants() -> None:
    client = OzonChatsClient(client_id="cid", api_key="key")

    payloads = client._chat_history_payloads(
        "oz-1",
        context={"last_message_id": "m-10", "first_unread_message_id": "m-09"},
    )

    assert {"chat_id": "oz-1"} in payloads
    assert {"chat_id": "oz-1", "limit": 50} in payloads
    assert {"chat": {"chat_id": "oz-1"}} in payloads
    assert {"chat_id": "oz-1", "limit": 50, "last_message_id": "m-10"} in payloads
    assert {"chat_id": "oz-1", "limit": 50, "from_message_id": "m-09"} in payloads


def test_build_ozon_chat_registry_from_provider(db_session, monkeypatch):
    fake_client = FakeOzonChatsClient()
    monkeypatch.setattr("src.services.communications.providers.OzonChatsClient", lambda **kwargs: fake_client)

    provider = OzonChatProvider(client_id="cid", api_key="key")
    count = provider.build_chat_registry(db_session, max_event_pages=5)
    db_session.commit()

    assert count == 2
    rows = list(db_session.scalars(select(ChatRegistry).where(ChatRegistry.marketplace == "ozon").order_by(ChatRegistry.chat_id)).all())
    assert [row.chat_id for row in rows] == ["oz-1", "oz-2"]
    assert rows[0].product_ids == [501]
    assert rows[0].current_chat_exists is True
    assert rows[0].source == "v3_chat_list+v1_chat_history"
    assert rows[1].product_ids == [777]
    assert provider.last_sync_diagnostics["known_good_status_code"] is None
    assert fake_client.known_good_calls == 0
    assert provider.last_sync_diagnostics["chat_list_status_code"] == 200
    assert provider.last_sync_diagnostics["fetched_chats_count"] == 2
    assert provider.last_sync_diagnostics["prepared_records_count"] == 2
    assert provider.last_sync_diagnostics["committed"] is False
    assert provider.last_sync_diagnostics["chat_registry_count_ozon"] == 2
    assert provider.last_sync_diagnostics["chats_with_order_linkage"] == 1
    assert provider.last_sync_diagnostics["reply_capable_chat_count"] == 1
    assert provider.last_sync_diagnostics["history_status"] == 200
    assert provider.last_sync_diagnostics["history_confirmed"] is True
    assert provider.last_sync_diagnostics["skipped_history"] is False
    assert provider.last_sync_diagnostics["used_chat_list_probe"] == "POST /v3/chat/list"
    assert provider.last_sync_diagnostics["used_chat_events_probe"] == "POST /v1/chat/history"


def test_ozon_campaign_send_stays_simulation_when_flag_disabled(db_session, monkeypatch):
    monkeypatch.setattr(settings, "wb_comm_real_send_enabled", True, raising=False)
    monkeypatch.setattr(settings, "wb_token", "wb-token", raising=False)
    monkeypatch.setattr(settings, "ozon_comm_real_send_enabled", False, raising=False)
    monkeypatch.setattr(settings, "ozon_client_id", "cid", raising=False)
    monkeypatch.setattr(settings, "ozon_api_key", "key", raising=False)

    monkeypatch.setattr(
        "src.services.communications.providers.OzonChatProvider.send_message",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("real send should not be called")),
    )

    campaign = CampaignService.create_campaign(
        session=db_session,
        marketplace="ozon",
        campaign_type="custom",
        name="Ozon test",
        message_text="hello",
    )
    db_session.commit()

    recipient = CampaignRecipient(
        campaign_id=campaign.id,
        marketplace="ozon",
        chat_id="oz-1",
        recipient_status="ready",
        selected=True,
    )
    db_session.add(recipient)
    db_session.commit()

    result = CampaignService.send_campaign_messages(
        session=db_session,
        campaign_id=campaign.id,
        recipient_ids=[recipient.id],
        dry_run=False,
        batch_limit=10,
    )
    db_session.commit()

    assert result["is_simulation"] is True
    assert result["processed_count"] == 1
    assert result["sent_count"] == 1
    assert recipient.recipient_status == "sent"


def test_build_ozon_chat_registry_keeps_sync_when_history_is_404(db_session, monkeypatch):
    class FakeOzon404HistoryClient(FakeOzonChatsClient):
        def get_chat_history(self, chat_id: str, context=None):
            result = {
                "operation": "chat_history",
                "endpoint": "/v1/chat/history",
                "attempts": [
                    {
                        "operation": "chat_history",
                        "endpoint": "/v1/chat/history",
                        "status_code": 404,
                        "elapsed_ms": 12,
                        "payload_sent": {"chat_id": chat_id},
                        "payload": {"message": "404 page not found"},
                        "response_top_level_type": "object",
                        "response_top_level_keys": ["message"],
                        "item_count": 0,
                        "pagination": {"keys_found": [], "values": {}, "has_pagination_signals": False},
                        "rate_limit_headers": {},
                        "error": "404 page not found",
                        "is_success": False,
                        "is_role_error": False,
                        "is_not_found": True,
                        "is_bad_request": False,
                        "is_auth_error": False,
                    }
                ],
            }
            result["result"] = result["attempts"][0]
            self.last_history_results.append(result)
            return result

    fake_client = FakeOzon404HistoryClient()
    monkeypatch.setattr("src.services.communications.providers.OzonChatsClient", lambda **kwargs: fake_client)

    provider = OzonChatProvider(client_id="cid", api_key="key")
    count = provider.build_chat_registry(db_session, max_event_pages=5)
    db_session.commit()

    rows = list(db_session.scalars(select(ChatRegistry).where(ChatRegistry.marketplace == "ozon")).all())
    assert count == 2
    assert len(rows) == 2
    assert provider.last_sync_diagnostics["history_status"] == 404
    assert provider.last_sync_diagnostics["history_confirmed"] is False
    assert provider.last_sync_diagnostics["skipped_history"] is True
    assert provider.last_sync_diagnostics["prepared_records_count"] == 2


def test_prepare_diagnostics_dataframe_casts_value_column_to_string() -> None:
    diagnostics_df = _prepare_diagnostics_dataframe(
        [
            {"metric": "records", "value": 0},
            {"metric": "send", "value": "отключена"},
        ]
    )

    assert diagnostics_df["value"].tolist() == ["0", "отключена"]
    assert diagnostics_df.attrs == {}


def test_probe_chat_list_only_exposes_compact_probe_summary(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ozon_client_id", "client-123456", raising=False)
    monkeypatch.setattr(settings, "ozon_api_key", "api-key-abcdef", raising=False)
    monkeypatch.setenv("OZON_CLIENT_ID", "client-123456")
    monkeypatch.setenv("OZON_API_KEY", "api-key-abcdef")

    client = OzonChatsClient(client_id="client-123456", api_key="api-key-abcdef")
    monkeypatch.setattr(
        client,
        "list_all_chats",
        lambda: {
            "operation": "chat_list_paginated",
            "endpoint": "/v3/chat/list",
            "attempts": [],
            "result": {"status_code": 404, "payload": {"chats": []}},
            "items": [],
            "fetched_pages": 0,
            "unique_chats": 0,
            "stop_reason": "initial_request_failed",
        },
    )

    result = client.probe_chat_list_only()

    runtime = result["runtime"]
    assert runtime["credentials_present"] is True
    assert runtime["masked_client_id"].startswith("clie")
    assert runtime["base_url"] == "https://api-seller.ozon.ru"
    assert runtime["chat_list_endpoint"] == "/v3/chat/list"
    assert runtime["env_ozon_client_id_present"] is True
    assert runtime["env_ozon_api_key_present"] is True
    assert runtime["settings_client_id_matches_env"] is True
    assert runtime["settings_api_key_matches_env"] is True
    assert result["probe_summary"]["method"] == "POST"
    assert result["probe_summary"]["endpoint"] == "/v3/chat/list"
    assert result["probe_summary"]["status_code"] == 404
    assert result["probe_summary"]["fetched_pages"] == 0
    assert result["probe_summary"]["unique_chats"] == 0


def test_build_ozon_registry_sync_message_uses_short_user_facing_text() -> None:
    level, message = _build_ozon_registry_sync_message({"chat_list_status_code": 200, "fetched_chats_count": 100})
    assert level == "success"
    assert message == "Синхронизация выполнена. Получено чатов: 100."

    level, message = _build_ozon_registry_sync_message({"chat_list_status_code": 404})
    assert level == "error"
    assert message == "Не удалось получить Ozon-чаты. API вернул status 404."


def test_chat_list_payloads_use_confirmed_limit_request() -> None:
    client = OzonChatsClient(client_id="cid", api_key="key")

    assert client._chat_list_payloads() == (
        {"limit": 100},
        {"limit": 100, "offset": 0},
    )


def test_build_ozon_chat_registry_dataframe_has_russian_columns_and_summary(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.services.communications.ui.load_tracked_articles_with_categories",
        lambda: [{"offer_id": "offer-1", "sku": 501, "category": "Футболки"}],
    )
    db_session.add(
        FactOzonPriceSnapshot(
            snapshot_at=datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
            snapshot_date=date(2026, 7, 10),
            offer_id="offer-1",
            product_id=1001,
            sku=501,
            name="Футболка Ozon",
            seller_status="ACTIVE",
        )
    )
    db_session.flush()

    chats = [
        ChatRegistry(
            marketplace="ozon",
            chat_id="oz-1",
            reply_sign=serialize_ozon_registry_meta(
                {
                    "chat_status": "OPENED",
                    "chat_type": "BUYER_TO_SELLER",
                    "can_reply": True,
                    "unread_count": 2,
                    "offer_id": "offer-1",
                    "sku": 501,
                    "vendor_code": "art-1",
                }
            ),
            current_chat_exists=True,
            product_ids=[501],
            first_activity_at=datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
            last_activity_at=datetime(2026, 7, 10, 10, 0, tzinfo=UTC),
            last_sender="buyer",
            source="v3_chat_list",
        ),
        ChatRegistry(
            marketplace="ozon",
            chat_id="oz-2",
            reply_sign=serialize_ozon_registry_meta(
                {
                    "chat_status": "CLOSED",
                    "chat_type": "ORDER",
                    "can_reply": False,
                    "unread_count": 0,
                    "product_id": 777,
                    "product_name": "Трусы",
                }
            ),
            current_chat_exists=True,
            product_ids=[777],
            first_activity_at=datetime(2026, 7, 2, 10, 0, tzinfo=UTC),
            last_activity_at=datetime(2026, 7, 11, 10, 0, tzinfo=UTC),
            last_sender="seller",
            source="v3_chat_list",
        ),
    ]

    df, summary = _build_ozon_chat_registry_dataframe(db_session, chats, now=datetime(2026, 7, 12, tzinfo=UTC))

    chat_id_col = OZON_CHAT_REGISTRY_DISPLAY_COLUMNS[0]
    status_col = OZON_CHAT_REGISTRY_DISPLAY_COLUMNS[1]
    can_reply_col = OZON_CHAT_REGISTRY_DISPLAY_COLUMNS[3]
    product_name_col = OZON_CHAT_REGISTRY_DISPLAY_COLUMNS[5]

    assert chat_id_col in df.columns
    assert status_col in df.columns
    assert can_reply_col in df.columns
    assert df.iloc[0][product_name_col] == "Футболка Ozon"
    assert df.iloc[0][can_reply_col] == "Технически да, отправка отключена"
    assert df.iloc[1][status_col] == "Закрыт"
    assert summary["total_chats"] == 2
    assert summary["opened_chats"] == 1
    assert summary["closed_chats"] == 1
    assert summary["unique_product_keys"] == 2


def test_filter_ozon_chat_registry_dataframe_filters_status_search_and_unread() -> None:
    chat_id_col = OZON_CHAT_REGISTRY_DISPLAY_COLUMNS[0]
    status_col = OZON_CHAT_REGISTRY_DISPLAY_COLUMNS[1]
    can_reply_col = OZON_CHAT_REGISTRY_DISPLAY_COLUMNS[3]
    df = pd.DataFrame(
        [
            {
                chat_id_col: "oz-1",
                status_col: "Открыт",
                can_reply_col: "Технически да, отправка отключена",
                "__status_key": "opened",
                "__can_reply": True,
                "__last_activity_date": date(2026, 7, 10),
                "__has_unread": True,
                "__search_text": "oz-1 offer-1 art-1",
            },
            {
                chat_id_col: "oz-2",
                status_col: "Закрыт",
                can_reply_col: "Нет",
                "__status_key": "closed",
                "__can_reply": False,
                "__last_activity_date": date(2026, 7, 11),
                "__has_unread": False,
                "__search_text": "oz-2 777",
            },
        ]
    )

    filtered = _filter_ozon_chat_registry_dataframe(
        df,
        status_filter="Открытые",
        can_reply_filter="Да",
        activity_date_from=date(2026, 7, 9),
        activity_date_to=date(2026, 7, 10),
        search_query="offer-1",
        unread_filter="Только с непрочитанными",
    )

    assert filtered[chat_id_col].tolist() == ["oz-1"]


def test_ozon_main_sections_hide_diagnostics_from_primary_options() -> None:
    assert OZON_MAIN_SECTIONS == [
        "Кампания Ozon",
        "Реестр Ozon-чатов",
        "История отправок Ozon",
    ]
    assert all("Диагностика" not in section for section in OZON_MAIN_SECTIONS)
    assert OZON_TECHNICAL_EXPANDER_LABEL == "Техническая диагностика Ozon"
    assert "Реестр Ozon-чатов пуст" in _build_campaign_registry_empty_message("ozon")


def test_ozon_campaign_audience_uses_only_ozon_registry_and_reply_metadata(db_session, monkeypatch):
    class StubOzonProvider:
        def build_chat_registry(self, session, max_event_pages=10):
            return 0

    monkeypatch.setattr("src.services.communications.audience_service.OzonChatProvider", lambda: StubOzonProvider())

    db_session.add_all([
        ChatRegistry(
            marketplace="ozon",
            chat_id="oz-1",
            reply_sign=serialize_ozon_registry_meta({"chat_status": "OPENED", "can_reply": True, "offer_id": "offer-1"}),
            current_chat_exists=True,
            product_ids=[501],
            last_activity_at=datetime.now(UTC),
        ),
        ChatRegistry(
            marketplace="ozon",
            chat_id="oz-2",
            reply_sign=serialize_ozon_registry_meta({"chat_status": "CLOSED", "can_reply": False, "offer_id": "offer-2"}),
            current_chat_exists=True,
            product_ids=[502],
            last_activity_at=datetime.now(UTC),
        ),
        ChatRegistry(
            marketplace="wb",
            chat_id="wb-1",
            reply_sign="sign-1",
            current_chat_exists=True,
            product_ids=[501],
            last_activity_at=datetime.now(UTC),
        ),
        SendLog(
            marketplace="wb",
            chat_id="oz-1",
            message_text="other marketplace",
            send_status="sent",
            sent_at=datetime.now(UTC) - timedelta(days=1),
        ),
    ])
    db_session.commit()

    campaign = CampaignService.create_campaign(
        session=db_session,
        marketplace="ozon",
        campaign_type="custom",
        name="Ozon audience",
        message_text="hello",
        filters={
            "activity_days": 30,
            "nm_ids": [501, 502],
            "only_with_reply_sign": True,
            "only_with_product_linkage": True,
            "exclude_global_lookback_days": 7,
            "recipient_limit": 10,
            "search_query": "offer-1",
        },
    )
    db_session.commit()

    stats = AudienceService.collect_and_filter_audience(db_session, campaign.id)
    db_session.commit()

    recipients = CampaignService.get_campaign_recipients(db_session, campaign.id)
    assert [recipient.chat_id for recipient in recipients] == ["oz-1", "oz-2"]
    ready_chat_ids = [recipient.chat_id for recipient in recipients if recipient.recipient_status == "ready"]
    assert ready_chat_ids == ["oz-1"]
    assert stats["ready"] == 1


def test_wb_campaign_audience_ignores_ozon_registry_and_ozon_send_logs(db_session, monkeypatch):
    class StubWBProvider:
        def build_chat_registry(self, session, max_event_pages=10):
            return 0

    monkeypatch.setattr("src.services.communications.audience_service.WBChatProvider", lambda: StubWBProvider())

    db_session.add_all([
        ChatRegistry(
            marketplace="wb",
            chat_id="wb-1",
            reply_sign="sign-1",
            current_chat_exists=True,
            product_ids=[100],
            last_activity_at=datetime.now(UTC),
        ),
        ChatRegistry(
            marketplace="ozon",
            chat_id="oz-1",
            current_chat_exists=True,
            product_ids=[100],
            last_activity_at=datetime.now(UTC),
        ),
        SendLog(
            marketplace="ozon",
            chat_id="wb-1",
            message_text="other marketplace",
            send_status="sent",
            sent_at=datetime.now(UTC) - timedelta(days=1),
        ),
    ])
    db_session.commit()

    campaign = CampaignService.create_campaign(
        session=db_session,
        marketplace="wb",
        campaign_type="custom",
        name="WB audience",
        message_text="hello",
        filters={
            "activity_days": 30,
            "nm_ids": [100],
            "only_with_reply_sign": True,
            "only_current_chats": True,
            "exclude_global_lookback_days": 7,
            "recipient_limit": 10,
        },
    )
    db_session.commit()

    stats = AudienceService.collect_and_filter_audience(db_session, campaign.id)
    db_session.commit()

    recipients = CampaignService.get_campaign_recipients(db_session, campaign.id)
    assert [recipient.chat_id for recipient in recipients] == ["wb-1"]
    assert recipients[0].marketplace == "wb"
    assert recipients[0].recipient_status == "ready"
    assert stats["ready"] == 1
