#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.clients.ozon_chats_client import OzonChatsClient


def main() -> int:
    client = OzonChatsClient()
    probe = client.probe_chat_list_only()
    summary = probe.get("probe_summary", {})

    print(f"method: {summary.get('method', 'POST')}")
    print(f"endpoint: {summary.get('endpoint', '/v3/chat/list')}")
    print(f"status_code: {summary.get('status_code')}")
    print(f"response_text_preview: {summary.get('response_text_preview', '')[:300]}")
    print(f"chat_count: {summary.get('chat_count', 0)}")
    print(f"fetched_pages: {summary.get('fetched_pages')}")
    print(f"unique_chats: {summary.get('unique_chats')}")
    print(f"stop_reason: {summary.get('stop_reason')}")
    print(f"credentials_present: {summary.get('credentials_present', False)}")
    print(f"masked_client_id: {summary.get('masked_client_id', '-')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
