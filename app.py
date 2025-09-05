# app.py — Senior Navigator (Planner → Recommendation → Costs → Household → Breakdown)
# Mobile-focused UX: one-question-at-a-time wizard, horizontal buttons, top-scroll on step change.
# Business logic lives in engines.py and JSON under ./data; this file handles UI/flow only.

from pathlib import Path
from types import SimpleNamespace
import traceback

import streamlit as st

# ---------- Page config ----------
st.set_page_config(page_title="Senior Navigator • Planner + Cost", page_icon="🧭", layout="centered")

# Subtle mobile spacing/legibility tweaks
st.markdown("""
<style>
@media (max-width: 480px){
  .block-container { padding-top: 0.75rem; padding-bottom: 4rem; }
  .stButton>button { padding:.75rem 1rem; border-radius:.5rem; }
  .stRadio > div{ gap:.5rem !important; }
  label { font-size: 1rem !important; }
}
</style>
""", unsafe_allow_html=True)

# ---------- Feature flags ----------
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
ENABLE_CHARTS = True  # Altair optional; auto-disables if not installed

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
    from engines import PlannerEngine, CalculatorEngine, CalcInputs  # CalcInputs is optional
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

# ---------- Mobile UX helpers ----------
def jump_to_top():
    """Scroll to top on next render if a previous handler set _jump_top."""
    if st.session_state.pop("_jump_top", False):
        st.markdown(
            "<script>window.scrollTo({top: 0, behavior: 'instant'});</script>",
            unsafe_allow_html=True,
        )

def row_buttons(*buttons):
    """
    Render a row of buttons that stay horizontal on mobile (best-effort).
    Usage:
      clicks = row_buttons(
        ("Back", "back_key"),
        ("Next", "next_key", True)   # True marks primary
      )
      if clicks["back_key"]: ...
    """
    n = max(1, len(buttons))
    cols = st.columns(n)
    clicks = {}
    for col, spec in zip(cols, buttons):
        label, key = spec[0], spec[1]
        primary = bool(spec[2]) if len(spec) > 2 else False
        with col:
            clicks[key] = st.button(label, key=key, use_container_width=True,
                                    type=("primary" if primary else "secondary"))
    return clicks

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
    jump_to_top()
    st.header("Who is this plan for?")
    role = st.radio("Select one:", ["Myself", "My spouse/partner", "My parent", "Both parents", "Someone else"])

    people = []
    if role == "Both parents":
        c1, c2 = st.columns(2)
        with c1:
            p1_val = st.session_state.get("p1_name", "")
            n1 = st.text_input("Parent 1 name", value=p1_val, placeholder="e.g., Mom", key="p1_name")
            st.selectbox("Parent 1 age", ["65–74", "75–84", "85+"], key="p1_age")
        with c2:
            p2_val = st.session_state.get("p2_name", "")
            n2 = st.text_input("Parent 2 name", value=p2_val, placeholder="e.g., Dad", key="p2_name")
            st.selectbox("Parent 2 age", ["65–74", "75–84", "85+"], key="p2_age")
        people = [
            {"id": "A", "display_name": n1 or "Parent 1", "relationship": "parent"},
            {"id": "B", "display_name": n2 or "Parent 2", "relationship": "parent"},
        ]
    else:
        placeholder_map = {"Myself": "e.g., Alex", "My spouse/partner": "e.g., Pat", "My parent": "e.g., Mom", "Someone else": "e.g., Aunt Jean"}
        ph = placeholder_map.get(role, "e.g., Alex")
        p_val = st.session_state.get("p_name", "")
        n = st.text_input("Name", value=p_val, placeholder=ph, key="p_name")
        st.selectbox("Approximate age", ["65–74", "75–84", "85+"], key="p_age")
        map_rel = {"Myself": "self", "My spouse/partner": "spouse", "My parent": "parent", "Someone else": "other"}
        people = [{"id": "A", "display_name": n or "Alex", "relationship": map_rel.get(role, "other")}]

    st.caption("Next, we’ll ask short care questions for each person.")
    if row_buttons(("Continue", "aud_continue", True))["aud_continue"]:
        st.session_state.people = people
        st.session_state.current_person = 0
        st.session_state.answers = {}
        st.session_state.planner_results = {}
        st.session_state.mobility_raw = {}
        st.session_state.care_overrides = {}
        st.session_state.person_costs = {}
        st.session_state.wizard_state = {}
        st.session_state.step = "partner_context" if ENABLE_PARTNER_INTERSTITIAL else "planner"
        st.session_state["_jump_top"] = True
        st.rerun()

