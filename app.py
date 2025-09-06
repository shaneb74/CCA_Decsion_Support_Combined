# app.py — Senior Navigator (stable flow + narrative + guardrails)
# Root-only JSON paths, robust PlannerEngine result handling,
# spouse interstitials, per-person Q&A one-at-a-time, and optional assets_engine.

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple
import traceback
import json
import streamlit as st

# ----------------------------- Page config -----------------------------------
st.set_page_config(page_title="Senior Navigator • Planner + Cost", page_icon="🧭", layout="centered")

# ----------------------------- Paths (root) -----------------------------------
ROOT = Path(__file__).resolve().parent
QA_PATH = ROOT / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = ROOT / "recommendation_logic_FINAL_MASTER_UPDATED.json"

# ----------------------------- Engines ----------------------------------------
try:
    from engines import PlannerEngine, CalculatorEngine  # your existing engines.py
except Exception:
    st.error("Failed to import engines.py")
    st.code(traceback.format_exc())
    st.stop()

# Optional (your drawers live here). We load it lazily & defensively.
try:
    import asset_engine  # must expose render_household_drawers(st) -> HouseholdResult
    HAVE_ASSET_ENGINE = True
except Exception:
    HAVE_ASSET_ENGINE = False

# ----------------------------- Load JSONs -------------------------------------
missing = [p for p in (QA_PATH, REC_PATH) if not p.exists()]
if missing:
    st.error("Missing required JSON files:\n" + "\n".join(f"• {m.name}" for m in missing))
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

# ----------------------------- Helpers ----------------------------------------

def make_inputs(**kwargs):
    """Create a calculator inputs object regardless of CalcInputs availability."""
    obj = SimpleNamespace()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj

def reset_all():
    for k in list(st.session_state.keys()):
        if not k.startswith("_"):
            del st.session_state[k]
    st.session_state.step = "intro"

def _is_intlike(x: Any) -> bool:
    try:
        int(str(x))
        return True
    except Exception:
        return False

def _ordered_answer_items(amap: dict) -> List[Tuple[str, str]]:
    """
    Return list of (key, label) in a human-friendly stable order.
    If keys are numeric-like strings, sort numerically; otherwise insertion order.
    """
    if not isinstance(amap, dict) or not amap:
        return []
    keys = list(amap.keys())
    if all(_is_intlike(k) for k in keys):
        keys_sorted = [str(k) for k in sorted(int(str(k)) for k in keys)]
    else:
        keys_sorted = keys  # JSON preserves insertion order
    return [(k, amap[k]) for k in keys_sorted]

def radio_from_answer_map(label: str, amap: dict, *, key: str, help_text: Optional[str] = None,
                          default_key: Optional[str] = None) -> str:
    items = _ordered_answer_items(amap)
    labels = [v for (k, v) in items]
    keys   = [k for (k, v) in items]
    if not labels:
        return default_key or ""
    idx = 0
    if default_key and str(default_key) in keys:
        idx = keys.index(str(default_key))
    choice = st.radio(label, labels, index=idx, key=key, help=help_text)
    return keys[labels.index(choice)]

def _safe_getattr_or(res: Any, attr: str, default: Any) -> Any:
    if hasattr(res, attr):
        return getattr(res, attr)
    if isinstance(res, dict):
        return res.get(attr, default)
    return default

def _collect_reasons_from_flags(flags: set[str]) -> List[str]:
    phrases = {
        "high_dependence": "needing help with daily tasks like meals, bathing, or dressing",
        "high_mobility_dependence": "major mobility support is needed",
        "no_support": "no regular caregiver support",
        "moderate_cognitive_decline": "notable memory or focus challenges",
        "severe_cognitive_risk": "significant cognitive/memory risks",
        "high_safety_concern": "home safety issues or fall risks",
        "moderate_safety_concern": "some home safety concerns",
    }
    picked = [phrases[f] for f in phrases.keys() if f in flags]
    return picked[:4]

def _render_preference_clause(pref: Optional[str]) -> str:
    if pref == "strongly_prefers_home":
        return "Staying home means a lot to you, so we’ll explore safe ways to make that work."
    if pref == "prefers_home":
        return "You’d prefer to stay home, so we’ll focus on keeping that safe and comfortable."
    if pref == "open_to_move":
        return "Since you’re open to options, we’ll compare choices and pick what feels right."
    return "We’ll focus on what keeps you safest and most comfortable."

