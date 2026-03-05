"""Facade panel generation via Rhino Compute + Speckle Automate."""

import json
import os
import sys

import compute_rhino3d.Grasshopper as gh
import compute_rhino3d.Util
import requests
import rhino3dm
from dotenv import load_dotenv
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
# Load environment variables from .env
# ----------------------------------------------------
load_dotenv()

COMPUTE_URL     = os.getenv("COMPUTE_URL", "").rstrip("/")
COMPUTE_API_KEY = os.getenv("COMPUTE_API_KEY", "")
SPECKLE_TOKEN   = os.getenv("SPECKLE_TOKEN", "")
SPECKLE_SERVER  = os.getenv("SPECKLE_SERVER_URL", "https://app.speckle.systems")

compute_rhino3d.Util.url    = COMPUTE_URL + "/"
compute_rhino3d.Util.apiKey = COMPUTE_API_KEY


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


def resolve_latest_version(project_id: str, model_id: str) -> str:
    """Fetch the latest version ID for a model — used for local testing only."""
    client = SpeckleClient(host=SPECKLE_SERVER)
    client.authenticate_with_token(SPECKLE_TOKEN)
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

    client     = automate_context.speckle_client
    project_id = automate_context.automation_run_data.project_id

    # STEP 1: Verify Rhino Compute is reachable
    print(f"Checking Rhino Compute at {COMPUTE_URL}...")
    try:
        r = requests.get(
            f"{COMPUTE_URL}/version",
            headers={"RhinoComputeKey": COMPUTE_API_KEY},
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

    # STEP 3: Extract curves
    print("Extracting curves from received model...")
    slab_curves = [
        obj
        for obj in flatten_base(version_root_object)
        if isinstance(obj, (Line, Polyline, Curve))
    ]
    print(f"  Curves found: {len(slab_curves)}")

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
                pts = [rhino3dm.Point3d(p.x, p.y, p.z) for p in c.as_points()]
                rhino_curve = rhino3dm.PolylineCurve(pts)
            else:
                pts = [rhino3dm.Point3d(p.x, p.y, p.z) for p in c.points]
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
    print(f"Running Grasshopper: {function_inputs.gh_file_path}")
    try:
        curve_tree = gh.DataTree("curves")
        curve_tree.Append([0], encoded_curves)
        output = gh.EvaluateDefinition(function_inputs.gh_file_path, [curve_tree])
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
# Local runner — the runner expects exactly:
#   sys.argv = ['main.py', 'run', '<path_to_inputs.json>']
# We build that here, patching token + resolving latest version
# ----------------------------------------------------
if __name__ == "__main__":
    # Accept either:
    #   python main.py example.function_inputs.json   (our shorthand)
    #   python main.py run example.function_inputs.json  (explicit)
    args = sys.argv[1:]

    if len(args) == 1 and args[0] != "run":
        inputs_path = args[0]
    elif len(args) == 2 and args[0] == "run":
        inputs_path = args[1]
    else:
        print("Usage: python main.py example.function_inputs.json")
        sys.exit(1)

    with open(inputs_path, "r") as f:
        raw = json.load(f)

    # Patch token from .env
    if SPECKLE_TOKEN:
        raw["speckleToken"] = SPECKLE_TOKEN

    # Resolve "latest" versionId automatically
    project_id = raw["automationRunData"]["project_id"]
    for trigger in raw["automationRunData"].get("triggers", []):
        payload = trigger.get("payload", {})
        model_id   = payload.get("modelId", "")
        version_id = payload.get("versionId", "")
        if version_id == "latest" and model_id and model_id != "YOUR_MODEL_ID":
            print(f"Resolving latest version for model {model_id}...")
            payload["versionId"] = resolve_latest_version(project_id, model_id)

    # Write patched file and set argv so the runner sees: ['run', '<patched_path>']
    patched_path = inputs_path + ".patched.json"
    with open(patched_path, "w") as f:
        json.dump(raw, f)

    sys.argv = [sys.argv[0], "run", patched_path]

    execute_automate_function(automate_function, FunctionInputs)