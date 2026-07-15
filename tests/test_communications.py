from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.db.communications_models import CampaignRecipient, ChatRegistry
from src.db.models import DimProduct
from src.services.communications.audience_service import AudienceService
from src.services.communications.campaign_service import CampaignService
from src.services.communications.providers import WBChatProvider
from src.services.communications.ui import (
    WB_CHAT_REGISTRY_DISPLAY_COLUMNS,
    WB_CHAT_REGISTRY_EXPORT_COLUMNS,
    _build_wb_chat_registry_dataframe,
    _filter_wb_chat_registry_dataframe,
)

ALL_LABEL = "Все"
YES_LABEL = "Да"
CURRENT_SOURCE_LABEL = "Текущие чаты"
HISTORY_SOURCE_LABEL = "История событий"

COL_CHAT_ID = WB_CHAT_REGISTRY_DISPLAY_COLUMNS[0]
COL_STATUS = WB_CHAT_REGISTRY_DISPLAY_COLUMNS[1]
COL_WB_ARTICLE = WB_CHAT_REGISTRY_DISPLAY_COLUMNS[2]
COL_TITLE = WB_CHAT_REGISTRY_DISPLAY_COLUMNS[3]
COL_FIRST_ACTIVITY = WB_CHAT_REGISTRY_DISPLAY_COLUMNS[4]
COL_LAST_ACTIVITY = WB_CHAT_REGISTRY_DISPLAY_COLUMNS[5]
COL_DAYS = WB_CHAT_REGISTRY_DISPLAY_COLUMNS[6]
COL_SOURCE = WB_CHAT_REGISTRY_DISPLAY_COLUMNS[7]
COL_CAN_REPLY = WB_CHAT_REGISTRY_DISPLAY_COLUMNS[8]
TECH_KEY_COL = WB_CHAT_REGISTRY_EXPORT_COLUMNS[-1]


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
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_create_and_duplicate_campaign(db_session):
    filters = {"activity_days": 30, "nm_ids": [12345]}
    campaign = CampaignService.create_campaign(
        session=db_session,
        marketplace="wb",
        campaign_type="price_increase",
        name="Test Campaign",
        message_text="Hello price increase!",
        promocode="PROMO123",
        event_date=date(2026, 7, 20),
        filters=filters,
        created_by="Test User",
        comment="Test Comment",
    )
    db_session.commit()

    assert campaign.id is not None
    assert campaign.status == "draft"
    assert campaign.marketplace == "wb"
    assert campaign.filters_json == filters

    campaigns = CampaignService.list_campaigns(db_session)
    assert len(campaigns) == 1
    assert campaigns[0].name == "Test Campaign"

    duplicate = CampaignService.duplicate_campaign(db_session, campaign.id)
    db_session.commit()

    assert duplicate.id is not None
    assert duplicate.id != campaign.id
    assert duplicate.name.startswith("Test Campaign (")
    assert duplicate.name.endswith(")")
    assert duplicate.marketplace == "wb"
    assert duplicate.message_text == "Hello price increase!"
    assert duplicate.filters_json == filters


