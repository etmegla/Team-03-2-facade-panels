"""Local test runner — bypasses Speckle Automate runner entirely.

Run with:
    python test_local.py
"""

import os
from dotenv import load_dotenv
from unittest.mock import MagicMock

from specklepy.api.client import SpeckleClient
from specklepy.api import operations
from specklepy.transports.server import ServerTransport

from main import automate_function, FunctionInputs

# ----------------------------------------------------
# Load config
# ----------------------------------------------------
load_dotenv()

SPECKLE_TOKEN  = os.getenv("SPECKLE_TOKEN", "")
SPECKLE_SERVER = os.getenv("SPECKLE_SERVER_URL", "https://app.speckle.systems")
PROJECT_ID     = "5a95953cb8"
MODEL_ID       = "46b9ec633c"  # receive-team 03.2

# ----------------------------------------------------
# Set up real Speckle client
# ----------------------------------------------------
client = SpeckleClient(host=SPECKLE_SERVER)
client.authenticate_with_token(SPECKLE_TOKEN)

# Get latest version of the source model
versions = client.version.get_versions(
    model_id=MODEL_ID,
    project_id=PROJECT_ID,
    limit=1,
)
latest = versions.items[0]
print(f"Using version: {latest.id} — {latest.message}")

# ----------------------------------------------------
# Build a mock AutomationContext that behaves like the real one
# but doesn't need real automation run IDs
# ----------------------------------------------------
transport = ServerTransport(client=client, stream_id=PROJECT_ID)

# Receive the actual model object
print("Receiving model...")
root_obj = operations.receive(latest.referenced_object, transport)

# Mock the context
mock_context = MagicMock()
mock_context.speckle_client = client
mock_context.automation_run_data.project_id = PROJECT_ID
mock_context.receive_version.return_value = root_obj

# Capture success/failure messages
def on_success(msg):
    print(f"\n SUCCESS: {msg}")

def on_failed(msg):
    print(f"\n FAILED: {msg}")

mock_context.mark_run_success.side_effect = on_success
mock_context.mark_run_failed.side_effect = on_failed

# ----------------------------------------------------
# Build function inputs
# ----------------------------------------------------
inputs = FunctionInputs(
    gh_file_path="assets/test_minimal.gh",
    slab_model_name="slab curves",
    facade_model_name="facade panels",
    whisper_message="test",
)

# ----------------------------------------------------
# Run the pipeline
# ----------------------------------------------------
print("\n--- Starting pipeline ---\n")
automate_function(mock_context, inputs)

# Debug: print all object types in the model
all_objects = list(flatten_base(root_obj))
print(f"Total objects: {len(all_objects)}")
for obj in all_objects[:20]:
    print(f"  {obj.speckle_type} — {type(obj).__name__}")