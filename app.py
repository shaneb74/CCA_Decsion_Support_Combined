# app.py — Senior Navigator (Planner → Recommendation → Costs → Household → Breakdown)
# Full production-style build with safe radio helpers, interstitials, spouse option,
# narrative rendering, mobility carryover, VA/LTC wizard, home decision, home mods,
# other monthly costs, drawer subtotals, and detailed breakdown (charts optional).

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple, Optional
import traceback

import streamlit as st

# ========================= Page Config =========================
st.set_page_config(
    page_title="Senior Navigator • Planner + Cost",
    page_icon="🧭",
    layout="centered"
)

# ========================= Feature Flags =========================
ENABLE_PARTNER_INTERSTITIAL = True         # ask about spouse/partner support
ENABLE_HANDOFF_BETWEEN_PEOPLE = True       # interstitial screen between Person A and B
ENABLE_REC_OVERRIDE = True                 # allow user to override recommended scenario
ENABLE_INHOME_DAYS_PER_MONTH = True        # expose "days per month" slider in in-home
ENABLE_MOBILITY_CARRYOVER = True           # map Q&A mobility into calculator mobility
ENABLE_HOUSEHOLD_DRAWERS = True            # show household income/assets/benefits drawers
ENABLE_HOME_DECISION = True                # sell/keep/HELOC/reverse with HOA/utilities
ENABLE_HOME_MODS = True                    # home modifications drawer with finish levels
ENABLE_OTHER_MONTHLIES = True              # medications/health/dental/other recurring
ENABLE_DETAILS_PAGE = True                 # “Detailed Breakdown” page
ENABLE_CHARTS = False                      # keep False by default on Streamlit Cloud

# ========================= Optional Charts Dependency =========================
try:
    import altair as alt  # noqa: F401
    HAVE_ALTAIR = True
except Exception:
    HAVE_ALTAIR = False

# ========================= Paths (all in repo root) =========================
ROOT = Path(__file__).resolve().parent
QA_PATH = ROOT / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = ROOT / "recommendation_logic_FINAL_MASTER_UPDATED.json"

# ========================= Engines =========================
try:
    from engines import PlannerEngine, CalculatorEngine
except Exception:
    st.error("Failed to import engines.py. See traceback:")
    st.code(traceback.format_exc())
    st.stop()

missing_files = [p for p in (QA_PATH, REC_PATH) if not p.exists()]
if missing_files:
    st.error("Missing required JSON files:\n" + "\n".join(f"• {m}" for m in missing_files))
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

# ========================= Helpers =========================
def make_inputs(**kwargs) -> Any:
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

def jump_top_once():
    """Scroll to top on next rerun (mobile nicety)."""
    st.session_state["_jump_top"] = True

# ----- Safe answer-map helpers (prevents KeyError on non-1..N keys) -----
def _order_answer_items(amap: dict) -> List[Tuple[str, str]]:
    """
    Return list of (key, label) pairs in a stable, human-friendly order.
    - If keys are numeric strings ('1','2',...), sort numerically.
    - Otherwise, preserve insertion order.
    """
    if not isinstance(amap, dict) or not amap:
        return []
    keys = list(amap.keys())
    try:
        keys_sorted = sorted(keys, key=lambda k: int(k))
    except Exception:
        keys_sorted = keys
    return [(str(k), amap[k]) for k in keys_sorted]

def radio_from_answer_map(
    label: str,
    amap: dict,
    *,
    key: str,
    help_text: Optional[str] = None,
    default_key: Optional[str] = None
) -> Optional[str]:
    """
    Render a radio from an answer map and return the SELECTED KEY (string).
    If amap is empty, returns default_key.
    """
    items = _order_answer_items(amap)
    labels = [v for (_k, v) in items]
    keys   = [k for (k, _v) in items]
    if not labels:
        return default_key

    # determine default index
    if default_key is not None and str(default_key) in keys:
        default_idx = keys.index(str(default_key))
    else:
        default_idx = 0

    choice = st.radio(label, labels, index=default_idx, key=key, help=help_text)
    sel_idx = labels.index(choice) if choice in labels else default_idx
    return keys[sel_idx]

def _safe_int(x, default=0) -> int:
    try:
        return int(x)
    except Exception:
        return default

# ========================= Session bootstrap =========================
if "step" not in st.session_state:
    st.session_state.step = "intro"

st.sidebar.title("Senior Navigator")
st.sidebar.caption("Planner → Costs → Budget → Breakdown")
st.sidebar.button("Start over", on_click=reset_all)

# ========================= UI Flow =========================

# ---------- Intro ----------
if st.session_state.step == "intro":
    st.title("Let’s take this one step at a time")
    st.markdown("""
Choosing senior living or in-home support can feel overwhelming.  
This tool breaks it down into clear steps.

**What happens next**
1. Answer short care questions → we recommend a care type.  
2. Review costs for that scenario (you can switch it).  
3. Optional: add income, benefits, and assets to see affordability.  
4. View a detailed breakdown you can save or revisit.
""")
    st.info("Typical time: 10–15 minutes. You can stop anytime.")
    if st.button("Start"):
        st.session_state.step = "audience"
        st.rerun()

