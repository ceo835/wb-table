from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class BacklogRow:
    block: str
    status: str
    reason: str
    next_step: str
    priority: str

    def as_dict(self) -> dict[str, str]:
        return {
            "block": self.block,
            "status": self.status,
            "reason": self.reason,
            "next_step": self.next_step,
            "priority": self.priority,
        }


_CANONICAL_BACKLOG_ROWS: tuple[BacklogRow, ...] = (
    BacklogRow(
        block="WB Content API / dim_product",
        status="PARTIAL",
        reason="live content cards response is empty for the current token/account; real rows were not invented",
        next_step="recheck catalog access or keep dim_product on confirmed content data only",
        priority="medium",
    ),
    BacklogRow(
        block="ВБро",
        status="MANUAL_EXTERNAL_SERVICE / MANUAL_UPLOAD",
        reason="operating profit is maintained manually in an external service and is not available via current project access",
        next_step="keep the user sheet blank for profit cells until the employee provides a manual upload/export flow",
        priority="high",
    ),
    BacklogRow(
        block="Локализация",
        status="PARTIAL",
        reason="region-sale remains partial; orders-geography is the target source for the missing geography fields",
        next_step="obtain a CSV/Excel sample or cabinet access for https://seller.wildberries.ru/remains-analytics/orders-geography",
        priority="medium",
    ),
    BacklogRow(
        block="РК стата",
        status="PARTIAL",
        reason="fullstats now returns live rows, but CPM and ROI remain unconfirmed and yesterday can be incomplete",
        next_step="for production runs, pull campaign statistics from D-2 or earlier and keep CPM/ROI blank until an explicit formula is approved",
        priority="high",
    ),
    BacklogRow(
        block="MPStat / Сравнение карточек",
        status="MPSTAT_401",
        reason="authentication still returns 401 on the smoke check",
        next_step="verify MPStat token, plan, and endpoint contract",
        priority="high",
    ),
    BacklogRow(
        block="Точка вх",
        status="CSV_ONLY / PRIVATE_ENDPOINT / NEEDS_EXPORT_SAMPLE",
        reason="customer profile data is expected from the seller cabinet, not from a confirmed public API",
        next_step="obtain a CSV/Excel sample or cabinet access for https://seller.wildberries.ru/platform-analytics/customer-profile",
        priority="medium",
    ),
    BacklogRow(
        block="Поисковые запросы",
        status="PARTIAL",
        reason="reference fields are enriched, but competitor percentiles and exact search-position sources remain unconfirmed",
        next_step="confirm the search percentile source before filling the remaining comparison fields",
        priority="medium",
    ),
    BacklogRow(
        block="Остатки",
        status="TECHNICAL / PARTIAL",
        reason="the sheet is a helper input, not an original standalone tab",
        next_step="keep it as a technical source for other MVP tabs",
        priority="low",
    ),
    BacklogRow(
        block="ИТОГО_FULL",
        status="LATER",
        reason="wide pivot still depends on unconfirmed and partial upstream blocks",
        next_step="keep the wide pivot deferred until the upstream blocks are complete",
        priority="low",
    ),
    BacklogRow(
        block="Настройки_артикулы",
        status="LATER",
        reason="managed nm_id scope still lives in code and needs a dedicated control tab",
        next_step="create a settings tab with nm_id, supplier_article, group_name, item_type, active, comment and item_type values normal/bundle/glue/multicard",
        priority="medium",
    ),
)


def build_backlog_rows() -> list[dict[str, str]]:
    return [row.as_dict() for row in _CANONICAL_BACKLOG_ROWS]


def iter_backlog_rows() -> Iterable[BacklogRow]:
    return iter(_CANONICAL_BACKLOG_ROWS)
