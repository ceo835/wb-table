from __future__ import annotations

import pytest
from datetime import datetime, UTC, timedelta
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.clients.ozon_chats_client import OzonChatsClient
from src.config.settings import settings
from src.db.base import Base
from src.db.communications_models import CampaignRecipient, ChatRegistry, SendLog
from src.services.communications.audience_service import AudienceService
from src.services.communications.campaign_service import CampaignService
from src.services.communications.providers import OzonChatProvider
from src.services.communications.ui import (
    OZON_MAIN_SECTIONS,
    OZON_TECHNICAL_EXPANDER_LABEL,
    _build_campaign_registry_empty_message,
    _prepare_diagnostics_dataframe,
)


class FakeOzonChatsClient:
    def __init__(self) -> None:
        self.last_known_good_result = {"status_code": 200}
        self.last_chat_list_result = None
        self.last_history_results = []

    def validate_known_good_access(self):
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
                    "payload": {
                        "chats": [
                            {
                                "chat": {
                                    "chat_id": "oz-1",
                                    "chat_status": "Opened",
                                    "created_at": "2026-07-01T10:00:00Z",
                                },
                                "sku": 501,
                                "updated_at": "2026-07-10T10:00:00Z",
                                "senderType": "buyer",
                                "can_reply": True,
                                "posting_number": "P-1",
                            },
                            {
                                "chat": {
                                    "chat_id": "oz-2",
                                    "chat_status": "Closed",
                                    "created_at": "2026-07-02T10:00:00Z",
                                },
                                "product_id": 777,
                                "updated_at": "2026-07-11T10:00:00Z",
                                "senderType": "seller",
                            },
                        ]
                    },
                    "response_top_level_type": "object",
                    "response_top_level_keys": ["chats"],
                    "item_count": 2,
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
        self.last_chat_list_result = result
        return result

    def get_chat_history(self, chat_id: str):
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
    assert rows[0].source == "v3_chat_list"
    assert rows[1].product_ids == [777]
    assert provider.last_sync_diagnostics["known_good_status_code"] == 200
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
        def get_chat_history(self, chat_id: str):
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


def test_probe_readonly_access_exposes_runtime_diagnostics(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ozon_client_id", "client-123456", raising=False)
    monkeypatch.setattr(settings, "ozon_api_key", "api-key-abcdef", raising=False)
    monkeypatch.setenv("OZON_CLIENT_ID", "client-123456")
    monkeypatch.setenv("OZON_API_KEY", "api-key-abcdef")

    client = OzonChatsClient(client_id="client-123456", api_key="api-key-abcdef")
    monkeypatch.setattr(client, "validate_known_good_access", lambda: {"status_code": 404, "payload_sent": {"limit": 1}})
    monkeypatch.setattr(
        client,
        "list_chats",
        lambda: {
            "operation": "chat_list",
            "endpoint": "/v3/chat/list",
            "attempts": [],
            "result": {"status_code": 404, "payload": {"chats": []}},
        },
    )

    result = client.probe_readonly_access()

    runtime = result["runtime"]
    assert runtime["credentials_present"] is True
    assert runtime["masked_client_id"].startswith("clie")
    assert runtime["base_url"] == "https://api-seller.ozon.ru"
    assert runtime["chat_list_endpoint"] == "/v3/chat/list"
    assert runtime["env_ozon_client_id_present"] is True
    assert runtime["env_ozon_api_key_present"] is True
    assert runtime["settings_client_id_matches_env"] is True
    assert runtime["settings_api_key_matches_env"] is True



def test_chat_list_payloads_use_confirmed_limit_request() -> None:
    client = OzonChatsClient(client_id="cid", api_key="key")

    assert client._chat_list_payloads() == (
        {"limit": 100},
        {"limit": 100, "offset": 0},
    )


def test_ozon_main_sections_hide_diagnostics_from_primary_options() -> None:
    assert OZON_MAIN_SECTIONS == [
        "Кампания Ozon",
        "Реестр Ozon-чатов",
        "История отправок Ozon",
    ]
    assert all("Диагностика" not in section for section in OZON_MAIN_SECTIONS)
    assert OZON_TECHNICAL_EXPANDER_LABEL == "Техническая диагностика Ozon"
    assert "Реестр Ozon-чатов пуст" in _build_campaign_registry_empty_message("ozon")


def test_ozon_campaign_audience_uses_only_ozon_registry_and_marketplace_scoped_send_logs(db_session, monkeypatch):
    class StubOzonProvider:
        def build_chat_registry(self, session, max_event_pages=10):
            return 0

    monkeypatch.setattr("src.services.communications.audience_service.OzonChatProvider", lambda: StubOzonProvider())

    db_session.add_all([
        ChatRegistry(
            marketplace="ozon",
            chat_id="oz-1",
            current_chat_exists=True,
            product_ids=[501],
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
            "nm_ids": [501],
            "only_with_product_linkage": True,
            "exclude_global_lookback_days": 7,
            "recipient_limit": 10,
            "search_query": "oz-1",
        },
    )
    db_session.commit()

    stats = AudienceService.collect_and_filter_audience(db_session, campaign.id)
    db_session.commit()

    recipients = CampaignService.get_campaign_recipients(db_session, campaign.id)
    assert [recipient.chat_id for recipient in recipients] == ["oz-1"]
    assert recipients[0].marketplace == "ozon"
    assert recipients[0].recipient_status == "ready"
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