# ---------- Audience ----------
elif st.session_state.step == "audience":
    st.header("Who is this plan for?")
    role = st.radio("Select one:", ["Myself", "My spouse/partner", "My parent", "Both parents", "Someone else"])
    people = []
    if role == "Both parents":
        c1, c2 = st.columns(2)
        with c1:
            n1 = st.text_input("Parent 1 name", value="Mom", key="p1_name", placeholder="Enter a name")
            st.selectbox("Parent 1 age", ["65–74", "75–84", "85+"], key="p1_age")
        with c2:
            n2 = st.text_input("Parent 2 name", value="Dad", key="p2_name", placeholder="Enter a name")
            st.selectbox("Parent 2 age", ["65–74", "75–84", "85+"], key="p2_age")
        people = [
            {"id": "A", "display_name": n1, "relationship": "parent"},
            {"id": "B", "display_name": n2, "relationship": "parent"},
        ]
    else:
        default = "Alex" if role != "My parent" else "Mom"
        n = st.text_input("Name", value=default, key="p_name", placeholder="Enter a name")
        st.selectbox("Approximate age", ["65–74", "75–84", "85+"], key="p_age")
        map_rel = {"Myself": "self", "My spouse/partner": "spouse", "My parent": "parent", "Someone else": "other"}
        people = [{"id": "A", "display_name": n, "relationship": map_rel.get(role, "other")}]

    st.caption("Next, we’ll ask short care questions for each person.")

    if st.button("Continue"):
        st.session_state.people = people
        st.session_state.current_person = 0
        st.session_state.answers = {}
        st.session_state.planner_results = {}
        st.session_state.mobility_raw = {}
        st.session_state.care_overrides = {}
        st.session_state.person_costs = {}
        # set mobile one-at-a-time index per person
        st.session_state.qa_index = {}
        st.session_state.step = "partner_context" if ENABLE_PARTNER_INTERSTITIAL else "planner"
        st.rerun()

# ---------- Partner interstitial ----------
elif st.session_state.step == "partner_context":
    people = st.session_state.get("people", [])
    single = len(people) == 1
    primary = people[0]["display_name"] if people else "Person A"

    st.header("Before we begin")
    st.markdown(f"""
If **{primary}** needs assisted living or memory care, their spouse/partner may also need some in-home help.  
You can include a simple support plan for them now so the household picture is complete.
""")

    if single:
        add = st.checkbox("Yes, I want to evaluate a plan for a spouse/partner",
                          value=False, key="care_partner_add")
        if add:
            st.text_input("Spouse/partner name", value="",
                          placeholder="Enter spouse/partner name", key="care_partner_name")

    c1, c2 = st.columns(2)
    with c1:
        if st.button(f"No, let’s just plan for **{primary}**"):
            st.session_state.step = "planner"
            st.rerun()
    with c2:
        btn_disabled = not st.session_state.get("care_partner_add", False)
        if st.button("Add spouse/partner and continue", disabled=btn_disabled):
            if single and st.session_state.get("care_partner_add"):
                st.session_state.people.append({
                    "id": "B",
                    "display_name": st.session_state.get("care_partner_name") or "Spouse/Partner",
                    "relationship": "spouse"
                })
            st.session_state.step = "planner"
            st.rerun()

