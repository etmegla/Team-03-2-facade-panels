"""Extract Floor Plate Curves from the trigger model and publish to the slab curves model."""

import logging

from pydantic import Field
from speckle_automate import (
    AutomateBase,
    AutomationContext,
    execute_automate_function,
)
from specklepy.objects import Base

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
            "Name of the layer collection to extract curves from. "
            "Use just the leaf name e.g. 'Floor Plate Curve', not the full path."
        ),
    )
    version_message: str = Field(
        default="Floor plate curves extracted by Automate",
        title="Version Message",
        description="Commit message for the new version in the target model.",
    )


def _get_children(obj: Base) -> list:
    """Get child objects from any of the known container attributes."""
    for attr in ("elements", "@elements", "objects", "@objects"):
        children = getattr(obj, attr, None)
        if children and isinstance(children, list):
            return children
    return []


def _find_layer_collection(obj: Base, target_name: str) -> Base | None:
    """Recursively find the collection object whose name matches target_name."""
    name = getattr(obj, "name", None)
    if name and target_name.lower() in name.lower():
        return obj

    for child in _get_children(obj):
        if isinstance(child, Base):
            result = _find_layer_collection(child, target_name)
            if result is not None:
                return result

    return None


def _extract_curves(obj: Base, collected: list) -> None:
    """Recursively extract all curve objects from a collection."""
    speckle_type = getattr(obj, "speckle_type", "")
    if any(speckle_type.startswith(ct) for ct in CURVE_TYPES):
        collected.append(obj)
        return

    for child in _get_children(obj):
        if isinstance(child, Base):
            _extract_curves(child, collected)


def automate_function(
    automate_context: AutomationContext,
    function_inputs: FunctionInputs,
) -> None:
    """Extract floor plate curves from the trigger model and publish to target."""

    # 1. Receive the trigger model
    version_root = automate_context.receive_version()

    # 2. Find the layer collection by name
    layer_filter = function_inputs.layer_name.strip()
    layer_collection = _find_layer_collection(version_root, layer_filter)

    if layer_collection is None:
        automate_context.mark_run_failed(
            f"Could not find a layer collection named '{layer_filter}' in the model. "
            "Check the Layer Name Filter matches the name shown in the Speckle viewer."
        )
        return

    logger.info("Found layer collection: %s", getattr(layer_collection, "name", "?"))

    # 3. Extract all curves from that collection
    curve_objects: list[Base] = []
    _extract_curves(layer_collection, curve_objects)

    logger.info("Extracted %d curves from layer '%s'.", len(curve_objects), layer_filter)

    if not curve_objects:
        automate_context.mark_run_failed(
            f"Layer '{layer_filter}' was found but contains no curve objects."
        )
        return

    # 4. Publish to the target model
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