def _guardrail_decision(name: str, care_type: str, flags: set[str], pref: Optional[str]) -> Tuple[str, Optional[str]]:
    """
    Guard against obviously-wrong outputs by re-evaluating flags.
    Returns possibly-updated (care_type, narrative_override).
    If no override, narrative_override = None.
    """
    severe = "severe_cognitive_risk" in flags
    high_dep = "high_dependence" in flags
    high_mob = "high_mobility_dependence" in flags
    no_support = "no_support" in flags
    high_safe = "high_safety_concern" in flags

    # Memory care override: severe cognitive + (no support OR high dependence OR high safety)
    if severe and (no_support or high_dep or high_safe):
        if care_type != "memory_care":
            reasons = _collect_reasons_from_flags(flags)
            msg = (f"Hi {name}, due to significant memory risks and daily support needs "
                   f"({'; '.join(reasons)}), **memory care** is the safest path right now. "
                   f"{_render_preference_clause(pref)}")
            return "memory_care", msg

    # Assisted living override: two or more heavy risk factors
    heavy_count = sum([high_dep, high_mob, no_support, high_safe, severe])
    if heavy_count >= 2 and care_type not in ("assisted_living", "memory_care"):
        reasons = _collect_reasons_from_flags(flags)
        msg = (f"Hi {name}, needs like {', '.join(reasons)} suggest **assisted living** for reliable daily help "
               f"and safety. {_render_preference_clause(pref)}")
        return "assisted_living", msg

    # None override: if engine says 'none' but any notable flag exists, force at least in_home
    notable = any(f in flags for f in [
        "high_dependence", "high_mobility_dependence", "moderate_cognitive_decline", "severe_cognitive_risk",
        "no_support", "moderate_safety_concern", "high_safety_concern"
    ])
    if care_type == "none" and notable:
        reasons = _collect_reasons_from_flags(flags)
        msg = (f"Hi {name}, while many things look okay, {', '.join(reasons)} means **some in-home support** "
               f"would be wise. {_render_preference_clause(pref)}")
        return "in_home", msg

    return care_type, None

def _pick_narrative(rec: Dict[str, Any]) -> Optional[str]:
    # Support old and new keys
    for k in ("advisory", "message", "message_rendered", "narrative"):
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return None

# ----------------------------- Session init -----------------------------------
if "step" not in st.session_state:
    st.session_state.step = "intro"

st.sidebar.title("Senior Navigator")
st.sidebar.caption("Planner → Costs → Budget → Breakdown")
st.sidebar.button("Start over", on_click=reset_all)

# ----------------------------- UI Flow ----------------------------------------

# INTRO
if st.session_state.step == "intro":
    st.title("Let’s take this one step at a time")
    st.markdown(
        "Choosing senior living or in-home support can feel overwhelming.\n\n"
        "This tool breaks it into clear steps:\n\n"
        "1. Answer short care questions → we recommend a care type.\n"
        "2. Review costs for that scenario (you can switch it).\n"
        "3. Add income, benefits, assets, and other costs (optional) to see affordability.\n"
        "4. View a detailed breakdown you can save or revisit."
    )
    if st.button("Start"):
        st.session_state.step = "audience"
        st.rerun()

# AUDIENCE (who)
elif st.session_state.step == "audience":
    st.header("Who is this plan for?")
    role = st.radio("Select one:", ["Myself", "My spouse/partner", "My parent", "Both parents", "Someone else"])

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
        st.caption("Next, we’ll ask short care questions for each person (1 at a time).")
        if st.button("Continue"):
            st.session_state.people = people
            st.session_state.current_person = 0
            st.session_state.answers = {}
            st.session_state.results = {}
            st.session_state.mobility_raw = {}
            st.session_state.step = "planner"
            st.rerun()
    else:
        default = "Alex" if role != "My parent" else "Mom"
        n = st.text_input("Name", value=default, key="p_name", placeholder="Name")
        map_rel = {"Myself": "self", "My spouse/partner": "spouse", "My parent": "parent", "Someone else": "other"}
        people = [{"id": "A", "display_name": n, "relationship": map_rel.get(role, "other")}]

        # spouse/partner interstitial (only when user is planning for a single person)
        st.caption("Before questions, consider the spouse/partner context.")
        if st.button("Continue"):
            st.session_state.people = people
            st.session_state.current_person = 0
            st.session_state.answers = {}
            st.session_state.results = {}
            st.session_state.mobility_raw = {}
            st.session_state.step = "partner_context"
            st.rerun()