# ---------- Planner (one-question-at-a-time, mobile-friendly) ----------
elif st.session_state.step == "planner":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if not people:
        reset_all(); st.rerun()
    person = people[i]
    pid = person["id"]
    name = person["display_name"]

    st.header(f"Care Plan Questions for {name}")
    st.caption(f"Person {i+1} of {len(people)}")

    qa = planner.qa or {}
    questions = qa.get("questions", [])
    answers = st.session_state.answers.get(pid, {})

    # Index for one-at-a-time nav
    idx = int(st.session_state.get("qa_index", {}).get(pid, 0))
    total_q = len(questions)
    idx = max(0, min(idx, total_q - 1))

    if questions:
        q = questions[idx]
        amap = q.get("answers", {}) or {}
        prev_val = answers.get(f"q{idx+1}")
        prev_key = str(prev_val) if prev_val is not None else None

        sel_key = radio_from_answer_map(
            label=q.get("question", f"Q{idx+1}"),
            amap=amap,
            key=f"{pid}_q{idx+1}",
            help_text=q.get("help"),
            default_key=prev_key
        )

        # Save selection
        try:
            answers[f"q{idx+1}"] = int(sel_key) if sel_key is not None else prev_val
        except Exception:
            answers[f"q{idx+1}"] = sel_key

        st.session_state.answers[pid] = answers

        # track mobility answer (for carryover)
        if "mobility" in q.get("question", "").lower():
            if sel_key is not None:
                try:
                    st.session_state.mobility_raw[pid] = int(sel_key)
                except Exception:
                    st.session_state.mobility_raw[pid] = sel_key

        # Nav buttons
        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("Back"):
                if idx == 0:
                    # back to partner interstitial or audience
                    if ENABLE_PARTNER_INTERSTITIAL:
                        st.session_state.step = "partner_context"
                    else:
                        st.session_state.step = "audience"
                else:
                    st.session_state.qa_index[pid] = idx - 1
                st.rerun()

        with b2:
            if st.button("Next"):
                if idx + 1 < total_q:
                    st.session_state.qa_index[pid] = idx + 1
                    st.rerun()
                else:
                    # Optional conditional question from JSON
                    conditional_answer = None
                    cond_cfg = qa.get("conditional_questions")
                    if cond_cfg:
                        # show only if likely cognitive trigger present in answers
                        # Heuristic: if any selected label mentions memory/dementia
                        try:
                            triggered = False
                            for j, qq in enumerate(questions, start=1):
                                lbl_map = qq.get("answers", {})
                                selected = answers.get(f"q{j}")
                                if selected is None:
                                    continue
                                s_key = str(selected)
                                s_label = lbl_map.get(s_key, "").lower()
                                if any(word in s_label for word in ("memory", "dementia", "cognitive")):
                                    triggered = True
                                    break
                            if triggered:
                                cq = cond_cfg[0]
                                c_amap = cq.get("answers", {"1": "Yes", "2": "No"})
                                sel_c = radio_from_answer_map(
                                    label=cq.get("question", "Additional question"),
                                    amap=c_amap,
                                    key=f"{pid}_condq",
                                    help_text=cq.get("help")
                                )
                                conditional_answer = sel_c
                                st.info("Thanks. Saved your additional answer.")
                        except Exception:
                            pass

                    # Run planner
                    try:
                        payload = {**answers, "_person_name": name}
                        res = planner.run(payload, conditional_answer=conditional_answer)
                    except Exception:
                        st.error("PlannerEngine.run failed.")
                        st.code(traceback.format_exc())
                        st.stop()

                    # Normalize result to dict
                    if hasattr(res, "__dict__"):
                        care_type = getattr(res, "care_type", None)
                        flags = set(getattr(res, "flags", set()) or set())
                        scores = getattr(res, "scores", {}) or {}
                        reasons = list(getattr(res, "reasons", []) or [])
                        narrative = (getattr(res, "advisory", None)
                                     or getattr(res, "message", None)
                                     or getattr(res, "message_rendered", None))
                    else:
                        care_type = res.get("care_type")
                        flags = set(res.get("flags", []))
                        scores = res.get("scores", {})
                        reasons = list(res.get("reasons", []))
                        narrative = (res.get("advisory")
                                     or res.get("message")
                                     or res.get("message_rendered"))

                    st.session_state.planner_results[pid] = {
                        "care_type": care_type,
                        "flags": list(flags),
                        "scores": scores,
                        "reasons": reasons,
                        "advisory": narrative
                    }

                    # move to next person or interstitial
                    if (i + 1) < len(people):
                        if ENABLE_HANDOFF_BETWEEN_PEOPLE:
                            st.session_state.step = "person_handoff"
                        else:
                            st.session_state.current_person = i + 1
                            st.session_state.qa_index[people[i+1]["id"]] = 0
                        jump_top_once()
                        st.rerun()
                    else:
                        st.session_state.step = "recommendations"
                        jump_top_once()
                        st.rerun()

        with b3:
            if st.button("Skip to summary"):
                # user bails; still try to run planner with whatever we have
                try:
                    payload = {**answers, "_person_name": name}
                    res = planner.run(payload, conditional_answer=None)
                except Exception:
                    st.error("PlannerEngine.run failed.")
                    st.code(traceback.format_exc())
                    st.stop()
                if hasattr(res, "__dict__"):
                    care_type = getattr(res, "care_type", None)
                    flags = set(getattr(res, "flags", set()) or set())
                    scores = getattr(res, "scores", {}) or {}
                    reasons = list(getattr(res, "reasons", []) or [])
                    narrative = (getattr(res, "advisory", None)
                                 or getattr(res, "message", None)
                                 or getattr(res, "message_rendered", None))
                else:
                    care_type = res.get("care_type")
                    flags = set(res.get("flags", []))
                    scores = res.get("scores", {})
                    reasons = list(res.get("reasons", []))
                    narrative = (res.get("advisory")
                                 or res.get("message")
                                 or res.get("message_rendered"))
                st.session_state.planner_results[pid] = {
                    "care_type": care_type,
                    "flags": list(flags),
                    "scores": scores,
                    "reasons": reasons,
                    "advisory": narrative
                }
                if (i + 1) < len(people):
                    if ENABLE_HANDOFF_BETWEEN_PEOPLE:
                        st.session_state.step = "person_handoff"
                    else:
                        st.session_state.current_person = i + 1
                        st.session_state.qa_index[people[i+1]["id"]] = 0
                    jump_top_once()
                    st.rerun()
                else:
                    st.session_state.step = "recommendations"
                    jump_top_once()
                    st.rerun()

