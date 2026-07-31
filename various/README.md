# Posit Connect Flask sample

A small Flask application that Posit Connect can host as a Python API/application.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app run --debug
```

## Deploy to Posit Connect

Install and configure the Posit Connect CLI, then deploy this directory:

```bash
pip install rsconnect-python
rsconnect add --api-key <api-key> --server <connect-server-url>
rsconnect deploy flask --entrypoint app:app
```

The deployment records the dependencies from `requirements.txt`. For reproducible
deployments, pin the package versions after testing them in your environment.

## Create a release

In GitHub, open **Actions** → **Create release** → **Run workflow**, then provide
a Semantic Version such as `1.0.0`. The workflow validates the version, creates
the `v1.0.0` tag at the selected commit, and creates a GitHub Release with
automatically generated notes. It then generates a manual UI test plan and
attaches it to the release as `manual-ui-test-cases-v1.0.0.md`.

Before running the workflow, add `OPENAI_API_KEY` as a repository Actions secret.
The workflow accepts an OpenAI model ID and API base URL, so it can also call an
OpenAI-compatible provider with that provider's key stored in the same secret.
The release context includes changed commits, the release diff, and source-file
excerpts; do not use this workflow if sending that code to an external provider
is not permitted.

GitHub Models cannot be selected because GitHub retired the service on July 30,
2026.
