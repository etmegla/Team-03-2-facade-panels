"""Facade panel generation via Rhino Compute + Speckle Automate."""

import json
import os
import sys

import compute_rhino3d.Grasshopper as gh
import compute_rhino3d.Util
import requests
import rhino3dm
from pydantic import Field, SecretStr
from speckle_automate import (
    AutomateBase,
    AutomationContext,
    execute_automate_function,
)
from specklepy.api import operations
from specklepy.api.client import SpeckleClient
from specklepy.core.api.inputs.model_inputs import CreateModelInput
from specklepy.core.api.inputs.version_inputs import CreateVersionInput
from specklepy.objects.base import Base
from specklepy.objects.geometry import Curve, Line, Mesh, Polyline
from specklepy.transports.server import ServerTransport

from flatten import flatten_base


# ----------------------------------------------------
# Function inputs (set in Speckle Automate UI)
# ----------------------------------------------------
class FunctionInputs(AutomateBase):
    """Inputs configured when creating the automation in Speckle."""

    gh_file_path: str = Field(
        title="Grasshopper File Path",
        description="Name or path of the .gh file on the Compute server, e.g. 'facade_panels.gh'",
    )
    slab_model_name: str = Field(
        title="Slab Curves Model Name",
        description="Model to send extracted slab curves to, e.g. 'slab/curves'",
    )
    facade_model_name: str = Field(
        title="Facade Panels Model Name",
        description="Model to send GH-generated facade panels to, e.g. 'facade/panels'",
    )
    whisper_message: SecretStr = Field(
        title="Whisper message",
        description="Unused — required by Speckle Automate template.",
    )


# ----------------------------------------------------
# Helpers
# ----------------------------------------------------

def _get_config():
    """Load config from environment — called at runtime, not at import."""
    from dotenv import load_dotenv
    load_dotenv()
    return {
        "compute_url":     os.getenv("COMPUTE_URL", "https://compute8.iaac.net").rstrip("/"),
        "compute_api_key": os.getenv("COMPUTE_API_KEY", "macad2026"),
        "speckle_token":   os.getenv("SPECKLE_TOKEN", ""),
        "speckle_server":  os.getenv("SPECKLE_SERVER_URL", "https://app.speckle.systems"),
    }


def get_or_create_model(client, project_id: str, model_name: str):
    """Return existing model by name, or create it if it doesn't exist."""
    models = client.model.get_models(project_id=project_id)
    model = next((m for m in models.items if m.name == model_name), None)
    if model is None:
        print(f"  Model '{model_name}' not found — creating it...")
        model = client.model.create(
            CreateModelInput(name=model_name, projectId=project_id)
        )
    return model


def send_to_model(client, project_id: str, model_name: str, obj: Base, message: str):
    """Send a Base object to a named model in the project."""
    model = get_or_create_model(client, project_id, model_name)
    transport = ServerTransport(client=client, stream_id=project_id)
    obj_id = operations.send(obj, [transport])
    client.version.create(
        CreateVersionInput(
            objectId=obj_id,
            modelId=model.id,
            projectId=project_id,
            message=message,
        )
    )
    print(f"  Sent to '{model_name}': {obj_id}")
    return obj_id


def resolve_latest_version(config: dict, project_id: str, model_id: str) -> str:
    """Fetch the latest version ID for a model — used for local testing only."""
    client = SpeckleClient(host=config["speckle_server"])
    client.authenticate_with_token(config["speckle_token"])
    versions = client.version.get_versions(
        model_id=model_id,
        project_id=project_id,
        limit=1,
    )
    latest = versions.items[0]
    print(f"  Resolved latest version: {latest.id} ({latest.message})")
    return latest.id


# ----------------------------------------------------
# Main automate function
# ----------------------------------------------------

