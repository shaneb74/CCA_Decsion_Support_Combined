# app.py — Senior Navigator (Planner → Recommendation → Costs → Household → Breakdown)
# Stable build with guardrails + safe session handling

from pathlib import Path
from types import SimpleNamespace
import traceback
import streamlit as st

# ---------- Page config ----------
st.set_page_config(page_title="Senior Navigator • Planner + Cost", page_icon="🧭", layout="centered")

# ---------- Feature flags ----------
ENABLE_PARTNER_INTERSTITIAL = True
ENABLE_REC_OVERRIDE = True
ENABLE_INHOME_DAYS_PER_MONTH = True
ENABLE_MOBILITY_CARRYOVER = True
ENABLE_HOUSEHOLD_SECTION = True
ENABLE_VA_WIZARD = True
ENABLE_DETAILS_PAGE = True
ENABLE_CHARTS = False  # keep False unless Altair present

# ---------- Optional charts dependency ----------
try:
    import altair as alt  # noqa: F401
    HAVE_ALTAIR = True
except Exception:
    HAVE_ALTAIR = False

# ---------- Safe answer-map helpers ----------
def _is_intlike(x) -> bool:
    try:
        int(str(x))
        return True
    except Exception:
        return False

def order_answer_map(amap: dict):
    """Return (ordered_keys, ordered_labels) safely whether keys are '1','2',... or arbitrary strings."""
    if not isinstance(amap, dict) or not amap:
        return [], []
    keys = list(amap.keys())
    if all(_is_intlike(k) for k in keys):
        ordered_keys = [str(k) for k in sorted(int(str(k)) for k in keys)]
    else:
        ordered_keys = [str(k) for k in sorted(map(str, keys))]
    ordered_labels = [amap[k] for k in ordered_keys]
    return ordered_keys, ordered_labels

def radio_from_answer_map(label, amap, *, key, help_text=None, default_key=None):
    """Render a radio from a JSON answer map and return the selected key (string)."""
    ordered_keys, ordered_labels = order_answer_map(amap)
    if not ordered_labels:
        return default_key
    if default_key is not None and str(default_key) in ordered_keys:
        idx = ordered_keys.index(str(default_key))
    else:
        idx = 0
    sel_label = st.radio(label, options=ordered_labels, index=idx, key=key, help=help_text)
    return ordered_keys[ordered_labels.index(sel_label)]

# ---------- Paths (all in repo root) ----------
ROOT = Path(__file__).resolve().parent
QA_PATH = ROOT / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = ROOT / "recommendation_logic_FINAL_MASTER_UPDATED.json"

# ---------- Engines ----------
try:
    from engines import PlannerEngine, CalculatorEngine
except Exception:
    st.error("Failed to import engines.py")
    st.code(traceback.format_exc())
    st.stop()

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

# ---------- Helpers ----------
def make_inputs(**kwargs):
    """Create a calculator inputs object."""
    obj = SimpleNamespace()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj

def reset_all():
    for k in list(st.session_state.keys()):
        if not k.startswith("_"):
            del st.session_state[k]
    st.session_state.step = "intro"

def normalize_planner_result(res_obj):
    """Return dict with keys: care_type, flags(set), scores(dict), reasons(list), narrative(str)."""
    if hasattr(res_obj, "__dict__"):
        care_type = getattr(res_obj, "care_type", None)
        flags = set(getattr(res_obj, "flags", set()) or set())
        scores = getattr(res_obj, "scores", {}) or {}
        reasons = list(getattr(res_obj, "reasons", []) or [])
        narrative = (
            getattr(res_obj, "advisory", None)
            or getattr(res_obj, "message", None)
            or getattr(res_obj, "message_rendered", None)
            or getattr(res_obj, "narrative", None)
            or ""
        )
    else:
        care_type = (res_obj or {}).get("care_type")
        flags = set((res_obj or {}).get("flags", []))
        scores = (res_obj or {}).get("scores", {}) or {}
        reasons = list((res_obj or {}).get("reasons", []) or [])
        narrative = (
            (res_obj or {}).get("advisory")
            or (res_obj or {}).get("message")
            or (res_obj or {}).get("message_rendered")
            or (res_obj or {}).get("narrative")
            or ""
        )
    return {
        "care_type": care_type,
        "flags": flags,
        "scores": scores,
        "reasons": reasons,
        "narrative": narrative,
    }

