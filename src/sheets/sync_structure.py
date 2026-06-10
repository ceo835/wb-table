from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Sequence

from .schema_definitions import USER_SHEET_SCHEMAS


@dataclass(frozen=True)
class SheetAction:
    sheet_name: str
    action: str
    details: str
    headers: tuple[str, ...] = ()


@dataclass(frozen=True)
class SyncPlan:
    actions: tuple[SheetAction, ...] = field(default_factory=tuple)


def build_sync_plan(existing_sheet_headers: Mapping[str, Sequence[str]]) -> SyncPlan:
    actions: List[SheetAction] = []
    normalized_existing = {name: tuple(headers) for name, headers in existing_sheet_headers.items()}

    for sheet_name, schema in USER_SHEET_SCHEMAS.items():
        expected_headers = schema.columns
        current_headers = normalized_existing.get(sheet_name)
        if current_headers is None:
            actions.append(
                SheetAction(
                    sheet_name=sheet_name,
                    action="create_sheet",
                    details="Sheet is missing and must be created.",
                )
            )
            actions.append(
                SheetAction(
                    sheet_name=sheet_name,
                    action="update_headers",
                    details="Write canonical header row only.",
                    headers=expected_headers,
                )
            )
            continue

        if current_headers != expected_headers:
            actions.append(
                SheetAction(
                    sheet_name=sheet_name,
                    action="update_headers",
                    details="Header row differs from canonical schema.",
                    headers=expected_headers,
                )
            )

    return SyncPlan(actions=tuple(actions))


def existing_project_sheet_names() -> List[str]:
    return [
        "README",
        "API Smoke Test",
        "Coverage",
        "Raw Samples Summary",
        "dim_product",
        "Воронка на день",
        "РасходРК",
        "РК стата",
        "Поисковые запросы",
        "Остатки",
        "Missing fields",
        "ИТОГО_v1",
        "Backlog",
    ]


def existing_project_sheet_headers() -> Dict[str, List[str]]:
    return {
        "README": [],
        "Coverage": [],
        "Backlog": [],
        "Validation_v1": [],
        "ИТОГО": [],
        "ИТОГО_FULL": [],
        "ИТОГО_v1": [],
        "Воронка на день": [],
        "РасходРК": [],
        "РК стата": [],
        "ВБро": [],
        "Точка вх": [],
        "Локализация": [],
        "Сравнение карточек": [],
        "Поисковые запросы": [],
        "Остатки": [],
    }


def apply_sync_plan(client, spreadsheet_id: str, plan: SyncPlan) -> List[SheetAction]:
    applied: List[SheetAction] = []
    for action in plan.actions:
        if action.action == "create_sheet":
            result = client.ensure_worksheet(spreadsheet_id, action.sheet_name)
        elif action.action == "update_headers":
            client.ensure_worksheet(spreadsheet_id, action.sheet_name)
            result = client.update_header_row(spreadsheet_id, action.sheet_name, list(action.headers))
        else:
            raise ValueError(f"Unsupported action: {action.action}")

        if result:
            applied.append(action)

    return applied
