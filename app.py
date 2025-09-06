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
QA_PATH  = ROOT / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = ROOT / "recommendation_logic_FINAL_MASTER_UPDATED.json"

# ----------------------- Imports ---------------------------
try:
    from engines import PlannerEngine, CalculatorEngine  # user-provided engines.py
except Exception:
    st.error("Failed to import engines.py")
    st.code(traceback.format_exc())
    st.stop()

# isolate drawers (no UX changes but kept outside app.py)
try:
    import asset_engine  # user-provided asset_engine.py
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
    """Return (ordered_keys, ordered_labels) even if the JSON answer keys are not '1'..'N'."""
    if not isinstance(amap, dict) or not amap:
        return [], []
    keys = list(amap.keys())
    if all(_is_intlike(k) for k in keys):
        ordered_keys = [str(k) for k in sorted(int(str(k)) for k in keys)]
    else:
        ordered_keys = [str(k) for k in keys]  # preserve JSON insertion order
    labels = [amap[k] for k in ordered_keys]
    return ordered_keys, labels


def radio_from_answer_map(label, amap, *, key, help_text=None, default_key=None) -> str | None:
    keys, labels = order_answer_map(amap)
    if not labels:
        return default_key
    if default_key is not None and str(default_key) in keys:
        idx = keys.index(str(default_key))
    else:
        idx = 0
    sel_label = st.radio(label, labels, index=idx, key=key, help=help_text)
    return keys[labels.index(sel_label)]


def clamp(n, lo, hi):
    return max(lo, min(hi, n))


# ----------------------- Load JSONs ------------------------
missing = [p for p in (QA_PATH, REC_PATH) if not p.exists()]
if missing:
    st.error("Missing required JSON files:\n" + "\n".join(f"• {m}" for m in missing))
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
        people = [
            {"id": "A", "display_name": n1, "relationship": "parent"},
            {"id": "B", "display_name": n2, "relationship": "parent"},
        ]
    else:
        default = "Alex" if role != "My parent" else "Mom"
        n = st.text_input("Name", value=default, key="p_name", placeholder="Name")
        map_rel = {"Myself": "self", "My spouse/partner": "spouse", "My parent": "parent", "Someone else": "other"}
        people = [{"id": "A", "display_name": n, "relationship": map_rel.get(role, "other")}]

    st.caption("Next, we’ll ask short care questions for each person.")
    if st.button("Continue"):
        st.session_state.people = people
        st.session_state.current_person = 0
        st.session_state.answers = {}
        st.session_state.planner_results = {}
        st.session_state.step = "partner_interstitial" if role != "Both parents" else "planner"
        st.rerun()

# PARTNER INTERSTITIAL (only when a single person was chosen)
elif st.session_state.step == "partner_interstitial":
    people = st.session_state.get("people", [])
    primary = people[0]["display_name"] if people else "Person A"

    st.header("Before we begin")
    st.markdown(
        f"""
If **{primary}** needs assisted living or memory care, their spouse/partner may also need some in-home help.

Would you like to evaluate a care support plan for a spouse/partner now so the household picture is complete?
"""
    )

    add = st.checkbox(
        "Yes, I want to evaluate a plan for a spouse/partner",
        value=False,
        key="care_partner_add",
    )
    if add:
        st.text_input(
            "Spouse/partner name",
            value="",
            placeholder="Enter spouse/partner name",
            key="care_partner_name",
        )
    c1, c2 = st.columns(2)
    with c1:
        if st.button(f"No, let’s just plan for **{primary}**"):
            st.session_state.step = "planner"
            st.rerun()
    with c2:
        disabled = not st.session_state.get("care_partner_add", False)
        if st.button("Add spouse/partner and continue", disabled=disabled):
            if add:
                st.session_state.people.append(
                    {
                        "id": "B",
                        "display_name": st.session_state.get("care_partner_name") or "Spouse/Partner",
                        "relationship": "spouse",
                    }
                )
            st.session_state.step = "planner"
            st.rerun()

