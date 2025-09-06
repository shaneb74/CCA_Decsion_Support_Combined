# app.py — Senior Navigator (stable UX + fixed recommendations glue)
# - Answers saved as INT so JSON rules fire
# - Pager reset between people (no Q9/9 carryover)
# - Narrative shown from multiple possible keys
# - JSON files read from repo ROOT
# - Household & Budget delegated to asset_engine.render_household_drawers(st) if present

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple, Optional

import traceback
import json
import streamlit as st

# -------------------------------- Page config ---------------------------------
st.set_page_config(page_title="Senior Navigator • Planner + Cost", page_icon="🧭", layout="centered")

# --------------------------------- Paths --------------------------------------
ROOT = Path(__file__).resolve().parent
QA_PATH  = ROOT / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = ROOT / "recommendation_logic_FINAL_MASTER_UPDATED.json"

# ------------------------------ Engine imports --------------------------------
try:
    from engines import PlannerEngine, CalculatorEngine  # your existing engines.py
except Exception:
    st.error("Failed to import engines.py")
    st.code(traceback.format_exc())
    st.stop()

# Optional: Household drawers separated to asset_engine
asset_engine = None
try:
    import asset_engine as _asset_engine  # your asset_engine.py
    asset_engine = _asset_engine
except Exception:
    asset_engine = None  # we’ll handle gracefully later

# ----------------------------- Load JSON (root) -------------------------------
missing = [p for p in (QA_PATH, REC_PATH) if not p.exists()]
if missing:
    st.error("Missing required JSON files:\n" + "\n".join(f"• {m}" for m in missing))
    st.stop()

try:
    planner = PlannerEngine(str(QA_PATH), str(REC_PATH))
except Exception:
    st.error("PlannerEngine() failed to initialize.")
    st.code(traceback.format_exc())
    st.stop()

try:
    calculator = CalculatorEngine()
except Exception:
    st.error("CalculatorEngine() failed to initialize.")
    st.code(traceback.format_exc())
    st.stop()

# ---------------------------- Small UI helpers --------------------------------
def make_inputs(**kwargs):
    """Create a simple inputs object engines.CalculatorEngine can read."""
    obj = SimpleNamespace()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj

def reset_all():
    for k in list(st.session_state.keys()):
        if not k.startswith("_"):
            del st.session_state[k]
    st.session_state.step = "intro"

