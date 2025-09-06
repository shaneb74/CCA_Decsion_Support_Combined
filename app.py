# app.py — Senior Navigator (planner → recommendations → costs → household)
# All JSON files (QA + recommendation) are expected in the repo root.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import traceback
import json
import random

import streamlit as st

# ----------------------- Page config -----------------------
st.set_page_config(page_title="Senior Navigator • Planner + Cost", page_icon="🧭", layout="centered")

# ----------------------- Paths (root) ----------------------
ROOT = Path(__file__).resolve().parent
QA_PATH = ROOT / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = ROOT / "recommendation_logic_FINAL_MASTER_UPDATED.json"

# ----------------------- Imports ---------------------------
try:
    from engines import PlannerEngine, CalculatorEngine, PlannerResult
except Exception:
    st.error("Failed to import engines.py")
    st.code(traceback.format_exc())
    st.stop()

# isolate drawers (no UX changes but kept outside app.py)
try:
    import asset_engine
except Exception:
    asset_engine = None  # we'll gracefully handle missing/older modules


# ----------------------- Utilities -------------------------
def make_inputs(**kwargs):
    """Create a light object for calculator inputs."""
    obj = SimpleNamespace()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj


def reset_all():
    for k in list(st.session_state.keys()):
        if not k.startswith("_"):
            del st.session_state[k]
    st.session_state.step = "intro"


def _is_intlike(x) -> bool:
    try:
        int(str(x))
        return True
    except Exception:
        return False


def order_answer_map(amap: dict[str, str]) -> tuple[list[str], list[str]]:
    """Return (ordered_keys, ordered_labels) even if the JSON answer keys are not '1'..'N'.
    Logs an error if amap is invalid."""
    if not isinstance(amap, dict) or not amap:
        st.error(f"Invalid or empty answer map: {amap}")
        return [], []
    keys = list(amap.keys())
    if not all(isinstance(k, str) for k in keys):
        st.error(f"Answer map keys must be strings: {amap}")
        return [], []
    if not all(isinstance(amap[k], str) for k in keys):
        st.error(f"Answer map values must be strings: {amap}")
        return [], []
    if all(_is_intlike(k) for k in keys):
        ordered_keys = [str(k) for k in sorted(int(str(k)) for k in keys)]
    else:
        ordered_keys = [str(k) for k in keys]  # preserve JSON insertion order
    labels = [amap[k] for k in ordered_keys]
    if not labels:
        st.warning(f"No valid labels generated from {amap}")
    return ordered_keys, labels


def radio_from_answer_map(label, amap, *, key, help_text=None, default_key=None) -> str | None:
    """Render a radio from a JSON answer map and return the SELECTED KEY (string).
    Handles invalid amap gracefully."""
    if not isinstance(amap, dict) or not amap:
        st.warning(f"Skipping radio for '{label}' due to invalid answer map: {amap}")
        return default_key
    keys, labels = order_answer_map(amap)
    if not labels:
        st.warning(f"No valid options for '{label}', using default: {default_key}")
        return default_key
    if default_key is not None and str(default_key) in keys:
        idx = keys.index(str(default_key))
    else:
        idx = 0
    try:
        sel_label = st.radio(label, labels, index=idx, key=key)  # Removed help_text
        return keys[labels.index(sel_label)]
    except Exception as e:
        st.error(f"Failed to render radio for '{label}': {e}. Using default: {default_key}")
        return default_key


def clamp(n, lo, hi):
    return max(lo, min(hi, n))


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
        people.append({
            "id": "A",
            "display_name": n1,
            "relationship": "parent",
        })
        people.append({
            "id": "B",
            "display_name": n2,
            "relationship": "parent",
        })
    else:
        default = "Alex" if role != "My parent" else "Mom"
        n = st.text_input("Name", value=default, key="p_name", placeholder="Name")
        rel = {"Myself": "self", "My spouse/partner": "spouse", "My parent": "parent", "Someone else": "other"}[role]
        people.append({
            "id": "A",
            "display_name": n,
            "relationship": rel,
        })

    if st.button("Continue"):
        st.session_state.people = people
        st.session_state.current_person = 0
        st.session_state.planner_results = {}
        st.session_state.person_costs = {}
        st.session_state.step = "planner"
        st.rerun()

# PLANNER (per person)
elif st.session_state.step == "planner":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    p = people[i]
    pid, name = p["id"], p["display_name"]

    st.header(f"Care Assessment for {name}")
    st.markdown("Answer these quick questions to get a personalized recommendation.")

    answers = {}
    for q_idx, q in enumerate(planner.qa.get("questions", [])):
        label = q["question"]
        amap = q.get("answers", {})
        if not amap or not isinstance(amap, dict):
            st.warning(f"Skipping question '{label}' due to invalid answers: {amap}")
            continue
        key = f"q{q_idx + 1}_{pid}"
        ans = radio_from_answer_map(label, amap, key=key, help_text=q.get("help_text"))
        if ans is not None:
            answers[f"q{q_idx + 1}"] = int(ans)

    if st.button("Save and continue"):
        if not answers:
            st.error("No answers provided. Please answer at least one question.")
        else:
            result = planner.run(answers, name=name)
            st.session_state.planner_results = st.session_state.get("planner_results", {})
            st.session_state.planner_results[pid] = result  # Store the object, not __dict__
            st.session_state.current_person += 1
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
        st.session_state.step = "recommendations"
        st.rerun()
    name = people[i]["display_name"]
    st.header("Great — first plan saved.")
    st.info(f"Now let’s assess **{name}**.")
    if st.button(f"Start {name}'s care plan"):
        st.session_state.step = "planner"
        st.rerun()

