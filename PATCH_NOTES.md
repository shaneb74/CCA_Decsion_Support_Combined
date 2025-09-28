# Senior Navigator — Patch Notes (  )

## What changed
- **Math fix:** Breakdown now includes **home sale net proceeds** and subtracts **upfront home-mods** when the checkbox is selected. Also shows **Monthly surplus** when applicable.
- **Care total wiring:** The cost panel now sets `st.session_state["care_monthly_total"]`, ensuring the Breakdown matches the chosen scenario.
- **Recommendation alignment:** Updated scoring to include `caregiver_support` and `home_preference`; removed unused `mental_health_concern`.
- **Safety override hook:** Added `dependence_override(flags)` helper in `engines.py` and a code marker where to apply it during final decisions.
- **Config seed:** Added `config/pricing_config.json` (not yet wired) to prepare for single-source pricing.

## Files touched
- `app.py` (math & surplus display)
- `cost_controls.py` (persist chosen care monthly)
- `recommendation_logic_FINAL_MASTER_UPDATED.json` (scoring keys/weights)
- `engines.py` (override helper + marker)
- `config/pricing_config.json` (new)

## Next steps (optional)
- Wire `pricing_config.json` in both `engines.py` and `cost_controls.py` to eliminate duplicated constants.
- Call `dependence_override(flags)` inside your final decision function to enforce the safety override deterministically.
- Add a shared `compute_totals(...)` function and reuse in PFMA and Breakdown.
