from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from dataclasses import asdict, is_dataclass
import traceback
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

# --------------------------------------------------------------------------------------
# Page config
# --------------------------------------------------------------------------------------
st.set_page_config(
    page_title="Senior Navigator • Planner + Cost",
    page_icon="🧭",
    layout="centered",
)

# --------------------------------------------------------------------------------------
# Robust answer-map helpers
# --------------------------------------------------------------------------------------
def _is_intlike(x: Any) -> bool:
    try:
        int(str(x))
        return True
    except Exception:
        return False


def order_answer_map(amap: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """Return (ordered_keys, ordered_labels) whether keys are 1..N strings or arbitrary."""
    if not isinstance(amap, dict) or not amap:
        return [], []
    keys = list(amap.keys())
    if all(_is_intlike(k) for k in keys):
        ordered_keys = [str(k) for k in sorted(int(str(k)) for k in keys)]
    else:
        ordered_keys = [str(k) for k in keys]  # insertion order is preserved by JSON
    labels = [amap[k] for k in ordered_keys]
    return ordered_keys, labels


def radio_from_answer_map(
    label: str,
    amap: Dict[str, str],
    *,
    key: str,
    help_text: Optional[str] = None,
    default_key: Optional[str] = None,
) -> Optional[str]:
    """Render a radio group from a JSON answer map and return the selected KEY (string)."""
    keys, labels = order_answer_map(amap)
    if not keys:
        return default_key
    if default_key and default_key in keys:
        idx = keys.index(default_key)
    else:
        idx = 0
    sel_label = st.radio(label, options=labels, index=idx, key=key, help=help_text)
    # map back to key
    return keys[labels.index(sel_label)]

# --------------------------------------------------------------------------------------
# Paths (root, not /data)
# --------------------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
QA_PATH  = ROOT / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = ROOT / "recommendation_logic_FINAL_MASTER_UPDATED.json"

# --------------------------------------------------------------------------------------
# Engines
# --------------------------------------------------------------------------------------
try:
    from engines import PlannerEngine, CalculatorEngine  # your existing file
except Exception:
    st.error("Failed to import engines.py")
    st.code(traceback.format_exc())
    st.stop()

# Optional household drawers engine (you provided this)
asset_engine = None
try:
    import asset_engine as _ae
    asset_engine = _ae
except Exception:
    asset_engine = None  # We'll handle gracefully below

# Check JSON files exist
missing = [p for p in (QA_PATH, REC_PATH) if not p.exists()]
if missing:
    st.error("Missing required JSON files:\n" + "\n".join(f"• {m}" for m in missing))
    st.stop()

# Instantiate engines
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

# --------------------------------------------------------------------------------------
# State helpers
# --------------------------------------------------------------------------------------
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


def _norm_planner_result(res: Any, person_name: str) -> Dict[str, Any]:
    """
    Normalize whatever PlannerEngine.run returns into the dict shape we use everywhere.
    Expected keys:
      - care_type: "in_home" | "assisted_living" | "memory_care" | "none"
      - flags: set/list
      - scores: dict
      - reasons: list[str]
      - narrative/advisory/message/message_rendered: optional strings
    """
    def _grab_narrative(obj: Any) -> Optional[str]:
        for k in ("narrative", "advisory", "message", "message_rendered"):
            v = getattr(obj, k, None) if not isinstance(obj, dict) else obj.get(k)
            if v:
                return str(v).replace("{name}", person_name)
        return None

    if hasattr(res, "__dict__") or is_dataclass(res):
        d = asdict(res) if is_dataclass(res) else res.__dict__
        care_type = d.get("care_type") or "in_home"
        flags     = set(d.get("flags", []) or [])
        scores    = d.get("scores", {}) or {}
        reasons   = list(d.get("reasons", []) or [])
        narrative = _grab_narrative(d)
    elif isinstance(res, dict):
        care_type = res.get("care_type") or "in_home"
        flags     = set(res.get("flags", []) or [])
        scores    = res.get("scores", {}) or {}
        reasons   = list(res.get("reasons", []) or [])
        narrative = _grab_narrative(res)
    else:
        # Total fallback, shouldn't happen
        care_type, flags, scores, reasons, narrative = "in_home", set(), {}, [], None

    return {
        "care_type": care_type,
        "flags": flags,
        "scores": scores,
        "reasons": reasons,
        "advisory": narrative or "",
    }


def _init_session_once():
    ss = st.session_state
    if "step" not in ss:
        ss.step = "intro"
    ss.setdefault("people", [])
    ss.setdefault("current_person", 0)
    ss.setdefault("answers", {})          # per person id -> {"q1": "1", ...}
    ss.setdefault("planner_results", {})  # per person id -> normalized dict
    ss.setdefault("care_overrides", {})   # per person id -> care_type str
    ss.setdefault("person_costs", {})     # per person id -> monthly int
    ss.setdefault("combined_monthly_cost", 0)

_init_session_once()

st.sidebar.title("Senior Navigator")
st.sidebar.caption("Planner → Costs → Budget → Breakdown")
st.sidebar.button("Start over", on_click=reset_all)

# --------------------------------------------------------------------------------------
# Flow
# --------------------------------------------------------------------------------------

# Intro -------------------------------------------------------------------------------
if st.session_state.step == "intro":
    st.title("Let’s take this one step at a time")
    st.markdown(
        "Choosing senior living or in-home support can feel overwhelming. "
        "This tool breaks it into clear steps."
    )
    st.markdown(
        "1) Answer quick care questions → we recommend a care type.  \n"
        "2) Review costs for that scenario (you can switch it).  \n"
        "3) Add income, benefits, and assets to see affordability.  \n"
        "4) View a detailed breakdown you can save or revisit."
    )
    if st.button("Start"):
        st.session_state.step = "audience"
        st.rerun()

# Audience ----------------------------------------------------------------------------
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
        map_rel = {
            "Myself": "self",
            "My spouse/partner": "spouse",
            "My parent": "parent",
            "Someone else": "other",
        }
        people = [{"id": "A", "display_name": n, "relationship": map_rel.get(role, "other")}]

    st.caption("Next, we’ll ask short care questions for each person.")
    if st.button("Continue"):
        st.session_state.people = people
        st.session_state.current_person = 0
        st.session_state.answers = {}
        st.session_state.planner_results = {}
        st.session_state.care_overrides = {}
        st.session_state.person_costs = {}
        # Route: if single person and NOT "Both parents", show spouse interstitial
        if role != "Both parents":
            st.session_state.step = "partner_context"
        else:
            st.session_state.step = "planner"
        st.rerun()

# Interstitial (spouse prompt) --------------------------------------------------------
elif st.session_state.step == "partner_context":
    people = st.session_state.get("people", [])
    single = len(people) == 1
    primary = people[0]["display_name"] if people else "Person A"

    st.header("Before we begin")
    st.markdown(
        f"If **{primary}** needs assisted living or memory care, their spouse/partner may also need "
        "some in-home help. You can include a simple support plan for them so the household picture "
        "is complete."
    )
    if single:
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
        btn_disabled = not st.session_state.get("care_partner_add", False)
        if st.button("Add spouse/partner and continue", disabled=btn_disabled):
            if single and st.session_state.get("care_partner_add"):
                st.session_state.people.append(
                    {
                        "id": "B",
                        "display_name": st.session_state.get("care_partner_name") or "Spouse/Partner",
                        "relationship": "spouse",
                    }
                )
            st.session_state.step = "planner"
            st.rerun()

# Planner (one-question wizard; desktop toggle to show all) ---------------------------
elif st.session_state.step == "planner":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if not people:
        reset_all(); st.rerun()
    person = people[i]
    pid = person["id"]
    name = person["display_name"]

    st.header(f"Care Plan — {name}")
    show_all = st.toggle("Show all questions (desktop reviewers)", value=False, help="Mobile shows one at a time")

    qa = getattr(planner, "qa", {}) or {}
    questions: List[Dict[str, Any]] = qa.get("questions", [])
    answers = st.session_state.answers.get(pid, {})

    if show_all:
        # Render all questions stacked
        for idx, q in enumerate(questions, start=1):
            amap = q.get("answers", {}) or {}
            sel_key = radio_from_answer_map(
                f"{q.get('question', f'Question {idx}')}",
                amap,
                key=f"{pid}_q{idx}",
                help_text=q.get("help"),
                default_key=str(answers.get(f"q{idx}", None)),
            )
            if sel_key is not None:
                answers[f"q{idx}"] = sel_key
        st.session_state.answers[pid] = answers

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Back"):
                if i == 0:
                    st.session_state.step = "partner_context" if len(people) == 1 else "audience"
                else:
                    st.session_state.current_person = i - 1
                st.rerun()
        with c2:
            if st.button("Finish"):
                try:
                    res = planner.run(answers)  # DO NOT pass unknown kwargs
                except Exception:
                    st.error("PlannerEngine.run failed.")
                    st.code(traceback.format_exc())
                    st.stop()

                norm = _norm_planner_result(res, name)
                st.session_state.planner_results[pid] = norm

                if i + 1 < len(people):
                    st.session_state.step = "next_person"
                else:
                    st.session_state.step = "recommendations"
                st.rerun()

    else:
        # One question at a time
        total_q = len(questions)
        idx = int(st.session_state.get(f"idx_{pid}", 0))
        idx = max(0, min(idx, total_q - 1))

        st.progress((idx + 1) / max(1, total_q), text=f"Question {idx + 1} of {total_q}")

        q = questions[idx]
        amap = q.get("answers", {}) or {}
        sel_key = radio_from_answer_map(
            f"{q.get('question', f'Question {idx+1}')}",
            amap,
            key=f"{pid}_q{idx+1}",
            help_text=q.get("help"),
            default_key=str(answers.get(f"q{idx+1}", None)),
        )
        if sel_key is not None:
            answers[f"q{idx+1}"] = sel_key
        st.session_state.answers[pid] = answers

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Back"):
                if idx == 0:
                    if i == 0:
                        st.session_state.step = "partner_context" if len(people) == 1 else "audience"
                    else:
                        # go back to previous person
                        st.session_state.current_person = i - 1
                        # ensure we start at their last index (or 0)
                    st.rerun()
                else:
                    st.session_state[f"idx_{pid}"] = idx - 1
                    st.rerun()
        with c2:
            # Next or Finish
            if idx + 1 < total_q:
                if st.button("Next"):
                    st.session_state[f"idx_{pid}"] = idx + 1
                    st.rerun()
            else:
                if st.button("Finish"):
                    try:
                        res = planner.run(answers)
                    except Exception:
                        st.error("PlannerEngine.run failed.")
                        st.code(traceback.format_exc())
                        st.stop()
                    norm = _norm_planner_result(res, name)
                    st.session_state.planner_results[pid] = norm

                    # Reset index for next person to start at Q1
                    st.session_state[f"idx_{pid}"] = 0

                    if i + 1 < len(people):
                        st.session_state.step = "next_person"
                    else:
                        st.session_state.step = "recommendations"
                    st.rerun()

# Interstitial between people ---------------------------------------------------------
elif st.session_state.step == "next_person":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if i + 1 >= len(people):
        st.session_state.step = "recommendations"; st.rerun()

    finished_name = people[i]["display_name"]
    next_name = people[i + 1]["display_name"]
    st.header("Great work!")
    st.markdown(f"We’ve completed the Care Plan for **{finished_name}**. Now let’s assess **{next_name}**.")
    if st.button(f"Start {next_name}’s questions"):
        st.session_state.current_person = i + 1
        # reset the per-person index
        st.session_state[f"idx_{people[i+1]['id']}"] = 0
        st.session_state.step = "planner"
        st.rerun()

# Recommendations ---------------------------------------------------------------------
elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without redoing questions.")

    label_map = {
        "none": "No care needed",
        "in_home": "In-home Care",
        "assisted_living": "Assisted Living",
        "memory_care": "Memory Care",
    }
    reverse_label_map = {v: k for k, v in label_map.items()}

    for p in st.session_state.people:
        pid = p["id"]
        name = p["display_name"]
        rec = st.session_state.planner_results.get(pid, {})

        rec_type = rec.get("care_type", "in_home")
        narrative = rec.get("advisory") or ""
        reasons = list(rec.get("reasons", []))

        st.subheader(f"{name}: {label_map.get(rec_type, rec_type).title()} (recommended)")
        if reasons:
            for r in reasons:
                st.write("• " + str(r))
        if narrative:
            st.info(narrative.replace("{name}", name))

        # Allow override without re-answering
        current_label = label_map.get(rec_type, "In-home Care")
        sel = st.selectbox(
            f"Care scenario for {name}",
            list(label_map.values()),
            index=list(label_map.values()).index(current_label),
            key=f"override_{pid}",
            help="Compare a different scenario without repeating the questions.",
        )
        st.session_state.care_overrides[pid] = reverse_label_map[sel]

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

# Calculator --------------------------------------------------------------------------
elif st.session_state.step == "calculator":
    st.header("Cost Planner")

    state = st.selectbox(
        "Location",
        ["National", "Washington", "California", "Texas", "Florida"],
        help="Adjusts for typical market rates in the selected state."
    )

    total = 0
    for p in st.session_state.people:
        pid = p["id"]
        name = p["display_name"]
        rec = st.session_state.planner_results.get(pid, {})
        care_type = st.session_state.care_overrides.get(pid, rec.get("care_type", "in_home"))

        st.subheader(f"{name} — Scenario: {care_type.replace('_', ' ').title()} "
                     f"(recommended: {rec.get('care_type','in_home').replace('_',' ').title()})")

        # Defaults informed by flags if present
        flags = rec.get("flags", set()) or set()
        default_care_level = "High" if ("severe_cognitive_risk" in flags or care_type == "memory_care") else "Medium"

        care_level = st.selectbox(
            "Care Level (staffing intensity)",
            ["Low", "Medium", "High"],
            index=["Low", "Medium", "High"].index(default_care_level),
            key=f"{pid}_care_level"
        )

        mobility_label = st.selectbox(
            "Mobility",
            ["Independent (no device)", "Assisted (cane/walker or needs help)", "Non-ambulatory (wheelchair/bedbound)"],
            index=1 if "high_mobility_dependence" in flags else 0,
            key=f"{pid}_mobility"
        )
        mobility_map = {
            "Independent (no device)": "Independent",
            "Assisted (cane/walker or needs help)": "Assisted",
            "Non-ambulatory (wheelchair/bedbound)": "Non-ambulatory"
        }
        mobility = mobility_map[mobility_label]

        chronic_label = st.selectbox(
            "Chronic conditions",
            ["None (no ongoing conditions)", "Some (1–2 manageable conditions)", "Multiple/Complex (several or complex needs)"],
            index=2 if "multiple_chronic" in flags else 1,
            key=f"{pid}_chronic"
        )
        chronic_map = {
            "None (no ongoing conditions)": "None",
            "Some (1–2 manageable conditions)": "Some",
            "Multiple/Complex (several or complex needs)": "Multiple/Complex"
        }
        chronic = chronic_map[chronic_label]

        inp = make_inputs(
            state=state,
            care_type=care_type,
            care_level=care_level,
            mobility=mobility,
            chronic=chronic
        )

        if care_type in ("assisted_living", "memory_care"):
            for k in (f"{pid}_hours", f"{pid}_days"):
                if k in st.session_state:
                    del st.session_state[k]
            room = st.selectbox("Room Type", ["Studio", "1 Bedroom", "Shared"], key=f"{pid}_room")
            setattr(inp, "room_type", room)
        else:
            if f"{pid}_room" in st.session_state:
                del st.session_state[f"{pid}_room"]
            hours = st.slider("In-home care hours per day", 0, 24, 4, 1, key=f"{pid}_hours")
            days = st.slider("Days of care per month", 0, 31, 20, 1, key=f"{pid}_days")
            setattr(inp, "in_home_hours_per_day", int(hours))
            setattr(inp, "in_home_days_per_month", int(days))

        # Compute monthly cost
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
        st.session_state.person_costs[pid] = int(monthly)
        st.divider()
        total += int(monthly)

    st.subheader("Combined Total")
    st.session_state.combined_monthly_cost = total
    st.metric("Estimated Combined Monthly Cost", f"${total:,.0f}")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Back to recommendations"):
            st.session_state.step = "recommendations"
            st.rerun()
    with c2:
        if st.button("Add Household & Budget"):
            st.session_state.step = "household"
            st.rerun()
    with c3:
        if st.button("View Detailed Breakdown"):
            st.session_state.step = "breakdown"
            st.rerun()

# Household & Budget (delegated to asset_engine) --------------------------------------
elif st.session_state.step == "household":
    st.header("Household & Budget (optional)")
    st.markdown("Add income, benefits, assets, home decisions, and other costs to see affordability. You can skip this.")

    if asset_engine is None:
        st.error("`asset_engine.py` was not imported. Make sure it exists in the repo root.")
    else:
        try:
            # Prefer the new function name; fallback to older names if your file differs
            render_fn = None
            for cand in ("render_household_drawers", "render_household_section", "render"):
                if hasattr(asset_engine, cand):
                    render_fn = getattr(asset_engine, cand)
                    break
            if render_fn is None:
                raise AttributeError("asset_engine has no render_* function exported.")

            result = render_fn(st)  # should return a dataclass or simple dict totals
            # Persist any useful totals to session for breakdown
            if result is not None:
                if is_dataclass(result):
                    result = asdict(result)
                # Expected keys (your asset engine already computes these); guard if missing
                st.session_state["household_income_total"] = int(result.get("income_total", 0))
                st.session_state["household_benefits_total"] = int(result.get("benefits_total", 0))
                st.session_state["household_costs_monthly"] = int(result.get("monthly_costs_total", 0))
                st.session_state["assets_total"] = int(result.get("assets_total", 0))
        except Exception:
            st.error("Household drawers failed.")
            st.code(traceback.format_exc())

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

# Breakdown ----------------------------------------------------------------------------
elif st.session_state.step == "breakdown":
    st.header("Detailed Breakdown")

    people = st.session_state.get("people", [])
    costs  = st.session_state.get("person_costs", {})

    care_total = sum(int(costs.get(p["id"], 0)) for p in people)

    # Household subtotals captured from drawers (if any)
    income_individual = int(st.session_state.get("household_income_total", 0))
    benefits_total    = int(st.session_state.get("household_benefits_total", 0))
    other_monthly     = int(st.session_state.get("household_costs_monthly", 0))
    assets_total      = int(st.session_state.get("assets_total", 0))

    income_total = income_individual + benefits_total
    monthly_need = care_total + other_monthly
    gap = monthly_need - income_total

    c1, c2, c3 = st.columns(3)
    c1.metric("Monthly Care + Selected Costs", f"${monthly_need:,.0f}")
    c2.metric("Total Monthly Income (incl. benefits)", f"${income_total:,.0f}")
    c3.metric("Estimated Monthly Gap", f"${gap:,.0f}")

    years = 0.0
    if gap > 0 and assets_total > 0:
        years = round(assets_total / max(gap, 1), 1)
    st.subheader(f"Estimated runway from assets: {years} years")

    # Per-person detail
    st.markdown("### Per-person care costs")
    for p in people:
        pname = p["display_name"]
        mo = int(costs.get(p["id"], 0))
        st.write(f"**{pname}**: ${mo:,.0f}/mo")

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

# --------------------------------------------------------------------------------------
# End
# --------------------------------------------------------------------------------------