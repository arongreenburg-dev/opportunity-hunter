# AI Builders Hackathon — Opportunity Hunter Submission Draft

## Project Title
Opportunity Hunter

## Tagline
Turn scattered opportunity discovery into a prioritized action portfolio.

## One-Sentence Product Statement
Opportunity Hunter is an AI workflow agent that finds, qualifies, prioritizes, tracks, and advances high-fit opportunities based on who the user is, what they can do, what they care about, and what they are trying to achieve.

## The Problem
High-value opportunities are scattered across job boards, hackathon sites, scholarship pages, marketplaces, local listings, newsletters, and professional networks. Finding links is easy; deciding what deserves attention is not. Users still have to verify whether an opportunity is current, assess eligibility, compare fit and upside, remember whether they have seen it before, notice material changes, and determine what to do next.

Opportunity Hunter addresses the follow-through gap between discovery and action.

## The Solution
Opportunity Hunter turns opportunity discovery into a five-stage decision workflow:

**Find → Qualify → Prioritize → Track → Act**

- **Find:** interpret a natural-language Hunt and search current sources.
- **Qualify:** verify candidate-specific evidence, status, eligibility, and important facts.
- **Prioritize:** score each opportunity against the user's goals, capabilities, constraints, expected value, likelihood of success, and effort.
- **Track:** store prior evaluations in Firestore and identify NEW, CHANGED, and UNCHANGED opportunities.
- **Act:** generate a practical pursuit plan for the strongest opportunities.

The product therefore returns not just search results, but an ordered opportunity portfolio with evidence, decisions, and next actions.

## Target Users
Opportunity Hunter is designed for people who repeatedly search across fragmented sources and need to decide what deserves limited time and attention. Examples include:

- builders and founders evaluating hackathons, grants, accelerators, partnerships, and calls for pilots;
- professionals evaluating jobs, consulting, advisory, speaking, and board opportunities;
- students and families searching for scholarships and competitions;
- collectors or buyers monitoring local or niche opportunities.

## Key Features
- Natural-language ad hoc Hunts
- Saved Hunts
- Persistent user profile and constraints
- Live current-source discovery
- Candidate-specific source verification
- Normalization and deduplication
- Weighted fit/value scoring
- PURSUE / CONSIDER / PASS recommendations
- Firestore NEW / CHANGED / UNCHANGED memory
- Pursuit Strategist with immediate next action and short plan
- Ranked results dashboard
- Copy Results and Export CSV

## Technical Architecture
Opportunity Hunter uses Google ADK to orchestrate a root agent and specialist workflows. Gemini 3.6 Flash on Vertex AI interprets Hunts, evaluates opportunities, and creates pursuit strategy. Google Search provides current discovery. Deterministic Python functions normalize, deduplicate, and score opportunities. Cloud Firestore stores user/Hunt context and evaluation history. FastAPI and Cloud Run provide the hosted application.

Core flow:

**User → Web UI → FastAPI/ADK Runner → Root Agent → Scout/Search → Verify/Normalize/Dedupe → Decision Scoring → Firestore Memory → Pursuit Strategist → Ranked Results**

## AI Technologies Used
- Google Agent Development Kit (ADK)
- Gemini 3.6 Flash on Vertex AI
- Google Search
- Cloud Firestore
- Cloud Run
- Cloud Build
- FastAPI
- Python

## Innovation
Most opportunity tools optimize discovery. Opportunity Hunter treats discovery as only the first step and manages the harder downstream work: evidence quality, personalized decision-making, persistent memory, material-change detection, and action planning. The product behaves more like an opportunity portfolio manager than a search assistant.

## Problem Solving & Impact
The product reduces repeated manual work across five activities users normally perform separately: search, validation, comparison, tracking, and planning. Instead of accumulating links and revisiting them manually, users can focus attention on opportunities with the strongest expected value relative to effort.

A simple adoption metric for future pilots would be:
- time spent from discovery to decision;
- percentage of surfaced opportunities that receive an explicit pursue/pass decision;
- percentage of pursued opportunities with a defined next action;
- duplicate/repeated review avoided through memory;
- conversion from surfaced opportunity to submitted application/outreach/action.

## User Experience
The user does not need to understand agent architecture or scoring logic. The main interface begins with a simple question: **“What should I hunt for?”** The system shows progress while working, then returns a ranked table with sources, scores, recommendation, and state. Detailed analysis is available without forcing it into the primary view.

## Challenges
Key implementation challenges included:

1. **Preventing stale or weak-source recommendations.** Live search initially surfaced generic portal or organization pages. Source guardrails were added so high-confidence recommendations require candidate-specific evidence.
2. **Avoiding repeated work.** Persistent state and fingerprint-based change detection were implemented so repeated Hunts distinguish NEW, CHANGED, and UNCHANGED opportunities.
3. **Making recommendations time-aware.** The Pursuit Strategist was updated to receive the current date so it does not recommend planning periods that have already passed.
4. **Connecting the browser to the agent workflow.** A server-side FastAPI endpoint was added to execute the ADK Runner cleanly from the public UI.

## Accomplishments
- Built and publicly deployed a working end-to-end agent workflow on Cloud Run.
- Implemented persistent Firestore state for user profiles, Saved Hunts, opportunities, and evaluations.
- Validated personalized scoring with strong-fit, poor-fit, and ineligible cases.
- Implemented deterministic normalization and deduplication.
- Added exact-source verification guardrails.
- Implemented NEW / UNCHANGED / CHANGED material-change detection.
- Added a specialist Pursuit Strategist.
- Built a functional public UI supporting both Saved Hunts and free-text Hunts.
- Added a ranked results experience, copy/export functions, and visible progress states.

## What We Learned
The biggest product insight is that discovery itself is increasingly commoditized. The valuable layer is decision infrastructure: understanding the user, enforcing evidence quality, distinguishing signal from repetition, and converting the best options into actions.

The technical lesson is that combining probabilistic agents with deterministic scoring, schemas, source rules, and persistent state produces a more trustworthy workflow than relying on a single open-ended agent response.

## Roadmap
Next steps include:
- scheduled recurring Hunts;
- alerts only for new or materially changed high-value opportunities;
- résumé and public-profile ingestion;
- Google Sheets, Gmail, and Calendar integrations;
- collaborative Hunts;
- learning from pursue/pass decisions and actual outcomes;
- portfolio analytics across opportunity categories.

## Development Disclosure
The current implementation was developed beginning August 24, 2026, within the AI Builders Hackathon build period beginning August 21, 2026. The same implementation was also used in the Google Cloud All Things Agentic Hackathon. The AI Builders submission emphasizes the broader product/SaaS workflow, technical implementation, usability, and adoption potential.

## Recommended Demo Story
1. Open Opportunity Hunter and state the problem: search results do not equal decisions.
2. Run **AI Competitions** or a clean free-text Hunt.
3. Show visible progress through current-source search and evaluation.
4. Show ranked results with source, score, recommendation, and NEW/CHANGED state.
5. Open one detailed analysis and Pursuit Plan.
6. Briefly show the architecture/memory loop.
7. Close with: **“Opportunity Hunter turns discovery into an action portfolio.”**