# ---------- Interstitial handoff between people ----------
elif st.session_state.step == "person_handoff":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if i + 1 >= len(people):
        st.session_state.step = "recommendations"
        st.rerun()
    done_person = people[i]["display_name"]
    next_person = people[i+1]["display_name"]
    st.header("Great — next person")
    st.markdown(f"We’ve saved **{done_person}**’s answers. Now let’s assess **{next_person}**.")
    if st.button(f"Continue with {next_person}"):
        st.session_state.current_person = i + 1
        st.session_state.qa_index[people[i+1]["id"]] = 0
        jump_top_once()
        st.session_state.step = "planner"
        st.rerun()

# ---------- Recommendations + override ----------
elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without redoing questions.")

    for p in st.session_state.get("people", []):
        rec = st.session_state.planner_results.get(p["id"], {})
        default = rec.get("care_type", "in_home")
        st.subheader(f"{p['display_name']}: {default.replace('_', ' ').title()} (recommended)")

        # Narrative
        narrative = (rec.get("advisory")
                     or rec.get("message")
                     or rec.get("narrative")
                     or rec.get("message_rendered")
                     or rec.get("message_template"))
        if narrative:
            st.info(narrative)

        # Reasons
        for r in rec.get("reasons", []):
            st.write("• " + str(r))

        # Override
        if ENABLE_REC_OVERRIDE:
            care_choices = ["in_home", "assisted_living", "memory_care", "none"]
            labels = {
                "in_home": "In-home Care",
                "assisted_living": "Assisted Living",
                "memory_care": "Memory Care",
                "none": "No plan needed"
            }
            idx = care_choices.index(default) if default in care_choices else 0
            label_sel = st.selectbox(
                f"Care scenario for {p['display_name']}",
                [labels[c] for c in care_choices],
                index=idx,
                key=f"override_{p['id']}",
                help="Compare a different scenario without repeating the questions."
            )
            reverse = {v: k for k, v in labels.items()}
            st.session_state.care_overrides[p['id']] = reverse[label_sel]

        st.divider()

    if st.button("See Costs"):
        st.session_state.step = "calculator"
        jump_top_once()
        st.rerun()

