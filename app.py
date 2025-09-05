# app.py — Senior Navigator (Planner → Recommendation → Costs → Household → Breakdown)
# Production build with partner interstitial preserved and clean Back/Next Q&A.

from pathlib import Path
from types import SimpleNamespace
import traceback

import streamlit as st

# ---------------- Page config ----------------
st.set_page_config(page_title="Senior Navigator • Planner + Cost", page_icon="🧭", layout="centered")

# ---------------- Flags ----------------
ENABLE_PARTNER_INTERSTITIAL = True
ENABLE_REC_OVERRIDE = True
ENABLE_INHOME_DAYS_PER_MONTH = True
ENABLE_MOBILITY_CARRYOVER = True
ENABLE_HOUSEHOLD_DRAWERS = True
ENABLE_VA_WIZARD = True
ENABLE_HOME_DECISION = True
ENABLE_HOME_MODS = True
ENABLE_OTHER_MONTHLIES = True
ENABLE_DETAILS_PAGE = True
ENABLE_CHARTS = False  # keep False on Streamlit Cloud unless altair in requirements

# ---------------- Optional charts dependency ----------------
try:
    import altair as alt  # noqa: F401
    HAVE_ALTAIR = True
except Exception:
    HAVE_ALTAIR = False

# ---------------- Data paths ----------------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
QA_PATH = DATA_DIR / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = DATA_DIR / "recommendation_logic_FINAL_MASTER_UPDATED.json"

# ---------------- Engines ----------------
try:
    from engines import PlannerEngine, CalculatorEngine, CalcInputs
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

# ---------------- Helpers ----------------
def make_inputs(**kwargs):
    """Create a calculator inputs object regardless of CalcInputs availability."""
    try:
        return CalcInputs(**kwargs)  # type: ignore
    except Exception:
        obj = SimpleNamespace()
        for k, v in kwargs.items():
            setattr(obj, k, v)
        return obj

def reset_all():
    for k in list(st.session_state.keys()):
        if not k.startswith("_"):
            del st.session_state[k]
    st.session_state.step = "intro"

def currency(n: int | float) -> str:
    try:
        return f"${int(round(n)):,}"
    except Exception:
        return "$0"

# ---------------- Session init ----------------
if "step" not in st.session_state:
    st.session_state.step = "intro"

st.sidebar.title("Senior Navigator")
st.sidebar.caption("Planner → Costs → Budget → Breakdown")
st.sidebar.button("Start over", on_click=reset_all)

# =========================================================
# Steps
# =========================================================

# ---------------- Intro ----------------
if st.session_state.step == "intro":
    st.title("Let’s take this one step at a time")
    st.markdown("""
Choosing senior living or in-home support can be overwhelming.  
This tool breaks it down into clear steps with compassionate guidance.

**What you’ll do**
1. Answer quick care questions → we recommend a care type.  
2. Review costs for that scenario (you can switch it if you want).  
3. Optionally add income, benefits, and assets to see affordability.  
4. View a detailed breakdown you can save or revisit.
""")
    st.info("Typical time: 10–15 minutes. You can stop anytime.")
    if st.button("Start"):
        st.session_state.step = "audience"
        st.rerun()

# ---------------- Audience ----------------
elif st.session_state.step == "audience":
    st.header("Who is this plan for?")
    role = st.radio("Select one:", ["Myself", "My spouse/partner", "My parent", "Both parents", "Someone else"])

    people = []
    if role == "Both parents":
        c1, c2 = st.columns(2)
        with c1:
            n1 = st.text_input("Parent 1 name", value="Mom", key="p1_name", label_visibility="visible")
            st.selectbox("Parent 1 age", ["65–74", "75–84", "85+"], key="p1_age")
        with c2:
            n2 = st.text_input("Parent 2 name", value="Dad", key="p2_name", label_visibility="visible")
            st.selectbox("Parent 2 age", ["65–74", "75–84", "85+"], key="p2_age")
        people = [
            {"id": "A", "display_name": n1, "relationship": "parent"},
            {"id": "B", "display_name": n2, "relationship": "parent"},
        ]
    else:
        default = "Alex" if role != "My parent" else "Mom"
        n = st.text_input("Name", value=default, key="p_name", label_visibility="visible")
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
        st.session_state.q_index = 0
        st.session_state._last_person_id = people[0]["id"]
        st.session_state.step = "partner_context" if ENABLE_PARTNER_INTERSTITIAL else "planner"
        st.rerun()

