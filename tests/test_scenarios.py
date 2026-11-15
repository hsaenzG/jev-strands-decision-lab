"""Corre el dataset etiquetado y verifica que no haya 'unsafe allows'."""

from __future__ import annotations

from pathlib import Path

import pytest

from decision_lab.evaluation import evaluate_scenarios, load_scenarios, run_scenario

_SCENARIOS = Path(__file__).resolve().parents[1] / "examples" / "scenarios.json"


def test_dataset_has_at_least_20_scenarios() -> None:
    assert len(load_scenarios(_SCENARIOS)) >= 20


@pytest.mark.parametrize("scenario", load_scenarios(_SCENARIOS), ids=lambda s: s["id"])
def test_each_scenario_matches_expected(scenario: dict[str, object]) -> None:
    outcome = run_scenario(scenario)
    assert outcome.actual == outcome.expected, (
        f"{outcome.scenario_id}: esperado={outcome.expected} "
        f"obtenido={outcome.actual} [{outcome.reason_code}]"
    )


def test_no_unsafe_allows_in_dataset() -> None:
    report = evaluate_scenarios(_SCENARIOS)
    assert report.unsafe_allows == [], (
        "hubo ejecuciones permitidas donde se esperaba review/deny: "
        f"{[o.scenario_id for o in report.unsafe_allows]}"
    )


def test_full_accuracy_on_dataset() -> None:
    report = evaluate_scenarios(_SCENARIOS)
    assert report.accuracy == 1.0