def test_build_chat_registry_from_provider_merges_current_chats_and_events(db_session, monkeypatch):
    chats_payload = {
        "result": [
            {
                "chatID": "chat-both",
                "replySign": "sign-both",
                "goodCard": {"nmID": 100},
                "lastMessage": {"addTimestamp": int(datetime(2026, 7, 10, tzinfo=UTC).timestamp() * 1000)},
            },
            {
                "chatID": "chat-current-only",
                "replySign": "sign-current",
                "goodCard": {"nmID": 300},
                "lastMessage": {"addTimestamp": int(datetime(2026, 7, 11, tzinfo=UTC).timestamp() * 1000)},
            },
        ]
    }
    events_payload = {
        "result": {
            "events": [
                {
                    "chatID": "chat-both",
                    "eventID": 10001,
                    "eventType": "message",
                    "sender": "client",
                    "addTimestamp": int(datetime(2026, 7, 5, tzinfo=UTC).timestamp() * 1000),
                    "message": {"attachments": {"goodCard": {"nmID": 200}}},
                },
                {
                    "chatID": "chat-event-only",
                    "eventID": 10002,
                    "eventType": "message",
                    "sender": "seller",
                    "addTimestamp": int(datetime(2026, 7, 3, tzinfo=UTC).timestamp() * 1000),
                    "message": {"attachments": {"goodCard": {"nmID": 400}}},
                },
            ],
            "next": 0,
        }
    }

    fake_client = FakeWBChatsClient(chats_payload, events_payload)
    monkeypatch.setattr("src.services.communications.providers.WBChatsClient", lambda **kwargs: fake_client)

    provider = WBChatProvider(token="test")
    count = provider.build_chat_registry(db_session, max_event_pages=1)
    db_session.commit()

    assert count == 3

    chats = {
        chat.chat_id: chat
        for chat in db_session.scalars(select(ChatRegistry).where(ChatRegistry.marketplace == "wb")).all()
    }
    assert set(chats) == {"chat-both", "chat-current-only", "chat-event-only"}

    merged_chat = chats["chat-both"]
    assert merged_chat.source == "BOTH"
    assert merged_chat.reply_sign == "sign-both"
    assert merged_chat.current_chat_exists is True
    assert set(merged_chat.product_ids or []) == {100, 200}
    assert merged_chat.first_activity_at.date() == date(2026, 7, 5)
    assert merged_chat.last_activity_at.date() == date(2026, 7, 10)
    assert merged_chat.last_sender == "client"

    current_only_chat = chats["chat-current-only"]
    assert current_only_chat.source == "SELLER_CHATS_ONLY"
    assert current_only_chat.reply_sign == "sign-current"
    assert current_only_chat.current_chat_exists is True
    assert current_only_chat.product_ids == [300]

    event_only_chat = chats["chat-event-only"]
    assert event_only_chat.source == "SELLER_EVENTS_ONLY"
    assert event_only_chat.reply_sign is None
    assert event_only_chat.current_chat_exists is False
    assert event_only_chat.product_ids == [400]


def test_audience_filtering_and_limits(db_session):
    now_utc = datetime.now(UTC)
    db_session.add_all(
        [
            ChatRegistry(
                marketplace="wb",
                chat_id="chat-1",
                reply_sign="sign-1",
                current_chat_exists=True,
                product_ids=[123, 456],
                last_activity_at=now_utc - timedelta(days=1),
                updated_at=datetime.now(),
            ),
            ChatRegistry(
                marketplace="wb",
                chat_id="chat-2",
                reply_sign="sign-2",
                current_chat_exists=True,
                product_ids=[123],
                last_activity_at=now_utc - timedelta(days=60),
                updated_at=datetime.now(),
            ),
            ChatRegistry(
                marketplace="wb",
                chat_id="chat-3",
                reply_sign="sign-3",
                current_chat_exists=True,
                product_ids=[789],
                last_activity_at=now_utc - timedelta(days=1),
                updated_at=datetime.now(),
            ),
        ]
    )
    db_session.commit()

    campaign = CampaignService.create_campaign(
        session=db_session,
        marketplace="wb",
        campaign_type="custom",
        name="Filter Test",
        message_text="Hello!",
        filters={
            "activity_days": 10,
            "nm_ids": [123],
            "only_with_reply_sign": True,
            "only_current_chats": True,
            "recipient_limit": 10,
        },
    )
    db_session.commit()

    from unittest.mock import patch

    with patch("src.services.communications.audience_service.WBChatProvider") as provider_cls:
        provider_cls.return_value.build_chat_registry.return_value = 0
        stats = AudienceService.collect_and_filter_audience(db_session, campaign.id)
        db_session.commit()

    recipients = CampaignService.get_campaign_recipients(db_session, campaign.id)
    assert len(recipients) == 3

    recipients_by_chat = {recipient.chat_id: recipient for recipient in recipients}
    assert recipients_by_chat["chat-1"].recipient_status == "ready"
    assert recipients_by_chat["chat-1"].selected is True
    assert recipients_by_chat["chat-2"].recipient_status == "excluded"
    assert recipients_by_chat["chat-2"].selected is False
    assert recipients_by_chat["chat-2"].reason
    assert recipients_by_chat["chat-3"].recipient_status == "excluded"
    assert recipients_by_chat["chat-3"].selected is False
    assert recipients_by_chat["chat-3"].reason
    assert stats["ready"] == 1
    assert stats["excluded"] == 2


