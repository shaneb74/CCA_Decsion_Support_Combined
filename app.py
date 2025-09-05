# app.py — Senior Navigator (Planner → Recommendation → Costs → Household → Breakdown)
# Stable build with: VA/LTC wizard, Home Decision math to assets, Home Mods upfront/amortize,
# One-time outlays table, conditional Q9, in-home days slider wired.
# CHANGES IN THIS FILE ONLY:
# 1) Home(Keep): HOA + Utilities included in monthly subtotal
# 2) Home Mods: layout cleanup, payment choice moved to bottom
# 3) New drawer: "Other monthly costs" → other_monthly_total

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
ENABLE_DETAILS_PAGE = True
ENABLE_CHARTS = False  # keep False unless Altair + charts desired

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

# ---------- Engines ----------
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

# ---------- Helpers ----------
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

def answers_trigger_flag(qa_json: dict, answers: dict, target_flag: str) -> bool:
    """Return True if any answer would set target_flag per QA triggers."""
    for idx, q in enumerate(qa_json.get("questions", []), start=1):
        sel = answers.get(f"q{idx}")
        if sel is None:
            continue
        trig = q.get("trigger") or {}
        for rules in trig.values():
            for rule in rules:
                if int(rule.get("answer", -999)) == int(sel) and rule.get("flag") == target_flag:
                    return True
    return False

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
            n1 = st.text_input("Parent 1 name", value="Mom", key="p1_name")
            st.selectbox("Parent 1 age", ["65–74", "75–84", "85+"], key="p1_age")
        with c2:
            n2 = st.text_input("Parent 2 name", value="Dad", key="p2_name")
            st.selectbox("Parent 2 age", ["65–74", "75–84", "85+"], key="p2_age")
        people = [
            {"id": "A", "display_name": n1, "relationship": "parent"},
            {"id": "B", "display_name": n2, "relationship": "parent"},
        ]
    else:
        default = "Alex" if role != "My parent" else "Mom"
        n = st.text_input("Name", value=default, key="p_name")
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
    answers = st.session_state.answers.get(person["id"], {})

    mobility_q_idx = None
    for idx, q in enumerate(qa.get("questions", []), start=1):
        if "mobility" in q.get("question", "").lower():
            mobility_q_idx = idx

        prev = answers.get(f"q{idx}")
        opts_map = q.get("answers", {})
        ordered_keys = [str(n) for n in sorted(map(int, opts_map.keys()))]
        label = f"{q.get('question', f'Question {idx}')} (for {name})"
        sel_label = st.radio(
            label,
            options=[opts_map[k] for k in ordered_keys],
            index=(ordered_keys.index(str(prev)) if prev in ordered_keys else 0),
            key=f"{person['id']}_q{idx}",
            help=q.get("help")
        )
        sel_key = ordered_keys[[opts_map[k] for k in ordered_keys].index(sel_label)]
        answers[f"q{idx}"] = int(sel_key)

    if mobility_q_idx is not None:
        st.session_state.mobility_raw[person["id"]] = answers.get(f"q{mobility_q_idx}")

    # Conditional Q9 — only if severe cognition is implied
    conditional_answer = None
    cond_cfg = qa.get("conditional_questions")
    if cond_cfg:
        cq = cond_cfg[0]
        prereq_flag = cq.get("trigger") or "severe_cognitive_decline"
        show_conditional = answers_trigger_flag(qa, answers, prereq_flag)
        if show_conditional:
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

            care_type = (getattr(res, "care_type", None) or res.get("care_type") or "in_home")
            flags = getattr(res, "flags", None) or set(res.get("flags", []))
            scores = getattr(res, "scores", None) or res.get("scores", {})
            reasons = getattr(res, "reasons", None) or res.get("reasons", [])
            advisory = getattr(res, "advisory", None) or res.get("advisory")

            st.session_state.planner_results[person["id"]] = {
                "care_type": care_type,
                "flags": set(flags),
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
            try:
                setattr(inp, "room_type", room)
            except Exception:
                pass
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
            st.rerun()
    with c2:
        if st.button("Add Household & Assets (optional)"):
            st.session_state.step = "household"
            st.rerun()
    with c3:
        if ENABLE_DETAILS_PAGE and st.button("View Detailed Breakdown"):
            st.session_state.step = "breakdown"
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
        try:
            return int(v)
        except Exception:
            return 0

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

    # VA / LTC wizard (unchanged)
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

    # Home decision (Keep now includes HOA + Utilities)
    if ENABLE_HOME_DECISION:
        with st.expander("Home decision (keep, sell, HELOC, reverse mortgage)", expanded=False):
            hd_choice = st.selectbox(
                "What do you plan to do with the home?",
                ["Keep", "Sell", "HELOC", "Reverse mortgage"],
                key="home_decision_choice",
                help="This affects one-time proceeds and/or ongoing monthly costs."
            )

            apply_to_assets = st.checkbox("Apply net proceeds to assets summary", value=True, key="home_apply_proceeds")

            home_monthly_total = 0
            home_proceeds = 0

            if hd_choice == "Keep":
                col1, col2, col3 = st.columns(3)
                with col1:
                    mort = st.number_input("Monthly mortgage/HELOC payment", min_value=0, step=50, key="home_keep_mort")
                with col2:
                    tax = st.number_input("Monthly property taxes", min_value=0, step=25, key="home_keep_tax")
                with col3:
                    ins = st.number_input("Monthly homeowners insurance", min_value=0, step=25, key="home_keep_ins")

                c4, c5 = st.columns(2)
                with c4:
                    hoa = st.number_input("HOA/maintenance fee (monthly)", min_value=0, step=25, key="home_keep_hoa",
                                          help="Condo/HOA dues or routine maintenance set-aside.")
                with c5:
                    utils = st.number_input("Average monthly utilities", min_value=0, step=25, key="home_keep_utils",
                                            help="Electric, gas, water, trash, internet.")

                home_monthly_total = int(mort + tax + ins + hoa + utils)

            elif hd_choice == "Sell":
                col1, col2, col3 = st.columns(3)
                with col1:
                    val = st.number_input("Estimated sale price", min_value=0, step=1000, key="home_sell_val")
                with col2:
                    payoff = st.number_input("Principal payoff at sale", min_value=0, step=1000, key="home_sell_payoff")
                with col3:
                    fee_pct = st.slider("Typical fees (realtor/closing)", 0.0, 10.0, 7.0, 0.5, key="home_sell_fees")
                fees = val * (fee_pct / 100.0)
                home_proceeds = max(int(val - payoff - fees), 0)
                st.caption(f"Estimated net proceeds: **${home_proceeds:,.0f}**")
                home_monthly_total = 0

            elif hd_choice == "HELOC":
                col1, col2, col3 = st.columns(3)
                with col1:
                    draw = st.number_input("HELOC draw (cash out)", min_value=0, step=1000, key="home_heloc_draw")
                with col2:
                    rate = st.number_input("Interest rate (APR %)", min_value=0.0, step=0.25, value=8.0, key="home_heloc_rate")
                with col3:
                    term = st.number_input("Term (years)", min_value=1, step=1, value=10, key="home_heloc_term")
                r = (rate / 100.0) / 12.0
                n = int(term * 12)
                pmt = int(draw * (r * (1 + r) ** n) / ((1 + r) ** n - 1)) if draw and r > 0 else int(draw / max(n, 1))
                home_monthly_total = max(pmt, 0)
                home_proceeds = int(draw)

            elif hd_choice == "Reverse mortgage":
                col1, col2 = st.columns(2)
                with col1:
                    advance = st.number_input("Estimated upfront advance", min_value=0, step=1000, key="home_rev_advance")
                with col2:
                    fees = st.number_input("Upfront fees/closing costs", min_value=0, step=500, key="home_rev_fees")
                home_proceeds = max(int(advance - fees), 0)
                home_monthly_total = 0

            st.metric("Subtotal — Home monthly costs", f"${home_monthly_total:,.0f}")
            st.session_state["home_monthly_total"] = int(home_monthly_total)
            st.session_state["home_net_proceeds"] = int(home_proceeds if apply_to_assets else 0)

    # Home modifications (layout cleaned; payment choice moved to bottom)
    if ENABLE_HOME_MODS:
        with st.expander("Home modifications (grab bars, ramps, bath, etc.)", expanded=False):
            st.caption("Select applicable projects. Costs are averages; choose finish level, select work, then pick how to pay.")

            # Finish level first
            level = st.selectbox("Finish level", ["Budget", "Standard", "Custom"], index=1, key="mods_level",
                                 help="Budget ≈ 0.8×, Standard = 1.0×, Custom ≈ 1.4×")
            mult = {"Budget": 0.8, "Standard": 1.0, "Custom": 1.4}[level]

            # Compact two-column checklist with inline qty
            projects = [
                ("Grab bars & railings", 800),
                ("Widen doorways", 2500),
                ("Ramp installation", 3500),
                ("Bathroom walk-in shower conversion", 12000),
                ("Stair lift", 4500),
                ("Lighting & fall-risk improvements", 1500),
                ("Smart home monitoring/sensors", 1200),
            ]
            total_capex = 0
            cols = st.columns(2)
            for i, (label, avg) in enumerate(projects):
                with cols[i % 2]:
                    row = st.columns([0.08, 0.62, 0.30])  # [checkbox, label, qty]
                    with row[0]:
                        selected = st.checkbox("", key=f"mod_{i}")
                    with row[1]:
                        st.write(f"**{label}** · avg ${avg:,}")
                    with row[2]:
                        qty = st.number_input("Qty", min_value=1, max_value=10, value=1, step=1,
                                              key=f"mod_{i}_qty", label_visibility="collapsed")
                    if selected:
                        total_capex += int(avg * mult * qty)

            # Payment method at the bottom near totals
            st.divider()
            pay_method = st.radio(
                "Payment method",
                ["Amortize monthly", "Pay upfront (one-time)"],
                index=0,
                key="mods_pay_method",
                horizontal=True,
                help="Amortize to see a monthly impact, or pay upfront to remove it from monthly costs."
            )
            if pay_method == "Amortize monthly":
                months = st.slider("Amortize over (months)", 12, 120, 60, 6, key="mods_amort")
            else:
                months = 0

            deduct_upfront = st.checkbox("Deduct upfront cost from assets summary", value=True, key="mods_deduct_assets")

            if pay_method == "Amortize monthly":
                mods_monthly = int(round(total_capex / max(months, 1))) if total_capex else 0
                st.metric("Subtotal — Home mods (amortized monthly)", f"${mods_monthly:,.0f}")
                st.session_state["mods_monthly_total"] = int(mods_monthly)
                st.session_state["mods_upfront_total"] = 0
            else:
                st.metric("Upfront cost — Home mods", f"${total_capex:,.0f}")
                st.caption("Monthly impact: $0 (paid upfront)")
                st.session_state["mods_monthly_total"] = 0
                st.session_state["mods_upfront_total"] = int(total_capex if deduct_upfront else 0)

            st.session_state["mods_capex_total"] = int(total_capex)

    # Other monthly costs (new drawer)
    with st.expander("Other monthly costs (medical & living)", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            meds = st.number_input("Medications (monthly)", min_value=0, step=25, key="omc_meds")
            health = st.number_input("Health insurance / Medicare*", min_value=0, step=25, key="omc_health",
                                     help="Medicare premiums, supplemental, Part D, Advantage, etc.")
        with c2:
            dental = st.number_input("Dental insurance", min_value=0, step=25, key="omc_dental")
            transport = st.number_input("Transportation", min_value=0, step=25, key="omc_transport",
                                        help="Fuel, rideshare, paratransit, etc.")
        with c3:
            food = st.number_input("Groceries / meals", min_value=0, step=25, key="omc_food")
            misc = st.number_input("Other recurring", min_value=0, step=25, key="omc_misc")

        other_monthly_total = int(meds + health + dental + transport + food + misc)
        st.metric("Subtotal — Other monthly costs", f"${other_monthly_total:,.0f}")
        st.session_state["other_monthly_total"] = other_monthly_total

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

    # One-time and assets
    mods_upfront   = int(s.get("mods_upfront_total", 0))
    home_proceeds  = int(s.get("home_net_proceeds", 0))

    assets_common  = int(s.get("assets_common_total", 0))
    assets_detail  = int(s.get("assets_detailed_total", 0))

    # Assets total: add home proceeds; subtract upfront mods
    assets_total   = max(assets_common + assets_detail + home_proceeds - mods_upfront, 0)

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

    # Tables
    try:
        import pandas as pd

        st.markdown("### Income breakdown")
        inc_df = pd.DataFrame([
            {"Category": "Individual A", "Amount": inc_A},
            {"Category": "Individual B", "Amount": inc_B},
            {"Category": "Household", "Amount": inc_house},
            {"Category": "VA benefits", "Amount": va_A + va_B},
        ])
        st.dataframe(inc_df, hide_index=True, use_container_width=True)

        st.markdown("### Additional monthly costs")
        costs_df = pd.DataFrame([
            {"Category": "Home (carry, taxes, fees)", "Amount": home_monthly},
            {"Category": "Home modifications (amortized)", "Amount": mods_monthly},
            {"Category": "Other recurring", "Amount": other_monthly},
        ])
        st.dataframe(costs_df, hide_index=True, use_container_width=True)

        st.markdown("### Assets summary")
        assets_df = pd.DataFrame([
            {"Category": "Common assets", "Amount": assets_common},
            {"Category": "Detailed assets", "Amount": assets_detail},
            {"Category": "Home proceeds (one-time)", "Amount": home_proceeds},
            {"Category": "Less upfront mods (one-time)", "Amount": -mods_upfront},
            {"Category": "Total assets (net)", "Amount": assets_total},
        ])
        st.dataframe(assets_df, hide_index=True, use_container_width=True)

        st.markdown("### One-time outlays")
        one_rows = []
        if mods_upfront > 0:
            one_rows.append({"Item": "Home modifications (upfront)", "Amount": mods_upfront})
        if one_rows:
            one_df = pd.DataFrame(one_rows)
            st.dataframe(one_df, hide_index=True, use_container_width=True)
        else:
            st.caption("No one-time outlays recorded.")
    except Exception:
        st.write("Table rendering failed; showing numeric summary:")
        st.write({
            "Income": {"A": inc_A, "B": inc_B, "Household": inc_house, "VA": va_A + va_B},
            "Costs": {"Home": home_monthly, "Mods amortized": mods_monthly, "Other": other_monthly},
            "Assets": {"Common": assets_common, "Detailed": assets_detail, "Home proceeds": home_proceeds,
                       "Less upfront mods": -mods_upfront, "Total": assets_total},
        })

    # Optional donuts
    try:
        if ENABLE_CHARTS and HAVE_ALTAIR:
            import pandas as pd, altair as alt  # noqa
            if inc_df["Amount"].sum() > 0:
                colA, colB = st.columns(2)
                with colA:
                    st.caption("Income composition")
                    st.altair_chart(
                        alt.Chart(inc_df).mark_arc(innerRadius=60).encode(
                            theta="Amount", color="Category", tooltip=["Category", "Amount"]),
                        use_container_width=True
                    )
                with colB:
                    comp_df = pd.DataFrame([
                        {"Category": "Care", "Amount": care_total},
                        {"Category": "Home/Mods/Other", "Amount": home_monthly + mods_monthly + other_monthly},
                    ])
                    if comp_df["Amount"].sum() > 0:
                        st.caption("Costs composition")
                        st.altair_chart(
                            alt.Chart(comp_df).mark_arc(innerRadius=60).encode(
                                theta="Amount", color="Category", tooltip=["Category", "Amount"]),
                            use_container_width=True
                        )
    except Exception:
        pass

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