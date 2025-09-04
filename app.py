# app.py — Senior Navigator (Planner → Recommendation → Costs → Household)
# Safe build: charts disabled, robust engine init, JSON paths explicit.

import traceback
from types import SimpleNamespace
from pathlib import Path

import streamlit as st

st.set_page_config(page_title='Senior Navigator • Planner + Cost', page_icon='🧭', layout='centered')

# ---- Chart switches (hard off for stability) ----
ENABLE_CHARTS = False
USE_MPL = False
try:
    import altair as alt  # noqa
    HAVE_ALTAIR = True
except Exception:
    HAVE_ALTAIR = False

# -------------------- Data paths --------------------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
QA_PATH = DATA_DIR / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = DATA_DIR / "recommendation_logic_FINAL_MASTER_UPDATED.json"

# -------------------- Engines import --------------------
try:
    from engines import PlannerEngine, CalculatorEngine, CalcInputs  # CalcInputs optional
except Exception:
    st.error("Failed to import engines.py. See the traceback:")
    st.code(traceback.format_exc())
    st.stop()

# -------------------- File presence checks --------------------
missing = []
if not QA_PATH.exists():
    missing.append(str(QA_PATH))
if not REC_PATH.exists():
    missing.append(str(REC_PATH))
if missing:
    st.error("Missing required data files:\n" + "\n".join(f"• {m}" for m in missing))
    st.stop()

# -------------------- Init engines defensively --------------------
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

# -------------------- Helpers --------------------
def make_inputs(**kwargs):
    """Create inputs object for calculator even if CalcInputs class is absent or mismatched."""
    try:
        obj = CalcInputs(**kwargs)
        return obj
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

# -------------------- Session init --------------------
if "step" not in st.session_state:
    st.session_state.step = "intro"

st.sidebar.title("Senior Navigator")
st.sidebar.caption("Planner → Costs → Budget")
st.sidebar.button("Start over", on_click=reset_all)

# -------------------- Intro --------------------
if st.session_state.step == "intro":
    st.title("Let’s take this one step at a time")
    st.markdown("""
Choosing senior living or in-home support can feel like a lot.  
This tool walks you through it with clear steps.

**What happens here**
1. Answer quick care questions → we recommend a care type  
2. Review costs for that scenario (you can override)  
3. Optional: add income, benefits, and assets to see affordability
""")
    st.info("Typical time: 10–15 minutes. You can stop anytime.")
    if st.button("Start"):
        st.session_state.step = "audience"
        st.rerun()

# -------------------- Audience selection --------------------
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
        st.session_state.step = "partner_context"
        st.rerun()

# -------------------- Partner interstitial --------------------
elif st.session_state.step == "partner_context":
    people = st.session_state.get("people", [])
    single = len(people) == 1
    primary = people[0]["display_name"] if people else "Person A"

    st.header("Before we begin")
    st.markdown(f"""
If **{primary}** needs assisted living or memory care, the spouse/partner often needs some in-home help too.  
You can include a support plan for them now so the household picture is complete.
""")

    if single:
        add = st.checkbox("Also include a simple support plan for the spouse/partner", value=False, key="care_partner_add")
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

