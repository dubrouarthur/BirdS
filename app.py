"""Vercel entrypoint (FastAPI preset): `app` in a default location at the repository root.

Configuration comes from environment variables only (see docs/DEPLOY_VERCEL.md). With no BIRD_BASE_URL the
deployment serves the scripted demo. Locally, `python scripts/serve.py --from-env` runs this same code path.
"""

from birds.web.entry import create_app_from_env

app = create_app_from_env()
