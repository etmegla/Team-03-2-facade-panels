"""Extract Floor Plate Curves from the trigger model and publish to the slab curves model."""

import logging

from pydantic import Field
from speckle_automate import (
    AutomateBase,
    AutomationContext,
    execute_automate_function,
)
from specklepy.objects import Base

from flatten import flatten_base

logger = logging.getLogger(__name__)

CURVE_TYPES = (
    "Objects.Geometry.Curve",
    "Objects.Geometry.Polyline",
    "Objects.Geometry.Line",
    "Objects.Geometry.Arc",
    "Objects.Geometry.Circle",
    "Objects.Geometry.Ellipse",
    "Objects.Geometry.Polycurve",
)


class FunctionInputs(AutomateBase):
    """Inputs for the curve extraction function."""

    target_model_id: str = Field(
        title="Target Model ID",
        description=(
            "Speckle model ID to publish the extracted curves into. "
            "Find it in the URL: /projects/.../models/<model-id>"
        ),
    )
    layer_name: str = Field(
        default="Floor Plate Curve",
        title="Layer Name Filter",
        description=(
            "Only extract objects on this Rhino layer. "
            "Must match exactly as it appears in Rhino (case-sensitive). "
            "Leave empty to extract all curve types."
        ),
    )
    version_message: str = Field(
        default="Floor plate curves extracted by Automate",
        title="Version Message",
        description="Commit message for the new version in the target model.",
    )


def _matches_layer(obj: Base, layer_name: str) -> bool:
    """Check if a Speckle object belongs to the given Rhino layer.

    Speckle stores the Rhino layer in different places depending on
    the connector version — check all known locations.
    """
    if not layer_name:
        return True  # no filter — accept everything

    # Most common: top-level 'layer' property
    if getattr(obj, "layer", None) == layer_name:
        return True

    # Nested under 'properties' (older connectors)
    props = getattr(obj, "properties", None)
    if props and getattr(props, "layer", None) == layer_name:
        return True

    # Sometimes stored as 'Layer' (capital L)
    if getattr(obj, "Layer", None) == layer_name:
        return True

    return False


def automate_function(
    automate_context: AutomationContext,
    function_inputs: FunctionInputs,
) -> None:
    """Extract floor plate curves from the trigger model and publish to target."""

    # 1. Receive the trigger model
    version_root = automate_context.receive_version()

    # 2. Flatten and filter by curve type + layer
    all_curves = [
        obj
        for obj in flatten_base(version_root)
        if any(
            getattr(obj, "speckle_type", "").startswith(ct)
            for ct in CURVE_TYPES
        )
    ]

    layer_filter = function_inputs.layer_name.strip()
    if layer_filter:
        curve_objects = [o for o in all_curves if _matches_layer(o, layer_filter)]
    else:
        curve_objects = all_curves

    logger.info(
        "Found %d total curves, %d on layer '%s'.",
        len(all_curves),
        len(curve_objects),
        layer_filter,
    )

    if not curve_objects:
        # Report which layers ARE present to help debug
        layers_found = {
            getattr(o, "layer", None) or getattr(o, "Layer", None)
            for o in all_curves
        }
        automate_context.mark_run_failed(
            f"No curves found on layer '{layer_filter}'. "
            f"Total curves in model: {len(all_curves)}. "
            f"Layers present: {', '.join(str(l) for l in layers_found if l)}. "
            "Check the Layer Name Filter matches exactly."
        )
        return

    # 3. Publish to the target model
    root = Base()
    root["@elements"] = curve_objects
    root["curveCount"] = len(curve_objects)
    root["sourceLayer"] = layer_filter
    root["sourceModelId"] = (
        automate_context.automation_run_data.triggers[0].payload.model_id
    )

    automate_context.create_new_version_in_project(
        root_object=root,
        model_id=function_inputs.target_model_id,
        version_message=function_inputs.version_message,
    )

    automate_context.attach_success_to_objects(
        category="Curve Extraction",
        affected_objects=curve_objects,
        message=(
            f"Extracted {len(curve_objects)} curves from layer '{layer_filter}' "
            f"→ model '{function_inputs.target_model_id}'"
        ),
        metadata={"curveCount": len(curve_objects), "layer": layer_filter},
    )

    automate_context.mark_run_success(
        f"Extracted {len(curve_objects)} floor plate curves from layer "
        f"'{layer_filter}' and published to model '{function_inputs.target_model_id}'."
    )


if __name__ == "__main__":
    execute_automate_function(automate_function, FunctionInputs)
