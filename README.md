# Speckle Automate function template - Python

This template repository is for a Speckle Automate function written in Python
using the [specklepy](https://pypi.org/project/specklepy/) SDK to interact with Speckle data.

This template contains the full scaffolding required to publish a function to the Automate environment.
It also has some sane defaults for development environment setups.

## Getting started

1. Use this template repository to create a new repository in your own / organization's profile.
1. Register the function

### Add new dependencies

To add new Python package dependencies to the project, edit the `pyproject.toml` file:

**For packages your function needs to run** (like pandas, requests, etc.):
```toml
dependencies = [
    "specklepy==3.0.0",
    "pandas==2.1.0",  # Add production dependencies here
]
```

**For development tools** (like testing or formatting tools):
```toml
[project.optional-dependencies]
dev = [
    "black==23.12.1",
    "pytest-mock==3.11.1",  # Add development dependencies here
    # ... other dev tools
]
```

**How to decide which section?**
- If your `main.py` (or other function logic) imports it → `dependencies`
- If it's just a tool to help you code → `[project.optional-dependencies].dev`

Example:
```python
# In your main.py
import pandas as pd  # ← This goes in dependencies
import specklepy     # ← This goes in dependencies

# You won't import these in main.py:
# pytest, black, mypy ← These go in [project.optional-dependencies].dev
```

### Change launch variables

Describe how the launch.json should be edited.

### GitHub Codespaces

Create a new repo from this template, and use the create new code.

### Using this Speckle Function

1. [Create](https://automate.speckle.dev/) a new Speckle Automation.
1. Select your Speckle Project and Speckle Model.
1. Select the deployed Speckle Function.
1. Enter a phrase to use in the comment.
1. Click `Create Automation`.

## Getting Started with Creating Your Own Speckle Function

1. [Register](https://automate.speckle.dev/) your Function with [Speckle Automate](https://automate.speckle.dev/) and select the Python template.
1. A new repository will be created in your GitHub account.
1. Make changes to your Function in `main.py`. See below for the Developer Requirements and instructions on how to test.
1. To create a new version of your Function, create a new [GitHub release](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository) in your repository.

## Developer Requirements

1. Install the following:
    - [Python 3.11+](https://www.python.org/downloads/)
1. Run the following to set up your development environment:
    ```bash
    python -m venv .venv
    # On Windows
    .venv\Scripts\activate
    # On macOS/Linux
    source .venv/bin/activate

    pip install --upgrade pip
    pip install .[dev]
    ```

**What this installs:**
- All the packages your function needs to run (`dependencies`)
- Plus development tools like testing and code formatting (`[project.optional-dependencies].dev`)

**Why separate sections?**
- `dependencies`: Only what gets deployed with your function (lightweight)
- `dev` dependencies: Extra tools to help you write better code locally

## Building and Testing

The code can be tested locally by running `pytest`.

### Alternative dependency managers

This template uses the modern **PEP 621** standard in `pyproject.toml`, which works with all modern Python dependency managers:

#### Using Poetry
```bash
poetry install  # Automatically reads pyproject.toml
```

#### Using uv
```bash
uv sync  # Automatically reads pyproject.toml
```

#### Using pip-tools
```bash
pip-compile pyproject.toml  # Generate requirements.txt from pyproject.toml
pip install -r requirements.txt
```

#### Using pdm
```bash
pdm install  # Automatically reads pyproject.toml
```

**Advantage**: All tools read the same `pyproject.toml` file, so there's no need to keep multiple files in sync!

### Building and running the Docker Container Image

Running and testing your code on your machine is a great way to develop your Function; the following instructions are a bit more in-depth and only required if you are having issues with your Function in GitHub Actions or on Speckle Automate.

#### Building the Docker Container Image

The GitHub Action packages your code into the format required by Speckle Automate. This is done by building a Docker Image, which Speckle Automate runs. You can attempt to build the Docker Image locally to test the building process.

To build the Docker Container Image, you must have [Docker](https://docs.docker.com/get-docker/) installed.

Once you have Docker running on your local machine:

1. Open a terminal
1. Navigate to the directory in which you cloned this repository
1. Run the following command:

    ```bash
    docker build -f ./Dockerfile -t speckle_automate_python_example .
    ```

#### Running the Docker Container Image

Once the GitHub Action has built the image, it is sent to Speckle Automate. When Speckle Automate runs your Function as part of an Automation, it will run the Docker Container Image. You can test that your Docker Container Image runs correctly locally.

1. To then run the Docker Container Image, run the following command:

    ```bash
    docker run --rm speckle_automate_python_example \
    python -u main.py run \
    '{"projectId": "1234", "modelId": "1234", "branchName": "myBranch", "versionId": "1234", "speckleServerUrl": "https://speckle.xyz", "automationId": "1234", "automationRevisionId": "1234", "automationRunId": "1234", "functionId": "1234", "functionName": "my function", "functionLogo": "base64EncodedPng"}' \
    '{}' \
    yourSpeckleServerAuthenticationToken
    ```

Let's explain this in more detail:

`docker run—-rm speckle_automate_python_example` tells Docker to run the Docker Container Image we built earlier. `speckle_automate_python_example` is the name of the Docker Container Image. The `--rm` flag tells Docker to remove the container after it has finished running, freeing up space on your machine.

The line `python -u main.py run` is the command run inside the Docker Container Image. The rest of the command is the arguments passed to the command. The arguments are:

- `'{"projectId": "1234", "modelId": "1234", "branchName": "myBranch", "versionId": "1234", "speckleServerUrl": "https://speckle.xyz", "automationId": "1234", "automationRevisionId": "1234", "automationRunId": "1234", "functionId": "1234", "functionName": "my function", "functionLogo": "base64EncodedPng"}'` - the metadata that describes the automation and the function.
- `{}` - the input parameters for the function the Automation creator can set. Here, they are blank, but you can add your parameters to test your function.
- `yourSpeckleServerAuthenticationToken`—the authentication token for the Speckle Server that the Automation can connect to. This is required to interact with the Speckle Server, for example, to get data from the Model.

## Resources

- [Learn](https://speckle.guide/dev/python.html) more about SpecklePy and interacting with Speckle from Python.

#ETM Notes

# Facade Panel Generator — Speckle Automate Function

A Speckle Automate function that:

1. **Receives** a model version (triggered automatically when a new version is published).
2. **Extracts** curve objects (Rhino/Grasshopper base curves for the facade panels).
3. **Sends** those curves to a **Rhino Compute** server, running your Grasshopper `.gh` definition.
4. **Publishes** the generated facade panel geometry as a new version in a target Speckle model.

---

## How it works

```
Speckle Model (trigger)
        │  curves
        ▼
[Speckle Automate]
        │  specklepy → rhino3dm JSON
        ▼
[Rhino Compute Server]  ←── your .gh file
        │  panel geometry (Brep / Mesh)
        ▼
[Speckle Automate]
        │  publish
        ▼
Speckle Model (output)
```

---

## Repository structure

```
facade-panel-function/
├── .github/workflows/main.yml    # Build & deploy pipeline
├── tests/
│   └── test_function.py          # Integration + unit tests
├── .env.example                  # Environment variable template
├── .gitignore
├── Dockerfile
├── flatten.py                    # Speckle object tree utility (from template)
├── main.py                       # ← YOUR FUNCTION (entry point)
├── pyproject.toml                # Dependencies
└── README.md
```

---

## Function Inputs (configured in the Speckle UI)

| Input | Description | Default |
|---|---|---|
| `compute_url` | Rhino Compute server URL | `http://localhost:5000/` |
| `compute_api_key` | API key for Rhino Compute (optional for localhost) | *(optional)* |
| `grasshopper_definition_url` | Public URL or local path to your `.gh` file | *(required)* |
| `curve_speckle_type` | `speckle_type` filter for input curves | `Objects.Geometry.Curve` |
| `gh_curve_input_name` | Grasshopper input parameter name | `Curves` |
| `gh_panel_output_name` | Grasshopper output parameter name | `Panels` |
| `panel_type` | Panel geometry type (`flat`, `folded`, `perforated`) | `flat` |
| `panel_depth` | Panel extrusion depth in metres | `0.2` |
| `target_model_id` | Speckle model to publish panels into | *(required)* |
| `output_version_message` | Commit message for the output version | *(optional)* |

---

## Grasshopper definition requirements

Your `.gh` file must expose:

- **Input**: a parameter named `Curves` (configurable) — accepts a list of curves.
- **Input**: a parameter named `PanelType` — string (`flat` / `folded` / `perforated`).
- **Input**: a parameter named `PanelDepth` — number (metres).
- **Output**: a parameter named `Panels` (configurable) — returns Brep or Mesh geometry.

The `.gh` file can be provided as a public URL (e.g. raw GitHub URL) or as a local path (e.g. `assets/test_minimal.gh`) for local development.

---

## Local development

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_ORG/facade-panel-function.git
cd facade-panel-function

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies (including dev tools)
pip install ".[dev]"

# 4. Copy and fill in env vars
cp .env.example .env
# edit .env with your Speckle token, project ID, automation ID

# 5. Run tests
pytest

# 6. One-command local run (minimal GH)
python -u main.py run "{\"project_id\":\"project id\",\"speckle_server_url\":\"https://latest.speckle.systems\",\"automation_id\":\"automation id\",\"automation_run_id\":\"automation run id\",\"function_run_id\":\"function run id\",\"triggers\":[{\"payload\":{\"modelId\":\"model id\",\"versionId\":\"version id\"},\"triggerType\":\"versionCreation\"}]}" "{\"compute_url\":\"http://localhost:5000/\",\"compute_api_key\":\"\",\"grasshopper_definition_url\":\"assets/test_minimal.gh\",\"gh_input_name\":\"Curves\",\"gh_output_name\":\"Mesh\",\"target_model_id\":\"YOUR_TARGET_MODEL_ID\",\"layer_name\":\"\",\"version_message\":\"Local minimal GH run\"}" "YOUR_SPECKLE_TOKEN"
```

---

## Deploying

1. Push your code to GitHub.
2. Create a **GitHub Release** (e.g. tag `v1.0.0`).
3. The GitHub Action builds the Docker image and registers the function with Speckle Automate.
4. In Speckle, create an **Automation** that links this function to your source model.

### Required GitHub secrets

| Secret | Where to find it |
|---|---|
| `SPECKLE_TOKEN` | Speckle → Profile → Access Tokens |
| `SPECKLE_SERVER_URL` | e.g. `https://app.speckle.systems/` |
| `SPECKLE_FUNCTION_ID` | Speckle → Functions → your function → ID |

---

## References

- [Speckle Automate docs](https://docs.speckle.systems/developers/automate/)
- [Rhino Compute docs](https://developer.rhino3d.com/guides/compute/)
- [compute-rhino3d Python SDK](https://github.com/mcneel/compute.rhino3d.appserver)
- [rhino3dm Python](https://github.com/mcneel/rhino3dm)