def postprocess_recommendation(person_name: str, res: dict, thresholds: dict | None = None) -> dict:
    """
    App-side guardrails so UI never shows wildly wrong outcomes if JSON/engine misses a case.
    """
    thresholds = thresholds or {}
    al_min = int(thresholds.get("assisted_living_min", 6))
    ih_min = int(thresholds.get("in_home_min", 3))

    flags = set(res.get("flags", set()) or set())
    scores = res.get("scores", {}) or {}

    # Hard stop: severe cognitive risk -> memory care
    if "severe_cognitive_risk" in flags:
        res["care_type"] = "memory_care"

    # Heavy daily support + safety/no support -> assisted living
    elif (
        {"high_dependence", "high_mobility_dependence", "high_safety_concern"} & flags
        and ("no_support" in flags or "moderate_cognitive_decline" in flags)
    ):
        res["care_type"] = "assisted_living"

    # Clean "no care needed" when zero risk & low scores
    if (
        not flags
        and scores.get("assisted_living", 0) < ih_min
        and scores.get("in_home", 0) < ih_min
    ):
        res["care_type"] = "none"
        if not (res.get("narrative") or "").strip():
            res["narrative"] = (
                f"Hi {person_name}, you’re doing well with **no support needs** right now. "
                "We’re here if things change—you can recheck anytime."
            )

    return res

def get_thresholds_from_planner(planner_engine) -> dict:
    try:
        # engines.PlannerEngine keeps the parsed rec JSON commonly as .rec
        data = getattr(planner_engine, "rec", {}) or {}
        return data.get("final_decision_thresholds", {}) or {}
    except Exception:
        return {}

# ---------- Session init ----------
if "step" not in st.session_state:
    st.session_state.step = "intro"

st.sidebar.title("Senior Navigator")
st.sidebar.caption("Planner → Costs → Budget → Breakdown")
st.sidebar.button("Start over", on_click=reset_all)

# ===================== UI Flow =====================

# Intro
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
    st.info("Typical time: 10–15 minutes. You can stop anytime.")
    if st.button("Start"):
        st.session_state.step = "audience"
        st.rerun()

# Audience
elif st.session_state.step == "audience":
    st.header("Who is this plan for?")
    role = st.radio("Select one:", ["Myself", "My spouse/partner", "My parent", "Both parents", "Someone else"])
    people = []
    if role == "Both parents":
        c1, c2 = st.columns(2)
        with c1:
            n1 = st.text_input("Parent 1 name", value="Mom", key="p1_name", placeholder="Enter name")
        with c2:
            n2 = st.text_input("Parent 2 name", value="Dad", key="p2_name", placeholder="Enter name")
        people = [
            {"id": "A", "display_name": n1, "relationship": "parent"},
            {"id": "B", "display_name": n2, "relationship": "parent"},
        ]
    else:
        default = "Alex" if role != "My parent" else "Mom"
        n = st.text_input("Name", value=default, key="p_name", placeholder="Enter name")
        map_rel = {"Myself": "self", "My spouse/partner": "spouse", "My parent": "parent", "Someone else": "other"}
        people = [{"id": "A", "display_name": n, "relationship": map_rel.get(role, "other")}]

    st.caption("Next, we’ll ask short care questions for each person.")
    if st.button("Continue"):
        st.session_state.people = people
        st.session_state.current_person = 0
        st.session_state.answers = {}
        st.session_state.results = {}
        st.session_state.mobility_raw = {}
        st.session_state.care_overrides = {}
        st.session_state.person_costs = {}
        if ENABLE_PARTNER_INTERSTITIAL:
            st.session_state.step = "partner_context"
        else:
            st.session_state.step = "planner"
        st.rerun()

