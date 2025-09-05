# app.py — Senior Navigator (Planner → Recommendation → Costs → Household → Breakdown)
# Production build: restored flow, VA wizard, home decisions, home mods, assets,
# normalized PlannerEngine results, safe inputs, mobility carryover, and two-person transition.

from pathlib import Path
from types import SimpleNamespace
from dataclasses import asdict, is_dataclass
from collections.abc import Mapping
import traceback
import streamlit as st

# ---------- Page config ----------
st.set_page_config(page_title="Senior Navigator • Planner + Cost",
                   page_icon="🧭", layout="centered")

# ---------- Feature flags ----------
ENABLE_PARTNER_INTERSTITIAL = True
ENABLE_REC_OVERRIDE = True
ENABLE_INHOME_DAYS_PER_MONTH = True
ENABLE_MOBILITY_CARRYOVER = True
ENABLE_VA_WIZARD = True
ENABLE_HOME_DECISION = True
ENABLE_HOME_MODS = True
ENABLE_ASSETS = True
ENABLE_OTHER_COSTS = True
ENABLE_DETAILS_PAGE = True
ENABLE_CHARTS = False  # keep False on Streamlit Cloud unless altair is installed

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
    from engines import PlannerEngine, CalculatorEngine
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
    """Create a calculator inputs object without depending on a dataclass."""
    obj = SimpleNamespace()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj

def reset_all():
    for k in list(st.session_state.keys()):
        if not k.startswith("_"):
            del st.session_state[k]
    st.session_state.step = "intro"

def _normalize_planner_result(res):
    """
    Convert PlannerEngine.run(...) output into a dict with keys:
    care_type, flags, scores, reasons, advisory.
    Accepts dataclass/object, dict, or tuple/list.
    """
    if is_dataclass(res):
        out = dict(asdict(res))
    elif isinstance(res, Mapping):
        out = dict(res)
    elif isinstance(res, (tuple, list)):
        out = {}
        if len(res) >= 1: out["care_type"] = res[0]
        if len(res) >= 2: out["flags"]    = res[1]
        if len(res) >= 3: out["scores"]   = res[2]
        if len(res) >= 4: out["reasons"]  = res[3]
        if len(res) >= 5: out["advisory"] = res[4]
    elif hasattr(res, "__dict__"):
        out = {
            "care_type": getattr(res, "care_type", None),
            "flags":    getattr(res, "flags", None),
            "scores":   getattr(res, "scores", None),
            "reasons":  getattr(res, "reasons", None),
            "advisory": getattr(res, "advisory", None),
        }
    else:
        out = {}

    out["care_type"] = out.get("care_type") or "in_home"
    out["flags"]     = list(out.get("flags")  or [])
    out["scores"]    = dict(out.get("scores") or {})
    out["reasons"]   = list(out.get("reasons") or [])
    # advisory can be None or str
    return out

def num(label, key, default=0, step=50, min_value=0, help=None):
    """Safer number input that only returns an int and doesn't mutate session state internally."""
    try:
        v0 = int(st.session_state.get(key, default) or default)
    except Exception:
        v0 = default
    v = st.number_input(label, min_value=min_value, step=step, value=v0, key=key, help=help)
    try:
        return int(v)
    except Exception:
        return default

