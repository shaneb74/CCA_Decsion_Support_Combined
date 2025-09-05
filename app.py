from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import traceback
import math

import streamlit as st

# Optional charts
try:
    import altair as alt
    HAVE_ALTAIR = True
except Exception:
    HAVE_ALTAIR = False

# ---------- Page config ----------
st.set_page_config(page_title="Senior Navigator • Planner + Cost", page_icon="🧭", layout="centered")

# ---------- Feature flags ----------
ENABLE_PARTNER_INTERSTITIAL = True
ENABLE_SECOND_PERSON_TRANSITION = True
ENABLE_REC_OVERRIDE = True
ENABLE_INHOME_DAYS_PER_MONTH = True
ENABLE_MOBILITY_CARRYOVER = True
ENABLE_HOUSEHOLD_DRAWERS = True
ENABLE_VA_WIZARD = True
ENABLE_HOME_DECISION = True
ENABLE_HOME_MODS = True
ENABLE_OTHER_MONTHLIES = True
ENABLE_DETAILS_PAGE = True
ENABLE_CHARTS = True  # only if Altair available

# ---------- Data paths (root) ----------
ROOT = Path(__file__).resolve().parent
QA_PATH = ROOT / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = ROOT / "recommendation_logic_FINAL_MASTER_UPDATED.json"

# ---------- Engines ----------
try:
    from engines import PlannerEngine, CalculatorEngine, PlannerResult
except Exception:
    st.error("Failed to import engines.py. See traceback:")
    st.code(traceback.format_exc())
    st.stop()

for p in (QA_PATH, REC_PATH):
    if not p.exists():
        st.error(f"Missing file: {p}")
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
    obj = SimpleNamespace()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj

def reset_all():
    for k in list(st.session_state.keys()):
        if not k.startswith("_"):
            del st.session_state[k]
    st.session_state.step = "intro"

def order_answer_map(amap):
    if not isinstance(amap, dict) or not amap:
        return [], []
    keys = list(amap.keys())
    def _intlike(x):
        try:
            int(str(x)); return True
        except Exception:
            return False
    if all(_intlike(k) for k in keys):
        ordered = [str(k) for k in sorted(int(str(k)) for k in keys)]
    else:
        ordered = [str(k) for k in keys]  # keep insertion order
    return ordered, [amap[k] for k in ordered]

def radio_from_answer_map(label, amap, *, key, help_text=None, default_key=None):
    ordered_keys, ordered_labels = order_answer_map(amap)
    if not ordered_labels:
        return default_key
    if default_key is not None and str(default_key) in ordered_keys:
        idx = ordered_keys.index(str(default_key))
    else:
        idx = 0
    sel_label = st.radio(label, options=ordered_labels, index=idx, key=key, help=help_text)
    return ordered_keys[ordered_labels.index(sel_label)]

def metric_money(label, value):
    st.metric(label, f"${int(value):,}")

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
3. Add income, benefits, assets, and home choices.  
4. View a detailed breakdown.
""")
    st.info("Typical time: 10–15 minutes. Stop anytime and resume later.")
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
            n1 = st.text_input("Parent 1 name", value="Mom", key="p1_name", placeholder="Name")
        with c2:
            n2 = st.text_input("Parent 2 name", value="Dad", key="p2_name", placeholder="Name")
        people = [{"id": "A", "display_name": n1, "relationship": "parent"},
                  {"id": "B", "display_name": n2, "relationship": "parent"}]
    else:
        default = "Alex" if role != "My parent" else "Mom"
        n = st.text_input("Name", value=default, key="p_name", placeholder="Name")
        rel = {"Myself": "self", "My spouse/partner": "spouse", "My parent": "parent", "Someone else": "other"}[role]
        people = [{"id": "A", "display_name": n, "relationship": rel}]
    st.caption("Next, we’ll ask short care questions for each person.")

    if st.button("Continue"):
        st.session_state.people = people
        st.session_state.current_person = 0
        st.session_state.answers = {}
        st.session_state.results = {}
        st.session_state.mobility_raw = {}
        st.session_state.care_overrides = {}
        st.session_state.person_costs = {}
        st.session_state.step = "partner_context" if ENABLE_PARTNER_INTERSTITIAL and role != "Both parents" else "planner"
        st.rerun()

# Partner interstitial (only if not “Both parents”)
elif st.session_state.step == "partner_context":
    people = st.session_state.get("people", [])
    single = len(people) == 1
    primary = people[0]["display_name"] if people else "Person A"

    st.header("Should we include the spouse/partner too?")
    st.markdown(f"""
