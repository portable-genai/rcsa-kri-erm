"""A read outside the caller's tenant is REFUSED, never answered with an empty result (check C2).

Two shapes of the same defect, and the second is the one that makes the first dangerous.

1. **The agent tools defaulted the tenant to a real one.** ``propose_control_merges`` declared
   ``tenant: str = "demo-bank"`` and ``assess_rcsa_control`` did ``tenant or "demo-bank"``, while
   the API derives the tenant from the verified principal. The same operation reached through the
   agent surface therefore read and acted on the seeded bank's partition when the caller named
   none. A ``tenant`` PARAMETER is the accepted pattern on this surface (the runtime propagates
   the resolved identity into it); a SILENT DEFAULT to a partition that holds data is not.
2. **A cross-tenant read returned an empty tuple.** ``list_controls`` filtered the seed by tenant
   and ``themes`` returned ``()`` for anything but the owner, so a caller from an unrelated
   tenant got a SUCCESSFUL, empty answer that is indistinguishable from a legitimate "this tenant
   has no controls". The service then computed a verdict over nothing and reported it as a
   result: ``propose_control_merges`` answered "no merge candidates" and ``reopen_from_themes``
   answered "no theme names this control", which are findings, not refusals.

The empty tenant is refused for the same reason: no tenant named is no authority to read, and
substituting one is exactly the defect above.
"""

from __future__ import annotations

import inspect

import pytest
from fastapi.testclient import TestClient

from rcsa_kri_erm.adapters.local.control_library import LocalControlLibraryAdapter
from rcsa_kri_erm.adapters.local.seed import SEED_TENANT
from rcsa_kri_erm.adapters.local.theme_feed import LocalThemeFeedAdapter
from rcsa_kri_erm.agent import tools as agent_tools
from rcsa_kri_erm.config import Container, Settings
from rcsa_kri_erm.domain.erm_models import RcsaAssessment
from rcsa_kri_erm.domain.erm_service import ErmService
from rcsa_kri_erm.domain.errors import TenantAccessDeniedError

from tests.conftest import LOOPBACK_PEER, local_settings

#: A tenant this deployment holds nothing for. Obviously fictional, and deliberately NOT the
#: empty string: the empty case is its own test below.
OTHER_TENANT = "other-bank"


def _settings() -> Settings:
    return local_settings()


def _erm(container: Container) -> ErmService:
    return ErmService(
        audit=container.audit,
        review_router=container.review_router,
        generation=container.generation,
        control_library=container.control_library,
        embeddings=container.embeddings,
        metric_feed=container.metric_feed,
        theme_feed=container.theme_feed,
        tracer=container.tracer,
    )


# ---------------------------------------------------------------------------------- #
# 1. The agent tools refuse rather than defaulting
# ---------------------------------------------------------------------------------- #
#: Every tool that names a tenant. A tool added later without a tenant is caught by the
#: signature test below rather than slipping past this list.
_TENANT_TOOLS = ("triage_case", "assess_rcsa_control", "propose_control_merges")


@pytest.mark.parametrize("name", _TENANT_TOOLS)
def test_no_agent_tool_defaults_its_tenant(name: str) -> None:
    """A default here is a partition chosen by the tool rather than by the caller's identity."""
    parameter = inspect.signature(getattr(agent_tools, name)).parameters["tenant"]
    assert parameter.default is inspect.Parameter.empty, (
        f"{name} defaults tenant to {parameter.default!r}: an unattributed call would read and "
        "act on that partition"
    )


def test_the_tool_table_holds_no_tenant_default_anywhere() -> None:
    """The rule applies to every tool in the table, including ones added after this was written."""
    offenders = [
        f"{fn.__name__}(tenant={p.default!r})"
        for fn in agent_tools.TOOL_FUNCTIONS
        for n, p in inspect.signature(fn).parameters.items()
        if n == "tenant" and p.default is not inspect.Parameter.empty
    ]
    assert not offenders, "agent tools default their tenant: " + ", ".join(offenders)


@pytest.mark.parametrize("name", _TENANT_TOOLS)
def test_an_agent_tool_refuses_an_empty_tenant(name: str) -> None:
    """No tenant means no read, not the seeded bank's partition."""
    tool = getattr(agent_tools, name)
    arguments: dict[str, object] = {"tenant": "", "settings": _settings()}
    if name == "triage_case":
        arguments |= {"subject": "Zeta Ltd (FICTIONAL)", "text": "routine stationery note"}
    if name == "assess_rcsa_control":
        arguments |= {"control_id": "CTL-CHG-04", "impact": 5, "likelihood": 5}
    with pytest.raises(TenantAccessDeniedError):
        tool(**arguments)