# PARTNER CONTEXT (interstitial for single-person audience)
elif st.session_state.step == "partner_context":
    people = st.session_state.get("people", [])
    if not people:
        reset_all(); st.rerun()
    single = len(people) == 1
    primary = people[0]["display_name"] if people else "Person A"

    st.header("Before we begin")
    st.markdown(
        f"If **{primary}** may need assisted living or memory care, their spouse/partner may also need a small in-home "
        "support plan. You can include that now so the household picture is complete."
    )

    add = False
    if single:
        add = st.checkbox("Yes, I want to evaluate a plan for a spouse/partner", value=False, key="care_partner_add")
        if add:
            st.text_input("Spouse/partner name", value="", placeholder="Enter spouse/partner name",
                          key="care_partner_name")

    c1, c2 = st.columns(2)
    with c1:
        if st.button(f"No, let's just plan for **{primary}**"):
            st.session_state.step = "planner"
            st.rerun()
    with c2:
        btn_disabled = not st.session_state.get("care_partner_add", False)
        if st.button("Add spouse/partner and continue", disabled=btn_disabled):
            if single and st.session_state.get("care_partner_add"):
                st.session_state.people.append({
                    "id": "B",
                    "display_name": st.session_state.get("care_partner_name") or "Spouse/Partner",
                    "relationship": "spouse",
                })
            st.session_state.step = "planner"
            st.rerun()

# PER-PERSON Q&A (one-question-at-a-time)
elif st.session_state.step == "planner":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if not people:
        reset_all(); st.rerun()
    person = people[i]
    name = person["display_name"]

    st.header(f"Care Plan — {name}")
    st.caption(f"Person {i+1} of {len(people)}")

    qa = planner.qa or {}
    questions = qa.get("questions", [])
    if not questions:
        st.error("No questions found in the QA JSON.")
        st.stop()

    ws = st.session_state.setdefault("qa_wizard", {})
    # initialize answer store
    answers = st.session_state.answers.get(person["id"], {})
    total_q = len(questions)
    idx = int(ws.get("idx", 0))
    idx = max(0, min(idx, total_q - 1))

    # toggle: reviewers can show all questions (desktop audit)
    show_all = st.toggle("Show all questions (desktop reviewers)", value=False, key=f"show_all_{person['id']}")

    def render_one(q_idx: int):
        q = questions[q_idx]
        amap = q.get("answers", {})
        label = f"{q.get('question', f'Question {q_idx+1}')} (for {name})"
        prev_key = answers.get(f"q{q_idx+1}")
        sel_key = radio_from_answer_map(label, amap,
                                        key=f"{person['id']}_q{q_idx+1}",
                                        help_text=q.get("help"),
                                        default_key=str(prev_key) if prev_key is not None else None)
        answers[f"q{q_idx+1}"] = int(sel_key) if _is_intlike(sel_key) else sel_key

    if show_all:
        for q_idx in range(total_q):
            render_one(q_idx)
            st.divider()
    else:
        st.progress((idx+1)/total_q, text=f"Question {idx+1} of {total_q}")
        render_one(idx)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Back", disabled=(idx == 0)):
                ws["idx"] = max(0, idx-1); st.rerun()
        with c2:
            if st.button("Next", disabled=(idx >= total_q-1)):
                ws["idx"] = min(total_q-1, idx+1); st.rerun()

    # Save answers back
    st.session_state.answers[person["id"]] = answers

    # Finish section
    if st.button("Finish"):
        # Run planner for this person
        try:
            res = planner.run(answers)  # your engine computes flags/scores/messages
        except Exception:
            st.error("PlannerEngine.run failed.")
            st.code(traceback.format_exc())
            st.stop()

        # Normalize result
        care_type = _safe_getattr_or(res, "care_type", None) or _safe_getattr_or(res, "recommendation", None) or "in_home"
        flags = set(_safe_getattr_or(res, "flags", [])) or set()
        scores = _safe_getattr_or(res, "scores", {}) or {}
        reasons = list(_safe_getattr_or(res, "reasons", [])) or []
        narrative = (
            _safe_getattr_or(res, "narrative", None)
            or _safe_getattr_or(res, "advisory", None)
            or _safe_getattr_or(res, "message", None)
            or _safe_getattr_or(res, "message_rendered", None)
        )

        # Pull preference flag if the engine set one (optional)
        pref = _safe_getattr_or(res, "preference", None)
        # Guardrail sanity check
        care_type_guard, override_msg = _guardrail_decision(name, care_type, flags, pref)
        if care_type_guard != care_type:
            care_type = care_type_guard
            if override_msg:
                narrative = override_msg

        st.session_state.results[person["id"]] = {
            "care_type": care_type,
            "flags": list(flags),
            "scores": scores,
            "reasons": reasons,
            "narrative": narrative or "",
            "name": name,
        }

        # Next person or interstitial
        if i + 1 < len(people):
            st.session_state.current_person = i + 1
            st.session_state.step = "next_person"
            st.rerun()
        else:
            st.session_state.step = "recommendations"
            st.rerun()

