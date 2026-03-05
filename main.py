"""Facade panel generation via Rhino Compute + Speckle Automate."""

import json

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
from specklepy.objects.base import Base
from specklepy.objects.geometry import Curve, Line, Mesh, Polyline
from specklepy.transports.server import ServerTransport

from flatten import flatten_base

# ----------------------------------------------------
# IAAC Rhino Compute server
# ----------------------------------------------------
COMPUTE_URL = "https://compute8.iaac.net"
API_KEY = "macad2026"

compute_rhino3d.Util.url = COMPUTE_URL + "/"
compute_rhino3d.Util.apiKey = API_KEY


class FunctionInputs(AutomateBase):
    """Inputs for the facade panel automation."""

    gh_file_path: str = Field(
        title="Grasshopper File Path",
        description="Path to the .gh file on the Compute server, e.g. 'facade_panels.gh'",
    )
    source_model_id: str = Field(
        title="Source Model ID",
        description="The Speckle model (branch) name to receive geometry from, e.g. 'main'",
    )
    output_model_id: str = Field(
        title="Output Model ID",
        description="The Speckle model (branch) name to send facade panels to, e.g. 'facade/output'",
    )
    whisper_message: SecretStr = Field(
        title="Whisper message (unused)",
        description="Required by template — not used in this function.",
    )


def automate_function(
    automate_context: AutomationContext,
    function_inputs: FunctionInputs,
) -> None:
    """Receive geometry → run Grasshopper on Rhino Compute → send panels back to Speckle."""

    # --------------------------------------------------
    # STEP 1: Verify Rhino Compute is reachable
    # --------------------------------------------------
    try:
        r = requests.get(
            f"{COMPUTE_URL}/version",
            headers={"RhinoComputeKey": API_KEY},
            timeout=10,
        )
        r.raise_for_status()
        print(f"Rhino Compute version: {r.text}")
    except Exception as e:
        automate_context.mark_run_failed(f"Cannot reach Rhino Compute: {e}")
        return

    # --------------------------------------------------
    # STEP 2: Receive the triggering version from Speckle
    # --------------------------------------------------
    print("Receiving version from Speckle...")
    version_root_object = automate_context.receive_version()

    # --------------------------------------------------
    # STEP 3: Extract curves from the received object tree
    # --------------------------------------------------
    print("Extracting curves...")
    slab_curves = [
        obj
        for obj in flatten_base(version_root_object)
        if isinstance(obj, (Line, Polyline, Curve))
    ]
    print(f"Curves found: {len(slab_curves)}")

    if not slab_curves:
        automate_context.mark_run_failed(
            "No curves found in the received model. "
            "Make sure the model contains Line, Polyline, or Curve objects."
        )
        return

    # --------------------------------------------------
    # STEP 4: Convert Speckle curves → Rhino → encoded JSON strings
    # Rhino Compute requires geometry as NurbsCurve JSON strings in DataTrees
    # --------------------------------------------------
    print("Converting curves to Rhino and encoding for Compute...")
    encoded_curves = []

    for c in slab_curves:
        try:
            if isinstance(c, Line):
                start = rhino3dm.Point3d(c.start.x, c.start.y, c.start.z)
                end = rhino3dm.Point3d(c.end.x, c.end.y, c.end.z)
                rhino_curve = rhino3dm.LineCurve(start, end)

            elif isinstance(c, Polyline):
                pts = [rhino3dm.Point3d(p.x, p.y, p.z) for p in c.as_points()]
                rhino_curve = rhino3dm.PolylineCurve(pts)

            else:
                # Generic Curve — attempt direct NurbsCurve encode
                pts = [rhino3dm.Point3d(p.x, p.y, p.z) for p in c.points]
                rhino_curve = rhino3dm.PolylineCurve(pts)

            encoded_curves.append(json.dumps(rhino_curve.ToNurbsCurve().Encode()))

        except Exception as e:
            print(f"  Skipped curve ({type(c).__name__}): {e}")

    print(f"Encoded curves ready for Compute: {len(encoded_curves)}")

    if not encoded_curves:
        automate_context.mark_run_failed(
            "Could not encode any curves for Rhino Compute. "
            "Check that the geometry types are supported (Line, Polyline)."
        )
        return

    # --------------------------------------------------
    # STEP 5: Run the Grasshopper definition on Rhino Compute
    # --------------------------------------------------
    print(f"Sending to Grasshopper: {function_inputs.gh_file_path}")

    try:
        curve_tree = gh.DataTree("curves")
        curve_tree.Append([0], encoded_curves)

        output = gh.EvaluateDefinition(function_inputs.gh_file_path, [curve_tree])

    except Exception as e:
        automate_context.mark_run_failed(f"Grasshopper evaluation failed: {e}")
        return

    if output.get("errors"):
        print("GH errors:", output["errors"])
    if output.get("warnings"):
        print("GH warnings:", output["warnings"])

    # --------------------------------------------------
    # STEP 6: Decode meshes from GH output
    # --------------------------------------------------
    print("Decoding mesh results from Grasshopper...")
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

    print(f"Meshes decoded: {len(speckle_meshes)}")

    if not speckle_meshes:
        automate_context.mark_run_failed(
            "Grasshopper ran but returned no meshes. "
            "Check that your .gh file outputs Mesh geometry."
        )
        return

    # --------------------------------------------------
    # STEP 7: Send panels back to Speckle
    # --------------------------------------------------
    print("Sending facade panels to Speckle...")

    client = automate_context.speckle_client
    project_id = automate_context.automation_run_data.project_id

    # Resolve output model — create it if it doesn't exist
    output_model_name = function_inputs.output_model_id
    existing_models = client.model.get_models(project_id=project_id)
    output_model = next(
        (m for m in existing_models.items if m.name == output_model_name), None
    )

    if output_model is None:
        print(f"Model '{output_model_name}' not found — creating it...")
        from specklepy.core.api.inputs.model_inputs import CreateModelInput
        output_model = client.model.create(
            CreateModelInput(name=output_model_name, projectId=project_id)
        )

    facade_transport = ServerTransport(client=client, stream_id=project_id)

    panel_container = Base()
    panel_container["panels"] = speckle_meshes
    panel_container["@displayValue"] = speckle_meshes  # makes them visible in viewer

    obj_id = operations.send(panel_container, [facade_transport])

    from specklepy.core.api.inputs.version_inputs import CreateVersionInput
    client.version.create(
        CreateVersionInput(
            objectId=obj_id,
            modelId=output_model.id,
            projectId=project_id,
            message=f"Facade panels — {len(speckle_meshes)} meshes generated",
        )
    )

    automate_context.mark_run_success(
        f"Pipeline complete: {len(slab_curves)} curves → "
        f"{len(speckle_meshes)} facade panel meshes sent to '{output_model_name}'"
    )


def automate_function_without_inputs(automate_context: AutomationContext) -> None:
    """Unused — placeholder required by template."""
    pass


if __name__ == "__main__":
    execute_automate_function(automate_function, FunctionInputs)
