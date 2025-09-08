# app.py — Senior Navigator (planner → recommendations → costs → household)
# JSON files live in repo root.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import traceback
import json
import streamlit as st

# local helpers
from ui_helpers import radio_from_answer_map
import cost_controls

# ----------------------- Page config -----------------------
st.set_page_config(page_title="Senior Navigator • Planner + Cost", page_icon="🧭", layout="centered")

# ----------------------- Paths (root) ----------------------
ROOT = Path(__file__).resolve().parent
QA_PATH = ROOT / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = ROOT / "recommendation_logic_FINAL_MASTER_UPDATED.json"

# ----------------------- Imports ---------------------------
try:
    from engines import PlannerEngine, CalculatorEngine, PlannerResult, resolve_narrative
except Exception:
    st.error("Failed to import engines.py")
    st.code(traceback.format_exc())
    st.stop()

# drawers isolated (unchanged)
try:
    import asset_engine
except Exception:
    asset_engine = None  # handle gracefully


# ----------------------- Utilities -------------------------
def make_inputs(**kwargs):
    obj = SimpleNamespace()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj


def reset_all():
    for k in list(st.session_state.keys()):
        if not k.startswith("_"):
            del st.session_state[k]
    st.session_state.step = "intro"


# ----------------------- Load JSONs ------------------------
missing = [p for p in (QA_PATH, REC_PATH) if not p.exists()]
if missing:
    st.error("Missing required JSON files:\n" + "\n".join(f"• {m.name}" for m in missing))
    st.stop()

# ----------------------- Engines ---------------------------
try:
    planner = PlannerEngine(str(QA_PATH), str(REC_PATH))
except Exception:
    st.error("PlannerEngine failed to initialize.")
    st.code(traceback.format_exc())
    st.stop()

try:
    calculator = CalculatorEngine()
except Exception:
    st.error("CalculatorEngine failed to initialize.")
    st.code(traceback.format_exc())
    st.stop()

# ----------------------- Session init ----------------------
if "step" not in st.session_state:
    st.session_state.step = "intro"

st.sidebar.title("Senior Navigator")
st.sidebar.caption("Planner → Recommendations → Costs → Household")
st.sidebar.button("Start over", on_click=reset_all)

# ----------------------- Steps -----------------------------

# INTRO
if st.session_state.step == "intro":
    st.title("Let’s take this one step at a time")
    st.markdown(
        """
Choosing senior living or in-home support can feel overwhelming.

**What happens next**
1. Answer quick care questions → we recommend a care type.  
2. Review costs for that scenario (you can switch).  
3. (Optional) Add income, benefits, assets, and home decisions.  
4. See a detailed breakdown and adjust anything.
"""
    )
    if st.button("Start"):
        st.session_state.step = "audience"
        st.rerun()

# AUDIENCE
elif st.session_state.step == "audience":
    st.header("Who is this plan for?")
    role = st.radio(
        "Select one:",
        ["Myself", "My spouse/partner", "My parent", "Both parents", "Someone else"],
        key="aud_role",
    )

    people = []
    if role == "Both parents":
        c1, c2 = st.columns(2)
        with c1:
            n1 = st.text_input("Parent 1 name", value="Mom", key="p1_name", placeholder="Name")
        with c2:
            n2 = st.text_input("Parent 2 name", value="Dad", key="p2_name", placeholder="Name")
        people.append({"id": "A", "display_name": n1, "relationship": "parent"})
        people.append({"id": "B", "display_name": n2, "relationship": "parent"})
    else:
        default = "Alex" if role != "My parent" else "Mom"
        n = st.text_input("Name", value=default, key="p_name", placeholder="Name")
        rel = {"Myself": "self", "My spouse/partner": "spouse", "My parent": "parent", "Someone else": "other"}[role]
        people.append({"id": "A", "display_name": n, "relationship": rel})

    if st.button("Continue"):
        st.session_state.people = people
        st.session_state.current_person = 0
        st.session_state.planner_results = {}
        st.session_state.person_costs = {}
        if role != "Both parents":
            st.session_state.step = "spouse_interstitial"
        else:
            st.session_state.step = "planner"
        st.rerun()