# INTERSTITIAL: moving to next person
elif st.session_state.step == "next_person":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if not people or i >= len(people):
        reset_all(); st.rerun()
    name = people[i]["display_name"]

    st.header("Great — one down!")
    st.markdown(f"Now let’s assess **{name}**.")
    if st.button("Continue"):
        st.session_state.step = "planner"
        st.rerun()

# RECOMMENDATIONS
elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without redoing questions.")

    results = st.session_state.get("results", {})
    if not results:
        st.info("No results yet."); st.stop()

    # selection labels
    choices = ["none", "in_home", "assisted_living", "memory_care"]
    labels  = {
        "none": "No care needed",
        "in_home": "In-home Care",
        "assisted_living": "Assisted Living",
        "memory_care": "Memory Care",
    }
    for pid, rec in results.items():
        name = rec.get("name", f"Person {pid}")
        care_type = rec.get("care_type", "in_home")
        narrative = _pick_narrative(rec) or "We’ll work with you to find the safest and most comfortable path."

        st.subheader(f"{name}: {labels.get(care_type, care_type.replace('_',' ').title())} (recommended)")
        st.info(narrative)

        # Also list high-level reasons (from flags)
        flags = set(rec.get("flags", []))
        reason_lines = _collect_reasons_from_flags(flags)
        if reason_lines:
            for r in reason_lines:
                st.write("• " + r)

        # Allow override without redoing Q&A
        idx = choices.index(care_type) if care_type in choices else 0
        sel = st.selectbox(f"Care scenario for {name}",
                           [labels[c] for c in choices],
                           index=idx, key=f"override_{pid}",
                           help="You can compare a different scenario without repeating the questions.")
        # save override (for costing)
        inv = {v: k for k, v in labels.items()}
        st.session_state.setdefault("care_overrides", {})[pid] = inv[sel]

        st.divider()

    if st.button("See Costs"):
        st.session_state.step = "calculator"
        st.rerun()

# CALCULATOR (simple; keeps your prior behavior)
elif st.session_state.step == "calculator":
    st.header("Cost Planner")
    state = st.selectbox("Location", ["National", "Washington", "California", "Texas", "Florida"],
                         help="Adjusts typical market rates for the selected state.")
    total = 0
    for p in st.session_state.get("people", []):
        pid = p["id"]; name = p["display_name"]
        base_rec = st.session_state.get("results", {}).get(pid, {}).get("care_type", "in_home")
        care_type = st.session_state.get("care_overrides", {}).get(pid, base_rec)

        st.subheader(f"{name} — Scenario: {care_type.replace('_',' ').title()} "
                     f"(recommended: {base_rec.replace('_',' ').title()})")

        # Minimal tunables (your full model may include more)
        care_level = st.selectbox("Care Level (staffing intensity)", ["Low", "Medium", "High"], key=f"{pid}_level")
        mobility   = st.selectbox("Mobility", ["Independent", "Assisted", "Non-ambulatory"], key=f"{pid}_mobility")
        chronic    = st.selectbox("Chronic Conditions", ["None", "Some", "Multiple/Complex"], key=f"{pid}_chronic")

        inp = make_inputs(state=state, care_type=care_type, care_level=care_level, mobility=mobility, chronic=chronic)
        if care_type in ("assisted_living", "memory_care"):
            room = st.selectbox("Room Type", ["Studio", "1 Bedroom", "Shared"], key=f"{pid}_room")
            setattr(inp, "room_type", room)
        else:
            hours = st.slider("In-home care hours per day", 0, 24, 4, 1, key=f"{pid}_hours")
            days  = st.slider("Days of care per month", 0, 31, 20, 1, key=f"{pid}_days")
            setattr(inp, "in_home_hours_per_day", int(hours))
            setattr(inp, "in_home_days_per_month", int(days))

        try:
            monthly = calculator.monthly_cost(inp) if hasattr(calculator, "monthly_cost") else 0
        except Exception:
            st.error("CalculatorEngine failed while computing monthly cost.")
            st.code(traceback.format_exc())
            st.stop()

        st.metric("Estimated Monthly Cost", f"${int(monthly):,}")
        st.session_state.setdefault("person_costs", {})[pid] = int(monthly)
        total += int(monthly)
        st.divider()

    st.subheader("Combined Total")
    st.metric("Estimated Combined Monthly Cost", f"${total:,.0f}")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back to recommendations"):
            st.session_state.step = "recommendations"; st.rerun()
    with c2:
        if st.button("Add Household & Assets (optional)"):
            st.session_state.step = "household"; st.rerun()

