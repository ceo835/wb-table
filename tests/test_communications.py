from __future__ import annotations

import pytest
from datetime import date, datetime, UTC, timedelta
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy import BigInteger
from sqlalchemy.dialects.postgresql import JSONB

from src.db.base import Base
from src.db.communications_models import Campaign, ChatRegistry, CampaignRecipient, SendLog
from src.db.models import DimProduct
from src.services.communications.campaign_service import CampaignService
from src.services.communications.audience_service import AudienceService
from src.services.communications.providers import WBChatProvider
from src.services.communications.ui import (
    WB_CHAT_REGISTRY_DETAILS_COLUMNS,
    WB_CHAT_REGISTRY_DISPLAY_COLUMNS,
    WB_CHAT_REGISTRY_EXPORT_COLUMNS,
    _build_wb_chat_registry_dataframe,
    _filter_wb_chat_registry_dataframe,
)


# Mock response helpers
class FakeResponse:
    def __init__(self, json_data: dict, status_code: int = 200) -> None:
        self._json_data = json_data
        self.status_code = status_code
        self.text = "error"
        self.headers = {}

    def json(self) -> dict:
        return self._json_data


class FakeWBChatsClient:
    def __init__(self, chats_payload=None, events_payload=None):
        self.chats_payload = chats_payload or {"result": []}
        self.events_payload = events_payload or {"result": {"events": [], "next": 0}}
        self.sent_messages = []

    def fetch_current_chats(self):
        return self.chats_payload

    def fetch_events(self, next_cursor=None):
        return self.events_payload

    def send_message(self, chat_id, text, reply_sign):
        self.sent_messages.append({"id": chat_id, "text": text, "replySign": reply_sign})
        return {"success": True, "result": {"messageId": "msg-123"}}


@pytest.fixture
def db_session():
    # Setup in-memory SQLite database
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    
    Session = sessionmaker(bind=engine, future=True)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_create_and_duplicate_campaign(db_session):
    # 1. Test creation
    filters = {"activity_days": 30, "nm_ids": [12345]}
    camp = CampaignService.create_campaign(
        session=db_session,
        marketplace="wb",
        campaign_type="price_increase",
        name="Test Campaign",
        message_text="Hello price increase!",
        promocode="PROMO123",
        event_date=date(2026, 7, 20),
        filters=filters,
        created_by="Test User",
        comment="Test Comment"
    )
    db_session.commit()

    assert camp.id is not None
    assert camp.status == "draft"
    assert camp.marketplace == "wb"
    assert camp.filters_json == filters

    # 2. Test listing
    camps = CampaignService.list_campaigns(db_session)
    assert len(camps) == 1
    assert camps[0].name == "Test Campaign"

    # 3. Test duplication
    dup = CampaignService.duplicate_campaign(db_session, camp.id)
    db_session.commit()
    
    assert dup.id is not None
    assert dup.id != camp.id
    assert dup.name == "Test Campaign (Копия)"
    assert dup.marketplace == "wb"
    assert dup.message_text == "Hello price increase!"
    assert dup.filters_json == filters


def test_build_chat_registry_from_provider(db_session, monkeypatch):
    # Prepare mock API responses
    chats_payload = {
        "result": [
            {
                "chatID": "chat-active-1",
                "replySign": "sign-active-1",
                "goodCard": {"nmID": 100},
                "lastMessage": {"addTimestamp": int(datetime(2026, 7, 10, tzinfo=UTC).timestamp() * 1000)}
            }
        ]
    }
    events_payload = {
        "result": {
            "events": [
                {
                    "chatID": "chat-hist-1",
                    "eventID": 10001,
                    "eventType": "message",
                    "sender": "client",
                    "addTimestamp": int(datetime(2026, 7, 5, tzinfo=UTC).timestamp() * 1000),
                    "message": {
                        "attachments": {
                            "goodCard": {"nmID": 200}
                        }
                    }
                }
            ],
            "next": 0
        }
    }

    fake_client = FakeWBChatsClient(chats_payload, events_payload)
    
    # Mock WBChatProvider client initialization
    monkeypatch.setattr("src.services.communications.providers.WBChatsClient", lambda **k: fake_client)
    
    provider = WBChatProvider(token="test")
    count = provider.build_chat_registry(db_session, max_event_pages=1)
    db_session.commit()

    assert count == 2  # Total 2 unique chats loaded to registry

    # Query registry to verify
    stmt = select(ChatRegistry).order_by(ChatRegistry.chat_id)
    chats = list(db_session.scalars(stmt).all())
    
    assert chats[0].chat_id == "chat-active-1"
    assert chats[0].reply_sign == "sign-active-1"
    assert chats[0].current_chat_exists is True
    assert chats[0].product_ids == [100]

    assert chats[1].chat_id == "chat-hist-1"
    assert chats[1].reply_sign is None
    assert chats[1].current_chat_exists is False
    assert chats[1].product_ids == [200]


