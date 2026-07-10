from __future__ import annotations

import time
from datetime import datetime, UTC
from typing import Any, Optional, Dict, List

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.db.communications_models import Campaign, CampaignRecipient, SendLog
from src.services.communications.providers import WBChatProvider, OzonChatProvider
from src.utils.logger import get_logger

logger = get_logger("campaign_service")


class CampaignService:
    """Сервис для управления кампаниями рассылок."""

    @staticmethod
    def create_campaign(
        session: Session,
        marketplace: str,
        campaign_type: str,
        name: str,
        message_text: str,
        promocode: Optional[str] = None,
        event_date: Optional[datetime.date] = None,
        filters: Optional[dict] = None,
        created_by: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> Campaign:
        """Создать новую кампанию."""
        campaign = Campaign(
            marketplace=marketplace.lower(),
            campaign_type=campaign_type.lower(),
            name=name,
            message_text=message_text,
            promocode=promocode,
            event_date=event_date,
            filters_json=filters,
            status="draft",
            created_by=created_by,
            comment=comment,
        )
        session.add(campaign)
        session.flush()  # Получить ID
        logger.info(f"Created campaign {campaign.id} ({campaign.name})")
        return campaign

    @staticmethod
    def get_campaign(session: Session, campaign_id: int) -> Optional[Campaign]:
        """Получить кампанию по ID."""
        return session.get(Campaign, campaign_id)

    @staticmethod
    def list_campaigns(session: Session) -> List[Campaign]:
        """Получить список всех кампаний, отсортированных по дате создания."""
        stmt = select(Campaign).order_by(desc(Campaign.created_at))
        return list(session.scalars(stmt).all())

    @staticmethod
    def duplicate_campaign(session: Session, campaign_id: int) -> Optional[Campaign]:
        """Продублировать существующую кампанию."""
        orig = session.get(Campaign, campaign_id)
        if not orig:
            return None
            
        dup = Campaign(
            marketplace=orig.marketplace,
            campaign_type=orig.campaign_type,
            name=f"{orig.name} (Копия)",
            message_text=orig.message_text,
            promocode=orig.promocode,
            event_date=orig.event_date,
            filters_json=orig.filters_json,
            status="draft",
            created_by=orig.created_by,
            comment=orig.comment,
        )
        session.add(dup)
        session.flush()
        logger.info(f"Duplicated campaign {campaign_id} into {dup.id}")
        return dup

    @staticmethod
    def get_campaign_recipients(
        session: Session, campaign_id: int, selected_only: bool = False
    ) -> List[CampaignRecipient]:
        """Получить список получателей кампании."""
        stmt = select(CampaignRecipient).where(CampaignRecipient.campaign_id == campaign_id)
        if selected_only:
            stmt = stmt.where(CampaignRecipient.selected == True)
        return list(session.scalars(stmt).all())

    @staticmethod
    def get_campaign_send_logs(session: Session, campaign_id: int) -> List[SendLog]:
        """Получить логи отправки для кампании."""
        stmt = select(SendLog).where(SendLog.campaign_id == campaign_id).order_by(desc(SendLog.sent_at))
        return list(session.scalars(stmt).all())

    @classmethod
    def send_campaign_messages(
        cls,
        session: Session,
        campaign_id: int,
        recipient_ids: List[int],
        dry_run: bool = False,
        batch_limit: int = 50,
        sent_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Запустить отправку сообщений по выбранным получателям.
        
        Параметр dry_run форсирует симуляцию отправки.
        Параметр settings.wb_comm_real_send_enabled определяет, разрешена ли реальная отправка в окружении.
        """
        campaign = session.get(Campaign, campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        # Проверяем разрешение реальной отправки в окружении (строгое И/AND)
        is_real_send_allowed = settings.wb_comm_real_send_enabled and bool(settings.wb_token)
        is_simulation = dry_run or not is_real_send_allowed

        logger.info(
            f"Starting campaign {campaign_id} sending. "
            f"Recipients to process: {len(recipient_ids)}. "
            f"Simulation mode: {is_simulation} (dry_run: {dry_run}, env_allow: {is_real_send_allowed})"
        )

        # Выбираем получателей со статусом 'ready' / 'test_only' / 'error' (чтобы можно было переотправлять ошибки)
        # И отфильтрованных по переданному списку выбранных ID
        stmt = select(CampaignRecipient).where(
            CampaignRecipient.campaign_id == campaign_id,
            CampaignRecipient.id.in_(recipient_ids),
            CampaignRecipient.recipient_status.in_(("ready", "test_only", "error", "unknown"))
        ).limit(batch_limit)
        
        recipients = list(session.scalars(stmt).all())
        if not recipients:
            logger.info("No eligible recipients found to send messages to")
            return {
                "campaign_id": campaign_id,
                "processed_count": 0,
                "sent_count": 0,
                "error_count": 0,
                "is_simulation": is_simulation,
                "finished": True,
            }

        # Инициализируем провайдер маркетплейса
        provider = None
        if not is_simulation:
            if campaign.marketplace == "wb":
                provider = WBChatProvider()
            elif campaign.marketplace == "ozon":
                provider = OzonChatProvider()
            else:
                raise ValueError(f"Unknown marketplace: {campaign.marketplace}")

        processed_count = 0
        sent_count = 0
        error_count = 0

        # Обновляем статус кампании на "sending"
        campaign.status = "sending"
        session.flush()

        for recipient in recipients:
            processed_count += 1
            chat_id = recipient.chat_id
            
            # 1. Симуляция отправки
            if is_simulation:
                send_status = "sent" if recipient.recipient_status != "error" else "skipped"
                log_text = f"[Simulation] Message: {campaign.message_text}"
                api_resp = {"simulation": True, "real_send_enabled_env": is_real_send_allowed}
                error_msg = None
                
                # Обновляем статус получателя
                recipient.recipient_status = "sent" if send_status == "sent" else "error"
                sent_count += 1
                
                logger.info(f"Simulated message send to chat {chat_id}")
            
            # 2. Реальная отправка
            else:
                logger.info(f"Executing real message send to chat {chat_id} via {campaign.marketplace}")
                try:
                    res = provider.send_message(
                        chat_id=chat_id,
                        text=campaign.message_text,
                        reply_sign=recipient.reply_sign
                    )
                    
                    if res.get("success"):
                        send_status = "sent"
                        recipient.recipient_status = "sent"
                        api_resp = res.get("raw_response")
                        error_msg = None
                        sent_count += 1
                    else:
                        send_status = "error"
                        recipient.recipient_status = "error"
                        api_resp = res.get("raw_response")
                        error_msg = res.get("error") or "Unknown API error"
                        error_count += 1
                        
                except Exception as exc:
                    send_status = "error"
                    recipient.recipient_status = "error"
                    api_resp = None
                    error_msg = str(exc)
                    error_count += 1
            
            # Записываем в лог отправки
            log_entry = SendLog(
                campaign_id=campaign_id,
                marketplace=campaign.marketplace,
                chat_id=chat_id,
                message_text=campaign.message_text,
                send_status=send_status,
                api_response=api_resp,
                error_message=error_msg,
                sent_by=sent_by
            )
            session.add(log_entry)
            
            # Задержка (Rate Limiting) между запросами для безопасности API
            if processed_count < len(recipients) and not is_simulation:
                time.sleep(1.0)

        # Проверяем, остались ли еще получатели со статусом 'ready'
        stmt_remain = select(CampaignRecipient).where(
            CampaignRecipient.campaign_id == campaign_id,
            CampaignRecipient.recipient_status.in_(("ready", "test_only"))
        ).limit(1)
        has_remaining = session.scalar(stmt_remain) is not None

        if not has_remaining:
            # Если все отправлены, переводим статус кампании
            campaign.status = "sent" if error_count == 0 else "failed"
        else:
            campaign.status = "audience_ready"  # Еще остались не отправленные
            
        session.flush()

        return {
            "campaign_id": campaign_id,
            "processed_count": processed_count,
            "sent_count": sent_count,
            "error_count": error_count,
            "is_simulation": is_simulation,
            "finished": not has_remaining,
        }