# -------------------- Planner Q&A --------------------
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
            index=(ordered_keys.index(str(prev)) if prev else 0),
            key=f"{person['id']}_q{idx}",
            help=q.get("help")
        )
        # map back to numeric key
        sel_key = ordered_keys[[opts_map[k] for k in ordered_keys].index(sel_label)]
        answers[f"q{idx}"] = int(sel_key)

    if mobility_q_idx is not None:
        st.session_state.mobility_raw[person["id"]] = answers.get(f"q{mobility_q_idx}")

    # Optional conditional question (e.g., cognitive decline)
    conditional_answer = None
    cond_cfg = qa.get("conditional_questions")
    if cond_cfg:
        cq = cond_cfg[0]
        label = cq.get("question", "Additional question")
        answers_map = cq.get("answers", {"1": "Yes", "2": "No"})
        ordered_ckeys = [str(n) for n in sorted(map(int, answers_map.keys()))]
        sel = st.radio(label, options=[answers_map[k] for k in ordered_ckeys], key=f"{person['id']}_cond")
        # map back
        for k, v in answers_map.items():
            if v == sel:
                conditional_answer = k
                break

    st.session_state.answers[person["id"]] = answers

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back"):
            if i == 0:
                st.session_state.step = "partner_context"
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

            # normalize
            care_type = (getattr(res, "care_type", None) or res.get("care_type") or "in_home")
            flags = getattr(res, "flags", None) or res.get("flags", [])
            scores = getattr(res, "scores", None) or res.get("scores", {})
            reasons = getattr(res, "reasons", None) or res.get("reasons", [])
            advisory = getattr(res, "advisory", None) or res.get("advisory")

            st.session_state.planner_results[person["id"]] = {
                "care_type": care_type,
                "flags": set(flags) if isinstance(flags, (list, set, tuple)) else set(),
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

# -------------------- Recommendations + override --------------------
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

        care_choices = ["in_home", "assisted_living", "memory_care"]
        labels = {"in_home": "In-home Care", "assisted_living": "Assisted Living", "memory_care": "Memory Care"}
        idx = care_choices.index(default) if default in care_choices else 0
        label_sel = st.selectbox(
            f"Care scenario for {p['display_name']}",
            [labels[c] for c in care_choices],
            index=idx,
            key=f"override_{p['id']}",
            help="Change the scenario here if you want to compare a different path."
        )
        reverse = {v: k for k, v in labels.items()}
        st.session_state.care_overrides[p["id"]] = reverse[label_sel]
        st.divider()

    if st.button("See Costs"):
        st.session_state.step = "calculator"
        st.rerun()

# -------------------- Calculator --------------------
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

        st.subheader(f"{name} — Scenario: {care_type.replace('_', ' ').title()} (recommended: {rec.get('care_type', 'in_home').replace('_', ' ').title()})")

        # Mobility carryover from planner
        raw_mob = st.session_state.get("mobility_raw", {}).get(pid)
        mobility_prefill = "Independent"
        if raw_mob in (2, 3):  # used a cane/walker or needs help
            mobility_prefill = "Assisted"
        if raw_mob == 4:
            mobility_prefill = "Non-ambulatory"

        care_level_default = "High" if ("severe_cognitive_decline" in rec.get("flags", set()) or care_type == "memory_care") else "Medium"
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
            # In-home sliders: hours/day and days/month
            if f"{pid}_room" in st.session_state:
                del st.session_state[f"{pid}_room"]
            hours = st.slider("In-home care hours per day", 0, 24, 4, 1, key=f"{pid}_hours")
            days = st.slider("Days of care per month", 0, 31, 20, 1, key=f"{pid}_days")
            # Pass both to calculator and also an "effective" monthlyized hours/day proxy if needed
            try:
                setattr(inp, "in_home_hours_per_day", int(hours))
                setattr(inp, "in_home_days_per_month", int(days))
            except Exception:
                pass

        # Compute monthly cost
        try:
            # Prefer a rich method if your calculator provides it; fallback to simple estimate
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
        st.session_state.setdefault("va_cache", {}).setdefault(pid, {})["care_cost"] = int(monthly)
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

# -------------------- Household (lightweight numeric-only baseline) --------------------
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

    # Individual income
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

    # Household income
    with st.expander("Monthly Income — Household (shared)", expanded=False):
        r = money("Rental income", "hh_rent", 0)
        an = money("Annuity income", "hh_annuity", 0)
        inv = money("Dividends/interest (joint)", "hh_invest", 0)
        tr = money("Trust distributions", "hh_trust", 0)
        oth = money("Other household income", "hh_other", 0)
        st.metric("Subtotal — Household income", f"${r+an+inv+tr+oth:,}")

    st.divider()
    st.caption("This baseline build focuses on stability. Charts are disabled; totals are numeric.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back to costs"):
            st.session_state.step = "calculator"
            st.rerun()
    with c2:
        if st.button("Finish"):
            st.session_state.step = "intro"
            st.rerun()