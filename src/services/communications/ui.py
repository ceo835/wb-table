from __future__ import annotations

import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any

from src.config.settings import settings
from sqlalchemy import select
from src.db.session import session_scope
from src.db.communications_models import Campaign, ChatRegistry, CampaignRecipient, SendLog
from src.services.communications.campaign_service import CampaignService
from src.services.communications.audience_service import AudienceService
from src.services.communications.providers import WBChatProvider


def render_communications_tab() -> None:
    st.header("Центр коммуникаций")
    
    # Информационный индикатор безопасности отправки
    is_real_send = settings.wb_comm_real_send_enabled
    if is_real_send:
        st.success("🟢 **Реальная отправка включена** (`WB_COMM_REAL_SEND_ENABLED=true`). Сообщения могут доставляться покупателям.")
    else:
        st.warning("🟡 **Режим симуляции по умолчанию** (`WB_COMM_REAL_SEND_ENABLED=false`). Все рассылки будут выполняться в режиме симуляции (Dry-run).")

    # Разделение по маркетплейсам
    tab_wb, tab_ozon = st.tabs(["Wildberries", "Ozon"])
    
    with tab_wb:
        # Подменю навигации внутри Wildberries
        wb_sub_tab = st.radio(
            "Раздел WB:",
            options=["Кампании WB", "Реестр WB-чатов", "История отправок WB"],
            horizontal=True,
            key="comm_wb_sub_tab"
        )
        st.write("---")
        with session_scope() as session:
            if wb_sub_tab == "Кампании WB":
                render_campaigns_subtab(session)
            elif wb_sub_tab == "Реестр WB-чатов":
                render_chats_registry_subtab(session)
            elif wb_sub_tab == "История отправок WB":
                render_history_subtab(session)

    with tab_ozon:
        st.info("ℹ️ **Ozon-коммуникации будут добавлены позже после аудита API**")
        st.radio(
            "Раздел Ozon (в разработке):",
            options=["Кампании Ozon", "Реестр Ozon-чатов", "История отправок Ozon"],
            horizontal=True,
            disabled=True,
            key="comm_ozon_sub_tab"
        )


def render_campaigns_subtab(session) -> None:
    # Инициализируем session_state для навигации по кампаниям
    if "comm_active_campaign_id" not in st.session_state:
        st.session_state.comm_active_campaign_id = None
    if "comm_creating_new" not in st.session_state:
        st.session_state.comm_creating_new = False
    if "comm_show_confirm" not in st.session_state:
        st.session_state.comm_show_confirm = False

    active_id = st.session_state.comm_active_campaign_id
    creating = st.session_state.comm_creating_new

    # Режим создания или редактирования/просмотра кампании
    if creating or active_id is not None:
        render_campaign_form(session, active_id)
        return

    # Главный экран: список кампаний
    st.subheader("Список кампаний WB")
    
    col_actions = st.columns([1, 4])
    if col_actions[0].button("➕ Создать кампанию", type="primary"):
        st.session_state.comm_creating_new = True
        st.rerun()

    campaigns = CampaignService.list_campaigns(session)
    if not campaigns:
        st.info("Кампаний пока не создано. Нажмите кнопку выше, чтобы запустить рассылку.")
        return

    # Собираем данные для отображения в таблице
    camp_list = []
    for c in campaigns:
        # Считаем аудиторию
        recipients = CampaignService.get_campaign_recipients(session, c.id)
        total_rec = len(recipients)
        ready_rec = sum(1 for r in recipients if r.recipient_status == "ready")
        sent_rec = sum(1 for r in recipients if r.recipient_status == "sent")
        error_rec = sum(1 for r in recipients if r.recipient_status == "error")

        camp_list.append({
            "ID": c.id,
            "Название": c.name,
            "Маркетплейс": c.marketplace.upper(),
            "Тип": c.campaign_type,
            "Статус": c.status,
            "Получателей": f"{ready_rec} из {total_rec} готово" if total_rec > 0 else "Нет аудитории",
            "Отправлено": sent_rec,
            "Ошибки": error_rec,
            "Создана": c.created_at.strftime("%Y-%m-%d %H:%M"),
        })

    df = pd.DataFrame(camp_list)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.write("---")
    st.write("**Действия с кампаниями:**")
    
    # Выбор кампании для детального просмотра
    c_options = {c.id: f"ID {c.id} | {c.name} ({c.status})" for c in campaigns}
    selected_camp_id = st.selectbox("Выберите кампанию для открытия или дублирования:", options=list(c_options.keys()), format_func=lambda x: c_options[x])

    col_btn = st.columns(3)
    if col_btn[0].button("📂 Открыть кампанию", use_container_width=True):
        st.session_state.comm_active_campaign_id = selected_camp_id
        st.rerun()
        
    if col_btn[1].button("👯 Продублировать", use_container_width=True):
        dup = CampaignService.duplicate_campaign(session, selected_camp_id)
        if dup:
            session.commit()
            st.success(f"Кампания успешно продублирована как ID {dup.id}!")
            st.rerun()