def test_audience_filtering_and_limits(db_session):
    # Seed ChatRegistry
    c1 = ChatRegistry(
        marketplace="wb",
        chat_id="chat-1",
        reply_sign="sign-1",
        current_chat_exists=True,
        product_ids=[123, 456],
        last_activity_at=datetime(2026, 7, 5, tzinfo=UTC),
        updated_at=datetime.now()
    )
    c2 = ChatRegistry(  # Excluded: older activity
        marketplace="wb",
        chat_id="chat-2",
        reply_sign="sign-2",
        current_chat_exists=True,
        product_ids=[123],
        last_activity_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime.now()
    )
    c3 = ChatRegistry(  # Excluded: wrong product
        marketplace="wb",
        chat_id="chat-3",
        reply_sign="sign-3",
        current_chat_exists=True,
        product_ids=[789],
        last_activity_at=datetime(2026, 7, 9, tzinfo=UTC),
        updated_at=datetime.now()
    )
    db_session.add_all([c1, c2, c3])
    db_session.commit()

    # Create Campaign with filters: activity_days=10, nm_ids=[123], limit=10
    filters = {
        "activity_days": 10,
        "nm_ids": [123],
        "only_with_reply_sign": True,
        "only_current_chats": True,
        "recipient_limit": 10
    }
    camp = CampaignService.create_campaign(
        session=db_session,
        marketplace="wb",
        campaign_type="custom",
        name="Filter Test",
        message_text="Hello!",
        filters=filters
    )
    db_session.commit()

    # We patch WBChatProvider's build_chat_registry in AudienceService to avoid API call
    from unittest.mock import patch
    with patch("src.services.communications.audience_service.WBChatProvider") as provider_cls:
        provider_cls.return_value.build_chat_registry.return_value = 0
        stats = AudienceService.collect_and_filter_audience(db_session, camp.id)
        db_session.commit()

    # Verify recipients
    recipients = CampaignService.get_campaign_recipients(db_session, camp.id)
    assert len(recipients) == 3

    # check status mapping
    r_map = {r.chat_id: r for r in recipients}
    assert r_map["chat-1"].recipient_status == "ready"
    assert r_map["chat-1"].selected is True

    assert r_map["chat-2"].recipient_status == "excluded"
    assert r_map["chat-2"].selected is False
    assert "нет активности в выбранном периоде" in r_map["chat-2"].reason

    assert r_map["chat-3"].recipient_status == "excluded"
    assert r_map["chat-3"].selected is False
    assert "нет связи с выбранным товаром" in r_map["chat-3"].reason


def test_send_campaign_simulation(db_session, monkeypatch):
    # Setup campaign & recipients
    camp = CampaignService.create_campaign(
        session=db_session,
        marketplace="wb",
        campaign_type="custom",
        name="Send Test",
        message_text="Final text"
    )
    db_session.commit()

    r1 = CampaignRecipient(
        campaign_id=camp.id,
        marketplace="wb",
        chat_id="chat-1",
        recipient_status="ready",
        selected=True
    )
    r2 = CampaignRecipient(
        campaign_id=camp.id,
        marketplace="wb",
        chat_id="chat-2",
        recipient_status="ready",
        selected=True
    )
    db_session.add_all([r1, r2])
    db_session.commit()

    # Test simulation (dry_run=True)
    res = CampaignService.send_campaign_messages(
        session=db_session,
        campaign_id=camp.id,
        recipient_ids=[r1.id, r2.id],
        dry_run=True,
        batch_limit=10
    )
    db_session.commit()

    assert res["processed_count"] == 2
    assert res["sent_count"] == 2
    assert res["error_count"] == 0
    assert res["is_simulation"] is True

    # Check database changes
    assert r1.recipient_status == "sent"
    assert r2.recipient_status == "sent"

    # Check send logs
    logs = CampaignService.get_campaign_send_logs(db_session, camp.id)
    assert len(logs) == 2
    assert logs[0].send_status == "sent"
    assert logs[0].message_text == "Final text"


