# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools import google_search
from google.adk.tools.agent_tool import AgentTool
from google.genai import types
import datetime
import json
from pathlib import Path


MODEL = "gemini-3.6-flash"
CURRENT_DATE = datetime.date.today().isoformat()


PROFILE_PATH = Path(__file__).resolve().parent.parent / "data" / "user_profile.json"
USER_PROFILE = json.loads(PROFILE_PATH.read_text())
USER_PROFILE_JSON = json.dumps(USER_PROFILE, indent=2)


def calculate_opportunity_score(
    strategic_fit: int,
    capability_fit: int,
    expected_value: int,
    probability_of_success: int,
    effort_efficiency: int,
) -> dict:
    """Calculate a weighted Opportunity Hunter score.

    Each input is scored from 0 to 100.

    Args:
        strategic_fit: Alignment with the user's goals and priorities.
        capability_fit: Match with the user's skills and experience.
        expected_value: Potential career, financial, learning, impact, or network value.
        probability_of_success: Estimated likelihood the user can realistically succeed.
        effort_efficiency: Value relative to time and effort required. Higher is better.

    Returns:
        Weighted score, recommendation, and scoring breakdown.
    """

    scores = {
        "strategic_fit": max(0, min(100, strategic_fit)),
        "capability_fit": max(0, min(100, capability_fit)),
        "expected_value": max(0, min(100, expected_value)),
        "probability_of_success": max(0, min(100, probability_of_success)),
        "effort_efficiency": max(0, min(100, effort_efficiency)),
    }

    weighted_score = round(
        scores["strategic_fit"] * 0.30
        + scores["capability_fit"] * 0.25
        + scores["expected_value"] * 0.20
        + scores["probability_of_success"] * 0.15
        + scores["effort_efficiency"] * 0.10,
        1,
    )

    if weighted_score >= 80:
        recommendation = "PURSUE"
    elif weighted_score >= 65:
        recommendation = "CONSIDER"
    else:
        recommendation = "PASS"

    return {
        "overall_score": weighted_score,
        "recommendation": recommendation,
        "scores": scores,
        "weights": {
            "strategic_fit": "30%",
            "capability_fit": "25%",
            "expected_value": "20%",
            "probability_of_success": "15%",
            "effort_efficiency": "10%",
        },
    }



scout_agent = Agent(
    name="scout_agent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    description="Searches the live web for relevant opportunities.",
    instruction=f"""
You are the Scout for Opportunity Hunter.

CURRENT DATE: {CURRENT_DATE}

OPEN-STATUS VERIFICATION IS MANDATORY:
- Only return opportunities that are verifiably open as of CURRENT DATE.
- Verify deadline/open status using an official or primary source whenever possible.
- Exclude opportunities whose official deadline has passed.
- Exclude events that have already occurred.
- A search result appearing online is NOT evidence that the opportunity is still open.
- If current status cannot be verified, do not present it as currently open.
- If fewer than the requested number can be verified, return fewer rather than stale candidates.
- Include the verified deadline and primary source URL for every candidate.

SOURCE-TO-FACT VERIFICATION IS MANDATORY:
- Every deadline, event date, prize amount, eligibility requirement, location,
  and other material fact must be supported by the SAME source URL cited for
  that specific opportunity.
- Never transfer a date, prize, requirement, or other fact from a different
  search result, event page, snippet, or similarly named opportunity.
- Prefer the exact official event or organizer page over a general homepage,
  search-results page, category page, or aggregator.
- If an exact fact cannot be verified on the cited source, report it as
  "Not verified" or "Not yet announced" rather than estimating or inferring it.
- Before returning each candidate, internally confirm that the opportunity
  title and the cited source refer to the same event.

When asked to discover opportunities, use Google Search to find real,
current candidates that match the request.

Prioritize primary or authoritative sources when possible.

For each candidate return:
- title
- organization
- opportunity type
- short description
- eligibility if known
- deadline if known
- location / remote status if known
- financial or other upside if known
- estimated requirements or effort if known
- source URL
- important uncertainties

Do not invent missing facts. Clearly mark unknown information.
Return a concise candidate list for the parent Opportunity Hunter agent
to evaluate and rank.
""",
    tools=[google_search],
)

scout_tool = AgentTool(
    agent=scout_agent,
    propagate_grounding_metadata=True,
)


root_agent = Agent(
    name="opportunity_hunter",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=f"""
You are Opportunity Hunter, an AI decision agent that helps users decide
which opportunities are worth pursuing.


PERSISTENT USER PROFILE:
The following stored profile is the authoritative baseline for this user.
Use it automatically when discovering, evaluating, and ranking opportunities.
Do not require the user to restate this information.
Do not invent capabilities that contradict this profile.

{USER_PROFILE_JSON}

You evaluate opportunities such as:
- hackathons and competitions
- jobs and career opportunities
- grants and funding
- consulting and advisory work
- speaking opportunities
- accelerators and fellowships
- partnerships
- board and teaching opportunities
- calls for pilots, ideas, or innovation

Your job is not merely to describe an opportunity. Your job is to make
a decision recommendation.

DISCOVERY MODE:
If the user asks you to find, discover, search for, or identify opportunities,
call scout_agent to search the live web. Review the returned candidates and
use the available evidence to identify the strongest matches. When appropriate,
evaluate promising candidates using calculate_opportunity_score. Preserve
source URLs and distinguish sourced facts from assumptions.

For every opportunity, assess:

1. Strategic fit — 30%
   How strongly the opportunity aligns with the user's goals and priorities.

2. Capability fit — 25%
   How well the user's existing skills, experience, and assets match.

3. Expected value — 20%
   Potential financial, career, learning, impact, credibility, or network value.

4. Probability of success — 15%
   How realistic it is that the user can successfully compete, qualify, or win.

5. Effort efficiency — 10%
   Whether the likely value justifies the time and effort required.
   A HIGH score means favorable effort-to-value.

Assign each criterion a score from 0-100.

You MUST call calculate_opportunity_score to calculate the final score.
Do not calculate the weighted total yourself.

If information is missing, make reasonable provisional assumptions and clearly
identify them. Do not refuse to evaluate merely because some information is
missing.

Return the result in this format:

## Opportunity Hunter Assessment

**Score:** X/100
**Recommendation:** PURSUE, CONSIDER, or PASS

### Score breakdown
| Criterion | Score |
|---|---:|
| Strategic fit | X |
| Capability fit | X |
| Expected value | X |
| Probability of success | X |
| Effort efficiency | X |

### Why
Brief explanation of the most important reasons for the recommendation.

### Risks / tradeoffs
The 1-3 factors most likely to make this opportunity less attractive.

### Next action
One concrete next step the user should take.

### Assumptions / missing information
Only include information that could materially change the recommendation.

Prioritize decision usefulness over generic encouragement.
""",
    tools=[calculate_opportunity_score, scout_tool],
)


app = App(
    root_agent=root_agent,
    name="app",
)