# ---------- Safe answer-map helpers (prevents KeyError on non-1..N keys) ------
def order_answer_map(amap: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """
    Return (ordered_keys, ordered_labels) safely whether keys are '1','2',... or arbitrary strings.
    - If all keys are int-like, sort numerically.
    - Else, sort by key as str for stability.
    """
    if not isinstance(amap, dict) or not amap:
        return [], []
    keys = list(amap.keys())

    def _is_intlike(x):
        try:
            int(str(x))
            return True
        except Exception:
            return False

    if all(_is_intlike(k) for k in keys):
        ordered_keys = [str(k) for k in sorted(int(str(k)) for k in keys)]
    else:
        ordered_keys = [str(k) for k in sorted(map(str, keys))]
    ordered_labels = [amap[k] for k in ordered_keys]
    return ordered_keys, ordered_labels

def radio_from_answer_map(
    label: str,
    amap: Dict[str, str],
    *,
    key: str,
    help_text: Optional[str] = None,
    default_key: Optional[str] = None
) -> str:
    """
    Render a radio from an answer map and return the SELECTED KEY (as string).
    """
    ordered_keys, ordered_labels = order_answer_map(amap)
    if not ordered_labels:
        # degenerate safety
        st.write(label)
        return default_key or "1"

    if default_key is not None and str(default_key) in ordered_keys:
        idx = ordered_keys.index(str(default_key))
    else:
        idx = 0

    sel_label = st.radio(label, options=ordered_labels, index=idx, key=key, help=help_text)
    return ordered_keys[ordered_labels.index(sel_label)]

# --------------------------- Session initialization ---------------------------
if "step" not in st.session_state:
    st.session_state.step = "intro"

# keep per-person answers and results
st.session_state.setdefault("people", [])
st.session_state.setdefault("answers", {})           # { person_id: { 'q1': int, ... } }
st.session_state.setdefault("planner_results", {})   # { person_id: {...} }
st.session_state.setdefault("care_overrides", {})    # { person_id: 'in_home' | 'assisted_living' | 'memory_care' | 'none' }
st.session_state.setdefault("current_person", 0)     # index into people
st.session_state.setdefault("_pager", {})            # per-person pager idx: { person_id: int }

# --------------------------------- Sidebar -----------------------------------
st.sidebar.title("Senior Navigator")
st.sidebar.caption("Planner → Costs → Budget → Breakdown")
st.sidebar.button("Start over", on_click=reset_all)

# ================================ FLOW =======================================

# ------------------------------ Intro ----------------------------------------
if st.session_state.step == "intro":
    st.title("Let’s take this one step at a time")
    st.markdown("""
Choosing senior living or in-home support can feel overwhelming.  
This tool breaks it into clear steps.

1. Answer quick care questions → we recommend a care type.  
2. Review costs for that scenario (you can switch it).  
3. Add income, benefits, and assets to see affordability.  
4. View a detailed breakdown you can save or revisit.
""")
    if st.button("Start"):
        st.session_state.step = "audience"
        st.rerun()

# ------------------------------ Audience -------------------------------------
elif st.session_state.step == "audience":
    st.header("Who is this plan for?")
    role = st.radio("Select one:", ["Myself", "My spouse/partner", "My parent", "Both parents", "Someone else"])

    people = []
    if role == "Both parents":
        c1, c2 = st.columns(2)
        with c1:
            n1 = st.text_input("Parent 1 name", value="Mom", key="p1_name", placeholder="Name")
        with c2:
            n2 = st.text_input("Parent 2 name", value="Dad", key="p2_name", placeholder="Name")
        people = [{"id": "A", "display_name": n1, "relationship": "parent"},
                  {"id": "B", "display_name": n2, "relationship": "parent"}]
    else:
        default = "Alex" if role != "My parent" else "Mom"
        n = st.text_input("Name", value=default, key="p_name", placeholder="Name")
        map_rel = {"Myself": "self", "My spouse/partner": "spouse", "My parent": "parent", "Someone else": "other"}
        people = [{"id": "A", "display_name": n, "relationship": map_rel.get(role, "other")}]

    st.caption("Next, we’ll ask short care questions for each person.")

    if st.button("Continue"):
        st.session_state.people = people
        st.session_state.current_person = 0
        # reset answers and results
        st.session_state.answers = {}
        st.session_state.planner_results = {}
        st.session_state.care_overrides = {}
        st.session_state._pager = {}
        # Interstitial if single person (spouse/partner planning option)
        # If you already have a 'partner_context' step you love, jump there:
        st.session_state.step = "planner"
        st.rerun()

# ------------------------------ Planner (Q&A) ---------------------------------
elif st.session_state.step == "planner":
    people = st.session_state.get("people", [])
    if not people:
        st.session_state.step = "audience"
        st.rerun()

    i = st.session_state.get("current_person", 0)
    i = max(0, min(i, len(people) - 1))
    person = people[i]
    pid = person["id"]
    name = person["display_name"]

    st.header(f"Care Plan Questions for {name}")
    st.caption(f"Person {i+1} of {len(people)}")

    # load QA
    qa = getattr(planner, "qa", None) or {}
    questions = qa.get("questions", [])
    cond_cfg = qa.get("conditional_questions")
    st.session_state.answers.setdefault(pid, {})
    answers = st.session_state.answers[pid]

    # per-person pager
    idx = st.session_state._pager.get(pid, 0)
    idx = max(0, min(idx, max(0, len(questions) - 1)))
    st.session_state._pager[pid] = idx

    # show ONE question at a time (mobile friendly)
    if questions:
        q = questions[idx]
        label = f"{q.get('question', f'Question {idx+1}')} (for {name})"
        amap = q.get("answers", {})
        help_text = q.get("help")
        default_key = None
        prev_k = answers.get(f"q{idx+1}")
        if prev_k is not None:
            default_key = str(prev_k)

        sel_key = radio_from_answer_map(
            label, amap, key=f"{pid}_q{idx+1}", help_text=help_text, default_key=default_key
        )
        # *** CRITICAL: store as INT so rule triggers match ***
        try:
            answers[f"q{idx+1}"] = int(sel_key)
        except Exception:
            # fall back: try to coerce known pattern or default 1
            try:
                answers[f"q{idx+1}"] = int(str(sel_key).strip() or "1")
            except Exception:
                answers[f"q{idx+1}"] = 1

        # pager controls
        b1, b2, b3 = st.columns([1,1,1])
        with b1:
            if st.button("Back", disabled=(idx == 0)):
                st.session_state._pager[pid] = max(0, idx - 1)
                st.rerun()
        with b2:
            if st.button("Next", disabled=(idx >= len(questions) - 1)):
                st.session_state._pager[pid] = min(len(questions) - 1, idx + 1)
                st.rerun()
        with b3:
            if st.button("Finish"):
                # optional conditional Q
                conditional_answer = None
                if cond_cfg:
                    cq = cond_cfg[0]
                    camap = cq.get("answers", {"1": "Yes", "2": "No"})
                    # pick from saved state if you render it elsewhere
                    # We’ll not render inline here to preserve UX; PlannerEngine
                    # should handle None safely.
                    for k in ("1","2","3"):
                        if k not in camap:
                            continue
                    # leave conditional_answer=None if you don't show it

                # Run engine
                try:
                    res = planner.run(answers, conditional_answer=conditional_answer)
                except Exception:
                    st.error("PlannerEngine.run failed.")
                    st.code(traceback.format_exc())
                    st.stop()

                # collect engine result robustly
                if hasattr(res, "__dict__"):
                    care_type = getattr(res, "care_type", None)
                    flags     = set(getattr(res, "flags", set()) or set())
                    scores    = getattr(res, "scores", {}) or {}
                    reasons   = list(getattr(res, "reasons", []) or [])
                    narrative = (getattr(res, "advisory", None)
                                 or getattr(res, "message", None)
                                 or getattr(res, "message_rendered", None)
                                 or getattr(res, "narrative", None))
                else:
                    care_type = res.get("care_type")
                    flags     = set(res.get("flags", []))
                    scores    = res.get("scores", {})
                    reasons   = list(res.get("reasons", []))
                    narrative = (res.get("advisory")
                                 or res.get("message")
                                 or res.get("message_rendered")
                                 or res.get("narrative"))

                st.session_state.planner_results[pid] = {
                    "care_type": care_type or "in_home",
                    "flags": flags,
                    "scores": scores,
                    "reasons": reasons,
                    "advisory": narrative or "",
                }

                # Move to next person or recommendations
                if i + 1 < len(people):
                    st.session_state.current_person = i + 1
                    # *** CRITICAL: reset pager and ensure fresh answers for next person ***
                    next_pid = people[i + 1]["id"]
                    st.session_state._pager[next_pid] = 0
                    st.session_state.answers.setdefault(next_pid, {})
                    st.rerun()
                else:
                    st.session_state.step = "recommendations"
                    st.rerun()
    else:
        st.info("No questions found in the planner JSON.")

# --------------------------- Recommendations ----------------------------------
elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without redoing questions.")

    for p in st.session_state.people:
        pid = p["id"]
        name = p["display_name"]
        rec = st.session_state.planner_results.get(pid, {}) or {}
        default_type = rec.get("care_type", "in_home")
        flags = rec.get("flags", set())
        reasons = rec.get("reasons", [])

        st.subheader(f"{name}: {default_type.replace('_',' ').title()} (recommended)")
        # Reasons as bullets (if present)
        if reasons:
            for r in reasons:
                st.write("• " + str(r))
        # Conversational narrative (from any key)
        narrative = (
            rec.get("advisory")
            or rec.get("message")
            or rec.get("narrative")
            or rec.get("message_rendered")
        )
        if narrative:
            st.info(narrative)

        # Allow override but keep recommended as default
        care_choices = ["none", "in_home", "assisted_living", "memory_care"]
        labels = {
            "none": "No plan needed",
            "in_home": "In-home Care",
            "assisted_living": "Assisted Living",
            "memory_care": "Memory Care",
        }
        idx = care_choices.index(default_type) if default_type in care_choices else care_choices.index("in_home")
        label_sel = st.selectbox(
            f"Care scenario for {name}",
            [labels[c] for c in care_choices],
            index=idx,
            key=f"override_{pid}",
            help="You can compare a different scenario without redoing questions."
        )
        reverse = {v: k for k, v in labels.items()}
        st.session_state.care_overrides[pid] = reverse[label_sel]

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

# ------------------------------ Calculator -----------------------------------
elif st.session_state.step == "calculator":
    st.header("Cost Planner")

    # simple state selection that your CalculatorEngine can use as a multiplier
    state = st.selectbox("Location", ["National", "Washington", "California", "Texas", "Florida"])

    total = 0
    for p in st.session_state.people:
        pid = p["id"]
        name = p["display_name"]
        rec = st.session_state.planner_results.get(pid, {}) or {}
        care_type = st.session_state.get("care_overrides", {}).get(pid, rec.get("care_type", "in_home"))

        st.subheader(f"{name} — Scenario: {care_type.replace('_', ' ').title()} "
                     f"(recommended: {rec.get('care_type','in_home').replace('_',' ').title()})")

        # Minimal knobs (match your engine expectations)
        care_level = st.selectbox("Care Level (staffing intensity)", ["Low", "Medium", "High"], key=f"{pid}_care_level")
        mobility   = st.selectbox("Mobility", ["Independent", "Assisted", "Non-ambulatory"], key=f"{pid}_mobility")
        chronic    = st.selectbox("Chronic Conditions", ["None", "Some", "Multiple/Complex"], key=f"{pid}_chronic")

        # Build inputs and compute monthly
        inp = make_inputs(
            state=state, care_type=care_type, care_level=care_level, mobility=mobility, chronic=chronic
        )
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
        total += int(monthly)
        st.divider()

    st.subheader("Combined Total")
    st.metric("Estimated Combined Monthly Cost", f"${total:,.0f}")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Back to recommendations"):
            st.session_state.step = "recommendations"
            st.rerun()
    with c2:
        if st.button("Add Household & Assets (optional)"):
            st.session_state.step = "household"
            st.rerun()
    with c3:
        if st.button("Finish"):
            st.session_state.step = "intro"
            st.rerun()

# --------------------------- Household & Budget -------------------------------
elif st.session_state.step == "household":
    st.header("Household & Budget (optional)")
    st.markdown("Add income, benefits, assets, home decisions, and other costs to see affordability. You can skip this.")

    if asset_engine and hasattr(asset_engine, "render_household_drawers"):
        try:
            result = asset_engine.render_household_drawers(st)  # returns HouseholdResult
            # We don’t need to do anything else here; asset_engine handles UX and
            # stores subtotals in st.session_state for the breakdown page if you have one.
        except Exception:
            st.error("Household drawers failed.")
            st.code(traceback.format_exc())
    else:
        st.error("Household drawers module not found (asset_engine.render_household_drawers).")

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back to Costs"):
            st.session_state.step = "calculator"
            st.rerun()
    with c2:
        if st.button("Finish"):
            st.session_state.step = "intro"
            st.rerun()

# ------------------------------- Fallback -------------------------------------
else:
    st.session_state.step = "intro"
    st.rerun()