def test_build_wb_chat_registry_dataframe_localizes_columns_and_joins_product_data(db_session):
    db_session.add(
        DimProduct(
            nm_id=100,
            supplier_article="SUP-100",
            title="Трусы женские",
            brand="VVBromo",
            subject="Белье",
            category="Женская одежда",
        )
    )
    db_session.commit()

    chats = [
        ChatRegistry(
            marketplace="wb",
            chat_id="chat-current",
            source="chats",
            reply_sign="reply-1",
            product_ids=[100],
            first_activity_at=datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
            last_activity_at=datetime(2026, 7, 12, 9, 0, tzinfo=UTC),
            updated_at=datetime.now(UTC),
        ),
        ChatRegistry(
            marketplace="wb",
            chat_id="chat-current-no-reply",
            source="chats",
            reply_sign="",
            product_ids=[101],
            first_activity_at=datetime(2026, 7, 2, 10, 0, tzinfo=UTC),
            last_activity_at=datetime(2026, 7, 11, 9, 0, tzinfo=UTC),
            updated_at=datetime.now(UTC),
        ),
        ChatRegistry(
            marketplace="wb",
            chat_id="chat-history",
            source="events",
            reply_sign=None,
            last_sender="client",
            product_ids=[999],
            first_activity_at=datetime(2026, 6, 30, 8, 0, tzinfo=UTC),
            last_activity_at=datetime(2026, 7, 3, 8, 0, tzinfo=UTC),
            updated_at=datetime.now(UTC),
        ),
    ]
    db_session.add_all(chats)
    db_session.commit()

    table_df, summary = _build_wb_chat_registry_dataframe(
        db_session,
        chats,
        now=datetime(2026, 7, 13, 12, 0, tzinfo=UTC),
    )
    rows = {row["ID чата"]: row for row in table_df.to_dict("records")}

    assert WB_CHAT_REGISTRY_DISPLAY_COLUMNS == [
        "ID чата",
        "Статус чата",
        "Артикул WB",
        "Название товара",
        "Первая активность",
        "Последняя активность",
        "Дней с последней активности",
        "Источник",
        "Можно ответить",
    ]
    assert "Технический ключ ответа" in WB_CHAT_REGISTRY_EXPORT_COLUMNS
    assert "Бренд" in WB_CHAT_REGISTRY_DETAILS_COLUMNS
    assert summary["total_chats"] == 3
    assert summary["current_source_chats"] == 2
    assert summary["history_source_chats"] == 1
    assert summary["unique_wb_articles"] == 3

    assert rows["chat-current"]["Источник"] == "Текущий чат"
    assert rows["chat-current"]["Можно ответить"] == "Да"
    assert rows["chat-current"]["Статус чата"] == "Текущий, доступен для ответа"
    assert rows["chat-current"]["Название товара"] == "Трусы женские"
    assert rows["chat-current"]["Артикул продавца"] == "SUP-100"
    assert rows["chat-current"]["Бренд"] == "VVBromo"
    assert rows["chat-current"]["Категория"] == "Женская одежда"
    assert rows["chat-current"]["Предмет"] == "Белье"
    assert rows["chat-current"]["Дней с последней активности"] == "1 день"

    assert rows["chat-current-no-reply"]["Можно ответить"] == "Нет"
    assert rows["chat-current-no-reply"]["Статус чата"] == "Исторический / только для анализа"

    assert rows["chat-history"]["Источник"] == "История событий"
    assert rows["chat-history"]["Можно ответить"] == "Нет"
    assert rows["chat-history"]["Название товара"] == "Название не найдено"
    assert rows["chat-history"]["Кто писал последним"] == "Покупатель"
    assert rows["chat-history"]["Технический ключ ответа"] == "-"


def test_filter_wb_chat_registry_dataframe_filters_source_reply_date_and_search(db_session):
    db_session.add(
        DimProduct(
            nm_id=100,
            supplier_article="SUP-100",
            title="Трусы женские",
            brand="VVBromo",
            subject="Белье",
            category="Женская одежда",
        )
    )
    db_session.commit()

    chats = [
        ChatRegistry(
            marketplace="wb",
            chat_id="chat-current",
            source="chats",
            reply_sign="reply-1",
            product_ids=[100],
            first_activity_at=datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
            last_activity_at=datetime(2026, 7, 12, 9, 0, tzinfo=UTC),
            updated_at=datetime.now(UTC),
        ),
        ChatRegistry(
            marketplace="wb",
            chat_id="chat-history",
            source="events",
            reply_sign=None,
            product_ids=[999],
            first_activity_at=datetime(2026, 6, 30, 8, 0, tzinfo=UTC),
            last_activity_at=datetime(2026, 7, 3, 8, 0, tzinfo=UTC),
            updated_at=datetime.now(UTC),
        ),
    ]
    table_df, _ = _build_wb_chat_registry_dataframe(
        db_session,
        chats,
        now=datetime(2026, 7, 13, 12, 0, tzinfo=UTC),
    )

    history_df = _filter_wb_chat_registry_dataframe(
        table_df,
        source_filter="История событий",
        can_reply_filter="Все",
        activity_date_from=None,
        activity_date_to=None,
        search_query="",
    )
    assert history_df["ID чата"].tolist() == ["chat-history"]

    replyable_df = _filter_wb_chat_registry_dataframe(
        table_df,
        source_filter="Все",
        can_reply_filter="Да",
        activity_date_from=None,
        activity_date_to=None,
        search_query="",
    )
    assert replyable_df["ID чата"].tolist() == ["chat-current"]

    searched_df = _filter_wb_chat_registry_dataframe(
        table_df,
        source_filter="Все",
        can_reply_filter="Все",
        activity_date_from=date(2026, 7, 10),
        activity_date_to=date(2026, 7, 12),
        search_query="sup-100",
    )
    assert searched_df["ID чата"].tolist() == ["chat-current"]
