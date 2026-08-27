# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types


MODEL = "gemini-3.6-flash"


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


root_agent = Agent(
    name="opportunity_hunter",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""
You are Opportunity Hunter, an AI decision agent that helps users decide
which opportunities are worth pursuing.

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
    tools=[calculate_opportunity_score],
)


app = App(
    root_agent=root_agent,
    name="app",
)