# Partner interstitial
elif st.session_state.step == "partner_context":
    people = st.session_state.get("people", [])
    single = len(people) == 1
    primary = people[0]["display_name"] if people else "Person A"

    st.header("Before we begin")
    st.markdown(
        f"If **{primary}** needs assisted living or memory care, their spouse/partner may also need some in-home help. "
        "You can include a simple support plan for them now so the household picture is complete."
    )

    if single:
        add = st.checkbox("Yes, I want to evaluate a plan for a spouse/partner", value=False, key="care_partner_add")
        if add:
            st.text_input("Spouse/partner name", value="", placeholder="Enter spouse/partner name", key="care_partner_name")

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
                    "relationship": "spouse"
                })
            st.session_state.step = "planner"
            st.rerun()

# Planner (Q&A; one person at a time)
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

    qa_all = getattr(planner, "qa", {}) or {}
    questions = qa_all.get("questions", [])
    cond_cfg = qa_all.get("conditional_questions", [])

    # one-at-a-time navigation
    ws = st.session_state.setdefault(f"nav_{pid}", {"idx": 0})
    total_q = len(questions)
    idx = int(ws.get("idx", 0))
    idx = max(0, min(idx, total_q - 1))

    answers = st.session_state.answers.get(pid, {})

    # render current question
    if total_q > 0:
        q = questions[idx]
        amap = q.get("answers", {})
        default_key = str(answers.get(f"q{idx+1}")) if f"q{idx+1}" in answers else None
        sel_key = radio_from_answer_map(
            label=q.get("question", f"Question {idx+1}"),
            amap=amap,
            key=f"{pid}_q{idx+1}",
            help_text=q.get("help"),
            default_key=default_key
        )
        if sel_key is not None:
            answers[f"q{idx+1}"] = int(sel_key) if _is_intlike(sel_key) else sel_key

        # remember mobility raw
        if "mobility" in q.get("question", "").lower():
            st.session_state.mobility_raw[pid] = answers.get(f"q{idx+1}")

        # nav buttons
        c1, c2, c3 = st.columns([1,1,2])
        with c1:
            if st.button("Back", disabled=(idx == 0), key=f"back_{pid}"):
                st.session_state[f"nav_{pid}"]["idx"] = max(0, idx - 1)
                st.rerun()
        with c2:
            if st.button("Next", key=f"next_{pid}"):
                if idx + 1 < total_q:
                    st.session_state[f"nav_{pid}"]["idx"] = idx + 1
                    st.rerun()
                else:
                    # end of base questions → possibly conditional
                    # if conditional exists, show it now; otherwise run
                    if cond_cfg:
                        st.session_state[f"nav_{pid}"]["show_conditional"] = True
                        st.rerun()
                    else:
                        # run planner
                        st.session_state.answers[pid] = answers
                        try:
                            raw = planner.run(answers)
                        except Exception:
                            st.error("PlannerEngine.run failed.")
                            st.code(traceback.format_exc()); st.stop()
                        res = normalize_planner_result(raw)
                        thresholds = get_thresholds_from_planner(planner)
                        res = postprocess_recommendation(name, res, thresholds)
                        st.session_state.results[pid] = res

                        # interstitial if more people remain
                        if i + 1 < len(people):
                            st.session_state.current_person = i + 1
                            st.session_state.step = "handoff_next_person"
                        else:
                            st.session_state.step = "recommendations"
                        st.rerun()

    # conditional block
    if ws.get("show_conditional"):
        st.subheader("One more question")
        cq = cond_cfg[0] if cond_cfg else {}
        cmap = cq.get("answers", {"1": "Yes", "2": "No"})
        default_key = None
        sel_key = radio_from_answer_map(
            label=cq.get("question", "Additional question"),
            amap=cmap,
            key=f"{pid}_cond",
            help_text=cq.get("help"),
            default_key=default_key
        )
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Back to questions", key=f"cond_back_{pid}"):
                st.session_state[f"nav_{pid}"]["show_conditional"] = False
                st.rerun()
        with c2:
            if st.button("Finish"):
                st.session_state.answers[pid] = answers
                try:
                    raw = planner.run(answers, conditional_answer=sel_key)
                except Exception:
                    st.error("PlannerEngine.run failed.")
                    st.code(traceback.format_exc()); st.stop()
                res = normalize_planner_result(raw)
                thresholds = get_thresholds_from_planner(planner)
                res = postprocess_recommendation(name, res, thresholds)
                st.session_state.results[pid] = res

                if i + 1 < len(people):
                    st.session_state.current_person = i + 1
                    st.session_state.step = "handoff_next_person"
                else:
                    st.session_state.step = "recommendations"
                st.rerun()