def test_send_campaign_simulation(db_session):
    campaign = CampaignService.create_campaign(
        session=db_session,
        marketplace="wb",
        campaign_type="custom",
        name="Send Test",
        message_text="Final text",
    )
    db_session.commit()

    recipients = [
        CampaignRecipient(
            campaign_id=campaign.id,
            marketplace="wb",
            chat_id="chat-1",
            recipient_status="ready",
            selected=True,
        ),
        CampaignRecipient(
            campaign_id=campaign.id,
            marketplace="wb",
            chat_id="chat-2",
            recipient_status="ready",
            selected=True,
        ),
    ]
    db_session.add_all(recipients)
    db_session.commit()

    result = CampaignService.send_campaign_messages(
        session=db_session,
        campaign_id=campaign.id,
        recipient_ids=[recipient.id for recipient in recipients],
        dry_run=True,
        batch_limit=10,
    )
    db_session.commit()

    assert result["processed_count"] == 2
    assert result["sent_count"] == 2
    assert result["error_count"] == 0
    assert result["is_simulation"] is True
    assert recipients[0].recipient_status == "sent"
    assert recipients[1].recipient_status == "sent"

    logs = CampaignService.get_campaign_send_logs(db_session, campaign.id)
    assert len(logs) == 2
    assert logs[0].send_status == "sent"
    assert logs[0].message_text == "Final text"


def test_build_wb_chat_registry_dataframe_localizes_columns_and_joins_product_data(db_session):
    db_session.add(
        DimProduct(
            nm_id=100,
            supplier_article="SUP-100",
            title="Womens briefs",
            brand="VVBromo",
            subject="Lingerie",
            category="Women",
        )
    )
    db_session.commit()

    chats = [
        ChatRegistry(
            marketplace="wb",
            chat_id="chat-current",
            source="SELLER_CHATS_ONLY",
            reply_sign="reply-1",
            current_chat_exists=True,
            product_ids=[100],
            first_activity_at=datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
            last_activity_at=datetime(2026, 7, 12, 9, 0, tzinfo=UTC),
            updated_at=datetime.now(UTC),
        ),
        ChatRegistry(
            marketplace="wb",
            chat_id="chat-both-no-reply",
            source="BOTH",
            reply_sign="",
            current_chat_exists=True,
            product_ids=[101],
            first_activity_at=datetime(2026, 7, 2, 10, 0, tzinfo=UTC),
            last_activity_at=datetime(2026, 7, 11, 9, 0, tzinfo=UTC),
            updated_at=datetime.now(UTC),
        ),
        ChatRegistry(
            marketplace="wb",
            chat_id="chat-history",
            source="SELLER_EVENTS_ONLY",
            reply_sign=None,
            current_chat_exists=False,
            last_sender="client",
            product_ids=[],
            first_activity_at=None,
            last_activity_at=datetime(2026, 7, 3, 8, 0, tzinfo=UTC),
            updated_at=datetime.now(UTC),
        ),
    ]

    table_df, summary = _build_wb_chat_registry_dataframe(
        db_session,
        chats,
        now=datetime(2026, 7, 13, 12, 0, tzinfo=UTC),
    )
    rows = {row[COL_CHAT_ID]: row for row in table_df.to_dict("records")}

    assert summary["total_chats"] == 3
    assert summary["current_source_chats"] == 2
    assert summary["history_source_chats"] == 1
    assert summary["unique_wb_articles"] == 2

    assert COL_CHAT_ID in table_df.columns
    assert COL_SOURCE in table_df.columns
    assert COL_CAN_REPLY in table_df.columns
    assert TECH_KEY_COL in table_df.columns

    assert rows["chat-current"][COL_TITLE] == "Womens briefs"
    assert rows["chat-current"]["__source_key"] == "seller_chats_only"
    assert rows["chat-current"]["__is_current_chat"] is True
    assert rows["chat-current"]["__can_reply"] is True
    assert "sup-100" in rows["chat-current"]["__search_text"]

    assert rows["chat-both-no-reply"]["__source_key"] == "both"
    assert rows["chat-both-no-reply"]["__is_current_chat"] is True
    assert rows["chat-both-no-reply"]["__can_reply"] is False

    assert rows["chat-history"]["__source_key"] == "seller_events_only"
    assert rows["chat-history"]["__is_current_chat"] is False
    assert rows["chat-history"]["__can_reply"] is False
    assert rows["chat-history"][TECH_KEY_COL] == "-"