def render_campaign_form(session, campaign_id: Optional[int]) -> None:
    # Загружаем существующую кампанию или готовим новую
    campaign = None
    if campaign_id is not None:
        campaign = CampaignService.get_campaign(session, campaign_id)

    title_text = f"Просмотр кампании ID {campaign_id}" if campaign else "Создание новой кампании рассылки"
    st.subheader(title_text)

    # Загрузка полей из сущности
    marketplace = "wb"
    campaign_type = "price_increase"
    name = ""
    promocode = ""
    event_date = date.today() + timedelta(days=3)
    message_text = ""
    comment = ""
    filters = {}

    if campaign:
        marketplace = campaign.marketplace
        campaign_type = campaign.campaign_type
        name = campaign.name
        promocode = campaign.promocode or ""
        event_date = campaign.event_date or (date.today() + timedelta(days=3))
        message_text = campaign.message_text
        comment = campaign.comment or ""
        filters = campaign.filters_json or {}

    # Поля ввода
    col_fields = st.columns(2)
    with col_fields[0]:
        input_marketplace = st.selectbox("Маркетплейс", options=["Wildberries", "Ozon (недоступно)"], index=0, disabled=True)
        input_type = st.selectbox(
            "Тип рассылки",
            options=["price_increase", "promo", "custom"],
            index=["price_increase", "promo", "custom"].index(campaign_type),
            format_func=lambda x: {
                "price_increase": "Предупреждение о повышении цены",
                "promo": "Промокод / Скидка",
                "custom": "Произвольное сообщение"
            }[x]
        )
        input_name = st.text_input("Название кампании (для ориентира)", value=name)
        input_comment = st.text_area("Комментарий / Заметки", value=comment)

    with col_fields[1]:
        input_promocode = st.text_input("Промокод (если применимо)", value=promocode)
        input_event_date = st.date_input("Дата события (например, дата повышения цены)", value=event_date)

    # Автозаполнение шаблона текста для price_increase
    template_price_increase = f"Добрый день! Хотели предупредить: с {input_event_date} цены на часть ассортимента будут выше. До этой даты можно успеть оформить заказ по текущей цене. Промокод: {input_promocode}."
    
    if input_type == "price_increase" and not message_text:
        default_text = template_price_increase
    else:
        default_text = message_text

    input_text = st.text_area("Текст сообщения для отправки", value=default_text, height=120)

    # Настройки фильтрации аудитории
    st.write("### Фильтры аудитории")
    
    # 1. Период последней активности
    act_days = filters.get("activity_days", "30")
    input_act_days = st.selectbox(
        "Период последней активности покупателя в чате",
        options=["7", "30", "90", "365"],
        index=["7", "30", "90", "365"].index(str(act_days))
    )

    # 2. Товары
    nm_ids_val = ", ".join(map(str, filters.get("nm_ids") or []))
    input_nm_ids_str = st.text_input(
        "Фильтр по товарам (nmID списком через запятую, оставьте пустым для всех товаров)",
        value=nm_ids_val,
        help="Например: 197330807, 37320545"
    )

    # Разбор nm_ids
    nm_ids_list = []
    if input_nm_ids_str:
        nm_ids_list = [int(x.strip()) for x in input_nm_ids_str.split(",") if x.strip().isdigit()]

    # 3. Дополнительные галочки
    input_only_reply_sign = st.checkbox("Только чаты, где разрешен ответ (есть replySign)", value=filters.get("only_with_reply_sign", True))
    input_only_current = st.checkbox("Только чаты из текущих 100 активных чатов (/seller/chats)", value=filters.get("only_current_chats", True))
    input_exclude_global = st.number_input("Исключить чаты, если отправляли рассылку за последние N дней", min_value=0, max_value=365, value=filters.get("exclude_global_lookback_days", 0))
    input_limit = st.number_input("Лимит получателей рассылки (guard limit)", min_value=1, max_value=1000, value=filters.get("recipient_limit", 50))

    # Сборка структуры фильтра
    current_filters = {
        "activity_days": int(input_act_days),
        "nm_ids": nm_ids_list,
        "only_with_reply_sign": input_only_reply_sign,
        "only_current_chats": input_only_current,
        "exclude_global_lookback_days": input_exclude_global,
        "recipient_limit": input_limit,
    }

    # Кнопки сохранения и сбора
    col_save = st.columns(4)
    
    if col_save[0].button("💾 Сохранить черновик", type="secondary", use_container_width=True):
        if not input_name:
            st.error("Пожалуйста, заполните название кампании.")
        else:
            if campaign:
                campaign.name = input_name
                campaign.campaign_type = input_type
                campaign.message_text = input_text
                campaign.promocode = input_promocode
                campaign.event_date = input_event_date
                campaign.comment = input_comment
                campaign.filters_json = current_filters
            else:
                campaign = CampaignService.create_campaign(
                    session,
                    marketplace="wb",
                    campaign_type=input_type,
                    name=input_name,
                    message_text=input_text,
                    promocode=input_promocode,
                    event_date=input_event_date,
                    filters=current_filters,
                    comment=input_comment
                )
            session.commit()
            st.success("Кампания сохранена как черновик!")
            st.session_state.comm_active_campaign_id = campaign.id
            st.session_state.comm_creating_new = False
            st.rerun()

    if col_save[1].button("🔍 Собрать аудиторию", type="primary", use_container_width=True):
        if not input_name:
            st.error("Пожалуйста, введите название кампании.")
        else:
            # Сначала сохраняем
            if campaign:
                campaign.name = input_name
                campaign.campaign_type = input_type
                campaign.message_text = input_text
                campaign.promocode = input_promocode
                campaign.event_date = input_event_date
                campaign.comment = input_comment
                campaign.filters_json = current_filters
            else:
                campaign = CampaignService.create_campaign(
                    session,
                    marketplace="wb",
                    campaign_type=input_type,
                    name=input_name,
                    message_text=input_text,
                    promocode=input_promocode,
                    event_date=input_event_date,
                    filters=current_filters,
                    comment=input_comment
                )
            
            # Собираем аудиторию (пересборка)
            with st.spinner("Синхронизация чатов с Wildberries и фильтрация..."):
                try:
                    stats = AudienceService.collect_and_filter_audience(session, campaign.id, max_event_pages=10)
                    session.commit()
                    st.success("Аудитория собрана успешно!")
                    st.session_state.comm_active_campaign_id = campaign.id
                    st.session_state.comm_creating_new = False
                    st.rerun()
                except Exception as ex:
                    st.error(f"Ошибка при сборе аудитории: {ex}")

    if col_save[3].button("↩️ Назад к списку", use_container_width=True):
        st.session_state.comm_active_campaign_id = None
        st.session_state.comm_creating_new = False
        st.session_state.comm_show_confirm = False
        st.rerun()

    # Показываем блок аудитории и отправки, если кампания сохранена
    if campaign:
        st.divider()
        render_audience_and_send_block(session, campaign)


