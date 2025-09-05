
# Recommendation Engine Hotfix

This bundle includes:
- `engines.py` — hardened PlannerEngine that:
  - Parses your JSON files exactly (flags -> categories -> scores).
  - Derives `dependence` when 2+ of the configured triggers hit.
  - Triggers `memory_care_required` when `severe_cognitive_risk` + `no_support` are both present.
  - Applies thresholds from `final_decision_thresholds` (AL ≥ 6, IH ≥ 3).
  - Selects narrative blocks from `final_recommendation` and safely renders templates.
- `app_recommendation_snippet.py` — drop-in snippet to normalize PlannerResult and show narratives.

## Install
1) Replace your project `engines.py` with the one in this zip.
2) In your `app.py`, when handling the planner result, use the code from `app_recommendation_snippet.py` to save the narrative into session and display it.
3) Ensure the JSONs live at:
   - `data/question_answer_logic_FINAL_UPDATED.json`
   - `data/recommendation_logic_FINAL_MASTER_UPDATED.json`

## Quick validation cases
- Severe cognitive + no support -> memory care with override narrative.
- All low-risk (no flags) and low scores -> no_care_needed narrative.
- Assisted-living score ≥ 6 -> assisted living narrative.
- In-home score ≥ 3 and AL < 6 -> in-home narrative (with financial/safety/mobility variants as applicable).