# SPOUSE INTERSTITIAL (checkbox + name; button disabled until checked)
elif st.session_state.step == "spouse_interstitial":
    people = st.session_state.get("people", [])
    primary = people[0]["display_name"] if people else "Person A"

    st.header("Add Spouse or Partner?")
    st.markdown(
        f"If **{primary}** needs assisted living or memory care, their spouse/partner may also need some in-home help."
        "\n\nWould you like to include a spouse/partner so the household picture is complete?"
    )

    add = st.checkbox("Yes, I want to include a spouse/partner", value=False, key="care_partner_add")
    if add:
        st.text_input("Spouse/partner name", value="", placeholder="Enter spouse/partner name", key="care_partner_name")

    c1, c2 = st.columns(2)
    with c1:
        if st.button(f"No, just plan for {primary}"):
            st.session_state.step = "planner"
            st.rerun()
    with c2:
        disabled = not st.session_state.get("care_partner_add", False)
        if st.button("Add spouse/partner and continue", disabled=disabled):
            if disabled is False:
                st.session_state.people.append({
                    "id": "B",
                    "display_name": (st.session_state.get("care_partner_name") or "Spouse/Partner"),
                    "relationship": "spouse",
                })
            st.session_state.step = "planner"
            st.rerun()

# PLANNER (all questions at once; safe radios)
elif st.session_state.step == "planner":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if not people or i >= len(people):
        st.session_state.step = "recommendations"; st.rerun()
    p = people[i]; pid, name = p["id"], p["display_name"]

    st.header(f"Care Assessment for {name}")
    st.caption("Answer these quick questions to get a personalized recommendation.")

    answers = {}
    for q_idx, q in enumerate(planner.qa.get("questions", []), start=1):
        label = q.get("question", f"Question {q_idx}")
        amap = q.get("answers", {})
        key = f"q{q_idx}_{pid}"
        sel = radio_from_answer_map(label, amap, key=key, help_text=q.get("help"))
        if sel is not None:
            try:
                answers[f"q{q_idx}"] = int(sel)
            except Exception:
                # gracefully handle non-int options
                pass

    if st.button("Save and continue"):
        try:
            result = planner.run(answers, name=name)
        except Exception:
            st.error("PlannerEngine.run failed.")
            st.code(traceback.format_exc())
            st.stop()

        st.session_state.planner_results[pid] = result
        st.session_state.current_person = i + 1
        if st.session_state.current_person >= len(people):
            st.session_state.step = "recommendations"
        else:
            st.session_state.step = "person_transition"
        st.rerun()

# PERSON TRANSITION
elif st.session_state.step == "person_transition":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if i >= len(people):
        st.session_state.step = "recommendations"; st.rerun()
    name = people[i]["display_name"]
    st.header("Great — first plan saved.")
    st.info(f"Now let’s assess **{name}**.")
    if st.button(f"Start {name}’s care plan"):
        st.session_state.step = "planner"
        st.rerun()

# RECOMMENDATIONS
elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without redoing questions.")

    overrides = st.session_state.get("care_overrides", {})
    for p in st.session_state.get("people", []):
        pid = p["id"]; name = p["display_name"]
        rec = st.session_state.planner_results.get(pid, PlannerResult("in_home", [], {}, [], "", None))

        care_type = rec.care_type if hasattr(rec, "care_type") else (rec.get("care_type") if isinstance(rec, dict) else "in_home")
        nice = {"none": "None", "in_home": "In-home Care", "assisted_living": "Assisted Living", "memory_care": "Memory Care"}
        st.subheader(f"{name}: {nice.get(care_type, care_type).title()} (recommended)")

        # Reasons (debug) then narrative
        if getattr(rec, "reasons", None):
            for r in rec.reasons:
                st.write("• " + str(r))
        narrative = resolve_narrative(rec)
        if narrative:
            st.info(narrative)

        # Allow override scenario here as well
        options = ["none", "in_home", "assisted_living", "memory_care"]
        idx = options.index(care_type) if care_type in options else 1
        label = st.selectbox(f"Care scenario for {name}", [nice[o] for o in options], index=idx, key=f"override_{pid}")
        reverse = {v: k for k, v in nice.items()}
        overrides[pid] = reverse[label]

        st.divider()

    st.session_state["care_overrides"] = overrides

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Back to questions"):
            st.session_state.step = "planner"; st.rerun()
    with c2:
        if st.button("See Costs"):
            st.session_state.step = "calculator"; st.rerun()
    with c3:
        if st.button("Finish"):
            st.session_state.step = "intro"; st.rerun()