def render_audience_and_send_block(session, campaign: Campaign) -> None:
    st.write("### Управление отправкой рассылки")
    
    recipients = CampaignService.get_campaign_recipients(session, campaign.id)
    if not recipients:
        st.info("Аудитория для этой кампании ещё не собрана. Нажмите кнопку 'Собрать аудиторию' выше.")
        return

    # Считаем統計
    total = len(recipients)
    ready = sum(1 for r in recipients if r.recipient_status == "ready")
    test_only = sum(1 for r in recipients if r.recipient_status == "test_only")
    unknown = sum(1 for r in recipients if r.recipient_status == "unknown")
    excluded = sum(1 for r in recipients if r.recipient_status == "excluded")
    sent = sum(1 for r in recipients if r.recipient_status == "sent")
    error = sum(1 for r in recipients if r.recipient_status == "error")

    # Отображаем красивые карточки статистики
    col_stats = st.columns(5)
    col_stats[0].metric("Всего чатов в базе", total)
    col_stats[1].metric("Готово к отправке", ready, delta_color="normal")
    col_stats[2].metric("Исключено по фильтрам", excluded)
    col_stats[3].metric("Отправлено ранее", sent)
    col_stats[4].metric("Ошибки отправки", error)

    # Таблица получателей с st.data_editor
    st.write("#### Предпросмотр получателей")
    st.caption("Вы можете снять галочку с отдельных чатов, чтобы исключить их из рассылки вручную.")

    rec_data = []
    for r in recipients:
        rec_data.append({
            "recipient_row_id": r.id,
            "Выбран": r.selected,
            "Статус": r.recipient_status,
            "Chat ID": r.chat_id,
            "Артикул товара": r.product_id or "—",
            "Причина включения/исключения": r.reason or "",
        })

    df_rec = pd.DataFrame(rec_data)
    
    # st.data_editor позволяет изменять чекбокс
    edited_df = st.data_editor(
        df_rec,
        use_container_width=True,
        hide_index=True,
        disabled=["recipient_row_id", "Статус", "Chat ID", "Артикул товара", "Причина включения/исключения"],
        column_config={
            "Выбран": st.column_config.CheckboxColumn("Выбрать для отправки", default=True),
        }
    )

    # Если пользователь внес изменения в чекбоксы, сохраняем их
    if not edited_df.equals(df_rec):
        for index, row in edited_df.iterrows():
            r_id = int(row["recipient_row_id"])
            is_sel = bool(row["Выбран"])
            # Находим получателя в БД и обновляем выбранное значение
            db_rec = session.get(CampaignRecipient, r_id)
            if db_rec:
                db_rec.selected = is_sel
        session.commit()
        st.success("Выбор получателей обновлен!")
        st.rerun()

    # Блок запуска
    st.write("---")
    st.write("#### Запуск отправки")

    # Отдельные флаги
    dry_run = st.checkbox("Режим симуляции (Dry-run, без реального запроса в WB API)", value=True, help="Рекомендуется для тестовой проверки. В этом режиме отправка будет просто записана в логи.")
    batch_size = st.number_input("Лимит отправки за один клик (размер пачки)", min_value=1, max_value=200, value=50)

    # Получаем количество выбранных
    stmt_sel_count = select(CampaignRecipient).where(
        CampaignRecipient.campaign_id == campaign.id,
        CampaignRecipient.selected == True,
        CampaignRecipient.recipient_status.in_(("ready", "test_only", "error", "unknown"))
    )
    selected_recipients = list(session.scalars(stmt_sel_count).all())
    selected_count = len(selected_recipients)

    if selected_count == 0:
        st.warning("Нет выбранных получателей со статусом 'Готово к отправке'. Отправка невозможна.")
        return

    # Запускаем отправку
    if st.button("🚀 Отправить выбранным", type="primary", use_container_width=True):
        st.session_state.comm_show_confirm = True

    if st.session_state.comm_show_confirm:
        st.warning("⚠️ **Подтвердите отправку сообщений!**")
        st.write(f"- **Кампания:** {campaign.name}")
        st.write(f"- **Текст сообщения:** {campaign.message_text}")
        st.write(f"- **Количество получателей:** {min(selected_count, batch_size)} чатов (из {selected_count} выбранных)")
        st.write(f"- **Режим:** {'СИМУЛЯЦИЯ' if (dry_run or not (settings.wb_comm_real_send_enabled and settings.wb_token)) else 'РЕАЛЬНАЯ ОТПРАВКА'}")
        
        col_conf = st.columns(2)
        if col_conf[0].button("Да, запустить рассылку!", type="primary", use_container_width=True):
            st.session_state.comm_show_confirm = False
            
            with st.spinner("Выполняется рассылка..."):
                recipient_ids = [r.id for r in selected_recipients]
                res = CampaignService.send_campaign_messages(
                    session=session,
                    campaign_id=campaign.id,
                    recipient_ids=recipient_ids,
                    dry_run=dry_run,
                    batch_limit=batch_size,
                    sent_by="Streamlit User"
                )
                
                processed = res["processed_count"]
                sent = res["sent_count"]
                errors = res["error_count"]
                
                session.commit()
                if errors == 0:
                    st.success(f"Отправка завершена! Успешно обработано {processed} чатов.")
                else:
                    st.error(f"Отправка завершена с ошибками! Обработано {processed} чатов (Ошибок: {errors}).")
                
                st.rerun()

        if col_conf[1].button("Отмена", use_container_width=True):
            st.session_state.comm_show_confirm = False
            st.rerun()


