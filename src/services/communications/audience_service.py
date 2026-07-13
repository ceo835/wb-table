from __future__ import annotations

from datetime import datetime, UTC, timedelta
from typing import Any, Dict, List, Set

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from src.db.communications_models import Campaign, ChatRegistry, CampaignRecipient, SendLog
from src.services.communications.providers import (
    OzonChatProvider,
    WBChatProvider,
    ozon_registry_can_reply,
    parse_ozon_registry_meta,
)
from src.utils.logger import get_logger

logger = get_logger("audience_service")


class AudienceService:
    """Сервис для сбора и фильтрации аудитории кампаний рассылок."""

    @classmethod
    def collect_and_filter_audience(
        cls,
        session: Session,
        campaign_id: int,
        max_event_pages: int = 10,
    ) -> Dict[str, Any]:
        """Собрать и отфильтровать аудиторию для кампании."""
        campaign = session.get(Campaign, campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        # 1. Синхронизируем реестр чатов с маркетплейсом
        logger.info(f"Syncing chat registry for campaign {campaign_id} ({campaign.marketplace})")
        if campaign.marketplace == "wb":
            provider = WBChatProvider()
            provider.build_chat_registry(session, max_event_pages=max_event_pages)
        elif campaign.marketplace == "ozon":
            provider = OzonChatProvider()
            # Ozon пока не реализован, выбросит ошибку
            provider.build_chat_registry(session)
        else:
            raise ValueError(f"Unknown marketplace: {campaign.marketplace}")

        # 2. Очищаем старых получателей в статусе черновиков (не отправленные и не с ошибкой)
        # Это реализует пересборку аудитории
        stmt_delete = delete(CampaignRecipient).where(
            CampaignRecipient.campaign_id == campaign_id,
            CampaignRecipient.recipient_status.notin_(("sent", "error"))
        )
        session.execute(stmt_delete)
        session.flush()

        # Получаем уже отправленные чаты для этой кампании (их нельзя дублировать)
        stmt_sent = select(CampaignRecipient.chat_id).where(
            CampaignRecipient.campaign_id == campaign_id,
            CampaignRecipient.recipient_status.in_(("sent", "error"))
        )
        already_sent_chat_ids = set(session.scalars(stmt_sent).all())

        # 3. Выгружаем все чаты из реестра для этого маркетплейса
        stmt_chats = select(ChatRegistry).where(ChatRegistry.marketplace == campaign.marketplace)
        registry_chats = list(session.scalars(stmt_chats).all())

        # Читаем фильтры
        filters = campaign.filters_json or {}
        
        # Фильтр: Период активности (lookback days)
        activity_days = filters.get("activity_days")
        now_utc = datetime.now(UTC)
        activity_cutoff = None
        if activity_days:
            activity_cutoff = now_utc - timedelta(days=int(activity_days))

        # Фильтр: Список nmID
        nm_ids_filter = filters.get("nm_ids")
        if isinstance(nm_ids_filter, list):
            nm_ids_set = {int(x) for x in nm_ids_filter if str(x).isdigit()}
        else:
            nm_ids_set = None

        # Фильтр: Исключить чаты, которым отправляли ЛЮБУЮ кампанию за последние N дней
        exclude_lookback_days = filters.get("exclude_global_lookback_days")
        excluded_global_chat_ids: Set[str] = set()
        if exclude_lookback_days:
            limit_date = now_utc - timedelta(days=int(exclude_lookback_days))
            stmt_global_sent = select(SendLog.chat_id).where(
                SendLog.sent_at >= limit_date,
                SendLog.send_status == "sent",
                SendLog.marketplace == campaign.marketplace,
            )
            excluded_global_chat_ids = set(session.scalars(stmt_global_sent).all())

        # Фильтры наличия replySign и присутствия в активных чатах
        only_with_reply_sign = filters.get("only_with_reply_sign", False)
        only_current_chats = filters.get("only_current_chats", False)
        only_with_product_linkage = filters.get("only_with_product_linkage", False)
        search_query = str(filters.get("search_query") or "").strip().lower()

        stats = {
            "total_registry_chats": len(registry_chats),
            "matched_period": 0,
            "matched_products": 0,
            "has_current_chats": 0,
            "has_reply_sign": 0,
            "excluded_repeats": 0,
            "ready": 0,
            "excluded": 0,
            "unknown": 0,
        }

        recipients_to_save = []
        ready_recipients = []

        for chat in registry_chats:
            chat_id = chat.chat_id
            
            # Проверяем, не отправляли ли уже эту кампанию в этот чат
            if chat_id in already_sent_chat_ids:
                # Уже отправлено, пропускаем создание нового получателя (строка сохраняется как sent/error)
                stats["excluded_repeats"] += 1
                continue

            # Проверяем фильтры и накапливаем причины исключения
            reasons = []
            is_ready = True
            
            # 1. Фильтр активности
            chat_last_act = chat.last_activity_at
            if chat_last_act and chat_last_act.tzinfo is None:
                chat_last_act = chat_last_act.replace(tzinfo=UTC)

            if activity_cutoff:
                if not chat_last_act or chat_last_act < activity_cutoff:
                    is_ready = False
                    reasons.append("нет активности в выбранном периоде")
                else:
                    stats["matched_period"] += 1
            else:
                stats["matched_period"] += 1

            # 2. Фильтр товаров (nmID)
            chat_product_ids = chat.product_ids or []
            if nm_ids_set:
                intersect = set(chat_product_ids) & nm_ids_set
                if not intersect:
                    is_ready = False
                    reasons.append("нет связи с выбранным товаром")
                else:
                    stats["matched_products"] += 1
            else:
                stats["matched_products"] += 1

            if only_with_product_linkage and not chat_product_ids:
                is_ready = False
                reasons.append("нет привязки к товару")

            # 3. Ozon reply capability / replySign
            chat_meta = parse_ozon_registry_meta(chat.reply_sign) if campaign.marketplace == "ozon" else {}
            chat_has_reply = ozon_registry_can_reply(chat_meta) if campaign.marketplace == "ozon" else bool(chat.reply_sign)
            if chat_has_reply:
                stats["has_reply_sign"] += 1
            elif only_with_reply_sign:
                is_ready = False
                reasons.append("\u043d\u0435\u0442 \u043f\u0440\u0438\u0437\u043d\u0430\u043a\u0430 \u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e\u0441\u0442\u0438 \u043e\u0442\u0432\u0435\u0442\u0430")

            # 4. Фильтр активных чатов
            if chat.current_chat_exists:
                stats["has_current_chats"] += 1
            elif only_current_chats:
                is_ready = False
                reasons.append("не входит в текущие /seller/chats")

            # 5. Глобальное исключение повторных отправок
            if chat_id in excluded_global_chat_ids:
                is_ready = False
                reasons.append(f"отправляли другую кампанию за последние {exclude_lookback_days} дн.")
                stats["excluded_repeats"] += 1

            if search_query:
                search_tokens = [chat_id.lower(), *(str(product_id).lower() for product_id in chat_product_ids)]
                if campaign.marketplace == "ozon":
                    search_tokens.extend(
                        str(chat_meta.get(field_name) or "").strip().lower()
                        for field_name in ("offer_id", "sku", "product_id", "product_name", "vendor_code")
                    )
                search_tokens = [token for token in search_tokens if token]
                if not any(search_query in token for token in search_tokens):
                    is_ready = False
                    reasons.append("не совпадает с поисковым фильтром")

            # ????????????? ?????? ??????????
            if is_ready:
                status = "ready"
                reason = "подходит под фильтры"
            else:
                status = "excluded"
                reason = "; ".join(reasons)

            if not chat.last_activity_at and status != "excluded":
                status = "unknown"
                reason = "недостаточно данных об активности чата"

            recipient = CampaignRecipient(
                campaign_id=campaign_id,
                marketplace=campaign.marketplace,
                chat_id=chat_id,
                product_id=chat.product_ids[0] if chat.product_ids else None,
                recipient_status=status,
                reason=reason,
                selected=True if status == "ready" else False,
            )

            recipients_to_save.append(recipient)
            if status == "ready":
                ready_recipients.append(recipient)
            else:
                stats[status] += 1

        # Фильтр: Лимит получателей (recipient_limit)
        recipient_limit = filters.get("recipient_limit")
        if recipient_limit and len(ready_recipients) > int(recipient_limit):
            limit_val = int(recipient_limit)
            logger.info(f"Applying recipient limit of {limit_val} to {len(ready_recipients)} ready recipients")
            
            # Разделяем на те, что влезают в лимит, и те, что выходят за рамки
            in_limit = ready_recipients[:limit_val]
            over_limit = ready_recipients[limit_val:]
            
            for r in over_limit:
                r.recipient_status = "excluded"
                r.reason = "превышен лимит получателей"
                r.selected = False
                stats["excluded"] += 1
                
            stats["ready"] = len(in_limit)
        else:
            stats["ready"] = len(ready_recipients)

        # Сохраняем получателей
        for r in recipients_to_save:
            session.add(r)
            
        # Обновляем статус кампании
        campaign.status = "audience_ready"
        session.flush()

        logger.info(
            f"Audience collected for campaign {campaign_id}. "
            f"Stats: Ready={stats['ready']}, Excluded={stats['excluded']}, Unknown={stats['unknown']}"
        )
        return stats
