from __future__ import annotations

import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any

from src.config.settings import settings
from sqlalchemy import func, select
from src.db.session import session_scope
from src.db.communications_models import Campaign, ChatRegistry, CampaignRecipient, SendLog
from src.services.communications.campaign_service import CampaignService
from src.services.communications.audience_service import AudienceService
from src.services.communications.providers import OzonChatProvider, WBChatProvider
from src.utils.logger import get_logger


def render_communications_tab() -> None:
    st.header("Центр коммуникаций")
    
    # Информационный индикатор безопасности отправки
    is_real_send = settings.wb_comm_real_send_enabled
    if is_real_send:
        st.success("🟢 **Реальная отправка включена** (`WB_COMM_REAL_SEND_ENABLED=true`). Сообщения могут доставляться покупателям.")
    else:
        st.warning("🟡 **Режим симуляции по умолчанию** (`WB_COMM_REAL_SEND_ENABLED=false`). Все рассылки будут выполняться в режиме симуляции (Dry-run).")

    # Разделение по маркетплейсам
    st.info("Реальная отправка Ozon отключена (`OZON_COMM_REAL_SEND_ENABLED=false`). В техническом разделе доступны только safe read-only проверки и sync реестра.")
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
                render_history_subtab(session, marketplace="wb")

    with tab_ozon:
        ozon_sub_tab = st.radio(
            "Раздел Ozon:",
            options=["Диагностика Ozon", "Реестр Ozon-чатов", "История отправок Ozon"],
            horizontal=True,
            key="comm_ozon_sub_tab"
        )
        st.write("---")
        with session_scope() as session:
            if ozon_sub_tab == "Диагностика Ozon":
                render_ozon_diagnostics_subtab(session)
            elif ozon_sub_tab == "Реестр Ozon-чатов":
                render_ozon_registry_subtab(session)
            elif ozon_sub_tab == "История отправок Ozon":
                render_history_subtab(session, marketplace="ozon")


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
    df.attrs.clear()
    st.dataframe(df, width="stretch", hide_index=True)

    st.write("---")
    st.write("**Действия с кампаниями:**")
    
    # Выбор кампании для детального просмотра
    c_options = {c.id: f"ID {c.id} | {c.name} ({c.status})" for c in campaigns}
    selected_camp_id = st.selectbox("Выберите кампанию для открытия или дублирования:", options=list(c_options.keys()), format_func=lambda x: c_options[x])

    col_btn = st.columns(3)
    if col_btn[0].button("📂 Открыть кампанию", width="stretch"):
        st.session_state.comm_active_campaign_id = selected_camp_id
        st.rerun()
        
    if col_btn[1].button("👯 Продублировать", width="stretch"):
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
    
    if col_save[0].button("💾 Сохранить черновик", type="secondary", width="stretch"):
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

    if col_save[1].button("🔍 Собрать аудиторию", type="primary", width="stretch"):
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

    if col_save[3].button("↩️ Назад к списку", width="stretch"):
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
    df_rec.attrs.clear()
    
    # st.data_editor позволяет изменять чекбокс
    edited_df = st.data_editor(
        df_rec,
        width="stretch",
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
    if st.button("🚀 Отправить выбранным", type="primary", width="stretch"):
        st.session_state.comm_show_confirm = True

    if st.session_state.comm_show_confirm:
        st.warning("⚠️ **Подтвердите отправку сообщений!**")
        st.write(f"- **Кампания:** {campaign.name}")
        st.write(f"- **Текст сообщения:** {campaign.message_text}")
        st.write(f"- **Количество получателей:** {min(selected_count, batch_size)} чатов (из {selected_count} выбранных)")
        st.write(f"- **Режим:** {'СИМУЛЯЦИЯ' if (dry_run or not (settings.wb_comm_real_send_enabled and settings.wb_token)) else 'РЕАЛЬНАЯ ОТПРАВКА'}")
        
        col_conf = st.columns(2)
        if col_conf[0].button("Да, запустить рассылку!", type="primary", width="stretch"):
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

        if col_conf[1].button("Отмена", width="stretch"):
            st.session_state.comm_show_confirm = False
            st.rerun()


def _format_chat_dt(value: Optional[datetime]) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else "-"


def render_chats_registry_subtab(session) -> None:
    st.subheader("Реестр чатов Wildberries")
    st.write("Сводная информация по чатам, найденным через `/seller/events` и `/seller/chats`.")

    if st.button("🔄 Синхронизировать реестр из API", type="primary"):
        with st.spinner("Загрузка данных из Wildberries..."):
            try:
                provider = WBChatProvider()
                prepared_count = provider.build_chat_registry(session, max_event_pages=10)
                session.commit()

                total_count = session.scalar(select(func.count()).select_from(ChatRegistry))
                wb_count = session.scalar(
                    select(func.count()).select_from(ChatRegistry).where(ChatRegistry.marketplace == "wb")
                )
                marketplaces = list(session.scalars(select(ChatRegistry.marketplace).distinct()).all())
                min_act = session.scalar(
                    select(func.min(ChatRegistry.last_activity_at)).where(ChatRegistry.marketplace == "wb")
                )
                max_act = session.scalar(
                    select(func.max(ChatRegistry.last_activity_at)).where(ChatRegistry.marketplace == "wb")
                )

                get_logger("communications_ui").info(
                    "WB chat registry sync diagnostics: "
                    f"prepared={prepared_count}, committed=True, total={total_count}, wb={wb_count}, "
                    f"marketplaces={marketplaces}, min_last_activity_at={min_act}, max_last_activity_at={max_act}"
                )
                st.success(
                    f"Синхронизация WB завершена. Подготовлено/обновлено: {prepared_count}. Чатов WB в реестре: {wb_count}."
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Ошибка при sync WB-реестра: {exc}")

    stmt = select(ChatRegistry).where(ChatRegistry.marketplace == "wb").order_by(ChatRegistry.last_activity_at.desc())
    chats = list(session.scalars(stmt).all())
    if not chats:
        st.info("WB-реестр пока пуст. Выполните синхронизацию из API.")
        return

    chat_rows = [
        {
            "Chat ID": chat.chat_id,
            "Product IDs": ", ".join(map(str, chat.product_ids or [])),
            "Reply sign": chat.reply_sign or "-",
            "First activity": _format_chat_dt(chat.first_activity_at),
            "Last activity": _format_chat_dt(chat.last_activity_at),
            "Source": chat.source or "-",
        }
        for chat in chats
    ]
    df_chats = pd.DataFrame(chat_rows)
    df_chats.attrs.clear()
    st.dataframe(df_chats, width="stretch", hide_index=True)


def render_ozon_diagnostics_subtab(session) -> None:
    st.subheader("Диагностика Ozon")
    st.info("Раздел Ozon работает только в техническом read-only режиме.")
    st.caption("Chat API доступен: `POST /v3/chat/list` OK. History endpoint: not confirmed, `POST /v1/chat/history` returned 404. Реальная отправка Ozon отключена.")

    col_actions = st.columns(2)
    if col_actions[0].button("Проверить доступ Ozon Chat API", type="primary"):
        with st.spinner("Проверка Ozon Chat API..."):
            try:
                provider = OzonChatProvider()
                st.session_state["comm_ozon_api_diag"] = provider.client.probe_readonly_access()
                st.success("Диагностика Ozon Chat API обновлена.")
            except Exception as exc:
                st.error(f"Ошибка при проверке Ozon Chat API: {exc}")

    if col_actions[1].button("Синхронизировать реестр Ozon-чатов"):
        with st.spinner("Синхронизация Ozon read-only реестра..."):
            try:
                provider = OzonChatProvider()
                prepared_count = provider.build_chat_registry(session, max_event_pages=3)
                session.commit()

                total_count = session.scalar(select(func.count()).select_from(ChatRegistry))
                ozon_count = session.scalar(
                    select(func.count()).select_from(ChatRegistry).where(ChatRegistry.marketplace == "ozon")
                )
                marketplaces = list(session.scalars(select(ChatRegistry.marketplace).distinct()).all())
                min_act = session.scalar(
                    select(func.min(ChatRegistry.last_activity_at)).where(ChatRegistry.marketplace == "ozon")
                )
                max_act = session.scalar(
                    select(func.max(ChatRegistry.last_activity_at)).where(ChatRegistry.marketplace == "ozon")
                )

                sync_diag = dict(provider.last_sync_diagnostics)
                sync_diag.update(
                    {
                        "committed": True,
                        "ChatRegistry total count after commit": total_count,
                        "ChatRegistry count for marketplace='ozon'": ozon_count,
                        "distinct marketplace values": marketplaces,
                        "min last_activity_at": str(min_act) if min_act else None,
                        "max last_activity_at": str(max_act) if max_act else None,
                    }
                )
                st.session_state["comm_ozon_sync_diag"] = sync_diag

                get_logger("communications_ui").info(
                    "Ozon sync diagnostics: "
                    f"prepared={prepared_count}, committed=True, total={total_count}, ozon={ozon_count}, "
                    f"marketplaces={marketplaces}, min_last_activity_at={min_act}, max_last_activity_at={max_act}, "
                    f"known_good_status={sync_diag.get('known_good_status_code')}, "
                    f"chat_list_status={sync_diag.get('chat_list_status_code')}, "
                    f"history_status={sync_diag.get('history_status')}, "
                    f"history_confirmed={sync_diag.get('history_confirmed')}, "
                    f"skipped_history={sync_diag.get('skipped_history')}"
                )
                st.success(
                    f"Read-only sync завершён. Подготовлено/обновлено: {prepared_count}. Чатов Ozon в реестре: {ozon_count}."
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Ошибка при sync Ozon-реестра: {exc}")

    diag = st.session_state.get("comm_ozon_api_diag")
    if diag:
        known_good = diag.get("known_good", {})
        chat_list_summary = diag.get("chat_list", {})
        chat_list_result = chat_list_summary.get("result", {})
        history_results = diag.get("chat_history", [])
        first_history_result = history_results[0].get("result", {}) if history_results else {}

        status_rows = [
            {"metric": "Client ID найден", "value": "Да" if diag.get("credentials", {}).get("client_id_present") else "Нет"},
            {"metric": "API Key найден", "value": "Да" if diag.get("credentials", {}).get("api_key_present") else "Нет"},
            {"metric": "Known-good endpoint", "value": f"status {known_good.get('status_code')}"},
            {
                "metric": "Chat API доступен",
                "value": "POST /v3/chat/list OK" if chat_list_result.get("status_code") == 200 else f"status {chat_list_result.get('status_code')}",
            },
            {"metric": "Найдено чатов", "value": diag.get("chat_count", 0)},
            {
                "metric": "History endpoint",
                "value": "not confirmed, POST /v1/chat/history returned 404" if first_history_result.get("status_code") == 404 else (f"status {first_history_result.get('status_code')}" if history_results else "не вызывался"),
            },
        ]
        st.write("#### Статус credentials и API")
        st.dataframe(pd.DataFrame(status_rows), width="stretch", hide_index=True)
        if first_history_result.get("status_code") == 404:
            st.warning("History endpoint: not confirmed, `POST /v1/chat/history` returned 404. Sync из `POST /v3/chat/list` это не ломает.")

        probe_rows = [
            {
                "Operation": known_good.get("operation"),
                "Endpoint": known_good.get("endpoint"),
                "Status": known_good.get("status_code") or "ERR",
                "Items": known_good.get("item_count") if known_good.get("item_count") is not None else "-",
                "Payload": str(known_good.get("payload_sent")),
                "Error": known_good.get("error") or "-",
            }
        ]
        for attempt in chat_list_summary.get("attempts", []):
            probe_rows.append(
                {
                    "Operation": attempt.get("operation"),
                    "Endpoint": attempt.get("endpoint"),
                    "Status": attempt.get("status_code") or "ERR",
                    "Items": attempt.get("item_count") if attempt.get("item_count") is not None else "-",
                    "Payload": str(attempt.get("payload_sent")),
                    "Error": attempt.get("error") or "-",
                }
            )
        for history_summary in history_results:
            for attempt in history_summary.get("attempts", []):
                probe_rows.append(
                    {
                        "Operation": attempt.get("operation"),
                        "Endpoint": attempt.get("endpoint"),
                        "Status": attempt.get("status_code") or "ERR",
                        "Items": attempt.get("item_count") if attempt.get("item_count") is not None else "-",
                        "Payload": str(attempt.get("payload_sent")),
                        "Error": attempt.get("error") or "-",
                    }
                )
        st.write("#### Диагностика confirmed methods")
        st.dataframe(pd.DataFrame(probe_rows), width="stretch", hide_index=True)

    sync_diag = st.session_state.get("comm_ozon_sync_diag")
    if sync_diag:
        st.write("#### Диагностика последнего sync")
        sync_df = pd.DataFrame([{"metric": key, "value": value} for key, value in sync_diag.items()])
        st.dataframe(sync_df, width="stretch", hide_index=True)
        if sync_diag.get("history_status") == 404:
            st.warning("History endpoint: not confirmed, `POST /v1/chat/history` returned 404. Enrichment из этого endpoint пропущен.")

    ozon_registry_count = session.scalar(
        select(func.count()).select_from(ChatRegistry).where(ChatRegistry.marketplace == "ozon")
    )
    st.write("#### Текущий статус реестра")
    st.dataframe(
        pd.DataFrame(
            [
                {"metric": "Ozon registry records", "value": ozon_registry_count or 0},
                {"metric": "Реальная отправка Ozon", "value": "отключена"},
                {"metric": "Запрещённые методы", "value": "start/send/read/file не вызываются"},
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    st.warning("Реальная отправка Ozon отключена. Методы start/send/read/file не вызываются.")


def render_ozon_registry_subtab(session) -> None:
    st.subheader("Реестр Ozon-чатов")
    st.caption("Реестр строится из `POST /v3/chat/list`. History endpoint: not confirmed, `POST /v1/chat/history` returned 404, но sync не считается проваленным.")

    stmt = select(ChatRegistry).where(ChatRegistry.marketplace == "ozon").order_by(ChatRegistry.last_activity_at.desc())
    chats = list(session.scalars(stmt).all())
    if not chats:
        st.info("Ozon-реестр пока пуст. Сначала выполните проверку доступа Ozon Chat API, затем sync реестра.")
        st.warning("Реальная отправка Ozon отключена. Методы start/send/read/file не вызываются.")
        return

    chat_rows = [
        {
            "Chat ID": chat.chat_id,
            "Product IDs": ", ".join(map(str, chat.product_ids or [])),
            "Last sender": chat.last_sender or "-",
            "First activity": _format_chat_dt(chat.first_activity_at),
            "Last activity": _format_chat_dt(chat.last_activity_at),
            "Current chat exists": "Да" if chat.current_chat_exists else "Нет",
            "Source": chat.source or "-",
        }
        for chat in chats
    ]
    df_chats = pd.DataFrame(chat_rows)
    df_chats.attrs.clear()
    st.dataframe(df_chats, width="stretch", hide_index=True)
    st.warning("Реальная отправка Ozon отключена. Методы start/send/read/file не вызываются.")


def render_history_subtab(session, marketplace: str = "wb") -> None:
    title = "История отправок WB" if marketplace == "wb" else "История отправок Ozon"
    st.subheader(title)
    st.write(f"История отправок по маркетплейсу `{marketplace}`.")

    stmt = select(SendLog).where(SendLog.marketplace == marketplace).order_by(SendLog.sent_at.desc())
    logs = list(session.scalars(stmt).all())

    if not logs:
        st.info("Сообщения по этому маркетплейсу еще не отправлялись.")
        return

    log_rows = []
    for l in logs:
        log_rows.append({
            "Дата отправки": l.sent_at.strftime("%Y-%m-%d %H:%M:%S"),
            "Кампания ID": l.campaign_id or "Удалена",
            "Чат ID": l.chat_id,
            "Текст сообщения": l.message_text,
            "Статус": l.send_status.upper(),
            "Ошибка API": l.error_message or "-",
        })

    df_logs = pd.DataFrame(log_rows)
    df_logs.attrs.clear()
    st.dataframe(df_logs, width="stretch", hide_index=True)
