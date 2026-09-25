"""The service half of the model pills: which model ANSWERED, and whether it searched.

The console shows two pills at the top right: the model that answered the last request, and
``Search`` when that answer used an online search tool. Both come from response headers the kit
emits (``install_answer_provenance`` in ``api/app.py``) for whatever the generation adapters
NOTED as they called. Before a request is answered the pill shows ``generator_model`` from
``/healthz``, so that value must be the model the bound adapter calls.

The generation port narrates ERM notes for the agent tools; no HTTP route reaches it today, so
a triage response carries neither header and the route is proved to carry both by standing a
noting engine in for the real one. The adapters are proved to note their model directly.
Narration is drafting, so it samples FREE: no temperature is sent at all.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hex_service_kit import provenance

from rcsa_kri_erm import config
from rcsa_kri_erm.adapters.gcp.generation import CloudGenerationAdapter
from rcsa_kri_erm.adapters.local.generation import LocalGenerationAdapter
from rcsa_kri_erm.api import app as app_module
from rcsa_kri_erm.domain.erm_narration import build_request
from rcsa_kri_erm.domain.models import TriageInput, TriageResult
from rcsa_kri_erm.domain.triage_service import TriageService

from tests import REPO_ROOT
from tests.conftest import local_settings
from tests.fixtures import sample_cases

ANSWERED_BY = "x-answered-by"
SEARCH_USED = "x-search-used"


@pytest.fixture(autouse=True)
def _local_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """CI targets run with no profile exported; this suite states the one it proves."""
    monkeypatch.setenv("ERM_PROFILE", "local")


def _triage(api_client: TestClient) -> dict[str, str]:
    case = sample_cases.ROUTINE_CASE
    response = api_client.post(
        "/v1/triage",
        json={"subject": case.subject, "text": case.text},
        headers={"X-Dev-Persona": "auditor"},
    )
    assert response.status_code == 200, response.text
    return dict(response.headers)


def test_a_deterministic_answer_names_no_model(api_client: TestClient) -> None:
    """Nothing noted, nothing sent: the pill never invents a model the engine did not call."""
    headers = _triage(api_client)
    assert ANSWERED_BY not in headers
    assert SEARCH_USED not in headers


class _AnsweringService(TriageService):
    """The real engine, plus what a model adapter that searched would note while it called."""

    def triage(self, case: TriageInput, *, actor: str) -> TriageResult:
        provenance.note_model("fake-answering-model")
        provenance.note_search()
        return super().triage(case, actor=actor)


def test_the_route_names_the_model_that_answered_and_that_it_searched(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "TriageService", _AnsweringService)
    headers = _triage(api_client)
    assert headers[ANSWERED_BY] == "fake-answering-model"
    assert headers[SEARCH_USED] == "true"
    # The next request is a fresh record: an answer never leaks into a later response.
    monkeypatch.setattr(app_module, "TriageService", TriageService)
    assert ANSWERED_BY not in _triage(api_client)


def _note_request() -> Any:
    return build_request("KRI breach", (("residual_score", "15"),), "Summarise the breach.")


def test_the_local_stub_notes_the_name_generator_model_reports() -> None:
    settings = local_settings()
    with provenance.scope() as record:
        response = LocalGenerationAdapter(settings).generate(_note_request())
    assert record.models == [settings.generator_model] == [config.OFFLINE_STUB_MODEL]
    assert response.model == config.OFFLINE_STUB_MODEL
    assert record.search_used is False


def test_narration_is_drafting_and_sends_no_temperature() -> None:
    assert _note_request().temperature is None


class _FakeModels:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(text='{"note": "drafted"}')


def _fake_genai(monkeypatch: pytest.MonkeyPatch) -> _FakeModels:
    models = _FakeModels()
    genai = types.ModuleType("google.genai")
    genai_types = types.ModuleType("google.genai.types")
    genai_types.GenerateContentConfig = lambda **kw: SimpleNamespace(**kw)  # type: ignore[attr-defined]
    genai.types = genai_types  # type: ignore[attr-defined]
    genai.Client = lambda **_: SimpleNamespace(models=models)  # type: ignore[attr-defined]
    google = sys.modules.get("google") or types.ModuleType("google")
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setattr(google, "genai", genai, raising=False)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", genai_types)
    return models


def test_the_managed_adapter_notes_the_model_generator_model_names_and_sends_no_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = _fake_genai(monkeypatch)
    settings = local_settings(profile="gcp")
    with provenance.scope() as record:
        CloudGenerationAdapter(settings).generate(_note_request())
    (call,) = models.calls
    assert record.models == [call["model"]] == [settings.generator_model]
    assert record.search_used is False
    assert not hasattr(call["config"], "temperature"), "drafting sends no temperature"


def test_a_pinned_request_reaches_the_managed_config(monkeypatch: pytest.MonkeyPatch) -> None:
    import dataclasses

    models = _fake_genai(monkeypatch)
    pinned = dataclasses.replace(_note_request(), temperature=0.0)
    CloudGenerationAdapter(local_settings(profile="gcp")).generate(pinned)
    assert models.calls[0]["config"].temperature == 0.0


def test_the_hard_reasoning_flag_does_not_exist() -> None:
    settings_file = (REPO_ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    assert "use_hard_reasoning" not in settings_file
    for source in sorted((REPO_ROOT / "src").rglob("*.py")):
        assert "use_hard_reasoning" not in source.read_text(encoding="utf-8"), source
