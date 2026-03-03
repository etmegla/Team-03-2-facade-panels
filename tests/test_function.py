"""Integration and unit tests for the facade panel automate function."""

import pytest

from speckle_automate import (
    AutomationContext,
    AutomationRunData,
    AutomationStatus,
    run_function,
)
from speckle_automate.fixtures import *  # noqa: F403

from main import FunctionInputs, automate_function


def test_function_run(
    test_automation_run_data: AutomationRunData,
    test_automation_token: str,
):
    """Integration test: run against a live Speckle server (requires env vars)."""
    automation_context = AutomationContext.initialize(
        test_automation_run_data, test_automation_token
    )
    automate_sdk = run_function(
        automation_context,
        automate_function,
        FunctionInputs(
            compute_url="https://compute8.iaac.net/",
            compute_api_key="test-api-key",
            grasshopper_definition_url="https://example.com/facade.gh",
            target_model_id="test-model-id",
        ),
    )

    assert automate_sdk.run_status in (
        AutomationStatus.SUCCEEDED,
        AutomationStatus.FAILED,
    )


def test_speckle_polyline_conversion():
    """A Speckle Polyline should convert to a Rhino JSON dict."""
    pytest.importorskip("rhino3dm")
    from main import _speckle_to_rhino_json
    from specklepy.objects import Base

    obj = Base()
    obj.speckle_type = "Objects.Geometry.Polyline"
    obj["value"] = [0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0]

    result = _speckle_to_rhino_json(obj)
    assert result is not None
    assert isinstance(result, dict)


def test_unknown_type_returns_none():
    """Non-curve objects should return None without raising."""
    pytest.importorskip("rhino3dm")
    from main import _speckle_to_rhino_json
    from specklepy.objects import Base

    obj = Base()
    obj.speckle_type = "Objects.BuiltElements.Wall"

    result = _speckle_to_rhino_json(obj)
    assert result is None


def test_parse_empty_gh_output():
    """Empty GH result should return an empty list."""
    from main import _parse_mesh_output

    result = _parse_mesh_output({"values": []}, "Mesh")
    assert result == []


def test_function_inputs_defaults():
    """FunctionInputs applies sensible defaults for optional fields."""
    inputs = FunctionInputs(
        compute_url="https://compute8.iaac.net/",
        compute_api_key="key",
        grasshopper_definition_url="https://example.com/file.gh",
        target_model_id="abc123",
    )

    assert inputs.gh_input_name == "Curves"
    assert inputs.gh_output_name == "Mesh"
    assert inputs.compute_url == "https://compute8.iaac.net/"