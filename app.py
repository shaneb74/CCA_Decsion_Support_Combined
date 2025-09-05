
from __future__ import annotations

# app.py — Senior Navigator (Planner → Recommendation → Costs → Household → Breakdown)
# Production build: robust narrative rendering, spouse button guard, mobile-friendly planner,
# VA wizard, home decisions, home mods, other costs, breakdown.


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
ENABLE_HOUSEHOLD_DRAWERS = True
ENABLE_VA_WIZARD = True
ENABLE_HOME_DECISION = True
ENABLE_HOME_MODS = True
ENABLE_OTHER_MONTHLY = True
ENABLE_DETAILS_PAGE = True
ENABLE_CHARTS = False            # keep False to avoid chart dependency issues
MOBILE_ONE_QUESTION = True

# ---------- Optional charts dependency ----------
try:
    import altair as alt  # noqa: F401
    HAVE_ALTAIR = True
except Exception:
    HAVE_ALTAIR = False

# ---------- Data paths ----------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
QA_PATH = DATA_DIR / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = DATA_DIR / "recommendation_logic_FINAL_MASTER_UPDATED.json"

# ---------- Helpers (safe string format, reco templates) ----------
def safe_format(template: str, ctx: dict) -> str:
    class _D(dict):
        def __missing__(self, k): 
            return "{" + k + "}"
    return (template or "").format_map(_D(ctx or {}))

def load_reco_templates(rec_path: str | Path) -> dict:
    try:
        with open(rec_path, "r", encoding="utf-8") as f:
            j = json.load(f)
        return j.get("recommendations", j)  # support either top-level or nested
    except Exception:
        return {}

# ---------- Engines ----------
try:
    from engines import PlannerEngine, CalculatorEngine  # CalcInputs isn't guaranteed
except Exception:
    st.error("Failed to import engines.py. See traceback:")
    st.code(traceback.format_exc())
    st.stop()

missing = []
if not QA_PATH.exists():
    missing.append(str(QA_PATH))
if not REC_PATH.exists():
    missing.append(str(REC_PATH))
if missing:
    st.error("Missing required data files:\n" + "\n".join(f"• {m}" for m in missing))
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

# ---------- Inputs wrapper ----------
def make_inputs(**kwargs):
    obj = SimpleNamespace()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj

# ---------- Reset ----------
def reset_all():
    for k in list(st.session_state.keys()):
        if not k.startswith("_"):
            del st.session_state[k]
    st.session_state.step = "intro"

# ---------- Session init ----------
if "step" not in st.session_state:
    st.session_state.step = "intro"

st.sidebar.title("Senior Navigator")
st.sidebar.caption("Planner → Costs → Budget → Breakdown")
st.sidebar.button("Start over", on_click=reset_all)

# ===================== Steps =====================