def automate_function(
    automate_context: AutomationContext,
    function_inputs: FunctionInputs,
) -> None:
    """Full pipeline: receive → extract curves → GH → send panels."""

    config = _get_config()
    compute_url     = config["compute_url"]
    compute_api_key = config["compute_api_key"]

    compute_rhino3d.Util.url    = compute_url + "/"
    compute_rhino3d.Util.apiKey = compute_api_key

    client     = automate_context.speckle_client
    project_id = automate_context.automation_run_data.project_id

    # STEP 1: Verify Rhino Compute is reachable
    print(f"Checking Rhino Compute at {compute_url}...")
    try:
        r = requests.get(
            f"{compute_url}/version",
            headers={"RhinoComputeKey": compute_api_key},
            timeout=10,
        )
        r.raise_for_status()
        print(f"  Rhino Compute: {r.text}")
    except Exception as e:
        automate_context.mark_run_failed(f"Cannot reach Rhino Compute: {e}")
        return

    # STEP 2: Receive the triggering version
    print("Receiving model version from Speckle...")
    version_root_object = automate_context.receive_version()

    # STEP 3: Extract curves from "Floor Plate Curve" layer only
    print("Extracting curves from received model...")

    TARGET_LAYER = "Floor Plate Curve"

    def collect_curves_from_layer(root, target_layer: str):
        """
        Walk the Speckle elements tree tracking the current layer name.
        Rhino connector structure:
          root
            └── elements[] → Layer  (.name = "Floor Plate Curve")
                  └── elements[] → Curve / Polyline / Line
        """
        matched = []
        all_layer_names = set()

        def _walk(obj, current_layer: str):
            if obj is None:
                return
            # Check if this object is a layer container (has a name but isn't geometry)
            obj_name = getattr(obj, "name", None)
            speckle_type = getattr(obj, "speckle_type", "") or ""
            is_geometry = isinstance(obj, (Line, Polyline, Curve))

            if obj_name and not is_geometry:
                current_layer = obj_name

            if current_layer:
                all_layer_names.add(current_layer)

            if is_geometry:
                if target_layer.lower() in current_layer.lower():
                    matched.append(obj)
                return

            # Walk elements / @elements children
            elements = getattr(obj, "elements", getattr(obj, "@elements", None))
            if elements:
                for child in elements:
                    _walk(child, current_layer)

        _walk(root, "")
        return matched, all_layer_names

    slab_curves, all_layer_names = collect_curves_from_layer(version_root_object, TARGET_LAYER)
    print(f"  All layer names found: {sorted(all_layer_names)}")
    print(f"  Floor Plate curves selected: {len(slab_curves)}")

    if not slab_curves:
        print(f"  WARNING: No curves matched layer '{TARGET_LAYER}'. Falling back to ALL curves.")
        slab_curves = [
            obj for obj in flatten_base(version_root_object)
            if isinstance(obj, (Line, Polyline, Curve))
        ]
        print(f"  Fallback total curves: {len(slab_curves)}")

    if not slab_curves:
        automate_context.mark_run_failed(
            "No curves found in the received model. "
            "Ensure the model contains Line, Polyline, or Curve objects."
        )
        return

    # STEP 4: Send curves to slab model
    print(f"Sending slab curves to '{function_inputs.slab_model_name}'...")
    slab_container = Base()
    slab_container["curves"] = slab_curves
    slab_container["@displayValue"] = slab_curves
    send_to_model(
        client, project_id,
        model_name=function_inputs.slab_model_name,
        obj=slab_container,
        message=f"Extracted {len(slab_curves)} slab curves",
    )

    # STEP 5: Encode curves for Rhino Compute
    print("Encoding curves for Rhino Compute...")
    encoded_curves = []
    for c in slab_curves:
        try:
            if isinstance(c, Line):
                start = rhino3dm.Point3d(c.start.x, c.start.y, c.start.z)
                end   = rhino3dm.Point3d(c.end.x,   c.end.y,   c.end.z)
                rhino_curve = rhino3dm.LineCurve(start, end)
            elif isinstance(c, Polyline):
                vals = c.value
                pts = [rhino3dm.Point3d(vals[i], vals[i+1], vals[i+2]) for i in range(0, len(vals), 3)]
                rhino_curve = rhino3dm.PolylineCurve(pts)
            else:
                vals = c.points
                pts = [rhino3dm.Point3d(vals[i], vals[i+1], vals[i+2]) for i in range(0, len(vals), 3)]
                rhino_curve = rhino3dm.PolylineCurve(pts)
            encoded_curves.append(json.dumps(rhino_curve.ToNurbsCurve().Encode()))
        except Exception as e:
            print(f"  Skipped curve ({type(c).__name__}): {e}")

    print(f"  Encoded: {len(encoded_curves)} curves")
    if not encoded_curves:
        automate_context.mark_run_failed(
            "Could not encode any curves for Rhino Compute."
        )
        return

    # STEP 6: Run Grasshopper
    gh_path = function_inputs.gh_file_path
    print(f"Running Grasshopper: {gh_path}")
    try:
        # If it's a URL, EvaluateDefinition uses it as a pointer (file must exist on Compute server)
        # If it's a local path, the file must exist inside the Docker container (committed to repo)
        if not gh_path.startswith("http"):
            if not os.path.isfile(gh_path):
                automate_context.mark_run_failed(
                    f"Grasshopper file not found: '{gh_path}'. "
                    "Either commit the .gh file to the repo at that path, "
                    "or provide a full URL (https://...) pointing to the file on Compute."
                )
                return
        curve_tree = gh.DataTree("curves")
        curve_tree.Append([0], encoded_curves)
        output = gh.EvaluateDefinition(gh_path, [curve_tree])
        if output is None:
            automate_context.mark_run_failed(
                "Rhino Compute returned an empty response. "
                "Check that the .gh file path/URL is correct and the file is valid."
            )
            return
    except Exception as e:
        automate_context.mark_run_failed(f"Grasshopper evaluation failed: {e}")
        return

    if output.get("errors"):
        print("  GH errors:", output["errors"])
    if output.get("warnings"):
        print("  GH warnings:", output["warnings"])

    # STEP 7: Decode meshes
    print("Decoding Grasshopper output...")
    speckle_meshes = []
    for value in output.get("values", []):
        for branch_key, branch_items in value["InnerTree"].items():
            for item in branch_items:
                try:
                    decoded = rhino3dm.CommonObject.Decode(json.loads(item["data"]))
                    if isinstance(decoded, rhino3dm.Mesh):
                        m = Mesh()
                        m.vertices = [
                            coord
                            for v in decoded.Vertices
                            for coord in (v.X, v.Y, v.Z)
                        ]
                        m.faces = list(decoded.Faces)
                        m.units = "m"
                        speckle_meshes.append(m)
                except Exception as e:
                    print(f"  Skipped item in branch {branch_key}: {e}")

    print(f"  Meshes decoded: {len(speckle_meshes)}")
    if not speckle_meshes:
        automate_context.mark_run_failed(
            "Grasshopper ran but returned no meshes. "
            "Check that your .gh file outputs Mesh geometry."
        )
        return

    # STEP 8: Send panels to facade model
    print(f"Sending facade panels to '{function_inputs.facade_model_name}'...")
    panel_container = Base()
    panel_container["panels"]        = speckle_meshes
    panel_container["@displayValue"] = speckle_meshes
    send_to_model(
        client, project_id,
        model_name=function_inputs.facade_model_name,
        obj=panel_container,
        message=f"Facade panels — {len(speckle_meshes)} meshes",
    )

    automate_context.mark_run_success(
        f"Pipeline complete: {len(slab_curves)} curves → "
        f"{len(speckle_meshes)} facade panel meshes sent to "
        f"'{function_inputs.facade_model_name}'"
    )