If **{primary}** needs assisted living or memory care, their spouse/partner may also need some in-home help.  
Include a simple support plan now so the household picture is complete.
""")

    if single:
        add = st.checkbox("Yes, include a spouse/partner plan", value=False, key="care_partner_add")
        if add:
            st.text_input("Spouse/partner name", value="", placeholder="Enter spouse/partner name", key="care_partner_name")

    c1, c2 = st.columns(2)
    with c1:
        if st.button(f"No, just plan for {primary}"):
            st.session_state.step = "planner"
            st.rerun()
    with c2:
        disabled = not st.session_state.get("care_partner_add", False)
        if st.button("Add spouse/partner and continue", disabled=disabled):
            if single and st.session_state.get("care_partner_add"):
                st.session_state.people.append({
                    "id": "B",
                    "display_name": st.session_state.get("care_partner_name") or "Spouse/Partner",
                    "relationship": "spouse"
                })
            st.session_state.step = "planner"
            st.rerun()

# Planner (per-person Q&A, one question per screen on mobile-ish)
elif st.session_state.step == "planner":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if not people:
        reset_all(); st.rerun()
    person = people[i]
    name = person["display_name"]

    st.header(f"Care Plan Questions for {name}")
    qa = planner.qa or {}
    questions = qa.get("questions", [])
    cond_cfg = qa.get("conditional_questions")

    # Per-person wizard state
    ws_key = f"wiz_{person['id']}"
    ws = st.session_state.get(ws_key, {"idx": 0})
    total_q = len(questions)
    idx = int(ws.get("idx", 0))
    idx = max(0, min(idx, total_q - 1))

    # Render 1 question at a time for readability
    q = questions[idx]
    opts_map = q.get("answers", {})
    ordered_keys, ordered_labels = order_answer_map(opts_map)
    label = q.get("question", f"Question {idx+1}") + f" (for {name})"
    help_text = q.get("help")
    # default index based on prior choice
    prev = st.session_state.get(f"{person['id']}_q{idx+1}")
    if prev and str(prev) in ordered_keys:
        def_idx = ordered_keys.index(str(prev))
    else:
        def_idx = 0
    sel_label = st.radio(label, options=ordered_labels, index=def_idx, key=f"{person['id']}_q{idx+1}", help=help_text)
    sel_key = ordered_keys[ordered_labels.index(sel_label)]

    # Nav buttons
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("Back", disabled=(idx == 0)):
            ws["idx"] = max(0, idx - 1)
            st.session_state[ws_key] = ws
            st.rerun()
    with c2:
        if st.button("Next"):
            # persist current answer
            ans = st.session_state.answers.get(person["id"], {})
            ans[f"q{idx+1}"] = int(sel_key)
            st.session_state.answers[person["id"]] = ans

            if idx + 1 < total_q:
                ws["idx"] = idx + 1
                st.session_state[ws_key] = ws
                st.rerun()
            else:
                # optional conditional question (appears only when configured by JSON rule)
                conditional_answer = None
                if cond_cfg:
                    cq = cond_cfg[0]
                    # show only if JSON says to based on triggered flag keys
                    # If the JSON has a `show_if_flags_any`, respect it; else default: show only if "severe_cognitive_risk" present
                    show_if = set(cq.get("show_if_flags_any", ["severe_cognitive_risk"]))
                    # derive a temp flag set from current answers to decide whether to show
                    temp_res = planner.run(ans)
                    if temp_res.flags & show_if:
                        st.session_state.step = "conditional_for_person"
                        st.session_state._pending_person = person["id"]
                        st.rerun()

                # finalize this person
                try:
                    res: PlannerResult = planner.run(st.session_state.answers[person["id"]])
                except Exception:
                    st.error("PlannerEngine.run failed.")
                    st.code(traceback.format_exc())
                    st.stop()

                st.session_state.results[person["id"]] = {
                    "care_type": res.care_type,
                    "flags": set(res.flags),
                    "scores": res.scores,
                    "reasons": res.reasons,
                    "narrative": res.narrative or "",
                }

                # If another person exists, show a transition screen
                if i + 1 < len(people) and ENABLE_SECOND_PERSON_TRANSITION:
                    st.session_state.current_person = i + 1
                    st.session_state.step = "between_people"
                    st.rerun()
                else:
                    st.session_state.step = "recommendations"
                    st.rerun()

# Optional conditional screen (when 9th question is relevant)
elif st.session_state.step == "conditional_for_person":
    pid = st.session_state.get("_pending_person")
    people = st.session_state.get("people", [])
    person = next((p for p in people if p["id"] == pid), None)
    if not person:
        st.session_state.step = "planner"; st.rerun()
    name = person["display_name"]

    qa = planner.qa or {}
    cond_cfg = qa.get("conditional_questions", [])
    if not cond_cfg:
        st.session_state.step = "planner"; st.rerun()
    cq = cond_cfg[0]
    answers_map = cq.get("answers", {"1": "Yes", "2": "No"})
    ordered_ckeys, ordered_clabels = order_answer_map(answers_map)
    sel = st.radio(cq.get("question", "Additional question"),
                   options=ordered_clabels, index=0, key=f"{pid}_cond")
    cond_key = ordered_ckeys[ordered_clabels.index(sel)]

    c1, c2 = st.columns([1,1])
    with c1:
        if st.button("Back"):
            st.session_state.step = "planner"; st.rerun()
    with c2:
        if st.button("Continue"):
            # recompute with conditional
            try:
                res: PlannerResult = planner.run(st.session_state.answers[pid], conditional_answer=cond_key)
            except Exception:
                st.error("PlannerEngine.run failed.")
                st.code(traceback.format_exc()); st.stop()
            st.session_state.results[pid] = {
                "care_type": res.care_type,
                "flags": set(res.flags),
                "scores": res.scores,
                "reasons": res.reasons,
                "narrative": res.narrative or "",
            }
            # advance to next person or recs
            people = st.session_state.get("people", [])
            cur_idx = next((i for i,p in enumerate(people) if p["id"] == pid), 0)
            if cur_idx + 1 < len(people) and ENABLE_SECOND_PERSON_TRANSITION:
                st.session_state.current_person = cur_idx + 1
                st.session_state.step = "between_people"
            else:
                st.session_state.step = "recommendations"
            st.rerun()

# Transition between person A and B
elif st.session_state.step == "between_people":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    prev = people[i-1]["display_name"] if i > 0 else "Person A"
    nxt = people[i]["display_name"] if i < len(people) else "Next person"
    st.header("Great — first plan captured.")
    st.write(f"We’ve saved the answers for **{prev}**. Now let’s assess **{nxt}**.")
    if st.button(f"Start {nxt}'s care questions"):
        st.session_state.step = "planner"
        st.rerun()

# Recommendations + override
elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without redoing questions.")

    for p in st.session_state.get("people", []):
        rec = st.session_state.results.get(p["id"], {})
        care_default = rec.get("care_type", "in_home")
        narrative = rec.get("narrative") or ""
        flags = rec.get("flags", set())

        label_map = {"in_home": "In-home Care", "assisted_living": "Assisted Living", "memory_care": "Memory Care", "none": "No plan needed"}
        st.subheader(f"{p['display_name']}: {label_map.get(care_default, care_default)}")

        if narrative:
            # replace placeholder {name}
            st.info(narrative.replace("{name}", p["display_name"]))

        if ENABLE_REC_OVERRIDE:
            choices = ["in_home", "assisted_living", "memory_care", "none"]
            idx = choices.index(care_default) if care_default in choices else 0
            sel = st.selectbox(f"Care scenario for {p['display_name']}",
                               [label_map[c] for c in choices],
                               index=idx, key=f"override_{p['id']}")
            inv = {v: k for k, v in label_map.items()}
            st.session_state.care_overrides[p['id']] = inv[sel]

        st.divider()

    if st.button("See Costs"):
        st.session_state.step = "calculator"; st.rerun()

# Cost calculator
elif st.session_state.step == "calculator":
    st.header("Cost Planner")

    state = st.selectbox("Location", ["National", "Washington", "California", "Texas", "Florida"],
                         help="Adjusts for typical market rates in the selected state.")

    total = 0
    for p in st.session_state.get("people", []):
        pid = p["id"]; name = p["display_name"]
        rec = st.session_state.results.get(pid, {})
        rec_care = rec.get("care_type", "in_home")
        care_type = st.session_state.get("care_overrides", {}).get(pid, rec_care)

        st.subheader(f"{name} — Scenario: {care_type.replace('_',' ').title()} "
                     f"(recommended: {rec_care.replace('_',' ').title()})")

        # Mobility carryover
        mobility_prefill = "Independent"
        if ENABLE_MOBILITY_CARRYOVER:
            # rough mapping: if flag present, prefill Assisted / Non-ambulatory
            flags = rec.get("flags", set())
            if "high_mobility_dependence" in flags:
                mobility_prefill = "Non-ambulatory"
            elif "moderate_mobility" in flags:
                mobility_prefill = "Assisted"

        care_level_default = "High" if care_type == "memory_care" else "Medium"
        care_level = st.selectbox("Care Level (staffing intensity)", ["Low","Medium","High"],
                                  index=["Low","Medium","High"].index(care_level_default), key=f"{pid}_care_level")

        mobility_options = [
            "Independent (no device)",
            "Assisted (cane/walker or needs help)",
            "Non-ambulatory (wheelchair/bedbound)"
        ]
        prefill_label = {
            "Independent": "Independent (no device)",
            "Assisted": "Assisted (cane/walker or needs help)",
            "Non-ambulatory": "Non-ambulatory (wheelchair/bedbound)"
        }[mobility_prefill]
        mobility_label = st.selectbox("Mobility", mobility_options,
                                      index=mobility_options.index(prefill_label), key=f"{pid}_mobility")
        mobility = {"Independent (no device)":"Independent",
                    "Assisted (cane/walker or needs help)":"Assisted",
                    "Non-ambulatory (wheelchair/bedbound)":"Non-ambulatory"}[mobility_label]

        chronic_options = [
            "None (no ongoing conditions)",
            "Some (1–2 manageable conditions)",
            "Multiple/Complex (several or complex needs)"
        ]
        chronic_label = st.selectbox("Chronic Conditions", chronic_options,
                                     index=1, key=f"{pid}_chronic")
        chronic = {"None (no ongoing conditions)":"None",
                   "Some (1–2 manageable conditions)":"Some",
                   "Multiple/Complex (several or complex needs)":"Multiple/Complex"}[chronic_label]

        inp = make_inputs(state=state, care_type=care_type, care_level=care_level, mobility=mobility, chronic=chronic)

        if care_type in ["assisted_living", "memory_care"]:
            for k in [f"{pid}_hours", f"{pid}_days"]:
                if k in st.session_state:
                    del st.session_state[k]
            room = st.selectbox("Room Type", ["Studio","1 Bedroom","Shared"], key=f"{pid}_room")
            setattr(inp, "room_type", room)
        elif care_type == "none":
            st.caption("No care plan needed at this time.")
            st.session_state.setdefault("person_costs", {})[pid] = 0
            st.divider()
            continue
        else:
            # In-home sliders
            if f"{pid}_room" in st.session_state:
                del st.session_state[f"{pid}_room"]
            hours = st.slider("In-home care hours per day", 0, 24, 4, 1, key=f"{pid}_hours")
            days  = st.slider("Days of care per month", 0, 31, 20, 1, key=f"{pid}_days",
                              disabled=not ENABLE_INHOME_DAYS_PER_MONTH)
            setattr(inp, "in_home_hours_per_day", int(hours))
            setattr(inp, "in_home_days_per_month", int(days))

        # Compute
        try:
            monthly = calculator.monthly_cost(inp)
        except Exception:
            st.error("CalculatorEngine failed.")
            st.code(traceback.format_exc()); st.stop()

        metric_money("Estimated Monthly Cost", monthly)
        st.session_state.setdefault("person_costs", {})[pid] = int(monthly)
        st.divider()
        total += int(monthly)

    st.subheader("Combined Total")
    st.metric("Estimated Combined Monthly Cost", f"${total:,.0f}")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back to recommendations"):
            st.session_state.step = "recommendations"; st.rerun()
    with c2:
        if st.button("Add Household & Assets"):
            st.session_state.step = "household"; st.rerun()

# Household drawers
elif st.session_state.step == "household":
    people = st.session_state.get("people", [])
    names = [p["display_name"] for p in people]
    nameA = names[0] if names else "Person A"
    nameB = names[1] if len(names) > 1 else "Person B"

    st.header("Household & Budget")
    st.markdown("Add income, benefits, assets, and home choices to see affordability.")

    s = st.session_state

    def money(label, key, default=0):
        v = int(s.get(key, default) or 0)
        out = st.number_input(label, min_value=0, step=50, value=v, key=key)
        s[key] = int(out)
        return int(out)

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
            names_local = names or ["Person A"]
            nA = names_local[0]
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
                        st.warning("Based on these answers, VA pension may not apply. Check with a local VSO.")
                        result["detail"] = "Wizard: uncertain"

                return result

            col1, col2 = st.columns(2)
            with col1:
                a_res = va_block("a", nA)
            with col2:
                if len(names) > 1:
                    b_res = va_block("b", nB)
                else:
                    st.write(""); st.write("")
                    b_res = {"monthly": 0, "detail": "No VA pension"}

            lc1, lc2 = st.columns(2)
            with lc1:
                a_ltc = st.selectbox(f"Long-Term Care insurance — {nA}", ["No", "Yes"], key="a_ltc")
            with lc2:
                if len(names) > 1:
                    b_ltc = st.selectbox(f"Long-Term Care insurance — {nB}", ["No", "Yes"], key="b_ltc")
                else:
                    st.selectbox("Long-Term Care insurance — (n/a)", ["No"], key="b_ltc_disabled", disabled=True)
                    b_ltc = "No"

            a_va = int(a_res.get("monthly", 0))
            b_va = int(b_res.get("monthly", 0)) if len(names) > 1 else 0
            st.session_state["a_va_monthly"] = a_va
            st.session_state["b_va_monthly"] = b_va

            benefits_total = (a_va + (ltc_add if a_ltc == "Yes" else 0)) + (b_va + (ltc_add if b_ltc == "Yes" else 0))
            st.metric("Subtotal — Benefits (VA + LTC add-ons)", f"${benefits_total:,.0f}")

    # Home decision
    if ENABLE_HOME_DECISION:
        with st.expander("Home decision (keep, sell, HELOC, reverse)", expanded=False):
            choice = st.selectbox("Home plan", ["Keep", "Sell", "HELOC", "Reverse mortgage"], key="home_plan")
            if choice == "Keep":
                m1, m2, m3 = st.columns(3)
                with m1: ho = money("Monthly HOA", "home_hoa", 0)
                with m2: ut = money("Monthly utilities", "home_utils", 0)
                with m3: mt = money("Mortgage (monthly)", "home_mortgage", 0)
                st.session_state["home_monthly_total"] = ho + ut + mt
            elif choice == "Sell":
                v = money("Estimated sale price", "home_sale_price", 0)
                p = money("Principal payoff", "home_principal", 0)
                fee_pct = st.slider("Agent + closing fee %", 0, 12, 7, 1, key="home_fee_pct")
                fees = int(round(v * (fee_pct / 100.0)))
                net = max(0, v - p - fees)
                st.metric("Estimated net proceeds", f"${net:,}")
                st.checkbox("Apply net proceeds to assets summary", value=True, key="home_apply_to_assets")
                st.session_state["home_monthly_total"] = 0
                st.session_state["home_net_proceeds"] = net
            else:
                # HELOC / Reverse: treat as monthly cash-in or offset
                draw = money("Estimated monthly draw", "home_draw", 0)
                carry = money("Ongoing home carry (HOA + utilities + taxes)", "home_carry", 0)
                st.session_state["home_monthly_total"] = max(0, carry - draw)

    # Home modifications
    if ENABLE_HOME_MODS:
        with st.expander("Home modifications (one-time with optional amortization)", expanded=False):
            finish = st.selectbox("Finish level", ["Budget (−20%)","Standard","Custom (+40%)"], index=1, key="mods_finish")
            mult = {"Budget (−20%)": 0.8, "Standard": 1.0, "Custom (+40%)": 1.4}[finish]

            # catalog (keep simple but realistic)
            CAT = [
                ("Widen doorways", 1200),
                ("Ramp installation", 2500),
                ("Grab bars & rails", 600),
                ("Walk-in shower conversion", 6500),
                ("Stair lift", 4500),
                ("Bathroom remodel (accessibility)", 9000),
                ("Lighting & fall-prevention improvements", 1200),
            ]

            total_upfront = 0
            for label, base in CAT:
                row = st.columns([0.06, 0.64, 0.3])
                with row[0]:
                    chk = st.checkbox("", key=f"mod_{label}", value=False)
                with row[1]:
                    st.write(label)
                with row[2]:
                    qty = st.number_input("Qty", min_value=0, step=1, value=1, key=f"qty_{label}")
                if chk:
                    total_upfront += int(round(base * mult * qty))

            st.metric("Upfront est. (selected)", f"${total_upfront:,}")

            pay_mode = st.radio("How to account for this cost?", ["Amortize monthly","Pay upfront"], index=0, key="mods_pay_mode")
            if pay_mode == "Amortize monthly":
                months = st.slider("Amortization months", 6, 60, 24, 6, key="mods_months")
                monthly = int(math.ceil(total_upfront / max(1, months)))
                st.metric("Monthly cost (amortized)", f"${monthly:,}")
                st.session_state["mods_monthly_total"] = monthly
                st.session_state["mods_upfront_total"] = 0
            else:
                st.checkbox("Deduct upfront total from assets summary", value=True, key="mods_deduct_assets")
                st.session_state["mods_monthly_total"] = 0
                st.session_state["mods_upfront_total"] = total_upfront

    # Other recurring monthly costs
    if ENABLE_OTHER_MONTHLIES:
        with st.expander("Other recurring monthly costs", expanded=False):
            meds   = money("Medications", "oth_meds", 0)
            medic  = money("Medicare/health insurance", "oth_medic", 0)
            dental = money("Dental insurance", "oth_dental", 0)
            other  = money("Other recurring", "oth_other", 0)
            s["other_monthly_total"] = meds + medic + dental + other
            st.metric("Subtotal — Other recurring", f"${s['other_monthly_total']:,}")

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

# Breakdown
elif st.session_state.step == "breakdown":
    st.header("Detailed Breakdown")

    people = st.session_state.get("people", [])
    costs  = st.session_state.get("person_costs", {})
    nameA = people[0]["display_name"] if people else "Person A"
    nameB = people[1]["display_name"] if len(people) > 1 else "Person B"

    care_A = int(costs.get("A", 0))
    care_B = int(costs.get("B", 0)) if len(people) > 1 else 0
    care_total = care_A + care_B

    s = st.session_state
    inc_A = int(s.get("a_ss", 0)) + int(s.get("a_pn", 0)) + int(s.get("a_other", 0))
    inc_B = int(s.get("b_ss", 0)) + int(s.get("b_pn", 0)) + int(s.get("b_other", 0)) if len(people) > 1 else 0
    inc_house = int(s.get("hh_rent", 0)) + int(s.get("hh_annuity", 0)) + int(s.get("hh_invest", 0)) + int(s.get("hh_trust", 0)) + int(s.get("hh_other", 0))
    va_A = int(s.get("a_va_monthly", 0))
    va_B = int(s.get("b_va_monthly", 0)) if len(people) > 1 else 0

    home_monthly = int(s.get("home_monthly_total", 0))
    mods_monthly = int(s.get("mods_monthly_total", 0))
    other_monthly= int(s.get("other_monthly_total", 0))
    addl_costs   = home_monthly + mods_monthly + other_monthly

    # Assets math (simple): add home net proceeds; subtract upfront mods if toggled
    assets_common  = int(s.get("assets_common_total", 0))
    assets_detail  = int(s.get("assets_detailed_total", 0))
    assets_total   = assets_common + assets_detail
    net_proceeds   = int(s.get("home_net_proceeds", 0)) if s.get("home_apply_to_assets") else 0
    upfront_mods   = int(s.get("mods_upfront_total", 0)) if s.get("mods_deduct_assets") else 0
    assets_total   = max(0, assets_total + net_proceeds - upfront_mods)

    income_total = inc_A + inc_B + inc_house + va_A + va_B
    monthly_need = care_total + addl_costs
    gap = monthly_need - income_total

    c1, c2, c3 = st.columns(3)
    c1.metric("Monthly Care + Selected Costs", f"${monthly_need:,.0f}")
    c2.metric("Total Monthly Income (incl. VA)", f"${income_total:,.0f}")
    c3.metric("Estimated Monthly Gap", f"${gap:,.0f}")

    years = 0.0
    if gap > 0 and assets_total > 0:
        years = round(assets_total / max(gap, 1), 1)
    st.subheader(f"Estimated runway from assets: {years} years")

    st.markdown("### Per-person care costs")
    if len(people) > 1:
        cA, cB = st.columns(2)
        with cA: st.write(f"**{nameA}**: ${care_A:,.0f}/mo")
        with cB: st.write(f"**{nameB}**: ${care_B:,.0f}/mo")
    elif people:
        st.write(f"**{nameA}**: ${care_A:,.0f}/mo")

    st.markdown("### Income breakdown")
    st.write({
        "Individual A": inc_A,
        "Individual B": inc_B,
        "Household": inc_house,
        "VA benefits": va_A + va_B,
    })

    st.markdown("### Additional monthly costs")
    st.write({
        "Home (carry/taxes/etc.)": home_monthly,
        "Home mods (amortized)": mods_monthly,
        "Other recurring": other_monthly,
    })

    st.markdown("### Assets summary")
    st.write({
        "Common assets": assets_common,
        "Detailed assets": assets_detail,
        "Home net proceeds applied": net_proceeds,
        "Upfront mods deducted": upfront_mods,
        "Total assets": assets_total,
    })

    if ENABLE_CHARTS and HAVE_ALTAIR:
        try:
            import pandas as pd
            inc_df = pd.DataFrame([
                {"Category": "Indiv A", "Amount": inc_A},
                {"Category": "Indiv B", "Amount": inc_B},
                {"Category": "Household", "Amount": inc_house},
                {"Category": "VA", "Amount": va_A + va_B},
            ])
            cost_df = pd.DataFrame([
                {"Category": "Care", "Amount": care_total},
                {"Category": "Other", "Amount": addl_costs},
            ])
            colA, colB = st.columns(2)
            with colA:
                st.caption("Income composition")
                st.altair_chart(
                    alt.Chart(inc_df).mark_arc(innerRadius=60).encode(theta="Amount", color="Category", tooltip=["Category","Amount"]),
                    use_container_width=True
                )
            with colB:
                st.caption("Costs composition")
                st.altair_chart(
                    alt.Chart(cost_df).mark_arc(innerRadius=60).encode(theta="Amount", color="Category", tooltip=["Category","Amount"]),
                    use_container_width=True
                )
        except Exception:
            st.info("Charts unavailable. Showing numeric breakdown above.")

    st.divider()
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Back to Household"):
            st.session_state.step = "household"; st.rerun()
    with b2:
        if st.button("Back to Costs"):
            st.session_state.step = "calculator"; st.rerun()