# RECOMMENDATIONS
elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without redoing questions.")

    for p in st.session_state.get("people", []):
        pid = p["id"]
        name = p["display_name"]
        rec = st.session_state.planner_results.get(pid, PlannerResult("in_home", [], {}, [], "", None))

        care_type = rec.care_type
        reasons = rec.reasons
        narrative = rec.narrative

        nice = {
            "none": "None",
            "in_home": "In-home Care",
            "assisted_living": "Assisted Living",
            "memory_care": "Memory Care",
        }
        st.subheader(f"{name}: {nice.get(care_type, care_type).title()} (recommended)")
        if reasons:
            for r in reasons:
                st.write("• " + str(r))
        if narrative:
            st.info(narrative)

        options = ["none", "in_home", "assisted_living", "memory_care"]
        idx = options.index(care_type) if care_type in options else 1
        label = st.selectbox(
            f"Care scenario for {name}",
            [nice[o] for o in options],
            index=idx,
            key=f"override_{pid}",
        )
        reverse = {v: k for k, v in nice.items()}
        st.session_state.care_overrides = st.session_state.get("care_overrides", {})
        st.session_state.care_overrides[pid] = reverse[label]

        st.divider()

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Back to questions"):
            st.session_state.step = "planner"
            st.rerun()
    with c2:
        if st.button("See Costs"):
            st.session_state.step = "calculator"
            st.rerun()
    with c3:
        if st.button("Finish"):
            st.session_state.step = "intro"
            st.rerun()

# CALCULATOR
elif st.session_state.step == "calculator":
    st.header("Cost Planner")

    state = st.selectbox("Location", ["National", "Washington", "California", "Texas", "Florida"])
    factor = {"National": 1.0, "Washington": 1.15, "California": 1.25, "Texas": 0.95, "Florida": 1.05}[state]

    combined = 0
    for p in st.session_state.get("people", []):
        pid = p["id"]
        name = p["display_name"]
        rec = st.session_state.planner_results.get(pid, PlannerResult("in_home", [], {}, [], "", None))
        care_type = st.session_state.get("care_overrides", {}).get(pid, rec.care_type)

        st.subheader(f"{name} — Scenario: {care_type.replace('_', ' ').title()}")

        inp = make_inputs(state=state, care_type=care_type)

        try:
            if hasattr(calculator, "monthly_cost"):
                monthly = calculator.monthly_cost(inp)
            else:
                monthly = calculator.estimate(getattr(inp, "care_type", "in_home"))
        except Exception:
            st.error("CalculatorEngine failed while computing monthly cost.")
            st.code(traceback.format_exc())
            st.stop()

        st.metric("Estimated Monthly Cost", f"${int(monthly):,}")
        st.session_state["person_costs"][pid] = int(monthly)
        combined += int(monthly)
        st.divider()

    st.subheader("Combined Total")
    st.metric("Estimated Combined Monthly Cost", f"${combined:,.0f}")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Back to recommendations"):
            st.session_state.step = "recommendations"
            st.rerun()
    with c2:
        if st.button("Add Household & Assets"):
            st.session_state.step = "household"
            st.rerun()
    with c3:
        if st.button("Finish"):
            st.session_state.step = "intro"
            st.rerun()

# HOUSEHOLD (delegated to asset_engine for the drawers)
elif st.session_state.step == "household":
    st.header("Household & Budget (optional)")
    st.caption("Add income, benefits, assets, home decisions, and other costs to see affordability. You can skip this.")

    if asset_engine is None:
        st.warning("The household budgeting feature is unavailable because asset_engine.py is missing or failed to load.")
    else:
        try:
            people = st.session_state.get("people", [])
            if hasattr(asset_engine, "IncomeAssetsEngine"):
                engine = asset_engine.IncomeAssetsEngine(calculator=calculator)
                result = engine.render(people)
            else:
                st.warning("The household budgeting feature is unavailable because asset_engine.py lacks a recognized render function.")
                result = None
        except Exception as e:
            st.error(f"Household drawers failed: {str(e)}")
            st.code(traceback.format_exc())
            result = None

        if result is not None and hasattr(result, "as_dict"):
            with st.expander("Details (for debugging)", expanded=False):
                st.json(result.as_dict())

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Back to Costs"):
            st.session_state.step = "calculator"
            st.rerun()
    with c2:
        if st.button("View Detailed Breakdown"):
            st.session_state.step = "breakdown"
            st.rerun()
    with c3:
        if st.button("Finish"):
            st.session_state.step = "intro"
            st.rerun()

# BREAKDOWN (lightweight numeric — charts removed to avoid runtime deps)
elif st.session_state.step == "breakdown":
    st.header("Detailed Breakdown")

    people = st.session_state.get("people", [])
    costs = st.session_state.get("person_costs", {})

    care_total = sum(int(costs.get(p["id"], 0)) for p in people)

    s = st.session_state
    inc_A = int(s.get("a_ss", 0)) + int(s.get("a_pn", 0)) + int(s.get("a_other", 0))
    inc_B = int(s.get("b_ss", 0)) + int(s.get("b_pn", 0)) + int(s.get("b_other", 0))
    inc_house = int(s.get("hh_rent", 0)) + int(s.get("hh_annuity", 0)) + int(s.get("hh_invest", 0)) + int(s.get("hh_trust", 0)) + int(s.get("hh_other", 0))

    va_A = int(s.get("a_va_monthly", 0))
    va_B = int(s.get("b_va_monthly", 0))

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
            st.session_state.step = "household"
            st.rerun()
    with b2:
        if st.button("Back to Costs"):
            st.session_state.step = "calculator"
            st.rerun()

# Fallback
else:
    reset_all()
    st.rerun()