# PLANNER (one question at a time)
elif st.session_state.step == "planner":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if not people:
        reset_all()
        st.rerun()

    person = people[i]
    pid = person["id"]
    name = person["display_name"]

    # load Q&A
    qa = getattr(planner, "qa", None) or {}
    questions = qa.get("questions", [])
    cond_cfg = qa.get("conditional_questions")  # list (optional)

    # per-person wizard index
    wizard_key = f"wizard_idx_{pid}"
    if wizard_key not in st.session_state:
        st.session_state[wizard_key] = 0
    idx = int(st.session_state[wizard_key])
    idx = clamp(idx, 0, max(0, len(questions) - 1))

    st.title(f"Care Plan Questions for {name}")
    st.caption(f"Person {i+1} of {len(people)} • Question {idx+1} of {len(questions)}")

    answers = st.session_state.answers.get(pid, {})

    # Render the single question at current index
    q = questions[idx]
    qlabel = q.get("question", f"Question {idx+1}")
    amap = q.get("answers", {})
    help_text = q.get("help")

    prev_key = answers.get(f"q{idx+1}")
    selected_key = radio_from_answer_map(
        f"{qlabel} (for {name})",
        amap,
        key=f"{pid}_q_{idx+1}",
        help_text=help_text,
        default_key=str(prev_key) if prev_key is not None else None,
    )
    if selected_key is not None:
        answers[f"q{idx+1}"] = int(selected_key) if _is_intlike(selected_key) else selected_key

    # Save back
    st.session_state.answers[pid] = answers

    # Nav controls
    b1, b2, b3 = st.columns([1, 1, 1])
    with b1:
        if st.button("Back", disabled=(idx == 0)):
            st.session_state[wizard_key] = clamp(idx - 1, 0, len(questions) - 1)
            st.rerun()
    with b2:
        if st.button("Next", disabled=(idx >= len(questions) - 1)):
            st.session_state[wizard_key] = clamp(idx + 1, 0, len(questions) - 1)
            st.rerun()
    with b3:
        if st.button("Finish", disabled=(idx != len(questions) - 1)):
            # Run engine (tolerate old/new signatures)
            try:
                res = planner.run(answers, conditional_answer=None)
            except TypeError:
                res = planner.run(answers)
            except Exception:
                st.error("PlannerEngine.run failed.")
                st.code(traceback.format_exc())
                st.stop()

            # normalize result
            if hasattr(res, "__dict__"):
                care_type = getattr(res, "care_type", None)
                flags = set(getattr(res, "flags", set()) or set())
                scores = getattr(res, "scores", {}) or {}
                reasons = list(getattr(res, "reasons", []) or [])
                narrative = (
                    getattr(res, "advisory", None)
                    or getattr(res, "message", None)
                    or getattr(res, "message_rendered", None)
                    or getattr(res, "narrative", None)
                )
            else:
                care_type = res.get("care_type")
                flags = set(res.get("flags", []))
                scores = res.get("scores", {})
                reasons = list(res.get("reasons", []))
                narrative = res.get("advisory") or res.get("message") or res.get("message_rendered") or res.get("narrative")

            # fail-safe default
            care_type = care_type or "in_home"

            st.session_state.planner_results[pid] = {
                "care_type": care_type,
                "flags": flags,
                "scores": scores,
                "reasons": reasons,
                "advisory": narrative or "",
            }

            # reset idx for next person
            st.session_state[wizard_key] = 0

            # handle next person or interstitial
            if i + 1 < len(people):
                st.session_state.current_person = i + 1
                st.session_state.step = "next_person_interstitial"
            else:
                st.session_state.step = "recommendations"
            st.rerun()

# INTERSTITIAL between persons
elif st.session_state.step == "next_person_interstitial":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    prev = people[i - 1]["display_name"] if i > 0 else "Person A"
    current = people[i]["display_name"] if i < len(people) else "Next"

    st.header("Great—first care plan complete")
    st.markdown(f"We’ve finished **{prev}**. Now let’s assess **{current}**.")
    if st.button(f"Start {current}'s questions"):
        st.session_state.step = "planner"
        st.rerun()