# ---------------------------------------------------------------------------------- #
# 2. A cross-tenant read is a refusal the caller can see
# ---------------------------------------------------------------------------------- #
@pytest.mark.parametrize("tenant", [OTHER_TENANT, ""], ids=["another-tenant", "no-tenant"])
def test_the_control_library_refuses_a_read_it_cannot_serve(tenant: str) -> None:
    adapter = LocalControlLibraryAdapter(_settings())
    with pytest.raises(TenantAccessDeniedError):
        adapter.list_controls(tenant)
    with pytest.raises(TenantAccessDeniedError):
        adapter.get_control("CTL-CHG-04", tenant)


@pytest.mark.parametrize("tenant", [OTHER_TENANT, ""], ids=["another-tenant", "no-tenant"])
def test_the_theme_feed_refuses_a_read_it_cannot_serve(tenant: str) -> None:
    adapter = LocalThemeFeedAdapter(_settings())
    with pytest.raises(TenantAccessDeniedError):
        adapter.themes(tenant)


def test_the_owning_tenant_still_reads_its_own_partition() -> None:
    """The control case: a refusal that refuses everybody is not isolation, it is an outage."""
    assert LocalControlLibraryAdapter(_settings()).list_controls(SEED_TENANT)
    assert LocalControlLibraryAdapter(_settings()).get_control("CTL-CHG-04", SEED_TENANT)
    assert LocalThemeFeedAdapter(_settings()).themes(SEED_TENANT)


# ---------------------------------------------------------------------------------- #
# 3. The service reports the refusal rather than a verdict computed over nothing
# ---------------------------------------------------------------------------------- #
def test_a_cross_tenant_merge_sweep_refuses_instead_of_reporting_no_candidates(
    container: Container,
) -> None:
    with pytest.raises(TenantAccessDeniedError):
        _erm(container).propose_control_merges(OTHER_TENANT, actor="attacker@other.example")


def test_a_cross_tenant_reopen_sweep_refuses_instead_of_reporting_no_themes(
    container: Container,
) -> None:
    assessments = (RcsaAssessment(control_id="CTL-ACCESS-01", tenant=OTHER_TENANT),)
    with pytest.raises(TenantAccessDeniedError):
        _erm(container).reopen_from_themes(
            assessments, OTHER_TENANT, actor="attacker@other.example"
        )


# ---------------------------------------------------------------------------------- #
# 4. The API reports the refusal as a 403, not as a server fault
# ---------------------------------------------------------------------------------- #
def test_the_api_answers_a_tenant_refusal_with_403_and_not_500() -> None:
    """The refusal is raised inside a port, so the app object is where the status is decided.

    ``/v1/triage`` reaches no tenant-scoped port today, so this drives the handler through a
    route registered for the duration of the test: the alternative is an app-level guarantee
    nobody has executed, which is how the first ERM route would have shipped answering 500.
    """
    from rcsa_kri_erm.api.app import app

    path = "/__test__/tenant-refusal"

    @app.get(path)
    def _refuse() -> None:
        raise TenantAccessDeniedError("refusing a read for 'other-bank'")

    try:
        with TestClient(app, client=LOOPBACK_PEER, raise_server_exceptions=False) as client:
            response = client.get(path)
    finally:
        app.router.routes[:] = [
            route for route in app.router.routes if getattr(route, "path", None) != path
        ]

    assert response.status_code == 403, (
        f"a cross-tenant refusal answered {response.status_code}: a 500 reads as a bug to fix "
        "rather than a boundary holding, and it leaks a stack trace where a status belongs"
    )
    assert "other-bank" in response.json()["detail"]


# ---------------------------------------------------------------------------------- #
# 5. The request schema does not advertise a tenant or an actor
# ---------------------------------------------------------------------------------- #
def test_the_request_schema_offers_the_client_no_tenant_and_no_actor() -> None:
    """Ignoring a client-supplied field is not enough: the surface must stop offering it.

    A field the schema accepts and the handler drops reads, to anyone holding the OpenAPI
    document, like a field that works. Deleting it is the only version of "the client does not
    choose" that a caller can see.
    """
    from rcsa_kri_erm.api.schemas import TriageRequest

    fields = set(TriageRequest.model_fields)
    assert fields == {"subject", "text"}, f"the request schema grew a field: {sorted(fields)}"
