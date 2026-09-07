# Opportunity Hunter — AI Builders Demo Script

Target length: 3:30–4:15

## 0:00–0:30 — Problem

“Finding opportunities is easy. Acting on the right ones is hard. Hackathons, jobs, grants, consulting opportunities and local opportunities are scattered across different sources. Even after finding them, users still have to verify them, compare fit, remember what they already reviewed, and decide what to do next.”

“Opportunity Hunter turns that fragmented process into one workflow: **Find → Qualify → Prioritize → Track → Act.**”

## 0:30–0:55 — Product thesis

Show the Opportunity Hunter home screen.

“Instead of another list of links, Opportunity Hunter creates a prioritized action portfolio. A user can run a saved Hunt or describe what they want in ordinary language and optionally add personal context.”

## 0:55–1:40 — Run a Hunt

Use a safe, non-private example such as **AI Competitions** or enter:

> Find active AI hackathons or innovation competitions that are still open, have meaningful prizes or career value, and are realistic for a solo builder using AI-assisted development.

While progress appears:

“The Scout Agent uses current web search to find candidates. The workflow then verifies sources, normalizes and deduplicates opportunities, and evaluates them against the user profile and Hunt criteria.”

## 1:40–2:35 — Explain the decision layer

Show the ranked results.

“Every viable opportunity is scored across five dimensions: strategic fit, capability fit, expected value, probability of success, and effort efficiency.”

“Those dimensions feed a deterministic weighted score, which produces a **PURSUE, CONSIDER, or PASS** recommendation. The source link stays visible so the recommendation is auditable.”

Open one strong result and its full analysis.

“For strong opportunities, a specialist Pursuit Strategist explains why it matters, key risks and tradeoffs, and the immediate next action.”

## 2:35–3:05 — Persistent memory

Show NEW / CHANGED / UNCHANGED state if available, or explain it over the results view.

“The other important difference is memory. Firestore stores prior evaluations so repeated Hunts can tell the user what is **NEW, CHANGED, or UNCHANGED** instead of forcing the same review work again.”

## 3:05–3:35 — Architecture

Show `docs/architecture.md` or the README architecture section.

“The system uses Google ADK for orchestration, Gemini on Vertex AI for interpretation and evaluation, Google Search for current discovery, deterministic Python scoring for consistency, Firestore for persistent state, and Cloud Run for the public application.”

## 3:35–4:00 — Impact and close

“The product is useful because discovery is becoming commoditized. The valuable layer is decision infrastructure: evidence quality, personalized tradeoffs, memory, and action.”

“Today Opportunity Hunter runs Hunts on demand. The next step is recurring Hunts and notifications only when a high-value opportunity appears or materially changes.”

“**Opportunity Hunter turns discovery into an action portfolio. Don’t give me more things to search. Give me the opportunities worth acting on.**”

## Recording Checklist

- Use a desktop browser at comfortable zoom.
- Close personal tabs and notifications.
- Use a safe Hunt with no private information.
- Confirm the live app loads before recording.
- Keep the final video under 5 minutes.
- Show the product working live, not only slides.
- Upload as YouTube unlisted (or Vimeo) and paste the public/unlisted link into Devpost.
