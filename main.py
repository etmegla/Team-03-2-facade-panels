"""Extract Floor Plate Curves from the trigger model and publish to the slab curves model."""

import logging
import sys
from collections.abc import Iterable

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
        default="3D-Model::Structure::Floor Plate Curve",
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

    normalized_filter = layer_name.strip()
    candidate_layers = _extract_layer_candidates(obj)

    return _match_layer_candidates(candidate_layers, normalized_filter)


def _extract_layer_candidates(obj: Base) -> set[str]:
    """Read all layer-like string values that may be attached to an object."""
    candidate_layers: set[str] = set()

    top_layer = getattr(obj, "layer", None)
    if isinstance(top_layer, str) and top_layer.strip():
        candidate_layers.add(top_layer.strip())

    cap_layer = getattr(obj, "Layer", None)
    if isinstance(cap_layer, str) and cap_layer.strip():
        candidate_layers.add(cap_layer.strip())

    props = getattr(obj, "properties", None)
    if props:
        prop_layer = getattr(props, "layer", None)
        if isinstance(prop_layer, str) and prop_layer.strip():
            candidate_layers.add(prop_layer.strip())

        prop_cap_layer = getattr(props, "Layer", None)
        if isinstance(prop_cap_layer, str) and prop_cap_layer.strip():
            candidate_layers.add(prop_cap_layer.strip())

    collection_type = getattr(obj, "collectionType", None)
    speckle_type = getattr(obj, "speckle_type", "")
    is_layer_collection = isinstance(collection_type, str) and (
        "layer" in collection_type.lower()
    )
    is_collection_type = isinstance(speckle_type, str) and speckle_type.endswith(
        ".Collection"
    )
    if is_layer_collection or is_collection_type:
        name = getattr(obj, "name", None)
        if isinstance(name, str) and name.strip():
            candidate_layers.add(name.strip())

    return candidate_layers


def _match_layer_candidates(candidate_layers: Iterable[str], layer_filter: str) -> bool:
    """Match a set of candidate layer labels against a requested layer filter."""
    normalized_filter = layer_filter.strip()
    filter_leaf = normalized_filter.split("::")[-1].strip()

    for candidate in candidate_layers:
        normalized_candidate = candidate.strip()
        if normalized_candidate == normalized_filter:
            return True

        # Accept when object stores a full layer path and filter is the last segment,
        # or vice versa.
        candidate_leaf = normalized_candidate.split("::")[-1].strip()
        if candidate_leaf == filter_leaf:
            return True

        if normalized_candidate.endswith(f"::{normalized_filter}"):
            return True

        if normalized_filter.endswith(f"::{normalized_candidate}"):
            return True

    return False


def _iter_base_with_inherited_layers(
    root: Base,
    inherited_layers: set[str] | None = None,
) -> Iterable[tuple[Base, set[str]]]:
    """Iterate object tree and carry layer labels from parent collections."""
    inherited = inherited_layers or set()
    node_layers = _extract_layer_candidates(root)
    effective_layers = inherited | node_layers

    yield root, effective_layers

    elements = getattr(root, "elements", getattr(root, "@elements", None))
    if elements is None:
        return

    for element in elements:
        yield from _iter_base_with_inherited_layers(element, effective_layers)


def automate_function(
    automate_context: AutomationContext,
    function_inputs: FunctionInputs,
) -> None:
    """Extract floor plate curves from the trigger model and publish to target."""

    # 1. Receive the trigger model
    version_root = automate_context.receive_version()

    # 2. Traverse tree and retain inherited layer context
    all_curves_with_layers = [
        (obj, effective_layers)
        for obj, effective_layers in _iter_base_with_inherited_layers(version_root)
        if any(
            getattr(obj, "speckle_type", "").startswith(ct)
            for ct in CURVE_TYPES
        )
    ]

    all_curves = [obj for obj, _ in all_curves_with_layers]

    layer_filter = function_inputs.layer_name.strip()
    if layer_filter:
        curve_objects = [
            obj
            for obj, effective_layers in all_curves_with_layers
            if _matches_layer(obj, layer_filter)
            or _match_layer_candidates(effective_layers, layer_filter)
        ]
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
        layers_found: set[str] = set()
        for _, effective_layers in all_curves_with_layers:
            layers_found.update(effective_layers)
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
    if len(sys.argv) < 2:
        print(
            "Run this function via Speckle Automate CLI arguments, not as a plain script.\n"
            "For local checks, use: pytest\n"
            "For container-style execution, use: python -u main.py run <automationRunDataJson> <functionInputsJson> <token>"
        )
        raise SystemExit(0)

    execute_automate_function(automate_function, FunctionInputs)
