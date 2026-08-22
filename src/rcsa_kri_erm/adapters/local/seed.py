"""The offline seed: one fictional bank's control library, KRI feed and Aud3 themes.

Synthetic data only. ``demo-bank`` is the owning tenant of everything here (the same partition the
seeded personas resolve to), so a caller whose verified identity resolves to any other tenant is
refused by the read services. These fixtures back the ``local`` adapter family and the demo; they
are deliberately shaped so the deterministic engines produce a mix of GREEN / AMBER / RED and at
least one merge candidate, one breach and one reopen, which is what makes the arc worth watching.
"""

from __future__ import annotations

from datetime import date

from ...domain.erm_models import (
    BreachDirection,
    ControlEffectiveness,
    ControlRecord,
    KriDefinition,
    MetricPoint,
    Theme,
)

SEED_TENANT = "demo-bank"

#: Rgc7's control library for the demo bank. Two access-recertification controls are deliberately
#: near-duplicates so the de-dup engine proposes a merge; effectiveness varies so residual bands do.
SEED_CONTROLS: tuple[ControlRecord, ...] = (
    ControlRecord(
        control_id="CTL-ACCESS-01",
        title="Quarterly privileged access recertification",
        tenant=SEED_TENANT,
        effectiveness=ControlEffectiveness.EFFECTIVE,
        description="Privileged access is recertified every quarter by the resource owner.",
    ),
    ControlRecord(
        control_id="CTL-ACCESS-07",
        title="Privileged access recertified each quarter",
        tenant=SEED_TENANT,
        effectiveness=ControlEffectiveness.PARTIAL,
        description="Each quarter privileged access rights are recertified by the owner.",
    ),
    ControlRecord(
        control_id="CTL-CHG-04",
        title="Emergency change approval",
        tenant=SEED_TENANT,
        effectiveness=ControlEffectiveness.INEFFECTIVE,
        description="Emergency changes require post-hoc approval within one business day.",
    ),
    ControlRecord(
        control_id="CTL-DR-02",
        title="Disaster-recovery failover test",
        tenant=SEED_TENANT,
        effectiveness=ControlEffectiveness.PARTIAL,
        description="Annual failover test of the primary banking platform.",
    ),
)

#: Adopted KRI/KCI definitions for the demo bank. Only adopted definitions evaluate; the proposed
#: one below proves a proposal is inert until a human adopts it.
SEED_KRIS: tuple[KriDefinition, ...] = (
    KriDefinition(
        kri_id="KRI-LOGIN-FAIL",
        category="information-security",
        metric_key="failed_login_rate",
        direction=BreachDirection.UPPER,
        warning_threshold=2.0,
        breach_threshold=5.0,
        appetite_limit=5.0,
        adopted=True,
    ),
    KriDefinition(
        kri_id="KRI-CAP-RATIO",
        category="capital",
        metric_key="capital_ratio",
        direction=BreachDirection.LOWER,
        warning_threshold=12.0,
        breach_threshold=10.5,
        appetite_limit=10.5,
        adopted=True,
    ),
    KriDefinition(
        kri_id="KRI-OUTSOURCE-SLA",
        category="third-party-risk",
        metric_key="outsource_sla_breaches",
        direction=BreachDirection.UPPER,
        warning_threshold=1.0,
        breach_threshold=3.0,
        appetite_limit=3.0,
        adopted=False,  # proposed, not yet adopted: the engine must skip it
    ),
)

#: The metric feed. ``failed_login_rate`` climbs into a persistent breach; ``capital_ratio`` holds
#: comfortably; the un-adopted ``outsource_sla_breaches`` is present but must never be evaluated.
SEED_METRICS: tuple[MetricPoint, ...] = (
    MetricPoint("failed_login_rate", 1.5, date(2026, 5, 31)),
    MetricPoint("failed_login_rate", 4.0, date(2026, 6, 30)),
    MetricPoint("failed_login_rate", 6.0, date(2026, 7, 31)),
    MetricPoint("failed_login_rate", 7.5, date(2026, 8, 31)),
    MetricPoint("capital_ratio", 13.1, date(2026, 6, 30)),
    MetricPoint("capital_ratio", 12.8, date(2026, 7, 31)),
    MetricPoint("capital_ratio", 12.9, date(2026, 8, 31)),
    MetricPoint("outsource_sla_breaches", 9.0, date(2026, 8, 31)),
)

#: Aud3 themes for the demo bank (the frozen contract until Aud3 is built). A high-weight theme
#: names an access control so the trigger engine reopens that assessment.
SEED_THEMES: tuple[Theme, ...] = (
    Theme(
        theme_id="THM-ACCESS-DRIFT",
        label="Privileged access drift across business units",
        control_ids=("CTL-ACCESS-01", "CTL-ACCESS-07"),
        weight=4,
        member_issue_ids=("ISS-1001", "ISS-1044", "ISS-1090"),
    ),
    Theme(
        theme_id="THM-DR-GAPS",
        label="Disaster-recovery test coverage gaps",
        control_ids=("CTL-DR-02",),
        weight=2,
        member_issue_ids=("ISS-1200",),
    ),
)