# ---------- Partner interstitial ----------
elif st.session_state.step == "partner_context":
    jump_to_top()
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
            st.text_input("Spouse/partner name", value=st.session_state.get("care_partner_name", ""), placeholder="e.g., Pat", key="care_partner_name")

    clicks = row_buttons(("Skip, start care questions", "pc_skip"),
                         ("Add spouse/partner and continue", "pc_add", True))
    if clicks["pc_skip"]:
        st.session_state.step = "planner"
        st.session_state["_jump_top"] = True
        st.rerun()
    if clicks["pc_add"]:
        if single and st.session_state.get("care_partner_add"):
            st.session_state.people.append({
                "id": "B",
                "display_name": st.session_state.get("care_partner_name") or "Spouse/Partner",
                "relationship": "spouse"
            })
        st.session_state.step = "planner"
        st.session_state["_jump_top"] = True
        st.rerun()

# ---------- Planner (Q&A) — mobile wizard (one-at-a-time); desktop toggle shows all ----------
elif st.session_state.step == "planner":
    jump_to_top()

    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if not people:
        reset_all(); st.rerun()

    person = people[i]
    pid = person["id"]
    name = person["display_name"]

    st.header(f"Care Plan — {name}")
    st.caption(f"Person {i+1} of {len(people)}")

    qa = planner.qa or {}
    questions = qa.get("questions", [])
    answers = st.session_state.answers.get(pid, {})

    # Wizard state for this person
    ws = st.session_state.wizard_state.setdefault(pid, {"idx": 0})

    # Desktop toggle (for reviewers)
    desktop_show_all = st.toggle("Show all questions (desktop reviewers)", value=False,
                                 help="Mobile users get one question at a time for readability.")

    def render_q(idx: int):
        q = questions[idx]
        qnum = idx + 1
        opts_map = q.get("answers", {})
        ordered_keys = [str(n) for n in sorted(map(int, opts_map.keys()))]
        prev_key = str(answers.get(f"q{qnum}", ordered_keys[0]))
        opts = [opts_map[k] for k in ordered_keys]
        label = q.get("question", f"Question {qnum}")
        help_txt = q.get("help", None)
        curr_idx = ordered_keys.index(prev_key) if prev_key in ordered_keys else 0
        sel = st.radio(label, options=opts, index=curr_idx, help=help_txt, key=f"{pid}_q{qnum}_wiz")
        sel_key = ordered_keys[opts.index(sel)]
        answers[f"q{qnum}"] = int(sel_key)
        # mobility capture for carryover
        if "mobility" in label.lower():
            st.session_state.setdefault("mobility_raw", {}).update({pid: int(sel_key)})

    if desktop_show_all:
        for idx in range(len(questions)):
            render_q(idx)
        st.session_state.answers[pid] = answers

        clicks = row_buttons(("Back", "plan_back_all"),
                             ("Next", "plan_next_all", True))
        if clicks["plan_back_all"]:
            if i == 0:
                st.session_state.step = "partner_context" if ENABLE_PARTNER_INTERSTITIAL else "audience"
            else:
                st.session_state.current_person = i - 1
            st.session_state["_jump_top"] = True
            st.rerun()

        if clicks["plan_next_all"]:
            try:
                res = planner.run(answers)
            except Exception:
                st.error("PlannerEngine.run failed.")
                st.code(traceback.format_exc()); st.stop()

            care_type = (getattr(res, "care_type", None) or res.get("care_type") or "in_home")
            flags = getattr(res, "flags", None) or set(res.get("flags", []))
            scores = getattr(res, "scores", None) or res.get("scores", {})
            reasons = getattr(res, "reasons", None) or res.get("reasons", [])
            advisory = getattr(res, "advisory", None) or res.get("advisory")

            st.session_state.planner_results[pid] = {
                "care_type": care_type,
                "flags": set(flags),
                "scores": scores,
                "reasons": reasons,
                "advisory": advisory
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
        total_q = len(questions)
        idx = int(ws.get("idx", 0))
        idx = max(0, min(idx, total_q - 1))
        ws["idx"] = idx

        st.progress((idx + 1) / total_q, text=f"Question {idx+1} of {total_q}")
        render_q(idx)
        st.session_state.answers[pid] = answers

        left_label = "Back" if idx > 0 else ("Back to start" if i == 0 else "Back")
        right_label = "Next" if idx + 1 < total_q else "Finish"
        clicks = row_buttons((left_label, "wiz_back"),
                             (right_label, "wiz_next", True))

        if clicks["wiz_back"]:
            if idx > 0:
                ws["idx"] = idx - 1
            else:
                if i == 0:
                    st.session_state.step = "partner_context" if ENABLE_PARTNER_INTERSTITIAL else "audience"
                else:
                    st.session_state.current_person = i - 1
                    prev_pid = people[i-1]["id"]
                    st.session_state.wizard_state.setdefault(prev_pid, {"idx": total_q - 1})
                st.session_state["_jump_top"] = True
            st.rerun()

        if clicks["wiz_next"]:
            if idx + 1 < total_q:
                ws["idx"] = idx + 1
                st.rerun()
            else:
                try:
                    res = planner.run(answers)
                except Exception:
                    st.error("PlannerEngine.run failed.")
                    st.code(traceback.format_exc()); st.stop()

                care_type = (getattr(res, "care_type", None) or res.get("care_type") or "in_home")
                flags = getattr(res, "flags", None) or set(res.get("flags", []))
                scores = getattr(res, "scores", None) or res.get("scores", {})
                reasons = getattr(res, "reasons", None) or res.get("reasons", [])
                advisory = getattr(res, "advisory", None) or res.get("advisory")

                st.session_state.planner_results[pid] = {
                    "care_type": care_type,
                    "flags": set(flags),
                    "scores": scores,
                    "reasons": reasons,
                    "advisory": advisory
                }

                if i + 1 < len(people):
                    st.session_state.current_person = i + 1
                    next_pid = people[i+1]["id"]
                    st.session_state.wizard_state.setdefault(next_pid, {"idx": 0})
                    st.session_state["_jump_top"] = True
                    st.rerun()
                else:
                    st.session_state.step = "recommendations"
                    st.session_state["_jump_top"] = True
                    st.rerun()

# ---------- Recommendations + override ----------
elif st.session_state.step == "recommendations":
    jump_to_top()
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without redoing questions.")

    for p in st.session_state.people:
        rec = st.session_state.planner_results.get(p["id"], {})
        default = rec.get("care_type", "in_home")
        st.subheader(f"{p['display_name']}: {default.replace('_', ' ').title()} (recommended)")
        for r in rec.get("reasons", []) or []:
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

    clicks = row_buttons(("Back to audience", "rec_back"),
                         ("See Costs", "rec_next", True))
    if clicks["rec_back"]:
        st.session_state.step = "audience"
        st.session_state["_jump_top"] = True
        st.rerun()
    if clicks["rec_next"]:
        st.session_state.step = "calculator"
        st.session_state["_jump_top"] = True
        st.rerun()

# ---------- Calculator ----------
elif st.session_state.step == "calculator":
    jump_to_top()
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

    clicks = row_buttons(("Back to recommendations", "calc_back"),
                         ("Add Household & Assets", "calc_house", True))
    if clicks["calc_back"]:
        st.session_state.step = "recommendations"
        st.session_state["_jump_top"] = True
        st.rerun()
    if clicks["calc_house"]:
        st.session_state.step = "household"
        st.session_state["_jump_top"] = True
        st.rerun()

# ---------- Household (drawers) ----------
elif st.session_state.step == "household":
    jump_to_top()
    people = st.session_state.get("people", [])
    names = [p["display_name"] for p in people]
    nameA = names[0] if names else "Person A"
    nameB = names[1] if len(names) > 1 else "Person B"

    st.header("Household & Budget (optional)")
    st.markdown("Add income, benefits, and assets to see affordability. You can skip this.")

    vals = st.session_state.get("house_vals", {})

    def money(label, key, default=0):
        v0 = int(vals.get(key, default) or st.session_state.get(key, default) or 0)
        v = st.number_input(label, min_value=0, step=50, value=v0, key=key)
        try:
            st.session_state[key] = int(v)
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
                    st.write("")
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

    # Home decision drawer (keep/sell/HELOC/reverse); includes HOA and utilities; proceeds option
    if ENABLE_HOME_DECISION:
        with st.expander("Home decision (keep, sell, HELOC, reverse mortgage)", expanded=True):
            plan = st.selectbox("What do you plan to do with the home?",
                                ["Keep", "Sell", "HELOC", "Reverse mortgage"], key="home_plan",
                                help="This helps us include monthly home costs or proceeds appropriately.")

            apply_proceeds = st.checkbox("Apply net proceeds to assets summary", value=True, key="home_apply_proceeds")

            monthly_home_costs = 0
            proceeds = 0

            if plan == "Keep":
                m_mort = money("Monthly mortgage/HELOC payment", "home_keep_mort", 0)
                m_tax  = money("Monthly property taxes", "home_keep_tax", 0)
                m_ins  = money("Monthly homeowners insurance", "home_keep_ins", 0)
                m_hoa  = money("Monthly HOA/maintenance", "home_keep_hoa", 0)
                m_util = money("Monthly utilities (avg.)", "home_keep_util", 0)
                monthly_home_costs = m_mort + m_tax + m_ins + m_hoa + m_util

            elif plan == "Sell":
                sale_price = money("Estimated sale price", "home_sell_price", 0)
                payoff     = money("Principal payoff at sale", "home_sell_payoff", 0)
                fee_pct    = st.slider("Typical fees (realtor/closing) — percent", 0.0, 10.0, 6.0, 0.25, key="home_sell_fee_pct")
                fees_abs   = round(sale_price * (fee_pct/100.0))
                proceeds   = max(sale_price - payoff - fees_abs, 0)
                st.caption(f"Estimated net proceeds: **${proceeds:,.0f}** (fees about ${fees_abs:,.0f})")

            elif plan == "HELOC":
                m_heloc = money("Monthly HELOC payment", "home_heloc_pay", 0)
                m_tax   = money("Monthly property taxes", "home_heloc_tax", 0)
                m_ins   = money("Monthly homeowners insurance", "home_heloc_ins", 0)
                m_hoa   = money("Monthly HOA/maintenance", "home_heloc_hoa", 0)
                m_util  = money("Monthly utilities (avg.)", "home_heloc_util", 0)
                monthly_home_costs = m_heloc + m_tax + m_ins + m_hoa + m_util

            elif plan == "Reverse mortgage":
                m_tax   = money("Monthly property taxes", "home_rev_tax", 0)
                m_ins   = money("Monthly homeowners insurance", "home_rev_ins", 0)
                m_hoa   = money("Monthly HOA/maintenance", "home_rev_hoa", 0)
                m_util  = money("Monthly utilities (avg.)", "home_rev_util", 0)
                monthly_home_costs = m_tax + m_ins + m_hoa + m_util

            st.metric("Subtotal — Home monthly costs", f"${monthly_home_costs:,.0f}")
            st.session_state["home_monthly_total"] = monthly_home_costs
            st.session_state["home_sale_proceeds"] = proceeds if apply_proceeds else 0
            st.session_state["home_apply_proceeds"] = apply_proceeds

    # Home modifications (with finish level, selectable items, amortize vs upfront)
    if ENABLE_HOME_MODS:
        with st.expander("Home modifications (grab bars, ramps, bath, etc.)", expanded=True):
            # catalog costs
            BASE = {
                "Grab bars & railings": 800,
                "Widen doorways": 2500,
                "Ramp installation": 3500,
                "Bathroom walk-in shower conversion": 12000,
                "Stair lift": 4500,
                "Smart home monitoring/sensors": 1200,
                "Lighting & fall-risk improvements": 1500,
            }
            level = st.selectbox("Finish level", ["Budget", "Standard", "Custom"], index=1,
                                 help="Budget uses basic fixtures/materials; Custom uses premium finishes.", key="mods_level")
            level_mult = {"Budget": 0.85, "Standard": 1.0, "Custom": 1.25}[level]

            # selections in two columns
            left, right = st.columns(2)
            sel = {}
            qty = {}

            def item(row, label, keybase, default_checked=False, default_qty=1):
                with row:
                    sel[keybase] = st.checkbox(f"{label} (avg ${BASE[label]:,})", value=default_checked, key=f"chk_{keybase}")
                    qty[keybase] = st.number_input("Qty", min_value=1, step=1, value=default_qty, key=f"qty_{keybase}") if sel[keybase] else 0

            item(left,  "Grab bars & railings", "bars", True, 2)
            item(right, "Widen doorways", "door", False, 1)
            item(left,  "Ramp installation", "ramp", False, 1)
            item(right, "Bathroom walk-in shower conversion", "bath", True, 1)
            item(left,  "Stair lift", "stair", False, 1)
            item(left,  "Smart home monitoring/sensors", "smart", False, 1)
            item(right, "Lighting & fall-risk improvements", "light", False, 1)

            # cost calc
            upfront_raw = 0
            mapping = {
                "bars": "Grab bars & railings",
                "door": "Widen doorways",
                "ramp": "Ramp installation",
                "bath": "Bathroom walk-in shower conversion",
                "stair": "Stair lift",
                "smart": "Smart home monitoring/sensors",
                "light": "Lighting & fall-risk improvements",
            }
            for k, checked in sel.items():
                if checked:
                    unit = BASE[mapping[k]]
                    upfront_raw += int(round(unit * level_mult) * qty.get(k, 0))

            pay_method = st.radio("Payment method", ["Amortize monthly", "Pay upfront (one-time)"], index=0, key="mods_pay_method")
            months = st.slider("Amortize over (months)", 6, 60, 12, 1, key="mods_months") if pay_method == "Amortize monthly" else 0

            deduct_assets = st.checkbox("Deduct upfront cost from assets summary", value=True, key="mods_deduct_assets")

            if pay_method == "Amortize monthly":
                monthly_mods = int(round(upfront_raw / max(months, 1)))
                st.metric("Subtotal — Home mods (amortized monthly)", f"${monthly_mods:,.0f}")
                st.caption(f"Upfront estimated: ${upfront_raw:,.0f} amortized over {months} months")
                st.session_state["mods_monthly_total"] = monthly_mods
                st.session_state["mods_upfront_total"] = 0
            else:
                st.metric("Upfront cost — Home mods", f"${upfront_raw:,.0f}")
                st.caption("Monthly impact: $0 (paid upfront)")
                st.session_state["mods_monthly_total"] = 0
                st.session_state["mods_upfront_total"] = upfront_raw if deduct_assets else 0
            st.session_state["mods_deduct_assets"] = deduct_assets

    # Other monthly recurring costs
    if ENABLE_OTHER_MONTHLIES:
        with st.expander("Other monthly costs (health, medications, transportation, etc.)", expanded=False):
            meds   = money("Prescription medications", "om_meds", 0)
            medic  = money("Medicare/health insurance premiums", "om_medic", 0)
            dental = money("Dental insurance", "om_dental", 0)
            transp = money("Transportation", "om_transp", 0)
            food   = money("Groceries & meals", "om_food", 0)
            other  = money("Other recurring", "om_other", 0)
            other_monthly_total = meds + medic + dental + transp + food + other
            st.metric("Subtotal — Other recurring costs", f"${other_monthly_total:,.0f}")
            st.session_state["other_monthly_total"] = other_monthly_total

    st.divider()
    clicks = row_buttons(("Back to Costs", "hh_back"),
                         ("Finish & View Breakdown", "hh_finish", True))
    if clicks["hh_back"]:
        st.session_state.step = "calculator"
        st.session_state["_jump_top"] = True
        st.rerun()
    if clicks["hh_finish"]:
        st.session_state.step = "breakdown"
        st.session_state["_jump_top"] = True
        st.rerun()

# ---------- Breakdown ----------
elif st.session_state.step == "breakdown":
    jump_to_top()
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

    # Assets (sum proceeds + upfront mods if deducted)
    assets_common  = int(s.get("assets_common_total", 0))  # reserved if you add common assets drawer later
    assets_detail  = int(s.get("assets_detailed_total", 0))
    proceeds_add   = int(s.get("home_sale_proceeds", 0))
    mods_upfront   = int(s.get("mods_upfront_total", 0))
    assets_total   = assets_common + assets_detail + proceeds_add - mods_upfront
    if assets_total < 0:
        assets_total = 0

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

    # Income composition (numeric fallback + optional donuts)
    st.markdown("### Income breakdown")
    inc_dict = {
        "Individual A": inc_A,
        "Individual B": inc_B,
        "Household": inc_house,
        "VA benefits": va_A + va_B,
    }
    st.write(inc_dict)

    st.markdown("### Additional monthly costs")
    cost_dict = {
        "Home (mortgage/tax/ins/HOA/utilities)": home_monthly,
        "Home modifications (amortized)": mods_monthly,
        "Other recurring": other_monthly,
    }
    st.write(cost_dict)

    st.markdown("### Assets summary")
    asset_dict = {
        "Common assets": assets_common,
        "Detailed assets": assets_detail,
        "Home sale proceeds applied": proceeds_add,
        "Upfront mods deducted": mods_upfront,
        "Total assets": assets_total,
    }
    st.write(asset_dict)

    # Optional donuts via Altair
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
    clicks = row_buttons(("Back to Household", "bd_house"),
                         ("Back to Costs", "bd_costs"))
    if clicks["bd_house"]:
        st.session_state.step = "household"
        st.session_state["_jump_top"] = True
        st.rerun()
    if clicks["bd_costs"]:
        st.session_state.step = "calculator"
        st.session_state["_jump_top"] = True
        st.rerun()