# ---------- Calculator ----------
elif st.session_state.step == "calculator":
    st.header("Cost Planner")

    # location factor
    state = st.selectbox("Location", ["National", "Washington", "California", "Texas", "Florida"],
                         help="Adjusts for typical market rates in the selected state.")

    total = 0
    for p in st.session_state.get("people", []):
        pid = p["id"]
        name = p["display_name"]
        rec = st.session_state.planner_results.get(pid, {})
        care_type = st.session_state.get("care_overrides", {}).get(pid, rec.get("care_type", "in_home"))

        st.subheader(f"{name} — Scenario: {care_type.replace('_', ' ').title()} "
                     f"(recommended: {rec.get('care_type', 'in_home').replace('_', ' ').title()})")

        # Mobility carryover
        mobility_prefill = "Independent"
        if ENABLE_MOBILITY_CARRYOVER:
            raw_mob = st.session_state.get("mobility_raw", {}).get(pid)
            try:
                raw_mob = int(raw_mob) if raw_mob is not None else None
            except Exception:
                pass
            # map original numeric picks to semantic labels
            # 2/3 = assisted, 4 = non-ambulatory (based on earlier conv. mapping)
            if raw_mob in (2, 3):
                mobility_prefill = "Assisted"
            elif raw_mob == 4:
                mobility_prefill = "Non-ambulatory"

        care_level_default = "High" if ("severe_cognitive_decline" in set(rec.get("flags", []))
                                        or care_type == "memory_care") else "Medium"
        care_level = st.selectbox("Care Level (staffing intensity)", ["Low", "Medium", "High"],
                                  index=["Low", "Medium", "High"].index(care_level_default),
                                  key=f"{pid}_care_level")

        mobility_options = [
            "Independent (no device)",
            "Assisted (cane/walker or needs help)",
            "Non-ambulatory (wheelchair/bedbound)"
        ]
        mobility_map_out = {
            "Independent (no device)": "Independent",
            "Assisted (cane/walker or needs help)": "Assisted",
            "Non-ambulatory (wheelchair/bedbound)": "Non-ambulatory"
        }
        prefill_label = {
            "Independent": "Independent (no device)",
            "Assisted": "Assisted (cane/walker or needs help)",
            "Non-ambulatory": "Non-ambulatory (wheelchair/bedbound)"
        }[mobility_prefill]
        mobility_label = st.selectbox("Mobility", mobility_options,
                                      index=mobility_options.index(prefill_label),
                                      key=f"{pid}_mobility")
        mobility = mobility_map_out[mobility_label]

        chronic_options = [
            "None (no ongoing conditions)",
            "Some (1–2 manageable conditions)",
            "Multiple/Complex (several or complex needs)"
        ]
        chronic_map_out = {
            chronic_options[0]: "None",
            chronic_options[1]: "Some",
            chronic_options[2]: "Multiple/Complex"
        }
        default_chronic_label = chronic_options[2] if "severe_cognitive_decline" in set(rec.get("flags", [])) else chronic_options[1]
        chronic_label = st.selectbox("Chronic Conditions", chronic_options,
                                     index=chronic_options.index(default_chronic_label),
                                     key=f"{pid}_chronic")
        chronic = chronic_map_out[chronic_label]

        inp = make_inputs(state=state, care_type=care_type, care_level=care_level, mobility=mobility, chronic=chronic)

        if care_type in ["assisted_living", "memory_care"]:
            for k in [f"{pid}_hours", f"{pid}_days"]:
                if k in st.session_state:
                    del st.session_state[k]
            room = st.selectbox("Room Type", ["Studio", "1 Bedroom", "Shared"], key=f"{pid}_room")
            try:
                setattr(inp, "room_type", room)
            except Exception:
                pass
        elif care_type == "none":
            st.info("No care plan selected for this person.")
        else:
            # In-home sliders
            if f"{pid}_room" in st.session_state:
                del st.session_state[f"{pid}_room"]
            hours = st.slider("In-home care hours per day", 0, 24, 4, 1, key=f"{pid}_hours")
            days = st.slider("Days of care per month", 0, 31, 20, 1, key=f"{pid}_days",
                             disabled=not ENABLE_INHOME_DAYS_PER_MONTH)
            try:
                setattr(inp, "in_home_hours_per_day", int(hours))
                setattr(inp, "in_home_days_per_month", int(days))
            except Exception:
                pass

        # Compute monthly cost
        try:
            if hasattr(calculator, "monthly_cost"):
                monthly = calculator.monthly_cost(inp)
            else:
                monthly = calculator.estimate(getattr(inp, "care_type", "in_home"))
        except Exception:
            st.error("CalculatorEngine failed while computing monthly cost.")
            st.code("Inputs:\n" + str(vars(inp)))
            st.code(traceback.format_exc())
            st.stop()

        st.metric("Estimated Monthly Cost", f"${int(monthly):,}")
        st.session_state.setdefault("person_costs", {})[pid] = int(monthly)
        st.divider()
        total += int(monthly)

    st.subheader("Combined Total")
    st.session_state.combined_monthly_cost = total
    st.metric("Estimated Combined Monthly Cost", f"${total:,.0f}")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Back to recommendations"):
            st.session_state.step = "recommendations"
            jump_top_once()
            st.rerun()
    with c2:
        if ENABLE_HOUSEHOLD_DRAWERS and st.button("Add Household & Assets (optional)"):
            st.session_state.step = "household"
            jump_top_once()
            st.rerun()
    with c3:
        if ENABLE_DETAILS_PAGE and st.button("View Detailed Breakdown"):
            st.session_state.step = "breakdown"
            jump_top_once()
            st.rerun()

