#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.clients.ozon_chats_client import CHAT_HISTORY_ENDPOINT, CHAT_ID_CANDIDATES, OzonChatsClient, extract_first_value


def _mask_chat_id(value: str) -> str:
    return f"<chat_id:{sha256(value.encode('utf-8')).hexdigest()[:10]}>"


def _sanitize_probe_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in {"chat_id", "chatid"}:
                sanitized[str(key)] = _mask_chat_id(str(item)) if item not in (None, "") else item
            elif lowered in {"last_message_id", "lastmessageid", "from_message_id", "frommessageid", "first_unread_message_id", "firstunreadmessageid"}:
                sanitized[str(key)] = "<message_id>" if item not in (None, "") else item
            else:
                sanitized[str(key)] = _sanitize_probe_payload(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_probe_payload(item) for item in value]
    return value


def main() -> int:
    client = OzonChatsClient()
    chat_list_summary = client.list_all_chats(max_pages=1, sleep_seconds=0)
    chat_list_result = chat_list_summary.get("result", {})
    rows = [item for item in chat_list_summary.get("items", []) if isinstance(item, dict)]

    print(f"chat_list_status: {chat_list_result.get('status_code')}")
    print(f"fetched_pages: {chat_list_summary.get('fetched_pages')}")
    print(f"unique_chats: {chat_list_summary.get('unique_chats')}")
    if not rows:
        print("history_probe_status: skipped_no_chat_id")
        return 0

    sample_row = rows[0]
    chat_id = extract_first_value(sample_row, CHAT_ID_CANDIDATES)
    if chat_id in (None, ""):
        print("history_probe_status: skipped_missing_chat_id")
        return 0

    chat_id_text = str(chat_id)
    print(f"masked_chat_id: {_mask_chat_id(chat_id_text)}")
    print(f"history_endpoint: {CHAT_HISTORY_ENDPOINT}")

    variants = client._chat_history_payloads(chat_id_text, context=sample_row)
    confirmed = False
    for idx, payload in enumerate(variants, start=1):
        result = client._post_json(endpoint=CHAT_HISTORY_ENDPOINT, payload=payload, operation=f"chat_history_probe_{idx}")
        print(f"variant_{idx}_payload: {json.dumps(_sanitize_probe_payload(payload), ensure_ascii=False)}")
        print(f"variant_{idx}_status: {result.get('status_code')}")
        print(f"variant_{idx}_response_preview: {(result.get('response_text_preview') or '')[:300]}")
        if result.get('status_code') == 200:
            confirmed = True

    print(f"history_confirmed: {confirmed}")
    print(f"history_not_confirmed_reason: {'all variants returned non-200' if not confirmed else 'confirmed'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
