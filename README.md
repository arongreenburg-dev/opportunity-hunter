# Opportunity Hunter

**An AI agent that discovers, evaluates, prioritizes, remembers, and helps pursue high-value opportunities based on who you are and what matters to you.**

**Live app:** https://opportunity-hunter-107621546882.us-central1.run.app/hunter

Built for the **Google Cloud All Things Agentic Hackathon — Taskmaster track**.

## The Problem

High-value opportunities are scattered across job boards, scholarship sites, competitions, marketplaces, local listings, newsletters, and countless other sources.

Finding links is not enough. Users still need to decide:

- Is this relevant to me?
- Am I eligible?
- Is it worth the effort?
- Is it current?
- Have I seen it before?
- Did something change?
- What should I do next?

Opportunity Hunter turns search into an agentic decision workflow:

**Know Me → Hunt → Decide → Remember → Act → Repeat**

## What It Does

Users can describe almost any opportunity in ordinary language, for example:

- "Find AI hackathons I can still enter."
- "Scholarships for a high school student interested in music and science."
- "Find sports-card estate sales within 25 miles."
- "Find consulting opportunities that fit my healthcare transformation experience."

Opportunity Hunter then interprets the request, searches current sources, verifies evidence, deduplicates results, scores opportunities, compares them with persistent memory, identifies what is new or changed, and recommends what to pursue next.

## Personalization and Saved Hunts

A Hunt can optionally incorporate what the user can do, what they care about, what they want to achieve, and their preferences or constraints.

Saved Hunt criteria persist in **Cloud Firestore**. The MVP includes examples such as:

- AI Competitions
- Sports Card Estate Sales

Firestore also stores prior opportunity evaluations so the system can identify **NEW**, **UNCHANGED**, and **CHANGED** opportunities.

Saved Hunts currently run on demand. Automated recurring execution is a roadmap item.

## Decision Scoring

Each opportunity is evaluated using a weighted framework:

- Strategic fit: 30%
- Capability fit: 25%
- Expected value: 20%
- Probability of success: 15%
- Effort efficiency: 10%

Recommendations are **PURSUE** at 80+, **CONSIDER** at 65–79, and **PASS** below 65.

## Source Discipline

High-confidence recommendations require candidate-specific evidence. Generic homepages, directories, category pages, search results, and login portals are not sufficient for a PURSUE recommendation when an exact listing should exist.

If an exact source cannot be verified, the opportunity is treated as needing verification rather than presented with false confidence.

## Pursuit Strategist

For strong opportunities, a specialist agent identifies why the opportunity matters, risks and tradeoffs, the immediate next action, and a time-aware pursuit plan.

The strategist receives the current date so it does not recommend planning phases that have already passed.

## Results Experience

The public UI provides:

- free-text Hunts,
- optional personal context,
- Saved Hunts,
- visible progress while the agent works,
- ranked results,
- scores and recommendations,
- source links,
- NEW / CHANGED state,
- expandable full analysis,
- Copy Results,
- Export CSV.

## Architecture

The core flow is:

User  
→ Opportunity Hunter Web UI  
→ Root Agent / Google ADK  
→ Profile + Hunt Context  
→ Scout Agent + Google Search  
→ Verify / Normalize / Deduplicate  
→ Decision Scoring  
→ Firestore Memory / Change Detection  
→ Pursuit Strategist  
→ Ranked Results + Next Actions

See `docs/architecture.md` for the architecture diagram.

## Google Cloud and Agent Stack

Opportunity Hunter uses:

- **Google Agent Development Kit (ADK)** for orchestration
- **Gemini 3.6 Flash** on Vertex AI
- **Google Search** for current opportunity discovery
- **Cloud Firestore** for persistent state and memory
- **Cloud Run** for the hosted application
- **Cloud Build** for deployment
- **FastAPI**
- **Python / uv**

## Repository Structure

- `app/agent.py` — core agents, scoring, and orchestration
- `app/fast_api_app.py` — FastAPI / ADK backend
- `app/hunter_ui.html` — web interface
- `app/memory_store.py` — Firestore persistence and change detection
- `data/` — profile and state schemas
- `docs/architecture.md` — architecture diagram
- `tests/` — test scaffold
- `Dockerfile` — Cloud Run container
- `pyproject.toml` — dependencies

## Local Setup

Requirements:

- Python
- uv
- Google Cloud SDK
- Google Agents CLI
- Google Cloud project with Vertex AI access

Install the Agents CLI:

    uv tool install google-agents-cli

Authenticate and choose a project:

    gcloud auth application-default login
    gcloud config set project YOUR_PROJECT_ID

Install dependencies:

    agents-cli install

Run locally:

    agents-cli playground

## Deployment

Enable the required Google Cloud services, including Vertex AI, Cloud Run, Cloud Build, and Firestore.

Deploy with:

    agents-cli deploy --project YOUR_PROJECT_ID --region us-central1

Current public hackathon deployment:

https://opportunity-hunter-107621546882.us-central1.run.app/hunter

## Validation

The MVP has been tested with:

- strong-fit PURSUE cases,
- weak-fit PASS cases,
- duplicate candidates,
- missing or unknown information,
- NEW → UNCHANGED → CHANGED persistence,
- Saved Hunts,
- free-text Hunts,
- exact-source verification,
- current-date pursuit planning,
- public Cloud Run execution.

## MVP Boundaries

The hackathon MVP intentionally does not include:

- authentication / multi-user accounts,
- automated Cloud Scheduler execution,
- direct Google Sheets synchronization,
- email / Slack / calendar notifications,
- payments,
- continuous broad web indexing.

These are roadmap extensions rather than requirements for demonstrating the core agent loop.

## What's Next

Natural extensions include:

- recurring automated Hunts,
- notifications only when high-value opportunities appear or change,
- résumé and public-profile ingestion,
- Google Sheets / Gmail / Calendar integrations,
- collaborative Hunts,
- learning from which opportunities users pursue or reject.

## Product Principle

**Don't give me more things to search. Give me the opportunities worth acting on.**

## Reproducible Testing

The easiest way to reproduce the core agent workflow is through the public application:

1. Open https://opportunity-hunter-107621546882.us-central1.run.app/hunter
2. Run the saved **AI Competitions** Hunt, or enter a free-text Hunt.
3. Confirm the agent displays progress while searching and evaluating.
4. Confirm the result contains ranked opportunities, source URLs, scores, and PURSUE / CONSIDER / PASS recommendations.
5. Run the same Saved Hunt again to exercise persistent Firestore memory and NEW / UNCHANGED / CHANGED behavior.
6. Expand **Full analysis** to inspect detailed assessment and pursuit-strategy output.

For local development, follow the Local Setup instructions above and run:

    agents-cli playground