# CALCULATOR (single location control + per-person cost controls)
elif st.session_state.step == "calculator":
    st.title("Cost Planner")
    factor = cost_controls.render_location_control()  # ONE place only
    _ = cost_controls.render_costs_for_active_recommendations(
        planner_results=st.session_state.get("planner_results", {}),
        overrides=st.session_state.get("care_overrides", {}),
        factor=factor,
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Back to recommendations"):
            st.session_state.step = "recommendations"; st.rerun()
    with c2:
        if st.button("Add Household & Assets"):
            st.session_state.step = "household"; st.rerun()
    with c3:
        if st.button("Finish"):
            st.session_state.step = "intro"; st.rerun()

# HOUSEHOLD (unchanged; delegated)
elif st.session_state.step == "household":
    st.header("Household & Budget (optional)")
    st.caption("Add income, benefits, assets, home decisions, and other costs to see affordability. You can skip this.")

    if asset_engine is None:
        st.warning("Household budgeting is unavailable (asset_engine.py missing).")
    else:
        try:
            people = st.session_state.get("people", [])
            if hasattr(asset_engine, "IncomeAssetsEngine"):
                engine = asset_engine.IncomeAssetsEngine(calculator=calculator)
                _result = engine.render(people)
            else:
                st.warning("Household budgeting unavailable: IncomeAssetsEngine not found.")
        except Exception:
            st.error("Household drawers failed.")
            st.code(traceback.format_exc())

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Back to Costs"):
            st.session_state.step = "calculator"; st.rerun()
    with c2:
        if st.button("View Detailed Breakdown"):
            st.session_state.step = "breakdown"; st.rerun()
    with c3:
        if st.button("Finish"):
            st.session_state.step = "intro"; st.rerun()

# BREAKDOWN (unchanged numeric summary)
elif st.session_state.step == "breakdown":
    st.header("Detailed Breakdown")

    people = st.session_state.get("people", [])
    costs = st.session_state.get("person_costs", {})
    care_total = sum(int(costs.get(p["id"], 0)) for p in people)

    s = st.session_state
    inc_A = int(s.get("a_ss", 0)) + int(s.get("a_pn", 0)) + int(s.get("a_other", 0))
    inc_B = int(s.get("b_ss", 0)) + int(s.get("b_pn", 0)) + int(s.get("b_other", 0))
    inc_house = int(s.get("hh_rent", 0)) + int(s.get("hh_annuity", 0)) + int(s.get("hh_invest", 0)) + int(s.get("hh_trust", 0)) + int(s.get("hh_other", 0))

    va_A = int(s.get("a_va_monthly", 0)); va_B = int(s.get("b_va_monthly", 0))
    home_monthly = int(s.get("home_monthly_total", 0))
    mods_monthly = int(s.get("mods_monthly_total", 0))
    other_monthly = int(s.get("other_monthly_total", 0))
    addl_costs = home_monthly + mods_monthly + other_monthly

    assets_common = int(s.get("assets_common_total", 0))
    assets_detail = int(s.get("assets_detailed_total", 0))
    assets_total = assets_common + assets_detail

    income_total = inc_A + inc_B + inc_house + va_A + va_B
    monthly_need = care_total + addl_costs
    gap = monthly_need - income_total

    c1, c2, c3 = st.columns(3)
    c1.metric("Monthly Care + Selected Costs", f"${monthly_need:,.0f}")
    c2.metric("Total Monthly Income (incl. VA)", f"${income_total:,.0f}")
    c3.metric("Estimated Monthly Gap", f"${gap:,.0f}")

    years = 0.0
    if gap > 0 and assets_total > 0:
        years = round(assets_total / max(gap, 1), 1)
    st.subheader(f"Estimated runway from assets: {years} years")

    st.divider()
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Back to Household"):
            st.session_state.step = "household"; st.rerun()
    with b2:
        if st.button("Back to Costs"):
            st.session_state.step = "calculator"; st.rerun()

# Fallback
else:
    reset_all(); st.rerun()