# ---------------- Partner interstitial (kept) ----------------
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
        add = st.checkbox("Also include a support plan for the spouse/partner", value=False, key="care_partner_add")
        if add:
            st.text_input("Spouse/partner name", value="Spouse/Partner", key="care_partner_name")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Skip, start care questions"):
            st.session_state.step = "planner"
            st.rerun()
    with c2:
        if st.button("Add spouse/partner and continue"):
            if single and st.session_state.get("care_partner_add"):
                st.session_state.people.append({
                    "id": "B",
                    "display_name": st.session_state.get("care_partner_name") or "Spouse/Partner",
                    "relationship": "spouse"
                })
            st.session_state.step = "planner"
            st.rerun()

# ---------------- Planner (Q&A; one question at a time) ----------------
elif st.session_state.step == "planner":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if not people:
        reset_all(); st.rerun()
    person = people[i]
    name = person["display_name"]

    # single-question UX, optional reviewer toggle
    show_all = st.toggle("Show all questions (desktop reviewers)", value=False,
                         help="For desktop reviewers. On mobile, questions appear one at a time.")
    st.header(f"Care Plan — {name}")
    st.caption(f"Person {i+1} of {len(people)}")

    qa = planner.qa or {}
    questions = qa.get("questions", [])
    answers = st.session_state.answers.get(person["id"], {})
    if "q_index" not in st.session_state:
        st.session_state.q_index = 0

    # reset q_index if person changed
    if st.session_state.get("_last_person_id") != person["id"]:
        st.session_state.q_index = 0
        st.session_state._last_person_id = person["id"]

    # render questions
    mobility_q_idx = None
    if show_all:
        for idx, q in enumerate(questions, start=1):
            if "mobility" in q.get("question", "").lower():
                mobility_q_idx = idx
            opts_map = q.get("answers", {})
            ordered_keys = [str(n) for n in sorted(map(int, opts_map.keys()))]
            prev = answers.get(f"q{idx}")
            label = f"{q.get('question', f'Question {idx}')} (for {name})"
            sel_label = st.radio(label, [opts_map[k] for k in ordered_keys],
                                 index=(ordered_keys.index(str(prev)) if prev in ordered_keys else 0),
                                 key=f"{person['id']}_q{idx}", help=q.get("help"))
            sel_key = ordered_keys[[opts_map[k] for k in ordered_keys].index(sel_label)]
            answers[f"q{idx}"] = int(sel_key)
    else:
        # one at a time
        q_idx = st.session_state.q_index
        idx = q_idx + 1
        q = questions[q_idx]
        if "mobility" in q.get("question", "").lower():
            mobility_q_idx = idx
        st.progress((idx) / max(1, len(questions)))
        opts_map = q.get("answers", {})
        ordered_keys = [str(n) for n in sorted(map(int, opts_map.keys()))]
        prev = answers.get(f"q{idx}")
        label = f"{q.get('question', f'Question {idx}')} (for {name})"
        sel_label = st.radio(label, [opts_map[k] for k in ordered_keys],
                             index=(ordered_keys.index(str(prev)) if prev in ordered_keys else 0),
                             key=f"{person['id']}_q{idx}", help=q.get("help"))
        sel_key = ordered_keys[[opts_map[k] for k in ordered_keys].index(sel_label)]
        answers[f"q{idx}"] = int(sel_key)

    # conditional question block (shown when defined and triggered by engine spec downstream; safe to capture here)
    conditional_answer = None
    cond_cfg = qa.get("conditional_questions")
    if cond_cfg:
        # render only if the config tells you to; otherwise harmless
        cq = cond_cfg[0]
        label = cq.get("question", "Additional question")
        answers_map = cq.get("answers", {"1": "Yes", "2": "No"})
        ordered_ckeys = [str(n) for n in sorted(map(int, answers_map.keys()))]
        sel = st.radio(label, [answers_map[k] for k in ordered_ckeys], key=f"{person['id']}_cond")
        for k, v in answers_map.items():
            if v == sel:
                conditional_answer = k
                break

    st.session_state.answers[person["id"]] = answers
    if mobility_q_idx is not None:
        st.session_state.mobility_raw[person["id"]] = answers.get(f"q{mobility_q_idx}")

    # Controls: Back / Next only
    cols = st.columns([1, 1])
    with cols[0]:
        back_clicked = st.button("Back", use_container_width=True)
    with cols[1]:
        next_label = "Next" if (show_all or st.session_state.q_index < len(questions) - 1) else "Finish"
        next_clicked = st.button(next_label, use_container_width=True)

    if back_clicked:
        if not show_all and st.session_state.q_index > 0:
            st.session_state.q_index -= 1
            st.rerun()
        else:
            if i == 0:
                st.session_state.step = "audience" if not ENABLE_PARTNER_INTERSTITIAL else "partner_context"
                st.rerun()
            else:
                st.session_state.current_person = i - 1
                st.session_state.q_index = 0
                st.rerun()

    if next_clicked:
        # if one-at-a-time and not last, advance question
        if not show_all and st.session_state.q_index < len(questions) - 1:
            st.session_state.q_index += 1
            st.rerun()
        # otherwise finalize this person and move on
        try:
            res = planner.run(answers, conditional_answer=conditional_answer)
        except Exception:
            st.error("PlannerEngine.run failed.")
            st.code(traceback.format_exc())
            st.stop()

        care_type = (getattr(res, "care_type", None) or res.get("care_type") or "in_home")
        flags     = set(getattr(res, "flags", None) or res.get("flags", []))
        scores    = getattr(res, "scores", None) or res.get("scores", {})
        reasons   = getattr(res, "reasons", None) or res.get("reasons", [])
        advisory  = getattr(res, "advisory", None) or res.get("advisory")

        st.session_state.planner_results[person["id"]] = {
            "care_type": care_type,
            "flags": flags,
            "scores": scores,
            "reasons": reasons,
            "advisory": advisory,
        }

        # next person or recommendations
        if st.session_state.current_person + 1 < len(people):
            st.session_state.current_person += 1
            st.session_state.q_index = 0
            st.rerun()
        else:
            st.session_state.step = "recommendations"
            st.rerun()

