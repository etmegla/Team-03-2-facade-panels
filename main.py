# ----------------------------------------------------
# RECEIVE MODEL → EXTRACT SLAB CURVES → RUN GH → SEND PANELS
# ----------------------------------------------------

import os
import rhino3dm
import compute_rhino3d.Grasshopper as gh
import compute_rhino3d.Util

from specklepy.api.client import SpeckleClient
from specklepy.api.credentials import get_default_account
from specklepy.transports.server import ServerTransport
from specklepy.api import operations
from specklepy.objects.base import Base
from specklepy.objects.geometry import Polyline, Line, Curve, Mesh

# ----------------------------------------------------
# CONFIG
# ----------------------------------------------------

SPECKLE_HOST = "https://app.speckle.systems"

RECEIVE_MODEL = "a15cb4bb48"
SLAB_STREAM_ID = "46b9ec633c"
FACADE_STREAM_ID = "628a79de4a"

GH_FILE = r"C:\Users\etmaglari\IAAC\Team-03-2-facade-panels\test_minimal.gh"

compute_rhino3d.Util.url = "http://localhost:5000/"

# ----------------------------------------------------
# CONNECT TO SPECKLE
# ----------------------------------------------------
print("Connecting to Speckle")

client = SpeckleClient(host=SPECKLE_HOST)

account = get_default_account()

client.authenticate_with_account(account)

transport = ServerTransport(
    client=client,
    stream_id=RECEIVE_MODEL
)
# ----------------------------------------------------
# RECEIVE MODEL
# ----------------------------------------------------

print("Receiving latest model")

# get the main branch (include the most recent commit)
branch = client.branches.get(RECEIVE_MODEL, "main", limit=1)

# newest commit
commit = branch.commits.items[0]

# receive the model object
model = operations.receive(commit.referencedObject, transport)

# ----------------------------------------------------
# EXTRACT CURVES
# ----------------------------------------------------

print("Extracting slab curves")

slab_curves = []


def find_curves(obj):

    if isinstance(obj, (Polyline, Line, Curve)):
        slab_curves.append(obj)

    if hasattr(obj, "__dict__"):

        for v in obj.__dict__.values():

            if isinstance(v, list):
                for i in v:
                    find_curves(i)

            else:
                find_curves(v)


find_curves(model)

print("Curves found:", len(slab_curves))

# ----------------------------------------------------
# SEND CURVES TO SLAB MODEL
# ----------------------------------------------------

print("Sending slab curves to slab model")

slab_transport = ServerTransport(client=client, stream_id=SLAB_STREAM_ID)

curve_container = Base()
curve_container["curves"] = slab_curves

obj_id = operations.send(curve_container, [slab_transport])

client.commits.create(
    stream_id=SLAB_STREAM_ID,
    object_id=obj_id,
    branch_name="main",
    message="Extracted slab curves",
)

# ----------------------------------------------------
# CONVERT TO RHINO CURVES
# ----------------------------------------------------

print("Converting curves to Rhino")

rhino_curves = []

for c in slab_curves:

    try:

        if isinstance(c, Line):

            start = rhino3dm.Point3d(c.start.x, c.start.y, c.start.z)
            end = rhino3dm.Point3d(c.end.x, c.end.y, c.end.z)

            rhino_curves.append(rhino3dm.LineCurve(start, end))

        elif isinstance(c, Polyline):

            pts = [rhino3dm.Point3d(p.x, p.y, p.z) for p in c.as_points()]

            rhino_curves.append(rhino3dm.PolylineCurve(pts))

    except:
        pass

print("Rhino curves:", len(rhino_curves))

# ----------------------------------------------------
# RUN GRASSHOPPER
# ----------------------------------------------------

print("Running Grasshopper")

tree = gh.DataTree("curves")
tree.Append([0], rhino_curves)

output = gh.EvaluateDefinition(GH_FILE, [tree])

# ----------------------------------------------------
# EXTRACT MESHES
# ----------------------------------------------------

print("Extracting meshes")

meshes = []

for value in output["values"]:

    for branch in value["InnerTree"].values():

        for item in branch:

            data = item["data"]

            mesh = Mesh()

            mesh.vertices = data["vertices"]
            mesh.faces = data["faces"]

            meshes.append(mesh)

print("Meshes generated:", len(meshes))

# ----------------------------------------------------
# SEND PANELS TO FACADE MODEL
# ----------------------------------------------------

print("Sending panels to facade model")

facade_transport = ServerTransport(client=client, stream_id=FACADE_STREAM_ID)

panel_container = Base()
panel_container["panels"] = meshes

obj_id = operations.send(panel_container, [facade_transport])

client.commits.create(
    stream_id=FACADE_STREAM_ID,
    object_id=obj_id,
    branch_name="main",
    message="Generated facade panels",
)

print("Pipeline complete")