def test_filter_wb_chat_registry_dataframe_treats_both_as_current_and_keeps_partial_history_rows(db_session):
    db_session.add(
        DimProduct(
            nm_id=100,
            supplier_article="SUP-100",
            title="Womens briefs",
            brand="VVBromo",
            subject="Lingerie",
            category="Women",
        )
    )
    db_session.commit()

    chats = [
        ChatRegistry(
            marketplace="wb",
            chat_id="chat-current",
            source="SELLER_CHATS_ONLY",
            reply_sign="reply-1",
            current_chat_exists=True,
            product_ids=[100],
            first_activity_at=datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
            last_activity_at=datetime(2026, 7, 12, 9, 0, tzinfo=UTC),
            updated_at=datetime.now(UTC),
        ),
        ChatRegistry(
            marketplace="wb",
            chat_id="chat-both",
            source="BOTH",
            reply_sign="reply-2",
            current_chat_exists=True,
            product_ids=[],
            first_activity_at=datetime(2026, 6, 30, 8, 0, tzinfo=UTC),
            last_activity_at=datetime(2026, 7, 11, 8, 0, tzinfo=UTC),
            updated_at=datetime.now(UTC),
        ),
        ChatRegistry(
            marketplace="wb",
            chat_id="chat-history-empty",
            source="SELLER_EVENTS_ONLY",
            reply_sign=None,
            current_chat_exists=False,
            product_ids=[],
            first_activity_at=None,
            last_activity_at=None,
            updated_at=datetime.now(UTC),
        ),
    ]

    table_df, _ = _build_wb_chat_registry_dataframe(
        db_session,
        chats,
        now=datetime(2026, 7, 13, 12, 0, tzinfo=UTC),
    )

    current_df = _filter_wb_chat_registry_dataframe(
        table_df,
        source_filter=CURRENT_SOURCE_LABEL,
        can_reply_filter=ALL_LABEL,
        activity_date_from=None,
        activity_date_to=None,
        search_query="",
    )
    assert current_df[COL_CHAT_ID].tolist() == ["chat-current", "chat-both"]

    history_df = _filter_wb_chat_registry_dataframe(
        table_df,
        source_filter=HISTORY_SOURCE_LABEL,
        can_reply_filter=ALL_LABEL,
        activity_date_from=None,
        activity_date_to=None,
        search_query="",
    )
    assert history_df[COL_CHAT_ID].tolist() == ["chat-history-empty"]

    replyable_df = _filter_wb_chat_registry_dataframe(
        table_df,
        source_filter=ALL_LABEL,
        can_reply_filter=YES_LABEL,
        activity_date_from=None,
        activity_date_to=None,
        search_query="",
    )
    assert replyable_df[COL_CHAT_ID].tolist() == ["chat-current", "chat-both"]

    unfiltered_df = _filter_wb_chat_registry_dataframe(
        table_df,
        source_filter=ALL_LABEL,
        can_reply_filter=ALL_LABEL,
        activity_date_from=None,
        activity_date_to=None,
        search_query="",
    )
    assert unfiltered_df[COL_CHAT_ID].tolist() == ["chat-current", "chat-both", "chat-history-empty"]

    searched_df = _filter_wb_chat_registry_dataframe(
        table_df,
        source_filter=ALL_LABEL,
        can_reply_filter=ALL_LABEL,
        activity_date_from=date(2026, 7, 10),
        activity_date_to=date(2026, 7, 12),
        search_query="sup-100",
    )
    assert searched_df[COL_CHAT_ID].tolist() == ["chat-current"]