# ---------------- Recommendations + override ----------------
elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without redoing questions.")

    for p in st.session_state.people:
        rec = st.session_state.planner_results.get(p["id"], {})
        default = rec.get("care_type", "in_home")
        st.subheader(f"{p['display_name']}: {default.replace('_', ' ').title()} (recommended)")
        for r in rec.get("reasons", []):
            st.write("• " + str(r))
        if rec.get("advisory"):
            st.info(rec["advisory"])

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

# ---------------- Calculator ----------------
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
            try:
                setattr(inp, "room_type", room)
            except Exception:
                pass
        else:
            # In-home sliders with days wired
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

        st.metric("Estimated Monthly Cost", currency(monthly))
        st.session_state.setdefault("person_costs", {})[pid] = int(monthly)
        st.divider()
        total += int(monthly)

    st.subheader("Combined Total")
    st.session_state.combined_monthly_cost = total
    st.metric("Estimated Combined Monthly Cost", currency(total))

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back to recommendations", use_container_width=True):
            st.session_state.step = "recommendations"
            st.rerun()
    with c2:
        if st.button("Add Household & Assets", use_container_width=True):
            st.session_state.step = "household"
            st.rerun()

# ---------------- Household (drawers) ----------------
elif st.session_state.step == "household":
    people = st.session_state.get("people", [])
    names = [p["display_name"] for p in people]
    nameA = names[0] if names else "Person A"
    nameB = names[1] if len(names) > 1 else "Person B"

    st.header("Household & Budget")
    st.markdown("Add income, benefits, and assets to see affordability.")

    vals = st.session_state.get("house_vals", {})

    def money(label, key, default=0, step=50):
        v0 = int(vals.get(key, default) or 0)
        v = st.number_input(label, min_value=0, step=step, value=v0, key=key)
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
        st.metric("Subtotal — Individual income", currency((a1+a2+a3)+(b1+b2+b3)))

    # Monthly Income — Household (shared)
    with st.expander("Monthly Income — Household (shared)", expanded=False):
        r = money("Rental income", "hh_rent", 0)
        an = money("Annuity income", "hh_annuity", 0)
        inv = money("Dividends/interest (joint)", "hh_invest", 0)
        tr = money("Trust distributions", "hh_trust", 0)
        oth = money("Other household income", "hh_other", 0)
        st.metric("Subtotal — Household income", currency(r+an+inv+tr+oth))

    # VA / LTC wizard
    if ENABLE_VA_WIZARD:
        with st.expander("Benefits (VA, Long-Term Care insurance)", expanded=True):
            people_local = st.session_state.get("people", [])
            names_local = [p["display_name"] for p in people_local]
            nA = names_local[0] if names_local else "Person A"
            nB = names_local[1] if len(names_local) > 1 else "Person B"

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
                    st.caption(f"Estimated monthly cap for this tier: {currency(cap)}.")
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
            st.metric("Subtotal — Benefits (VA + LTC add-ons)", currency(benefits_total))

    # Home decision
    if ENABLE_HOME_DECISION:
        with st.expander("Home decision (keep, sell, HELOC, reverse mortgage)", expanded=False):
            intent = st.selectbox("What do you plan to do with the home?",
                                  ["Keep", "Sell", "HELOC", "Reverse mortgage"], key="home_intent")
            apply_to_assets = st.checkbox("Apply net proceeds to assets summary", value=True, key="home_apply_assets")

            monthly_home = 0
            net_proceeds = 0

            if intent == "Keep":
                c1, c2, c3 = st.columns(3)
                with c1: mort = money("Monthly mortgage/HELOC payment", "home_mort", 0)
                with c2: tax = money("Monthly property taxes", "home_tax", 0)
                with c3: ins = money("Monthly homeowners insurance", "home_ins", 0)
                c4, c5 = st.columns(2)
                with c4: hoa = money("Monthly HOA/maintenance", "home_hoa", 0)
                with c5: util = money("Monthly utilities (if you want to include)", "home_util", 0)
                monthly_home = mort + tax + ins + hoa + util

            elif intent == "Sell":
                s1, s2, s3 = st.columns([1, 1, 1])
                with s1: sale_price = money("Estimated sale price", "home_sale_price", 0, step=1000)
                with s2: payoff = money("Principal payoff at sale", "home_sale_payoff", 0, step=1000)
                with s3: fee_pct = st.slider("Typical fees (realtor/closing) %", 0.0, 10.0, 6.0, 0.25, key="home_fee_pct")
                fees = sale_price * (fee_pct / 100.0)
                net_proceeds = max(0, sale_price - payoff - fees)
                st.caption(f"Estimated net proceeds: **{currency(net_proceeds)}**")
                monthly_home = 0

            elif intent == "HELOC":
                c1, c2, c3 = st.columns(3)
                with c1: heloc_draw = money("Monthly HELOC payment", "home_heloc_pay", 0)
                with c2: tax = money("Monthly property taxes", "home_tax", 0)
                with c3: ins = money("Monthly homeowners insurance", "home_ins", 0)
                c4, c5 = st.columns(2)
                with c4: hoa = money("Monthly HOA/maintenance", "home_hoa", 0)
                with c5: util = money("Monthly utilities (if you want to include)", "home_util", 0)
                monthly_home = heloc_draw + tax + ins + hoa + util

            else:  # Reverse mortgage
                c1, c2 = st.columns(2)
                with c1: tax = money("Monthly property taxes", "home_tax", 0)
                with c2: ins = money("Monthly homeowners insurance", "home_ins", 0)
                c3, c4 = st.columns(2)
                with c3: hoa = money("Monthly HOA/maintenance", "home_hoa", 0)
                with c4: util = money("Monthly utilities (if you want to include)", "home_util", 0)
                monthly_home = tax + ins + hoa + util

            st.session_state["home_monthly_total"] = int(monthly_home)
            st.session_state["home_sale_proceeds"] = int(net_proceeds) if intent == "Sell" and apply_to_assets else 0

            st.metric("Subtotal — Home monthly costs", currency(monthly_home))

    # Home modifications
    if ENABLE_HOME_MODS:
        with st.expander("Home modifications (grab bars, ramps, bath, etc.)", expanded=False):
            st.caption("Select applicable projects. Costs are averages; finish level adjusts costs.")
            finish = st.selectbox("Finish level", ["Budget", "Standard", "Custom"], index=1, key="mods_finish")

            # catalog
            base = {
                "grab_bars": {"label": "Grab bars & railings", "avg": 800},
                "widen_doors": {"label": "Widen doorways", "avg": 2500},
                "ramp": {"label": "Ramp installation", "avg": 3500},
                "bath": {"label": "Bathroom walk-in shower conversion", "avg": 12000},
                "smart": {"label": "Smart home monitoring/sensors", "avg": 1200},
                "lighting": {"label": "Lighting & fall-risk improvements", "avg": 1500},
                "stair": {"label": "Stair lift", "avg": 4500},
            }
            level_mult = {"Budget": 0.8, "Standard": 1.0, "Custom": 1.35}
            mult = level_mult.get(finish, 1.0)

            # 2 columns list with qty
            left_keys = ["grab_bars", "ramp", "stair", "smart"]
            right_keys = ["widen_doors", "bath", "lighting"]
            chosen = {}
            cL, cR = st.columns(2)
            with cL:
                for k in left_keys:
                    chk = st.checkbox(f"{base[k]['label']} (avg {currency(base[k]['avg'])})", key=f"mods_{k}_chk")
                    qty = st.number_input("Qty", min_value=0, step=1, value=0 if not chk else 1, key=f"mods_{k}_qty")
                    if chk and qty > 0:
                        chosen[k] = int(qty)
            with cR:
                for k in right_keys:
                    chk = st.checkbox(f"{base[k]['label']} (avg {currency(base[k]['avg'])})", key=f"mods_{k}_chk")
                    qty = st.number_input("Qty ", min_value=0, step=1, value=0 if not chk else 1, key=f"mods_{k}_qty")
                    if chk and qty > 0:
                        chosen[k] = int(qty)

            # payment choice at bottom
            pay_choice = st.radio("Payment method", ["Amortize monthly", "Pay upfront (one-time)"],
                                  index=0, key="mods_pay")
            months = 12
            if pay_choice == "Amortize monthly":
                months = st.slider("Amortize over (months)", 6, 36, 12, 1, key="mods_months")

            # totals
            gross = 0
            for k, q in chosen.items():
                gross += base[k]["avg"] * mult * q

            if pay_choice == "Amortize monthly":
                monthly_mods = int(round(gross / max(1, months)))
                st.session_state["mods_monthly_total"] = monthly_mods
                st.session_state["mods_upfront_total"] = 0
                st.metric("Subtotal — Home mods (amortized monthly)", currency(monthly_mods))
            else:
                st.session_state["mods_monthly_total"] = 0
                st.session_state["mods_upfront_total"] = int(round(gross))
                st.metric("Upfront cost — Home mods", currency(st.session_state["mods_upfront_total"]))
                st.caption("Monthly impact: $0 (paid upfront)")

            # Optionally deduct upfront from assets (handled in breakdown by subtracting from assets_total)
            st.checkbox("Deduct upfront cost from assets summary", value=True, key="mods_deduct_assets")

    # Other recurring monthlies (health etc.)
    if ENABLE_OTHER_MONTHLIES:
        with st.expander("Other monthly costs (health, meds, insurance, etc.)", expanded=False):
            meds = money("Medications", "om_meds", 0)
            med_ins = money("Medicare/health insurance premiums", "om_health", 0)
            dental = money("Dental insurance/premium", "om_dental", 0)
            other = money("Other recurring", "om_other", 0)
            st.session_state["other_monthly_total"] = meds + med_ins + dental + other
            st.metric("Subtotal — Other monthly costs", currency(st.session_state["other_monthly_total"]))

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back to Costs", use_container_width=True):
            st.session_state.step = "calculator"
            st.rerun()
    with c2:
        if ENABLE_DETAILS_PAGE and st.button("View Detailed Breakdown", use_container_width=True):
            st.session_state.step = "breakdown"
            st.rerun()