def render_chats_registry_subtab(session) -> None:
    st.subheader("Реестр чатов Wildberries")
    st.write("Сводная информация по чатам, найденным через `/seller/events` (история) и `/seller/chats` (актуальные).")

    if st.button("🔄 Синхронизировать реестр из API", type="primary"):
        with st.spinner("Загрузка данных из Wildberries..."):
            try:
                from sqlalchemy import func
                from src.utils.logger import get_logger
                ui_logger = get_logger("communications_ui")
                
                provider = WBChatProvider()
                prepared_count = provider.build_chat_registry(session, max_event_pages=10)
                
                # Явно коммитим сессию
                session.commit()
                committed = True
                
                # Получаем диагностические данные
                total_count = session.scalar(select(func.count()).select_from(ChatRegistry))
                wb_count = session.scalar(select(func.count()).select_from(ChatRegistry).where(ChatRegistry.marketplace == "wb"))
                marketplaces = list(session.scalars(select(ChatRegistry.marketplace).distinct()).all())
                
                min_act = session.scalar(select(func.min(ChatRegistry.last_activity_at)))
                max_act = session.scalar(select(func.max(ChatRegistry.last_activity_at)))
                
                ui_logger.info(
                    f"Sync diagnostics:\n"
                    f"- prepared records count: {prepared_count}\n"
                    f"- committed: {committed}\n"
                    f"- ChatRegistry total count after commit: {total_count}\n"
                    f"- ChatRegistry count for marketplace='wb': {wb_count}\n"
                    f"- distinct marketplace values: {marketplaces}\n"
                    f"- min/max last_activity_at: {min_act} / {max_act}"
                )
                
                st.success(f"Синхронизация завершена. Добавлено/обновлено: {prepared_count} записей. Всего в реестре чатов WB: {wb_count} (всего в БД: {total_count}).")
                st.rerun()
            except Exception as e:
                import logging
                logging.getLogger("communications_ui").error(f"Error during registry sync: {e}", exc_info=True)
                st.error(f"Ошибка при синхронизации чатов: {e}")

    stmt = select(ChatRegistry).order_by(ChatRegistry.last_activity_at.desc())
    chats = list(session.scalars(stmt).all())
    
    if not chats:
        st.info("Реестр чатов пока пуст. Выполните синхронизацию.")
        return

    chat_rows = []
    for c in chats:
        chat_rows.append({
            "Chat ID": c.chat_id,
            "Товары (nmIDs)": ", ".join(map(str, c.product_ids or [])),
            "Последний отправитель": c.last_sender or "—",
            "Есть в seller/chats": "Да" if c.current_chat_exists else "Нет",
            "replySign": "Есть" if c.reply_sign else "Нет",
            "Первое событие": c.first_activity_at.strftime("%Y-%m-%d %H:%M") if c.first_activity_at else "—",
            "Последнее событие": c.last_activity_at.strftime("%Y-%m-%d %H:%M") if c.last_activity_at else "—",
        })

    st.dataframe(pd.DataFrame(chat_rows), use_container_width=True, hide_index=True)


def render_history_subtab(session) -> None:
    st.subheader("История отправок WB")
    st.write("История отправленных сообщений по кампаниям WB.")

    stmt = select(SendLog).order_by(SendLog.sent_at.desc())
    logs = list(session.scalars(stmt).all())

    if not logs:
        st.info("Сообщения еще не отправлялись.")
        return

    log_rows = []
    for l in logs:
        log_rows.append({
            "Дата отправки": l.sent_at.strftime("%Y-%m-%d %H:%M:%S"),
            "Кампания ID": l.campaign_id or "Удалена",
            "Чат ID": l.chat_id,
            "Текст сообщения": l.message_text,
            "Статус": l.send_status.upper(),
            "Ошибка API": l.error_message or "—",
        })

    st.dataframe(pd.DataFrame(log_rows), use_container_width=True, hide_index=True)