# Interstitial between people
elif st.session_state.step == "handoff_next_person":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if i >= len(people):
        st.session_state.step = "recommendations"; st.rerun()
    next_name = people[i]["display_name"]
    st.header("Great, that set is done.")
    st.write(f"Now let’s assess **{next_name}**.")
    if st.button("Continue"):
        st.session_state.step = "planner"
        st.rerun()

# Recommendations + override
elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without redoing questions.")

    for p in st.session_state.people:
        rec = st.session_state.results.get(p["id"], {}) or {}
        default = rec.get("care_type", "in_home")
        label_default = default.replace("_", " ").title()
        st.subheader(f"{p['display_name']}: {label_default} (recommended)")

        # Reasons bullets
        for r in rec.get("reasons", []):
            st.write("• " + str(r))

        # Narrative/advisory
        narrative = (
            rec.get("narrative")
            or rec.get("advisory")
            or rec.get("message")
            or rec.get("message_rendered")
        )
        if narrative:
            st.info(narrative)

        # Debug toggle
        if st.checkbox(f"Show details for {p['display_name']}", key=f"dbg_{p['id']}"):
            st.json({
                "care_type": rec.get("care_type"),
                "flags": sorted(list(rec.get("flags", []))),
                "scores": rec.get("scores", {}),
                "reasons": rec.get("reasons", []),
                "narrative": narrative or "",
            })

        if ENABLE_REC_OVERRIDE:
            care_choices = ["in_home", "assisted_living", "memory_care", "none"]
            labels = {
                "in_home": "In-home Care",
                "assisted_living": "Assisted Living",
                "memory_care": "Memory Care",
                "none": "No care needed"
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

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back"):
            # back to last person's planner
            st.session_state.current_person = max(0, len(st.session_state.people) - 1)
            st.session_state.step = "planner"
            st.rerun()
    with c2:
        if st.button("See Costs"):
            st.session_state.step = "calculator"
            st.rerun()

# Calculator
elif st.session_state.step == "calculator":
    st.header("Cost Planner")

    state = st.selectbox("Location", ["National", "Washington", "California", "Texas", "Florida"],
                         help="Adjusts for typical market rates in the selected state.")

    total = 0
    for p in st.session_state.people:
        pid = p["id"]
        name = p["display_name"]
        rec = st.session_state.results.get(pid, {})
        care_type = st.session_state.get("care_overrides", {}).get(pid, rec.get("care_type", "in_home"))

        st.subheader(f"{name} — Scenario: {care_type.replace('_', ' ').title()} "
                     f"(recommended: {rec.get('care_type', 'in_home').replace('_', ' ').title()})")

        # Mobility carryover
        mobility_prefill = "Independent"
        if ENABLE_MOBILITY_CARRYOVER:
            raw_mob = st.session_state.get("mobility_raw", {}).get(pid)
            if raw_mob in (2, 3):
                mobility_prefill = "Assisted"
            if raw_mob in (4, "4"):
                mobility_prefill = "Non-ambulatory"

        care_level_default = "High" if ("severe_cognitive_risk" in rec.get("flags", set())
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
        default_chronic_label = chronic_options[2] if "severe_cognitive_risk" in rec.get("flags", set()) else chronic_options[1]
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
            setattr(inp, "room_type", room)
        elif care_type == "none":
            # zero cost
            st.metric("Estimated Monthly Cost", "$0")
            st.session_state.setdefault("person_costs", {})[pid] = 0
            st.divider()
            total += 0
        else:
            # In-home sliders
            if f"{pid}_room" in st.session_state:
                del st.session_state[f"{pid}_room"]
            hours = st.slider("In-home care hours per day", 0, 24, 4, 1, key=f"{pid}_hours")
            days = st.slider("Days of care per month", 0, 31, 20, 1, key=f"{pid}_days",
                             disabled=not ENABLE_INHOME_DAYS_PER_MONTH)
            setattr(inp, "in_home_hours_per_day", int(hours))
            setattr(inp, "in_home_days_per_month", int(days))

        # Compute monthly cost
        try:
            if care_type == "none":
                monthly = 0
            else:
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

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back to recommendations"):
            st.session_state.step = "recommendations"
            st.rerun()
    with c2:
        if ENABLE_HOUSEHOLD_SECTION and st.button("Add Household & Assets (optional)"):
            st.session_state.step = "household"
            st.rerun()

# Household (drawers)
elif st.session_state.step == "household":
    people = st.session_state.get("people", [])
    names = [p["display_name"] for p in people]
    nameA = names[0] if names else "Person A"
    nameB = names[1] if len(names) > 1 else "Person B"

    st.header("Household & Budget (optional)")
    st.markdown("Add income, benefits, and assets to see affordability. You can skip this.")

    # Safe money helper (no widget/session key collision)
    def money(label, key, default=0):
        vals = st.session_state.get("house_vals", {})
        widget_key = f"house_{key}"
        v0 = int(vals.get(key, default) or 0)
        v = st.number_input(label, min_value=0, step=50, value=v0, key=widget_key)
        vals[key] = int(v or 0)
        st.session_state["house_vals"] = vals
        return vals[key]

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
            st.metric("Subtotal — Individual income", f"${(a1+a2+a3)+(b1+b2+b3):,}")
        else:
            a1 = money(f"Social Security — {nameA}", "a_ss", 0)
            a2 = money(f"Pension — {nameA}", "a_pn", 0)
            a3 = money(f"Other — {nameA}", "a_other", 0)
            st.metric("Subtotal — Individual income", f"${(a1+a2+a3):,}")

    # Monthly Income — Household (shared)
    with st.expander("Monthly Income — Household (shared)", expanded=False):
        r = money("Rental income", "hh_rent", 0)
        an = money("Annuity income", "hh_annuity", 0)
        inv = money("Dividends/interest (joint)", "hh_invest", 0)
        tr = money("Trust distributions", "hh_trust", 0)
        oth = money("Other household income", "hh_other", 0)
        st.metric("Subtotal — Household income", f"${r+an+inv+tr+oth:,}")

    # VA / LTC wizard (simple)
    if ENABLE_VA_WIZARD:
        with st.expander("Benefits (VA, Long-Term Care insurance)", expanded=True):
            names_local = [p["display_name"] for p in people]
            nA = names_local[0] if names_local else "Person A"
            nB = names_local[1] if len(names_local) > 1 else "Person B"

            # lightweight defaults if calculator didn't have them
            settings = getattr(calculator, "settings", {}) or {}
            if "va_mapr_2025" not in settings:
                settings["va_mapr_2025"] = {
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
                    [
                        "Not a veteran / No VA pension",
                        "I already receive or qualify for VA pension/Aid & Attendance",
                        "I served, but I’m not sure if I qualify",
                    ],
                    index=0,
                    key=f"{prefix}_va_path",
                )
                result = {"monthly": 0, "detail": "No VA pension"}

                if choice.startswith("I already receive"):
                    tier = st.selectbox("Select status", list(va_mapr.keys()), key=f"{prefix}_va_tier")
                    cap = int(va_mapr[tier])
                    st.caption(f"Estimated monthly cap for this tier: ${cap:,}.")
                    amt = st.number_input(
                        "Monthly VA payment (enter actual if known; otherwise use cap)",
                        min_value=0, step=25, value=cap, key=f"{prefix}_va_actual",
                    )
                    result = {"monthly": int(amt), "detail": tier}
                elif choice.startswith("I served"):
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
                return result

            col1, col2 = st.columns(2)
            with col1:
                a_res = va_block("a", nA)
            with col2:
                if len(people) > 1:
                    b_res = va_block("b", nB)
                else:
                    st.write(""); st.write("")
                    b_res = {"monthly": 0, "detail": "No VA pension"}

            lc1, lc2 = st.columns(2)
            with lc1:
                a_ltc = st.selectbox(f"Long-Term Care insurance — {nA}", ["No", "Yes"], key="a_ltc")
            with lc2:
                if len(people) > 1:
                    b_ltc = st.selectbox(f"Long-Term Care insurance — {nB}", ["No", "Yes"], key="b_ltc")
                else:
                    st.selectbox("Long-Term Care insurance — (n/a)", ["No"], key="b_ltc_disabled", disabled=True)
                    b_ltc = "No"

            a_va = int(a_res.get("monthly", 0))
            b_va = int(b_res.get("monthly", 0)) if len(people) > 1 else 0
            st.session_state["a_va_monthly"] = a_va
            st.session_state["b_va_monthly"] = b_va

            benefits_total = (a_va + (ltc_add if a_ltc == "Yes" else 0)) + (b_va + (ltc_add if b_ltc == "Yes" else 0))
            st.metric("Subtotal — Benefits (VA + LTC add-ons)", f"${benefits_total:,.0f}")

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Back to Costs"):
            st.session_state.step = "calculator"; st.rerun()
    with c2:
        if ENABLE_DETAILS_PAGE and st.button("View Detailed Breakdown"):
            st.session_state.step = "breakdown"; st.rerun()
    with c3:
        if st.button("Finish"):
            st.session_state.step = "intro"; st.rerun()

# Breakdown (lightweight numeric summary; charts optional)
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
    hv = s.get("house_vals", {})
    inc_A = int(hv.get("a_ss", 0)) + int(hv.get("a_pn", 0)) + int(hv.get("a_other", 0))
    inc_B = int(hv.get("b_ss", 0)) + int(hv.get("b_pn", 0)) + int(hv.get("b_other", 0)) if len(people) > 1 else 0
    inc_house = int(hv.get("hh_rent", 0)) + int(hv.get("hh_annuity", 0)) + int(hv.get("hh_invest", 0)) + int(hv.get("hh_trust", 0)) + int(hv.get("hh_other", 0))

    # Benefits (from VA wizard)
    va_A = int(s.get("a_va_monthly", 0))
    va_B = int(s.get("b_va_monthly", 0)) if len(people) > 1 else 0

    income_total = inc_A + inc_B + inc_house + va_A + va_B
    monthly_need = care_total  # extend when you add home/mods/other
    gap = monthly_need - income_total

    c1, c2, c3 = st.columns(3)
    c1.metric("Monthly Care + Selected Costs", f"${monthly_need:,.0f}")
    c2.metric("Total Monthly Income (incl. VA)", f"${income_total:,.0f}")
    c3.metric("Estimated Monthly Gap", f"${gap:,.0f}")

    st.markdown("### Per-person care costs")
    if people:
        if len(people) > 1:
            cA, cB = st.columns(2)
            with cA: st.write(f"**{nameA}**: ${care_A:,.0f}/mo")
            with cB: st.write(f"**{nameB}**: ${care_B:,.0f}/mo")
        else:
            st.write(f"**{nameA}**: ${care_A:,.0f}/mo")

    st.markdown("### Income breakdown")
    st.write({
        "Individual A": inc_A,
        "Individual B": inc_B,
        "Household": inc_house,
        "VA benefits": va_A + va_B,
    })

    st.divider()
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Back to Household"):
            st.session_state.step = "household"; st.rerun()
    with b2:
        if st.button("Back to Costs"):
            st.session_state.step = "calculator"; st.rerun()