def metric_money(label, amount):
    st.metric(label, f"${int(amount):,}")

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
1. Answer care questions → we recommend a care type.  
2. Review costs for that scenario.  
3. Add income, benefits, and assets.  
4. View a detailed breakdown.
""")
    st.info("Typical time: 10–15 minutes. You can stop anytime.")
    if st.button("Start"):
        st.session_state.step = "audience"
        st.rerun()

# ---------- Audience ----------
elif st.session_state.step == "audience":
    st.header("Who is this plan for?")
    role = st.radio("Select one:", ["Myself", "My spouse/partner", "My parent",
                                    "Both parents", "Someone else"])

    people = []
    if role == "Both parents":
        c1, c2 = st.columns(2)
        with c1:
            n1 = st.text_input("Parent 1 name", value="", placeholder="Enter name", key="p1_name")
        with c2:
            n2 = st.text_input("Parent 2 name", value="", placeholder="Enter name", key="p2_name")
        people = [
            {"id": "A", "display_name": n1 or "Mom", "relationship": "parent"},
            {"id": "B", "display_name": n2 or "Dad",  "relationship": "parent"},
        ]
    else:
        n = st.text_input("Name", value="", placeholder="Enter name", key="p_name")
        map_rel = {"Myself": "self", "My spouse/partner": "spouse",
                   "My parent": "parent", "Someone else": "other"}
        people = [{"id": "A", "display_name": (n or "Person A"),
                   "relationship": map_rel.get(role, "other")}]

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
If **{primary}** needs to leave the home for assisted living or memory care, their spouse/partner may also need to consider some in-home help.  

Would you like to evaluate a care support plan for a spouse or parter now so the household picture is complete.
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
        if st.button("Add spouse/partner and continue", 
                 disabled=not st.session_state.get("care_partner_add", False)):
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

    st.header(f"Care Plan — {name}")
    st.caption(f"Person {i+1} of {len(people)}")

    qa = planner.qa or {}
    answers = st.session_state.answers.get(person["id"], {})

    mobility_q_idx = None
    for idx, q in enumerate(qa.get("questions", []), start=1):
        if "mobility" in q.get("question", "").lower():
            mobility_q_idx = idx
        opts_map = q.get("answers", {})
        ordered_keys = [str(n) for n in sorted(map(int, opts_map.keys()))]
        prev = answers.get(f"q{idx}")
        label = f"{q.get('question', f'Question {idx}')} (for {name})"
        sel_label = st.radio(label,
                             options=[opts_map[k] for k in ordered_keys],
                             index=(ordered_keys.index(str(prev)) if prev in ordered_keys else 0),
                             key=f"{person['id']}_q{idx}",
                             help=q.get("help"))
        sel_key = ordered_keys[[opts_map[k] for k in ordered_keys].index(sel_label)]
        answers[f"q{idx}"] = int(sel_key)

    if mobility_q_idx is not None:
        st.session_state.mobility_raw[person["id"]] = answers.get(f"q{mobility_q_idx}")

    # optional conditional
    conditional_answer = None
    cond_cfg = qa.get("conditional_questions")
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

            norm = _normalize_planner_result(res)
            st.session_state.planner_results[person["id"]] = norm

            # Transition screen before next person
            if i + 1 < len(people):
                st.session_state.next_person_index = i + 1
                st.session_state.step = "planner_transition"
                st.rerun()
            else:
                st.session_state.step = "recommendations"
                st.rerun()

# ---------- Planner transition (A → B) ----------
elif st.session_state.step == "planner_transition":
    idx = st.session_state.get("next_person_index", None)
    people = st.session_state.get("people", [])
    if idx is None or idx >= len(people):
        st.session_state.step = "recommendations"
        st.rerun()
    just_done = people[idx - 1]["display_name"] if idx - 1 >= 0 else "Person 1"
    next_up   = people[idx]["display_name"]
    st.header("Great — first set complete")
    st.write(f"You’ve finished the care questions for **{just_done}**.")
    st.write(f"Now let’s assess **{next_up}**.")
    if st.button("Continue"):
        st.session_state.current_person = idx
        st.session_state.step = "planner"
        st.rerun()

# ---------- Recommendations + override ----------
elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without redoing questions.")

    for p in st.session_state.people:
        rec = st.session_state.planner_results.get(p["id"], {}) or {}
        default = rec.get("care_type", "in_home")
        human = default.replace("_", " ").title()
        st.subheader(f"{p['display_name']}: {human} (recommended)")
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

    cols = st.columns(2)
    with cols[0]:
        if st.button("Back to questions"):
            st.session_state.step = "planner"
            st.rerun()
    with cols[1]:
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
        rec = st.session_state.planner_results.get(pid, {}) or {}
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
            if hasattr(calculator, "monthly_cost"):
                monthly = calculator.monthly_cost(inp)
            else:
                monthly = calculator.estimate(getattr(inp, "care_type", "in_home"))
        except Exception:
            st.error("CalculatorEngine failed while computing monthly cost.")
            st.code("Inputs:\n" + str(vars(inp)))
            st.code(traceback.format_exc())
            st.stop()

        metric_money("Estimated Monthly Cost", monthly)
        st.session_state.setdefault("person_costs", {})[pid] = int(monthly)
        st.divider()
        total += int(monthly)

    st.subheader("Combined Total")
    st.session_state.combined_monthly_cost = total
    metric_money("Estimated Combined Monthly Cost", total)

    cols = st.columns(2)
    with cols[0]:
        if st.button("Back to recommendations"):
            st.session_state.step = "recommendations"
            st.rerun()
    with cols[1]:
        if st.button("Add Household & Assets"):
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

    # Monthly Income — Individual
    with st.expander("Monthly Income — Individual", expanded=True):
        if len(people) > 1:
            a_ss, a_pn, a_oth = st.columns(3)
            with a_ss: a1 = num(f"Social Security — {nameA}", "a_ss", 0)
            with a_pn: a2 = num(f"Pension — {nameA}", "a_pn", 0)
            with a_oth: a3 = num(f"Other — {nameA}", "a_other", 0)
            b_ss, b_pn, b_oth = st.columns(3)
            with b_ss: b1 = num(f"Social Security — {nameB}", "b_ss", 0)
            with b_pn: b2 = num(f"Pension — {nameB}", "b_pn", 0)
            with b_oth: b3 = num(f"Other — {nameB}", "b_other", 0)
        else:
            a1 = num(f"Social Security — {nameA}", "a_ss", 0)
            a2 = num(f"Pension — {nameA}", "a_pn", 0)
            a3 = num(f"Other — {nameA}", "a_other", 0)
            b1 = b2 = b3 = 0
        indiv_total = (a1+a2+a3) + (b1+b2+b3)
        metric_money("Subtotal — Individual income", indiv_total)

    # Monthly Income — Household (shared)
    with st.expander("Monthly Income — Household (shared)", expanded=False):
        r = num("Rental income", "hh_rent", 0)
        an = num("Annuity income", "hh_annuity", 0)
        inv = num("Dividends/interest (joint)", "hh_invest", 0)
        tr = num("Trust distributions", "hh_trust", 0)
        oth = num("Other household income", "hh_other", 0)
        hh_total = r+an+inv+tr+oth
        metric_money("Subtotal — Household income", hh_total)

    # VA / LTC wizard
    if ENABLE_VA_WIZARD:
        with st.expander("Benefits (VA, Long-Term Care insurance)", expanded=True):
            names_local = [p["display_name"] for p in st.session_state.get("people", [])]
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
                    amt = num("Monthly VA payment (enter actual if known; otherwise use cap)",
                              f"{prefix}_va_actual", cap, step=25)
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
                if len(names_local) > 1:
                    b_res = va_block("b", nB)
                else:
                    st.write(""); st.write("")
                    b_res = {"monthly": 0, "detail": "No VA pension"}

            lc1, lc2 = st.columns(2)
            with lc1:
                a_ltc = st.selectbox(f"Long-Term Care insurance — {nA}", ["No", "Yes"], key="a_ltc")
            with lc2:
                if len(names_local) > 1:
                    b_ltc = st.selectbox(f"Long-Term Care insurance — {nB}", ["No", "Yes"], key="b_ltc")
                else:
                    st.selectbox("Long-Term Care insurance — (n/a)", ["No"], key="b_ltc_disabled", disabled=True)
                    b_ltc = "No"

            a_va = int(a_res.get("monthly", 0))
            b_va = int(b_res.get("monthly", 0)) if len(names_local) > 1 else 0
            st.session_state["a_va_monthly"] = a_va
            st.session_state["b_va_monthly"] = b_va

            benefits_total = (a_va + (ltc_add if a_ltc == "Yes" else 0)) + (b_va + (ltc_add if b_ltc == "Yes" else 0))
            metric_money("Subtotal — Benefits (VA + LTC add-ons)", benefits_total)

    # Home decision drawer
    if ENABLE_HOME_DECISION:
        with st.expander("Home decision (keep, sell, HELOC, reverse mortgage)", expanded=False):
            decision = st.selectbox("What do you plan to do with the home?",
                                    ["Keep", "Sell", "HELOC", "Reverse mortgage"], key="home_decision",
                                    help="These inputs help estimate monthly costs and potential proceeds.")
            apply_to_assets = False
            home_monthly = 0
            proceeds = 0

            if decision == "Keep":
                st.checkbox("Apply net proceeds to assets summary", value=False, key="home_apply_assets", disabled=True)
                m = num("Monthly mortgage/HELOC payment", "home_mortgage", 0)
                t = num("Monthly property taxes", "home_taxes", 0)
                i = num("Monthly homeowners insurance", "home_ins", 0)
                h = num("Monthly HOA/maintenance (optional)", "home_hoa", 0)
                u = num("Monthly utilities (optional)", "home_utils", 0)
                home_monthly = m + t + i + h + u
                metric_money("Subtotal — Home monthly costs", home_monthly)

            if decision == "Sell":
                sale = num("Estimated sale price", "home_sale_price", 500000, step=1000)
                payoff = num("Principal payoff at sale", "home_payoff", 120000, step=1000)
                fee_pct = st.slider("Typical fees (realtor/closing) percent", 4.0, 8.0, 6.0, 0.25, key="home_fee_pct")
                fees = int(round(sale * (fee_pct / 100.0)))
                proceeds = max(sale - payoff - fees, 0)
                st.caption(f"Estimated net proceeds: ${proceeds:,.0f}")
                apply_to_assets = st.checkbox("Apply net proceeds to assets summary", value=True, key="home_apply_assets")
                home_monthly = 0
                metric_money("Subtotal — Home monthly costs", home_monthly)

            if decision == "HELOC":
                heloc_pay = num("Monthly HELOC payment", "home_heloc_pay", 0)
                t = num("Monthly property taxes", "home_taxes2", 0)
                i = num("Monthly homeowners insurance", "home_ins2", 0)
                h = num("Monthly HOA/maintenance (optional)", "home_hoa2", 0)
                u = num("Monthly utilities (optional)", "home_utils2", 0)
                home_monthly = heloc_pay + t + i + h + u
                metric_money("Subtotal — Home monthly costs", home_monthly)

            if decision == "Reverse mortgage":
                draw = num("Monthly reverse-mortgage draw (adds to income)", "home_rev_draw", 0)
                t = num("Monthly property taxes", "home_taxes3", 0)
                i = num("Monthly homeowners insurance", "home_ins3", 0)
                h = num("Monthly HOA/maintenance (optional)", "home_hoa3", 0)
                u = num("Monthly utilities (optional)", "home_utils3", 0)
                # add the draw to household income bucket
                st.session_state["hh_other"] = int(st.session_state.get("hh_other", 0)) + int(draw)
                home_monthly = t + i + h + u
                metric_money("Subtotal — Home monthly costs", home_monthly)

            st.session_state["home_monthly_total"] = int(home_monthly)
            st.session_state["assets_home_proceeds"] = int(proceeds) if apply_to_assets else 0

    # Home modifications drawer
    if ENABLE_HOME_MODS:
        with st.expander("Home modifications (grab bars, ramps, bath, etc.)", expanded=False):
            st.caption("Select applicable projects. Costs are averages; scaled by finish level.")
            finish = st.selectbox("Finish level", ["Budget", "Standard", "Custom"], index=1, key="mods_finish",
                                  help="Budget ≈ 0.8x, Standard ≈ 1.0x, Custom ≈ 1.3x")
            scale = {"Budget": 0.8, "Standard": 1.0, "Custom": 1.3}[finish]

            # Items
            colL, colR = st.columns(2)
            with colL:
                c1 = st.checkbox("Grab bars & railings (avg $800)", key="m_bars")
                q1 = st.number_input("Qty", min_value=1, step=1, value=1, key="m_bars_qty", disabled=not c1)
                c2 = st.checkbox("Ramp installation (avg $3,500)", key="m_ramp")
                q2 = st.number_input("Qty ", min_value=1, step=1, value=1, key="m_ramp_qty", disabled=not c2)
                c3 = st.checkbox("Stair lift (avg $4,500)", key="m_stair")
                q3 = st.number_input("Qty  ", min_value=1, step=1, value=1, key="m_stair_qty", disabled=not c3)
                c4 = st.checkbox("Smart home monitoring/sensors (avg $1,200)", key="m_sensors")
                q4 = st.number_input("Qty   ", min_value=1, step=1, value=1, key="m_sensors_qty", disabled=not c4)
            with colR:
                c5 = st.checkbox("Widen doorways (avg $2,500)", key="m_doors")
                q5 = st.number_input("Qty    ", min_value=1, step=1, value=1, key="m_doors_qty", disabled=not c5)
                c6 = st.checkbox("Bathroom walk-in shower conversion (avg $12,000)", key="m_bath")
                q6 = st.number_input("Qty     ", min_value=1, step=1, value=1, key="m_bath_qty", disabled=not c6)
                c7 = st.checkbox("Lighting & fall-risk improvements (avg $1,500)", key="m_light")
                q7 = st.number_input("Qty      ", min_value=1, step=1, value=1, key="m_light_qty", disabled=not c7)

            base = (
                (800*c1*q1) + (3500*c2*q2) + (4500*c3*q3) + (1200*c4*q4) +
                (2500*c5*q5) + (12000*c6*q6) + (1500*c7*q7)
            )
            total_mods = int(round(base * scale))

            pay_method = st.radio("Payment method", ["Amortize monthly", "Pay upfront (one-time)"],
                                  index=0, horizontal=True, key="mods_pay_method")
            months = 12
            mods_monthly = 0
            upfront = 0
            if pay_method.startswith("Amortize"):
                months = st.slider("Amortize over (months)", 6, 48, 12, 1, key="mods_months")
                mods_monthly = int(round(total_mods / max(months, 1)))
                upfront = 0
                metric_money("Subtotal — Home mods (amortized monthly)", mods_monthly)
            else:
                upfront = total_mods
                mods_monthly = 0
                st.checkbox("Deduct upfront cost from assets summary", value=True, key="mods_apply_assets")
                metric_money("Upfront cost — Home mods", upfront)

            st.session_state["mods_monthly_total"] = int(mods_monthly)
            st.session_state["mods_upfront_total"] = int(upfront if st.session_state.get("mods_apply_assets", False) else 0)

    # Assets drawers
    if ENABLE_ASSETS:
        with st.expander("Assets — Common", expanded=False):
            a_cash = num("Cash/checking/savings", "as_cash", 0, step=500)
            a_brok = num("Brokerage (taxable)", "as_brokerage", 0, step=500)
            a_ret  = num("Retirement accounts (IRA/401k)", "as_retire", 0, step=500)
            a_cd   = num("CDs / money market", "as_cd", 0, step=500)
            common_total = a_cash + a_brok + a_ret + a_cd
            # Include home sale proceeds and mod upfront if selected
            common_total += int(st.session_state.get("assets_home_proceeds", 0))
            common_total -= int(st.session_state.get("mods_upfront_total", 0))
            metric_money("Subtotal — Common assets", common_total)
            st.session_state["assets_common_total"] = int(common_total)

        with st.expander("Assets — Detailed (optional)", expanded=False):
            a_hsa  = num("HSA balance", "as_hsa", 0, step=500)
            a_529  = num("529/education accounts", "as_529", 0, step=500)
            a_car  = num("Vehicle equity (resale value)", "as_car", 0, step=500)
            a_li   = num("Life insurance cash value", "as_life", 0, step=500)
            a_other= num("Other assets", "as_other", 0, step=500)
            detailed_total = a_hsa + a_529 + a_car + a_li + a_other
            metric_money("Subtotal — Detailed assets", detailed_total)
            st.session_state["assets_detailed_total"] = int(detailed_total)

    # Other recurring costs drawer
    if ENABLE_OTHER_COSTS:
        with st.expander("Other monthly costs (medications, insurance, etc.)", expanded=False):
            med = num("Medications", "oc_med", 0, step=25)
            med_ins = num("Medicare / health insurance premium", "oc_medins", 0, step=25)
            dental = num("Dental insurance", "oc_dental", 0, step=25)
            other = num("Other recurring", "oc_other", 0, step=25)
            other_total = med + med_ins + dental + other
            metric_money("Subtotal — Other monthly costs", other_total)
            st.session_state["other_monthly_total"] = int(other_total)

    st.divider()
    cols = st.columns(3)
    with cols[0]:
        if st.button("Back to Costs"):
            st.session_state.step = "calculator"
            st.rerun()
    with cols[1]:
        if ENABLE_DETAILS_PAGE and st.button("View Detailed Breakdown"):
            st.session_state.step = "breakdown"
            st.rerun()
    with cols[2]:
        if st.button("Start Over"):
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

    # Benefits (from VA wizard) + LTC add-ons
    settings = getattr(calculator, "settings", {}) or {}
    ltc_add = int(settings.get("ltc_monthly_add", 1800))
    a_va = int(s.get("a_va_monthly", 0))
    b_va = int(s.get("b_va_monthly", 0)) if len(people) > 1 else 0
    a_ltc_add = ltc_add if s.get("a_ltc") == "Yes" else 0
    b_ltc_add = ltc_add if s.get("b_ltc") == "Yes" else 0

    # Other monthly costs
    home_monthly   = int(s.get("home_monthly_total", 0))
    mods_monthly   = int(s.get("mods_monthly_total", 0))
    other_monthly  = int(s.get("other_monthly_total", 0))
    addl_costs     = home_monthly + mods_monthly + other_monthly

    # Assets
    assets_common  = int(s.get("assets_common_total", 0))
    assets_detail  = int(s.get("assets_detailed_total", 0))
    assets_total   = assets_common + assets_detail

    # Totals
    income_total = inc_A + inc_B + inc_house + a_va + b_va + a_ltc_add + b_ltc_add
    monthly_need = care_total + addl_costs
    gap = monthly_need - income_total

    # Headline tiles
    c1, c2, c3 = st.columns(3)
    c1.metric("Monthly Care + Selected Costs", f"${monthly_need:,.0f}")
    c2.metric("Total Monthly Income (incl. VA & LTC add-ons)", f"${income_total:,.0f}")
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

    # Composition (numeric + optional charts)
    st.markdown("### Income breakdown")
    income_dict = {
        "Individual A": inc_A,
        "Individual B": inc_B,
        "Household": inc_house,
        "VA + LTC": a_va + b_va + a_ltc_add + b_ltc_add,
    }
    st.write(income_dict)

    st.markdown("### Additional monthly costs")
    st.write({
        "Home (carry, taxes, fees)": home_monthly,
        "Home modifications (amortized)": mods_monthly,
        "Other recurring": other_monthly,
    })

    st.markdown("### Assets summary")
    st.write({
        "Common assets (incl. proceeds, less upfront mods)": assets_common,
        "Detailed assets": assets_detail,
        "Total assets": assets_total,
    })

    try:
        if ENABLE_CHARTS and HAVE_ALTAIR:
            import pandas as pd, altair as alt  # noqa: F401
            inc_df = pd.DataFrame([
                {"Category": "Indiv A", "Amount": inc_A},
                {"Category": "Indiv B", "Amount": inc_B},
                {"Category": "Household", "Amount": inc_house},
                {"Category": "VA + LTC", "Amount": a_va + b_va + a_ltc_add + b_ltc_add},
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
            st.rerun()
    with b2:
        if st.button("Back to Costs"):
            st.session_state.step = "calculator"
            st.rerun()