def automate_function_without_inputs(automate_context: AutomationContext) -> None:
    """Unused — placeholder required by Speckle Automate template."""
    pass


# ----------------------------------------------------
# Entry point
# On Speckle Automate servers: called as
#   python main.py run <inputs_file>
#   python main.py generate_schema <schema_file>
#
# Locally: called as
#   python main.py example.function_inputs.json
# ----------------------------------------------------
if __name__ == "__main__":
    args = sys.argv[1:]

    # Production / CI: pass straight through (run or generate_schema)
    if len(args) == 2 and args[0] in ("run", "generate_schema"):
        execute_automate_function(automate_function, FunctionInputs)

    # Local shorthand: python main.py example.function_inputs.json
    elif len(args) == 1 and args[0].endswith(".json"):
        config = _get_config()
        inputs_path = args[0]

        with open(inputs_path, "r") as f:
            raw = json.load(f)

        if config["speckle_token"]:
            raw["speckleToken"] = config["speckle_token"]

        project_id = raw["automationRunData"]["project_id"]
        for trigger in raw["automationRunData"].get("triggers", []):
            payload    = trigger.get("payload", {})
            model_id   = payload.get("modelId", "")
            version_id = payload.get("versionId", "")
            if version_id == "latest" and model_id and model_id != "YOUR_MODEL_ID":
                print(f"Resolving latest version for model {model_id}...")
                payload["versionId"] = resolve_latest_version(config, project_id, model_id)

        patched_path = inputs_path + ".patched.json"
        with open(patched_path, "w") as f:
            json.dump(raw, f)

        sys.argv = [sys.argv[0], "run", patched_path]
        execute_automate_function(automate_function, FunctionInputs)

    else:
        execute_automate_function(automate_function, FunctionInputs)