# ---------- Household (drawers) ----------
elif st.session_state.step == "household":
    people = st.session_state.get("people", [])
    names = [p["display_name"] for p in people]
    nameA = names[0] if names else "Person A"
    nameB = names[1] if len(names) > 1 else "Person B"

    st.header("Household & Budget (optional)")
    st.markdown("Add income, benefits, and assets to see affordability. You can skip this.")

    vals = st.session_state.get("house_vals", {})

    def money(label, key, default=0):
        v0 = int(vals.get(key, default) or 0)
        v = st.number_input(label, min_value=0, step=50, value=v0, key=key)
        st.session_state[key] = int(v)
        return int(v)

    # Monthly Income — Individual
    with st.expander("Monthly Income — Individual", expanded=True):
        if len(people) > 1:
            a_ss, a_pn, a_oth = st.columns(3)
            with a_ss: a1 = money(f"Social Security — {nameA}", "a_ss", 0)
            with a_pn: a2 = money(f"Pension — {nameA}", "a_pn", 0)
            with a_oth: a3 = money(f"Other — {nameA}", "a_other", 0)
            b_ss, b_pn, b_oth = st.columns(3)
            with b_ss: b1 = money(f"Social Security — {nameB}", "b_ss", 0)
            with b_pn: b2 = money(f"Pension — {nameB}", "b_pn", 0)
            with b_oth: b3 = money(f"Other — {nameB}", "b_other", 0)
        else:
            a1 = money(f"Social Security — {nameA}", "a_ss", 0)
            a2 = money(f"Pension — {nameA}", "a_pn", 0)
            a3 = money(f"Other — {nameA}", "a_other", 0)
            b1 = b2 = b3 = 0
        st.metric("Subtotal — Individual income", f"${(a1+a2+a3)+(b1+b2+b3):,}")

    # Monthly Income — Household (shared)
    with st.expander("Monthly Income — Household (shared)", expanded=False):
        r = money("Rental income", "hh_rent", 0)
        an = money("Annuity income", "hh_annuity", 0)
        inv = money("Dividends/interest (joint)", "hh_invest", 0)
        tr = money("Trust distributions", "hh_trust", 0)
        oth = money("Other household income", "hh_other", 0)
        st.metric("Subtotal — Household income", f"${r+an+inv+tr+oth:,}")

    # Benefits (VA, LTC)
    with st.expander("Benefits (VA, Long-Term Care insurance)", expanded=True):
        people_local = st.session_state.get("people", [])
        names_local = [p["display_name"] for p in people_local]
        nA = names_local[0] if names_local else "Person A"
        nB = names_local[1] if len(names_local) > 1 else "Person B"

        settings = getattr(calculator, "settings", {}) or {}
        if "va_mapr_2025" not in settings:
            settings["va_mapr_2025"] = {
                "Not a veteran / No VA pension": 0,
                "Veteran (no dependents) — A&A": 2358,
                "Veteran + 1 dependent — A&A": 2795,
                "Two veterans married, one A&A": 2795,
                "Surviving spouse — A&A": 1515,
                "Surviving spouse + 1 child — A&A": 1808,
            }
        if "ltc_monthly_add" not in settings:
            settings["ltc_monthly_add"] = 1800
        calculator.settings = settings
        va_mapr = settings["va_mapr_2025"]
        ltc_add = int(settings["ltc_monthly_add"])

        def va_block(prefix: str, person_name: str):
            st.write(f"**{person_name}**")
            choice = st.radio(
                f"Choose an option for {person_name}:",
                list(va_mapr.keys()) + ["I served, but I’m not sure if I qualify"],
                index=0,
                key=f"{prefix}_va_path",
            )
            result = {"monthly": 0, "detail": "No VA pension"}

            if choice == "I served, but I’m not sure if I qualify":
                st.info("Quick check (not exhaustive):")
                wartime   = st.checkbox("Served during a wartime period", key=f"{prefix}_wartime")
                age_dis   = st.checkbox("65+ or permanently and totally disabled", key=f"{prefix}_age_dis")
                discharge = st.checkbox("Discharge not dishonorable", key=f"{prefix}_discharge")
                need_aa   = st.checkbox("Needs help with daily activities or housebound", key=f"{prefix}_need_aa")
                networth  = st.checkbox("Net worth under VA limit", key=f"{prefix}_networth")
                likely = wartime and age_dis and discharge and networth
                if likely:
                    st.success("You may qualify for VA pension; Aid & Attendance may apply if daily help/housebound.")
                    result["detail"] = "Wizard: likely eligible"
                else:
                    st.warning("Based on these answers, VA pension may not apply. You can still check with a local VSO.")
                    result["detail"] = "Wizard: uncertain"
            else:
                cap = int(va_mapr[choice])
                st.caption(f"Estimated monthly cap for this tier: ${cap:,}.")
                amt = st.number_input(
                    "Monthly VA payment (enter actual if known; otherwise use cap)",
                    min_value=0,
                    step=25,
                    value=cap,
                    key=f"{prefix}_va_actual",
                )
                result = {"monthly": int(amt), "detail": choice}
            return result

        col1, col2 = st.columns(2)
        with col1:
            a_res = va_block("a", nA)
        with col2:
            if len(people_local) > 1:
                b_res = va_block("b", nB)
            else:
                st.write(""); st.write("")
                b_res = {"monthly": 0, "detail": "No VA pension"}

        lc1, lc2 = st.columns(2)
        with lc1:
            a_ltc = st.selectbox(f"Long-Term Care insurance — {nA}", ["No", "Yes"], key="a_ltc")
        with lc2:
            if len(people_local) > 1:
                b_ltc = st.selectbox(f"Long-Term Care insurance — {nB}", ["No", "Yes"], key="b_ltc")
            else:
                st.selectbox("Long-Term Care insurance — (n/a)", ["No"], key="b_ltc_disabled", disabled=True)
                b_ltc = "No"

        a_va = int(a_res.get("monthly", 0))
        b_va = int(b_res.get("monthly", 0)) if len(people_local) > 1 else 0
        st.session_state["a_va_monthly"] = a_va
        st.session_state["b_va_monthly"] = b_va

        benefits_total = (a_va + (ltc_add if a_ltc == "Yes" else 0)) + (b_va + (ltc_add if b_ltc == "Yes" else 0))
        st.metric("Subtotal — Benefits (VA + LTC add-ons)", f"${benefits_total:,.0f}")

    # Home decision
    if ENABLE_HOME_DECISION:
        with st.expander("Home decision (if applicable)", expanded=False):
            choice = st.radio("Plan for the home", ["Keep", "Sell", "HELOC", "Reverse mortgage"], key="home_choice")
            # Common carrying costs
            c1, c2, c3 = st.columns(3)
            with c1: hoa = money("HOA (monthly)", "home_hoa", 0)
            with c2: maint = money("Maintenance (monthly)", "home_maint", 0)
            with c3: utils = money("Utilities (monthly)", "home_utils", 0)
            carry_monthly = hoa + maint + utils

            if choice == "Sell":
                sale_price = money("Estimated sale price", "home_sale_price", 0)
                payoff     = money("Mortgage principal payoff", "home_payoff", 0)
                fees_pct   = st.slider("Estimated selling fees (%)", 0, 15, 7, 1, key="home_sell_fees_pct")
                fees_amt   = int(sale_price * (fees_pct/100.0))
                net_proceeds = max(sale_price - payoff - fees_amt, 0)
                st.metric("Estimated net proceeds", f"${net_proceeds:,.0f}")
                st.session_state["home_net_proceeds"] = net_proceeds
                st.session_state["home_monthly_total"] = carry_monthly  # pre-sale carry if timing matters
            elif choice == "HELOC":
                heloc_limit = money("HELOC available", "home_heloc_limit", 0)
                heloc_rate  = st.number_input("HELOC rate (%)", min_value=0.0, value=8.0, step=0.1, key="home_heloc_rate")
                draw        = money("Monthly draw (if used)", "home_heloc_draw", 0)
                # simple interest-only est
                interest_only = int((heloc_limit * (heloc_rate/100.0)) / 12.0)
                st.metric("Estimated interest-only monthly", f"${interest_only:,.0f}")
                st.session_state["home_monthly_total"] = carry_monthly + interest_only
            elif choice == "Reverse mortgage":
                rm_credit = money("Estimated line of credit", "home_rm_credit", 0)
                rm_fee    = money("Monthly service/insurance", "home_rm_fee", 0)
                st.session_state["home_monthly_total"] = carry_monthly + rm_fee
                st.session_state["home_net_proceeds"] = rm_credit
            else:
                st.session_state["home_monthly_total"] = carry_monthly

            st.metric("Subtotal — Home monthly carrying costs", f"${int(st.session_state.get('home_monthly_total', 0)):,}")

    # Home modifications
    if ENABLE_HOME_MODS:
        with st.expander("Home modifications (if staying at home)", expanded=False):
            st.caption("Select finish level first, then choose modifications. You can pay upfront or amortize.")

            # finish level multiplier
            finish = st.selectbox("Finish level", ["Budget", "Standard", "Custom"], index=1, key="mods_finish")
            mult_map = {"Budget": 0.8, "Standard": 1.0, "Custom": 1.25}
            mult = mult_map.get(finish, 1.0)

            st.markdown("**Choose modifications:**")
            # Base costs (example averages; adjust to your canonical values)
            base_costs = {
                "Ramps": 2000,
                "Grab bars": 400,
                "Widen doorways": 2500,
                "Roll-in shower": 6000,
                "Stair lift": 4500,
                "Lighting & fall prevention": 1200,
                "Smart home alerts": 800
            }

            sel_items = []
            cols = st.columns(2)
            pairs = list(base_costs.items())
            for idx, (label, cost) in enumerate(pairs):
                with cols[idx % 2]:
                    if st.checkbox(f"{label} (avg ${cost:,})", key=f"mod_{label}"):
                        sel_items.append((label, cost))

            upfront = int(sum(int(cost * mult) for (_label, cost) in sel_items))
            st.metric("Estimated upfront cost", f"${upfront:,.0f}")

            amortize = st.checkbox("Amortize instead of paying upfront", value=False, key="mods_amortize")
            months = 0
            monthly_mod = 0
            if amortize:
                months = st.slider("Amortize period (months)", 6, 84, 36, 6, key="mods_months")
                # naive amortization without interest
                monthly_mod = int(upfront / max(months, 1)) if upfront > 0 else 0
            st.metric("Estimated monthly (if amortized)", f"${monthly_mod:,.0f}")

            st.session_state["mods_upfront_total"] = upfront
            st.session_state["mods_monthly_total"] = monthly_mod

    # Other monthly recurring
    if ENABLE_OTHER_MONTHLIES:
        with st.expander("Other monthly costs", expanded=False):
            meds = money("Medications", "mo_meds", 0)
            hi   = money("Medicare/health insurance", "mo_health", 0)
            den  = money("Dental insurance", "mo_dental", 0)
            oth  = money("Other recurring", "mo_other_rec", 0)
            st.session_state["other_monthly_total"] = meds + hi + den + oth
            st.metric("Subtotal — Other monthly costs", f"${int(st.session_state['other_monthly_total']):,}")

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Back to Costs"):
            st.session_state.step = "calculator"
            jump_top_once()
            st.rerun()
    with c2:
        if ENABLE_DETAILS_PAGE and st.button("View Detailed Breakdown"):
            st.session_state.step = "breakdown"
            jump_top_once()
            st.rerun()
    with c3:
        if st.button("Finish"):
            st.session_state.step = "intro"
            jump_top_once()
            st.rerun()