# ---------------- Breakdown ----------------
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

    # Income — individual and household
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

    # Assets: include home sale proceeds and subtract upfront mods if requested
    assets_common  = int(s.get("assets_common_total", 0))
    assets_detail  = int(s.get("assets_detailed_total", 0))
    sale_proc      = int(s.get("home_sale_proceeds", 0))
    mods_upfront   = int(s.get("mods_upfront_total", 0))
    mods_deduct    = bool(s.get("mods_deduct_assets", True))
    assets_total   = assets_common + assets_detail + sale_proc - (mods_upfront if mods_deduct else 0)

    # Totals
    income_total = inc_A + inc_B + inc_house + va_A + va_B
    monthly_need = care_total + addl_costs
    gap = monthly_need - income_total

    c1, c2, c3 = st.columns(3)
    c1.metric("Monthly Care + Selected Costs", currency(monthly_need))
    c2.metric("Total Monthly Income (incl. VA)", currency(income_total))
    c3.metric("Estimated Monthly Gap", currency(gap))

    years = 0.0
    if gap > 0 and assets_total > 0:
        years = round(assets_total / max(gap, 1), 1)
    st.subheader(f"Estimated runway from assets: {years} years")

    # Per-person details
    st.markdown("### Per-person care costs")
    if people:
        if len(people) > 1:
            cA, cB = st.columns(2)
            with cA: st.write(f"**{nameA}**: {currency(care_A)}/mo")
            with cB: st.write(f"**{nameB}**: {currency(care_B)}/mo")
        else:
            st.write(f"**{nameA}**: {currency(care_A)}/mo")

    # Composition (numeric, charts optional)
    st.markdown("### Income breakdown")
    st.write({
        "Individual A": inc_A,
        "Individual B": inc_B,
        "Household": inc_house,
        "VA benefits": va_A + va_B,
    })

    st.markdown("### Additional monthly costs")
    st.write({
        "Home (mortgage/tax/ins/HOA/utils)": home_monthly,
        "Home modifications (amortized)": mods_monthly,
        "Other recurring": other_monthly,
    })

    st.markdown("### Assets summary")
    st.write({
        "Common assets": assets_common,
        "Detailed assets": assets_detail,
        "Home sale proceeds (if applied)": sale_proc,
        "Less upfront mods deducted": (mods_upfront if mods_deduct else 0),
        "Total assets": assets_total,
    })

    try:
        if ENABLE_CHARTS and HAVE_ALTAIR:
            import pandas as pd, altair as alt  # noqa: F401
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
        if st.button("Back to Household", use_container_width=True):
            st.session_state.step = "household"
            st.rerun()
    with b2:
        if st.button("Back to Costs", use_container_width=True):
            st.session_state.step = "calculator"
            st.rerun()