# ---------- Intro ----------
if st.session_state.step == "intro":
    st.title("Let’s take this one step at a time")
    st.markdown("""
Choosing senior living or in-home support can feel overwhelming.  
This tool breaks it down into clear steps.

**What happens next**
1. Answer quick care questions → we recommend a care type.  
2. Review costs for that scenario (you can override).  
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
            n1 = st.text_input("Parent 1 name", value="", placeholder="Enter first parent's name", key="p1_name")
            st.selectbox("Parent 1 age", ["65–74", "75–84", "85+"], key="p1_age")
        with c2:
            n2 = st.text_input("Parent 2 name", value="", placeholder="Enter second parent's name", key="p2_name")
            st.selectbox("Parent 2 age", ["65–74", "75–84", "85+"], key="p2_age")
        people = [
            {"id": "A", "display_name": (n1 or "Parent 1"), "relationship": "parent"},
            {"id": "B", "display_name": (n2 or "Parent 2"), "relationship": "parent"},
        ]
    else:
        default = "" if role == "My parent" else ""
        n = st.text_input("Name", value=default, placeholder="Enter name", key="p_name")
        st.selectbox("Approximate age", ["65–74", "75–84", "85+"], key="p_age")
        map_rel = {"Myself": "self", "My spouse/partner": "spouse", "My parent": "parent", "Someone else": "other"}
        people = [{"id": "A", "display_name": (n or "Person A"), "relationship": map_rel.get(role, "other")}]

    st.caption("Next, we’ll ask short care questions for each person.")
    if st.button("Continue"):
        st.session_state.people = people
        st.session_state.current_person = 0
        st.session_state.answers = {}
        st.session_state.planner_results = {}
        st.session_state.mobility_raw = {}
        st.session_state.care_overrides = {}
        st.session_state.person_costs = {}
        st.session_state.step = "partner_context" if ENABLE_PARTNER_INTERSTITIAL else "planner"
        st.rerun()

# ---------- Partner interstitial ----------
elif st.session_state.step == "partner_context":
    people = st.session_state.get("people", [])
    single = len(people) == 1
    primary = people[0]["display_name"] if people else "Person A"

    st.header("Before we begin")
    st.markdown(f"""
If **{primary}** needs to leave the home for assisted living or memory care, 
their spouse/partner may also need to consider some in-home help.  

Would you like to evaluate a care support plan for a spouse or partner now so the household picture is complete.
""")

    if single:
        add = st.checkbox("Yes, I want to evaluate a plan for a spouse/partner",
                          value=False, key="care_partner_add")
        if add:
            st.text_input("Spouse/partner name", value="",
                          placeholder="Enter spouse/partner name", key="care_partner_name")

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
                    "display_name": (st.session_state.get("care_partner_name") or "Spouse/Partner"),
                    "relationship": "spouse"
                })
            st.session_state.step = "planner"
            st.rerun()

# ---------- Planner (Q&A) ----------
elif st.session_state.step == "planner":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if not people:
        reset_all(); st.rerun()
    person = people[i]
    name = person["display_name"]

    st.header(f"Care Plan Questions for {name}")
    st.caption(f"Person {i+1} of {len(people)}")

    qa = planner.qa or {}
    questions = qa.get("questions", [])
    answers = st.session_state.answers.get(person["id"], {})
    cond_cfg = qa.get("conditional_questions")

    # one-question mode for mobile readability
    if MOBILE_ONE_QUESTION:
        ws = st.session_state.setdefault("planner_wizard", {}).setdefault(person["id"], {})
        total_q = len(questions)
        idx = int(ws.get("idx", 0))
        idx = max(0, min(idx, total_q - 1))

        q = questions[idx]
        # record mobility index for carryover
        if "mobility" in q.get("question", "").lower():
            st.session_state.mobility_raw[person["id"]] = answers.get(f"q{idx+1}")

        opts_map = q.get("answers", {})
        ordered_keys = [str(n) for n in sorted(map(int, opts_map.keys()))]
        prev = answers.get(f"q{idx+1}")
        sel_label = st.radio(
            q.get("question", f"Question {idx+1}"),
            options=[opts_map[k] for k in ordered_keys],
            index=(ordered_keys.index(str(prev)) if prev in ordered_keys else 0),
            key=f"{person['id']}_q{idx+1}",
            help=q.get("help")
        )
        sel_key = ordered_keys[[opts_map[k] for k in ordered_keys].index(sel_label)]
        answers[f"q{idx+1}"] = int(sel_key)
        st.session_state.answers[person["id"]] = answers

        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("Back"):
                if idx == 0:
                    if i == 0:
                        st.session_state.step = "partner_context" if ENABLE_PARTNER_INTERSTITIAL else "audience"
                    else:
                        st.session_state.current_person = i - 1
                        st.session_state["_jump_top"] = True
                    st.rerun()
                else:
                    ws["idx"] = idx - 1
                    st.session_state["_jump_top"] = True
                    st.rerun()
        with c2:
            st.write(f"Question {idx+1} of {total_q}")
        with c3:
            at_end = (idx == total_q - 1)
            if st.button("Next"):
                if not at_end:
                    ws["idx"] = idx + 1
                    st.session_state["_jump_top"] = True
                    st.rerun()
                else:
                    # optional conditional only when warranted
                    conditional_answer = None
                    if cond_cfg:
                        cq = cond_cfg[0]
                        trig = cq.get("trigger", "").lower()
                        # basic trigger: if any answer text contains 'cognitive'/'memory' flag
                        # engine will double-check; UI keeps it simple
                        cond_show = any("cognit" in q.get("question", "").lower() for q in questions)
                        if cond_show:
                            st.session_state.step = "planner_conditional"
                            st.rerun()
                    # else go straight to results
                    try:
                        res = planner.run(answers, conditional_answer=None)
                    except Exception:
                        st.error("PlannerEngine.run failed.")
                        st.code(traceback.format_exc())
                        st.stop()

                    # normalize result (object or dict)
                    care_type = (getattr(res, "care_type", None) or (res.get("care_type") if isinstance(res, dict) else None))
                    flags     = set(getattr(res, "flags", None) or (res.get("flags", []) if isinstance(res, dict) else []))
                    scores    = getattr(res, "scores", None) or (res.get("scores", {}) if isinstance(res, dict) else {})
                    reasons   = getattr(res, "reasons", None) or (res.get("reasons", []) if isinstance(res, dict) else [])
                    advisory  = getattr(res, "advisory", None) or (res.get("advisory") if isinstance(res, dict) else None)

                    st.session_state.planner_results[person["id"]] = {
                        "care_type": care_type,
                        "flags": flags,
                        "scores": scores,
                        "reasons": reasons,
                        "advisory": advisory,
                    }

                    if i + 1 < len(people):
                        st.session_state.current_person = i + 1
                        st.session_state["_jump_top"] = True
                        st.rerun()
                    else:
                        st.session_state.step = "recommendations"
                        st.session_state["_jump_top"] = True
                        st.rerun()

    else:
        # classic all-questions on one page
        mobility_q_idx = None
        for idx, q in enumerate(questions, start=1):
            if "mobility" in q.get("question", "").lower():
                mobility_q_idx = idx

            prev = answers.get(f"q{idx}")
            opts_map = q.get("answers", {})
            ordered_keys = [str(n) for n in sorted(map(int, opts_map.keys()))]
            sel_label = st.radio(
                q.get("question", f"Question {idx}"),
                options=[opts_map[k] for k in ordered_keys],
                index=(ordered_keys.index(str(prev)) if prev in ordered_keys else 0),
                key=f"{person['id']}_q{idx}",
                help=q.get("help")
            )
            sel_key = ordered_keys[[opts_map[k] for k in ordered_keys].index(sel_label)]
            answers[f"q{idx}"] = int(sel_key)

        if mobility_q_idx is not None:
            st.session_state.mobility_raw[person["id"]] = answers.get(f"q{mobility_q_idx}")

        # optional conditional
        conditional_answer = None
        if cond_cfg:
            cq = cond_cfg[0]
            label = cq.get("question", "Additional question")
            answers_map = cq.get("answers", {"1": "Yes", "2": "No"})
            ordered_ckeys = [str(n) for n in sorted(map(int, answers_map.keys()))]
            sel = st.radio(label, options=[answers_map[k] for k in ordered_ckeys], key=f"{person['id']}_cond")
            for k, v in answers_map.items():
                if v == sel:
                    conditional_answer = k
                    break

        st.session_state.answers[person["id"]] = answers

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Back"):
                if i == 0:
                    st.session_state.step = "partner_context" if ENABLE_PARTNER_INTERSTITIAL else "audience"
                else:
                    st.session_state.current_person = i - 1
                st.rerun()
        with c2:
            if st.button("Next"):
                try:
                    res = planner.run(answers, conditional_answer=conditional_answer)
                except Exception:
                    st.error("PlannerEngine.run failed.")
                    st.code(traceback.format_exc())
                    st.stop()

                care_type = (getattr(res, "care_type", None) or (res.get("care_type") if isinstance(res, dict) else None))
                flags     = set(getattr(res, "flags", None) or (res.get("flags", []) if isinstance(res, dict) else []))
                scores    = getattr(res, "scores", None) or (res.get("scores", {}) if isinstance(res, dict) else {})
                reasons   = getattr(res, "reasons", None) or (res.get("reasons", []) if isinstance(res, dict) else [])
                advisory  = getattr(res, "advisory", None) or (res.get("advisory") if isinstance(res, dict) else None)

                st.session_state.planner_results[person["id"]] = {
                    "care_type": care_type,
                    "flags": flags,
                    "scores": scores,
                    "reasons": reasons,
                    "advisory": advisory
                }

                if i + 1 < len(people):
                    st.session_state.current_person = i + 1
                    st.rerun()
                else:
                    st.session_state.step = "recommendations"
                    st.rerun()

# ---------- Recommendations + override ----------
elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without redoing questions.")

    reco_map = load_reco_templates(REC_PATH)

    for p in st.session_state.people:
        rec = st.session_state.planner_results.get(p["id"], {})
        default = rec.get("care_type", "in_home")
        st.subheader(f"{p['display_name']}: {default.replace('_', ' ').title()} (recommended)")

        # reasons bullets
        #for r in rec.get("reasons", []):
        #    st.write("• " + str(r))

        # conversational blurb: try multiple keys, fallback to template
        narrative = (
            rec.get("advisory")
            or rec.get("message")
            or rec.get("narrative")
            or rec.get("message_rendered")
            or rec.get("message_template")
        )
        if not narrative:
            node = reco_map.get(default) if isinstance(reco_map, dict) else None
            if isinstance(node, dict):
                tpl = node.get("message_template") or node.get("helper_text") or node.get("message")
                ctx = {"name": p.get("display_name") or "your loved one",
                       "greeting": "Good news," if default == "in_home" else "Based on the answers,",
                       "positive_state": "doing well",
                       "encouragement": "Keep what’s working and re-check as needs change",
                       "preference_clause": ""}
                if tpl:
                    narrative = safe_format(tpl, ctx)
        if narrative:
            st.info(narrative)

        if ENABLE_REC_OVERRIDE:
            care_choices = ["in_home", "assisted_living", "memory_care"]
            labels = {"in_home": "In-home Care", "assisted_living": "Assisted Living", "memory_care": "Memory Care"}
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
        st.rerun()

# ---------- Calculator ----------
elif st.session_state.step == "calculator":
    st.header("Cost Planner")

    state = st.selectbox("Location", ["National", "Washington", "California", "Texas", "Florida"],
                         help="Adjusts for typical market rates in the selected state.")

    total = 0
    for p in st.session_state.people:
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
            if raw_mob in (2, 3):
                mobility_prefill = "Assisted"
            if raw_mob == 4:
                mobility_prefill = "Non-ambulatory"

        care_level_default = "High" if ("severe_cognitive_decline" in rec.get("flags", set())
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
        default_chronic_label = chronic_options[2] if "severe_cognitive_decline" in rec.get("flags", set()) else chronic_options[1]
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
            monthly = calculator.monthly_cost(inp) if hasattr(calculator, "monthly_cost") else calculator.estimate(getattr(inp, "care_type", "in_home"))
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
        if st.button("Add Household & Assets (optional)"):
            st.session_state.step = "household"
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

    # VA / LTC wizard
    if ENABLE_VA_WIZARD:
        with st.expander("Benefits (VA, Long-Term Care insurance)", expanded=True):
            people_local = st.session_state.get("people", [])
            names_local = [p["display_name"] for p in people_local]
            nA = names_local[0] if names_local else "Person A"
            nB = names_local[1] if len(people_local) > 1 else "Person B"

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
                    tier = st.selectbox(
                        "Select status",
                        list(va_mapr.keys()),
                        key=f"{prefix}_va_tier",
                        help="Monthly caps from VA MAPR. Enter your actual payment if you know it."
                    )
                    cap = int(va_mapr[tier])
                    st.caption(f"Estimated monthly cap for this tier: ${cap:,}.")
                    amt = st.number_input(
                        "Monthly VA payment (enter actual if known; otherwise use cap)",
                        min_value=0,
                        step=25,
                        value=cap,
                        key=f"{prefix}_va_actual",
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
        with st.expander("Home decision (sell / keep / HELOC / reverse)", expanded=False):
            mode = st.selectbox("Choose home plan", ["Sell", "Keep", "HELOC", "Reverse mortgage"], key="home_mode")
            if mode == "Sell":
                val = money("Estimated home value", "home_value", 0)
                payoff = money("Mortgage payoff / liens", "home_payoff", 0)
                fee_pct = st.slider("Estimated selling costs (%)", 0, 12, 7, 1, key="home_fee_pct")
                fees = int(val * fee_pct / 100.0)
                net = max(0, val - payoff - fees)
                st.session_state["home_sale_net"] = net
                st.metric("Estimated net proceeds", f"${net:,}")
            elif mode == "Keep":
                pmt = money("Monthly mortgage/association", "home_monthly_carry", 0)
                taxes = money("Monthly property taxes/insurance", "home_monthly_ti", 0)
                hoa = money("Monthly HOA/maintenance", "home_monthly_hoa", 0)
                util = money("Monthly utilities", "home_monthly_util", 0)
                keep_total = pmt + taxes + hoa + util
                st.session_state["home_monthly_total"] = keep_total
                st.metric("Monthly carrying total", f"${keep_total:,}")
            elif mode == "HELOC":
                draw = money("Planned monthly HELOC draw available", "home_heloc_draw", 0)
                pay = money("Monthly HELOC payment (if any)", "home_heloc_pay", 0)
                st.session_state["home_monthly_total"] = max(0, pay)
                st.metric("Monthly net effect", f"${draw - pay:,}")
            elif mode == "Reverse mortgage":
                draw = money("Estimated monthly reverse draw", "home_rev_draw", 0)
                ins  = money("Monthly servicing/insurance", "home_rev_ins", 0)
                st.session_state["home_monthly_total"] = max(0, ins)
                st.metric("Monthly net effect", f"${draw - ins:,}")

    # Home modifications
    if ENABLE_HOME_MODS:
        with st.expander("Home modifications (in-home accessibility)", expanded=False):
            finish = st.selectbox("Finish level", ["Budget", "Standard", "Custom"], key="mods_finish")
            finish_mult = {"Budget": 0.8, "Standard": 1.0, "Custom": 1.4}[finish]
            st.caption("Select needed projects:")
            cols = st.columns(2)
            defaults = {
                "entry_ramp": 1500, "widen_doors": 2500, "grab_bars": 300, "walk_in_shower": 6000,
                "stair_lift": 3500, "lighting": 800, "handheld_shower": 250, "non_slip_floor": 1800
            }
            chosen_cost = 0
            for i, (k, base) in enumerate(defaults.items()):
                col = cols[i % 2]
                with col:
                    chk = st.checkbox(k.replace("_", " ").title(), key=f"mods_{k}")
                    if chk:
                        cost = int(base * finish_mult)
                        st.number_input("Cost", min_value=0, step=50, value=cost, key=f"mods_cost_{k}")
                        chosen_cost += int(st.session_state.get(f"mods_cost_{k}", cost))

            st.write("---")
            pay_mode = st.radio("How will you pay?", ["Pay up front", "Amortize monthly"], index=0, key="mods_paymode")
            if pay_mode == "Pay up front":
                st.session_state["mods_monthly_total"] = 0
                st.metric("One-time estimated cost", f"${chosen_cost:,}")
            else:
                months = st.slider("Amortize over months", 1, 84, 36, 1, key="mods_months")
                monthly = int(round(chosen_cost / max(1, months)))
                st.session_state["mods_monthly_total"] = monthly
                st.metric("Estimated monthly (amortized)", f"${monthly:,}")

    # Other monthly costs
    if ENABLE_OTHER_MONTHLY:
        with st.expander("Other recurring monthly costs", expanded=False):
            meds = money("Medications", "om_meds", 0)
            medicare = money("Medicare/health insurance premiums", "om_medicare", 0)
            dental = money("Dental/vision", "om_dental", 0)
            misc = money("Other recurring", "om_misc", 0)
            other_total = meds + medicare + dental + misc
            st.session_state["other_monthly_total"] = other_total
            st.metric("Subtotal — other monthly", f"${other_total:,}")

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Back to Costs"):
            st.session_state.step = "calculator"
            st.rerun()
    with c2:
        if ENABLE_DETAILS_PAGE and st.button("View Detailed Breakdown"):
            st.session_state.step = "breakdown"
            st.rerun()
    with c3:
        if st.button("Finish"):
            st.session_state.step = "intro"
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

    # Other monthly costs
    home_monthly   = int(s.get("home_monthly_total", 0))
    mods_monthly   = int(s.get("mods_monthly_total", 0))
    other_monthly  = int(s.get("other_monthly_total", 0))
    addl_costs     = home_monthly + mods_monthly + other_monthly

    # Assets placeholders (if captured elsewhere)
    assets_common  = int(s.get("assets_common_total", 0))
    assets_detail  = int(s.get("assets_detailed_total", 0))
    assets_total   = assets_common + assets_detail + int(s.get("home_sale_net", 0))

    # Totals
    income_total = inc_A + inc_B + inc_house + va_A + va_B
    monthly_need = care_total + addl_costs
    gap = monthly_need - income_total

    # Headline tiles
    c1, c2, c3 = st.columns(3)
    c1.metric("Monthly Care + Selected Costs", f"${monthly_need:,.0f}")
    c2.metric("Total Monthly Income (incl. VA)", f"${income_total:,.0f}")
    c3.metric("Estimated Monthly Gap", f"${gap:,.0f}")

    # Years funded from assets (bounded)
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

    # Composition (numeric fallback)
    st.markdown("### Income breakdown")
    st.write({
        "Individual A": inc_A,
        "Individual B": inc_B,
        "Household": inc_house,
        "VA benefits": va_A + va_B,
    })

    st.markdown("### Additional monthly costs")
    st.write({
        "Home (carry, taxes, HOA, utilities)": home_monthly,
        "Home modifications (amortized)": mods_monthly,
        "Other recurring": other_monthly,
    })

    st.markdown("### Assets summary")
    st.write({
        "Common assets": assets_common,
        "Detailed assets": assets_detail,
        "Home sale net": int(s.get("home_sale_net", 0)),
        "Total assets": assets_total,
    })

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