# HOUSEHOLD (drawers come from asset_engine)
elif st.session_state.step == "household":
    st.header("Household & Budget (optional)")
    st.markdown("Add income, benefits, assets, home decisions, and other costs to see affordability. You can skip this.")
    if not HAVE_ASSET_ENGINE:
        st.warning("`asset_engine.py` not found. The drawers module is optional; if you want it, include the file.")
    else:
        try:
            result = asset_engine.render_household_drawers(st)  # returns HouseholdResult dataclass or SimpleNamespace
            # stash compact summary for breakdown
            st.session_state["household_result"] = json.loads(json.dumps(result, default=lambda o: asdict(o) if hasattr(o, "__dict__") else o))
        except Exception:
            st.error("Household drawers failed.")
            st.code(traceback.format_exc())
            st.stop()

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back to Costs"): st.session_state.step = "calculator"; st.rerun()
    with c2:
        if st.button("View Detailed Breakdown"): st.session_state.step = "breakdown"; st.rerun()

# BREAKDOWN (uses household_result if present)
elif st.session_state.step == "breakdown":
    st.header("Detailed Breakdown")
    people = st.session_state.get("people", [])
    costs  = st.session_state.get("person_costs", {})
    nameA = people[0]["display_name"] if people else "Person A"
    nameB = people[1]["display_name"] if len(people) > 1 else "Person B"

    care_A = int(costs.get("A", 0))
    care_B = int(costs.get("B", 0)) if len(people) > 1 else 0
    care_total = care_A + care_B

    # Pull structured household result if present
    hr = st.session_state.get("household_result", {})
    # Fallback to zeros if not present
    inc_indiv = hr.get("monthly_income_individual_total", 0)
    inc_house = hr.get("monthly_income_household_total", 0)
    benefits  = hr.get("benefits_total_monthly", 0)  # VA + LTC add-ons
    addl_costs = hr.get("other_monthly_total", 0) + hr.get("home_monthly_total", 0) + hr.get("mods_monthly_total", 0)
    assets_total = hr.get("assets_total", 0)

    income_total = int(inc_indiv) + int(inc_house) + int(benefits)
    monthly_need = int(care_total) + int(addl_costs)
    gap = monthly_need - income_total

    c1, c2, c3 = st.columns(3)
    c1.metric("Monthly Care + Selected Costs", f"${monthly_need:,.0f}")
    c2.metric("Total Monthly Income", f"${income_total:,.0f}")
    c3.metric("Estimated Monthly Gap", f"${gap:,.0f}")

    years = 0.0
    if gap > 0 and assets_total > 0:
        years = round(assets_total / max(gap, 1), 1)
    st.subheader(f"Estimated runway from assets: {years} years")

    st.markdown("### Per-person care costs")
    if len(people) > 1:
        ca, cb = st.columns(2)
        with ca: st.write(f"**{nameA}**: ${care_A:,.0f}/mo")
        with cb: st.write(f"**{nameB}**: ${care_B:,.0f}/mo")
    elif people:
        st.write(f"**{nameA}**: ${care_A:,.0f}/mo")

    st.divider()
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Back to Household"):
            st.session_state.step = "household"; st.rerun()
    with b2:
        if st.button("Back to Costs"):
            st.session_state.step = "calculator"; st.rerun()

# default safety
else:
    reset_all(); st.rerun()