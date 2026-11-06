# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import contextlib
import logging
import os
from collections.abc import AsyncIterator

import google.auth
import google.auth.exceptions
from a2a.server.tasks import InMemoryTaskStore
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner
from google.cloud import logging as google_cloud_logging
from google.genai import types

from app.app_utils import services
from app.app_utils.a2a import attach_a2a_routes
from app.app_utils.typing import Feedback
from app.tracker_api import router as tracker_router

load_dotenv()
try:
    _, project_id = google.auth.default()
    HAS_GCP_CREDENTIALS = True
except google.auth.exceptions.DefaultCredentialsError:
    # Without credentials, discovery (Gemini + Search) is unavailable but the
    # decision tracker, source rechecks and the offline demo still work.
    project_id = None
    HAS_GCP_CREDENTIALS = False

if HAS_GCP_CREDENTIALS:
    logger = google_cloud_logging.Client().logger(__name__)
else:
    _std_logger = logging.getLogger(__name__)

    class _StdLogger:
        def log_struct(self, info: dict, severity: str = "INFO") -> None:
            _std_logger.info("%s %s", severity, info)

    logger = _StdLogger()
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from app.agent import app as adk_app
    from app.agent import root_agent

    runner = Runner(
        app=adk_app,
        session_service=services.get_session_service(),
        artifact_service=services.get_artifact_service(),
        auto_create_session=True,
    )
    app.state.runner = runner
    app.state.agent_app_name = adk_app.name
    await attach_a2a_routes(
        app,
        agent=root_agent,
        runner=runner,
        task_store=InMemoryTaskStore(),
        rpc_path=f"/a2a/{adk_app.name}",
    )
    yield


app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=services.ARTIFACT_SERVICE_URI,
    allow_origins=allow_origins,
    session_service_uri=services.SESSION_SERVICE_URI,
    otel_to_cloud=HAS_GCP_CREDENTIALS,
    lifespan=lifespan,
)
app.title = "opportunity-hunter"
app.description = "API for interacting with the Agent opportunity-hunter"
app.include_router(tracker_router)


@app.get("/hunter", include_in_schema=False)
def hunter_ui() -> FileResponse:
    """Serve the Opportunity Hunter user interface."""
    return FileResponse(os.path.join(os.path.dirname(__file__), "hunter_ui.html"))


@app.post("/hunter/run", include_in_schema=False)
async def run_hunter(payload: dict) -> dict:
    """Run either a Saved Hunt or a free-text Opportunity Hunt."""
    hunt_name = (payload.get("hunt_name") or "").strip()
    query = (payload.get("query") or "").strip()
    profile_context = (payload.get("profile_context") or "").strip()

    if not hunt_name and not query:
        return {
            "status": "error",
            "message": "Describe what you want Opportunity Hunter to find.",
        }

    if not HAS_GCP_CREDENTIALS:
        return {
            "status": "error",
            "message": (
                "Discovery needs Google Cloud credentials for Gemini and Google "
                "Search (run `gcloud auth application-default login`). Your "
                "watchlist, source rechecks and the demo work without them."
            ),
        }

    user_id = "opportunity-hunter-demo"
    runner = app.state.runner

    session = await runner.session_service.create_session(
        app_name=app.state.agent_app_name,
        user_id=user_id,
    )

    if hunt_name:
        prompt = (
            f"Run my {hunt_name} Hunt now. Follow all saved Hunt criteria. "
            "Find and rank the best current opportunities, use my stored profile "
            "where relevant, surface NEW or CHANGED results, and give a pursuit "
            "plan for the strongest result."
        )
        label = hunt_name
    else:
        prompt = (
            "Run an ad hoc Opportunity Hunt based on this user's request:\n\n"
            f"{query}\n\n"
            "Infer the most useful search criteria from the request, including "
            "opportunity type, keywords, location or remote preference, value, "
            "time horizon, effort, and exclusions when they are reasonably clear. "
            "Do not require the user to know the Opportunity Hunter schema. "
            "Use reasonable assumptions when non-critical information is missing "
            "and clearly state those assumptions. Find current opportunities, "
            "verify material facts from exact opportunity/listing sources whenever "
            "possible, rank the results by fit and value, and provide a concrete "
            "next action for the strongest opportunities."
        )

        if profile_context:
            prompt += (
                "\n\nThe user also provided this additional personal context. "
                "Use it to personalize evaluation and ranking where relevant:\n"
                f"{profile_context}"
            )

        prompt += (
            "\n\nAlso use the stored Opportunity Hunter profile when it is "
            "relevant, but do not assume career-oriented profile information is "
            "relevant to unrelated personal Hunts."
        )

        label = query[:80]

    message = types.Content(
        role="user",
        parts=[types.Part(text=prompt)],
    )

    final_text = ""

    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session.id,
            new_message=message,
        ):
            content = getattr(event, "content", None)
            if content and getattr(content, "role", None) == "model":
                for part in getattr(content, "parts", []) or []:
                    part_text = getattr(part, "text", None)
                    if part_text:
                        final_text = part_text
    except Exception as exc:
        logger.log_struct({"hunt_error": repr(exc)}, severity="ERROR")
        return {
            "status": "error",
            "message": f"The Hunt could not finish: {type(exc).__name__}. Try again in a moment.",
        }

    return {
        "status": "success",
        "hunt_name": label,
        "text": final_text or "Hunt completed, but no final text was returned.",
    }


@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    """Collect and log feedback.

    Args:
        feedback: The feedback data to log

    Returns:
        Success message
    """
    logger.log_struct(feedback.model_dump(), severity="INFO")
    return {"status": "success"}


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