# RECOMMENDATIONS
elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without redoing questions.")

    for p in st.session_state.get("people", []):
        pid = p["id"]
        name = p["display_name"]
        rec = st.session_state.planner_results.get(pid, {})

        care_type = rec.get("care_type", "in_home")
        reasons = rec.get("reasons", [])
        narrative = (
            rec.get("advisory")
            or rec.get("message")
            or rec.get("narrative")
            or rec.get("message_rendered")
        )

        human = {"in_home": "In-home Care", "assisted_living": "Assisted Living", "memory_care": "Memory Care", "none": "None"}
        st.subheader(f"{name}: {human.get(care_type, care_type.replace('_',' ').title())} (recommended)")

        # bullets (friendly summaries, if any)
        for r in reasons:
            st.write("• " + str(r))

        if narrative:
            st.info(narrative)

        labels = ["In-home Care", "Assisted Living", "Memory Care", "No plan needed"]
        reverse = {
            "In-home Care": "in_home",
            "Assisted Living": "assisted_living",
            "Memory Care": "memory_care",
            "No plan needed": "none",
        }
        current_label = [k for k, v in reverse.items() if v == care_type]
        label_idx = labels.index(current_label[0]) if current_label else 0
        sel = st.selectbox(
            f"Care scenario for {name}",
            labels,
            index=label_idx,
            key=f"override_{pid}",
            help="Compare a different scenario without repeating the questions.",
        )
        st.session_state.setdefault("care_overrides", {})[pid] = reverse[sel]

        st.divider()

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back to questions"):
            st.session_state.step = "planner"
            st.rerun()
    with c2:
        if st.button("See Costs"):
            st.session_state.step = "calculator"
            st.rerun()

# CALCULATOR (lean; in-home vs AL/MC)
elif st.session_state.step == "calculator":
    st.header("Cost Planner")

    # simple location selector used by CalculatorEngine internally if it supports it
    state = st.selectbox("Location", ["National", "California", "Florida", "Texas", "Washington"], key="calc_state")

    combined = 0
    st.session_state.setdefault("person_costs", {})

    for p in st.session_state.get("people", []):
        pid = p["id"]
        name = p["display_name"]

        base_rec = st.session_state.planner_results.get(pid, {}).get("care_type", "in_home")
        care_type = st.session_state.get("care_overrides", {}).get(pid, base_rec)

        st.subheader(f"{name} — Scenario: {care_type.replace('_',' ').title()}")

        inp = make_inputs(state=state, care_type=care_type)

        # Simple in-home toggles (hours × days)
        if care_type == "in_home":
            hrs = st.slider("In-home care hours per day", 0, 24, 4, 1, key=f"{pid}_hrs")
            days = st.slider("Days per month", 0, 31, 20, 1, key=f"{pid}_days")
            setattr(inp, "in_home_hours_per_day", int(hrs))
            setattr(inp, "in_home_days_per_month", int(days))
        else:
            room = st.selectbox("Room Type", ["Studio", "1 Bedroom", "Shared"], key=f"{pid}_room")
            setattr(inp, "room_type", room)

        # Compute
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
        st.error("asset_engine.py not found. Please include it in the repo root.")
    else:
        try:
            # Preferred new API
            if hasattr(asset_engine, "render_household_drawers"):
                result = asset_engine.render_household_drawers(st)  # returns HouseholdResult
            # Backward-compat function name
            elif hasattr(asset_engine, "render_drawers"):
                result = asset_engine.render_drawers(st)
            # Class-based API fallback
            elif hasattr(asset_engine, "HouseholdEngine"):
                eng = asset_engine.HouseholdEngine()
                result = eng.render(st)
            else:
                raise AttributeError("asset_engine has no recognized render function.")
        except Exception:
            st.error("Household drawers failed.")
            st.code(traceback.format_exc())
            result = None

        if result is not None and hasattr(result, "to_dict"):
            with st.expander("Details (for debugging)", expanded=False):
                st.json(result.to_dict())

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
    costs  = st.session_state.get("person_costs", {})

    care_total = sum(int(costs.get(p["id"], 0)) for p in people)

    s = st.session_state
    inc_A = int(s.get("a_ss", 0)) + int(s.get("a_pn", 0)) + int(s.get("a_other", 0))
    inc_B = int(s.get("b_ss", 0)) + int(s.get("b_pn", 0)) + int(s.get("b_other", 0))
    inc_house = int(s.get("hh_rent", 0)) + int(s.get("hh_annuity", 0)) + int(s.get("hh_invest", 0)) + int(s.get("hh_trust", 0)) + int(s.get("hh_other", 0))

    va_A = int(s.get("a_va_monthly", 0))
    va_B = int(s.get("b_va_monthly", 0))

    home_monthly   = int(s.get("home_monthly_total", 0))
    mods_monthly   = int(s.get("mods_monthly_total", 0))
    other_monthly  = int(s.get("other_monthly_total", 0))
    addl_costs     = home_monthly + mods_monthly + other_monthly

    assets_common  = int(s.get("assets_common_total", 0))
    assets_detail  = int(s.get("assets_detailed_total", 0))
    assets_total   = assets_common + assets_detail

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