# ---------- Breakdown ----------
elif st.session_state.step == "breakdown":
    st.header("Detailed Breakdown")

    people = st.session_state.get("people", [])
    costs  = st.session_state.get("person_costs", {})
    nameA = people[0]["display_name"] if people else "Person A"
    nameB = people[1]["display_name"] if len(people) > 1 else "Person B"

    # Care costs
    care_A = int(costs.get("A", 0))
    care_B = int(costs.get("B", 0)) if len(people) > 1 else 0
    care_total = care_A + care_B

    # Income — individual
    s = st.session_state
    inc_A = int(s.get("a_ss", 0)) + int(s.get("a_pn", 0)) + int(s.get("a_other", 0))
    inc_B = int(s.get("b_ss", 0)) + int(s.get("b_pn", 0)) + int(s.get("b_other", 0)) if len(people) > 1 else 0
    inc_house = int(s.get("hh_rent", 0)) + int(s.get("hh_annuity", 0)) + int(s.get("hh_invest", 0)) + int(s.get("hh_trust", 0)) + int(s.get("hh_other", 0))

    # Benefits (from VA wizard)
    va_A = int(s.get("a_va_monthly", 0))
    va_B = int(s.get("b_va_monthly", 0)) if len(people) > 1 else 0

    # Other monthly costs (home carry, mods, other recurring)
    home_monthly   = int(s.get("home_monthly_total", 0))
    mods_monthly   = int(s.get("mods_monthly_total", 0))
    other_monthly  = int(s.get("other_monthly_total", 0))
    addl_costs     = home_monthly + mods_monthly + other_monthly

    # Assets (placeholder totals if captured elsewhere)
    assets_common  = int(s.get("assets_common_total", 0))
    assets_detail  = int(s.get("assets_detailed_total", 0))
    assets_total   = assets_common + assets_detail

    # Totals
    income_total = inc_A + inc_B + inc_house + va_A + va_B
    monthly_need = care_total + addl_costs
    gap = monthly_need - income_total

    # Headline tiles
    c1, c2, c3 = st.columns(3)
    c1.metric("Monthly Care + Selected Costs", f"${monthly_need:,.0f}")
    c2.metric("Total Monthly Income (incl. VA)", f"${income_total:,.0f}")
    c3.metric("Estimated Monthly Gap", f"${gap:,.0f}")

    # Years funded from assets
    years = 0.0
    if gap > 0 and assets_total > 0:
        years = round(assets_total / max(gap, 1), 1)
    st.subheader(f"Estimated runway from assets: {years} years")

    # Per-person details
    st.markdown("### Per-person care costs")
    if people:
        if len(people) > 1:
            cA, cB = st.columns(2)
            with cA: st.write(f"**{nameA}**: ${care_A:,.0f}/mo")
            with cB: st.write(f"**{nameB}**: ${care_B:,.0f}/mo")
        else:
            st.write(f"**{nameA}**: ${care_A:,.0f}/mo")

    st.markdown("### Income breakdown (numbers)")
    st.write({
        "Individual A": inc_A,
        "Individual B": inc_B,
        "Household": inc_house,
        "VA benefits": va_A + va_B,
    })

    st.markdown("### Additional monthly costs (numbers)")
    st.write({
        "Home carrying": home_monthly,
        "Home modifications (amortized)": mods_monthly,
        "Other recurring": other_monthly,
    })

    st.markdown("### Assets summary (numbers)")
    st.write({
        "Common assets": assets_common,
        "Detailed assets": assets_detail,
        "Total assets": assets_total,
    })

    # Optional donuts via Altair
    try:
        if ENABLE_CHARTS and HAVE_ALTAIR:
            import pandas as pd  # noqa: F401
            inc_df = pd.DataFrame([
                {"Category": "Indiv A", "Amount": inc_A},
                {"Category": "Indiv B", "Amount": inc_B},
                {"Category": "Household", "Amount": inc_house},
                {"Category": "VA", "Amount": va_A + va_B},
            ])
            cost_df = pd.DataFrame([
                {"Category": "Care", "Amount": care_total},
                {"Category": "Home/Mods/Other", "Amount": addl_costs},
            ])
            colA, colB = st.columns(2)
            with colA:
                st.caption("Income composition")
                st.altair_chart(
                    alt.Chart(inc_df).mark_arc(innerRadius=60).encode(theta="Amount", color="Category",
                                                                     tooltip=["Category", "Amount"]),
                    use_container_width=True
                )
            with colB:
                st.caption("Costs composition")
                st.altair_chart(
                    alt.Chart(cost_df).mark_arc(innerRadius=60).encode(theta="Amount", color="Category",
                                                                       tooltip=["Category", "Amount"]),
                    use_container_width=True
                )
    except Exception:
        st.info("Charts unavailable. Showing numeric breakdown above.")

    st.divider()
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Back to Household"):
            st.session_state.step = "household"
            jump_top_once()
            st.rerun()
    with b2:
        if st.button("Back to Costs"):
            st.session_state.step = "calculator"
            jump_top_once()
            st.rerun()

# ---------- Jump top helper ----------
if st.session_state.get("_jump_top"):
    # dummy anchor trick for mobile scroll reset
    st.markdown("<a id='top'></a>", unsafe_allow_html=True)
    st.session_state["_jump_top"] = False