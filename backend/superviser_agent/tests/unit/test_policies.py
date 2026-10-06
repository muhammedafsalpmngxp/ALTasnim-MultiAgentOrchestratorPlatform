"""backend/.env SUPERVISOR_MAX_* override the loop limits of config/policies.yaml."""

import pytest
from orchestrator_agent.settings import ENV_LIMITS, load_policies
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def _no_env_limits(monkeypatch):
    for env in ENV_LIMITS.values():
        monkeypatch.delenv(env, raising=False)


def test_without_env_the_yaml_values_apply():
    p = load_policies()
    assert (p.max_replans, p.max_plan_repairs, p.max_clarifications) == (2, 2, 2)


def test_env_overrides_each_limit(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_MAX_REPLANS", "4")
    monkeypatch.setenv("SUPERVISOR_MAX_PLAN_REPAIRS", "1")
    monkeypatch.setenv("SUPERVISOR_MAX_CLARIFICATIONS", "0")
    p = load_policies()
    assert (p.max_replans, p.max_plan_repairs, p.max_clarifications) == (4, 1, 0)
    assert p.max_steps == 10  # the rest still comes from the yaml


def test_an_empty_env_value_keeps_the_yaml(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_MAX_REPLANS", " ")
    assert load_policies().max_replans == 2


@pytest.mark.parametrize("value", ["two", "-1", "1.5"])
def test_a_typo_fails_at_startup(monkeypatch, value):
    monkeypatch.setenv("SUPERVISOR_MAX_REPLANS", value)
    with pytest.raises(ValueError, match="SUPERVISOR_MAX_REPLANS"):
        load_policies()


def test_out_of_range_fails(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_MAX_PLAN_REPAIRS", "99")
    with pytest.raises(ValidationError):
        load_policies()
