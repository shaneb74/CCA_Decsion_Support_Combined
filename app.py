# app.py — Senior Navigator (Planner → Recommendation → Costs → Household → Breakdown)
# Complete production-style build with robust state handling and fallbacks.

from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
import traceback
import math

import streamlit as st

# ==================== PAGE CONFIG ====================
st.set_page_config(page_title="Senior Navigator • Planner + Cost", page_icon="🧭", layout="centered")


# ==================== OPTIONAL DEPS ====================
try:
    import altair as alt  # optional, used on Breakdown
    HAVE_ALTAIR = True
except Exception:
    HAVE_ALTAIR = False


# ==================== FILE PATHS (ROOT) ====================
ROOT = Path(__file__).resolve().parent
QA_PATH  = ROOT / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = ROOT / "recommendation_logic_FINAL_MASTER_UPDATED.json"


# ==================== ENGINES ====================
try:
    from engines import PlannerEngine, CalculatorEngine
except Exception:
    st.error("Failed to import engines.py")
    st.code(traceback.format_exc())
    st.stop()

# Verify JSON files exist
missing = [p for p in (QA_PATH, REC_PATH) if not p.exists()]
if missing:
    st.error("Missing required JSON files:\n" + "\n".join(f"• {m}" for m in missing))
    st.stop()

# Instantiate engines
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


# ==================== HELPERS ====================
def reset_all():
    for k in list(st.session_state.keys()):
        if not k.startswith("_"):
            del st.session_state[k]
    st.session_state.step = "intro"


def fmt_money(x: float | int) -> str:
    try:
        return f"${int(x):,}"
    except Exception:
        return "$0"


def make_inputs(**kwargs):
    """Create a lightweight object the calculator can read."""
    obj = SimpleNamespace()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj


def clamp(v, lo, hi):
    try:
        return max(lo, min(hi, v))
    except Exception:
        return lo


# ---- Safe answer-map helpers (prevents KeyError on non-1..N keys) ----------
def order_answer_map(amap):
    """Return (ordered_keys, ordered_labels) safely whether keys are '1','2',... or arbitrary strings."""
    if not isinstance(amap, dict) or not amap:
        return [], []
    keys = list(amap.keys())

    def _is_intlike(x):
        try:
            int(str(x))
            return True
        except Exception:
            return False

    if all(_is_intlike(k) for k in keys):
        ordered_keys = [str(k) for k in sorted(int(str(k)) for k in keys)]
    else:
        ordered_keys = [str(k) for k in sorted(map(str, keys))]
    ordered_labels = [amap[k] for k in ordered_keys]
    return ordered_keys, ordered_labels


def radio_from_answer_map(label, amap, *, key, help_text=None, default_key=None):
    """Render a radio from a JSON answer map and return the *selected key* (string)."""
    ordered_keys, ordered_labels = order_answer_map(amap)
    if not ordered_labels:
        return default_key
    if default_key is not None and str(default_key) in ordered_keys:
        idx = ordered_keys.index(str(default_key))
    else:
        idx = 0
    sel_label = st.radio(label, options=ordered_labels, index=idx, key=key, help=help_text)
    return ordered_keys[ordered_labels.index(sel_label)]


def money(label, key, default=0, *, step=50, min_value=0, help_text=None):
    """Safe money input that doesn't mutate st.session_state programmatically."""
    try:
        v0 = int(st.session_state.get(key, default) or default)
    except Exception:
        v0 = default
    v = st.number_input(label, min_value=min_value, step=step, value=v0, key=key, help=help_text)
    try:
        return int(v)
    except Exception:
        return 0


def pretty_care(ct: str) -> str:
    m = {
        "in_home": "In-home Care",
        "assisted_living": "Assisted Living",
        "memory_care": "Memory Care",
        "none": "No care needed",
        None: "In-home Care",
    }
    return m.get(ct, ct.replace("_", " ").title() if ct else "In-home Care")


def narrative_from_result(rec: dict) -> str | None:
    """Prefer advisory/message/narrative fields in order."""
    return (
        rec.get("advisory")
        or rec.get("message")
        or rec.get("narrative")
        or rec.get("message_rendered")
        or rec.get("message_template")
    )


# ==================== SESSION INIT ====================
if "step" not in st.session_state:
    st.session_state.step = "intro"

st.sidebar.title("Senior Navigator")
st.sidebar.caption("Planner → Costs → Budget → Breakdown")
st.sidebar.button("Start over", on_click=reset_all)


# ==================== UI FLOW ====================

# ---------- Intro ----------
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
    if st.button("Start"):
        st.session_state.step = "audience"; st.rerun()


# ---------- Audience ----------
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
        single = False
    else:
        default = "Alex" if role != "My parent" else "Mom"
        n = st.text_input("Name", value=default, key="p_name", placeholder="Name")
        map_rel = {"Myself": "self", "My spouse/partner": "spouse", "My parent": "parent", "Someone else": "other"}
        people = [{"id": "A", "display_name": n, "relationship": map_rel.get(role, "other")}]
        single = True

    st.caption("Next, we’ll ask short care questions for each person.")
    if st.button("Continue"):
        st.session_state.people = people
        st.session_state.current_person = 0
        st.session_state.answers = {}
        st.session_state.planner_results = {}
        st.session_state.care_overrides = {}
        st.session_state.person_costs = {}
        st.session_state.step = "partner_context" if single else "planner"
        st.rerun()


# ---------- Partner interstitial ----------
elif st.session_state.step == "partner_context":
    people = st.session_state.get("people", [])
    single = len(people) == 1
    primary = people[0]["display_name"] if people else "Person A"

    st.header("Before we begin")
    st.markdown(
        f"If **{primary}** needs to leave the home for assisted living or memory care, "
        "their spouse/partner may also need some in-home help. "
        "You can include a simple support plan for them now so the household picture is complete."
    )

    add = False
    if single:
        add = st.checkbox("Yes, I want to evaluate a plan for a spouse/partner",
                          value=False, key="care_partner_add")
        if add:
            st.text_input("Spouse/partner name", value="",
                          placeholder="Enter spouse/partner name", key="care_partner_name")

    c1, c2 = st.columns(2)
    with c1:
        if st.button(f"No, let's just plan for **{primary}**"):
            st.session_state.step = "planner"; st.rerun()
    with c2:
        btn_disabled = not st.session_state.get("care_partner_add", False)
        if st.button("Add spouse/partner and continue", disabled=btn_disabled):
            if single and st.session_state.get("care_partner_add"):
                st.session_state.people.append({
                    "id": "B",
                    "display_name": st.session_state.get("care_partner_name") or "Spouse/Partner",
                    "relationship": "spouse"
                })
            st.session_state.step = "planner"; st.rerun()


# ---------- Planner (Q&A one-at-a-time) ----------
elif st.session_state.step == "planner":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if not people:
        reset_all(); st.rerun()

    person = people[i]
    pid    = person["id"]
    name   = person["display_name"]

    st.header(f"Care Plan — {name}")

    qa = planner.qa or {}
    questions = qa.get("questions", [])
    total_q = len(questions)

    idx_key = f"qidx_{pid}"
    if idx_key not in st.session_state:
        st.session_state[idx_key] = 0
    idx = clamp(st.session_state[idx_key], 0, max(0, total_q - 1))
    st.session_state[idx_key] = idx

    answers = st.session_state.answers.get(pid, {})

    st.caption(f"Question {idx+1} of {total_q}")
    st.progress((idx + 1) / max(1, total_q))

    # Render single question
    if total_q > 0:
        q = questions[idx]
        amap = q.get("answers", {})
        label = q.get("question", f"Question {idx+1}")
        sel_key = radio_from_answer_map(label, amap, key=f"{pid}_q{idx+1}", help_text=q.get("help"))
        # store int if possible
        try:
            answers[f"q{idx+1}"] = int(sel_key)
        except Exception:
            answers[f"q{idx+1}"] = sel_key
        st.session_state.answers[pid] = answers

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Back", disabled=(idx == 0)):
            st.session_state[idx_key] = max(0, idx - 1)
            st.rerun()
    with c2:
        if st.button("Next", disabled=(idx >= total_q - 1)):
            st.session_state[idx_key] = min(total_q - 1, idx + 1)
            st.rerun()
    with c3:
        if st.button("Finish", disabled=(idx < total_q - 1)):
            try:
                res = planner.run(answers)  # IMPORTANT: no 'name=' kwarg
            except Exception:
                st.error("PlannerEngine.run failed.")
                st.code(traceback.format_exc())
                st.stop()

            # normalize
            if hasattr(res, "__dict__"):
                care_type = getattr(res, "care_type", None)
                flags     = getattr(res, "flags", None) or []
                scores    = getattr(res, "scores", None) or {}
                reasons   = getattr(res, "reasons", None) or []
                narrative = (
                    getattr(res, "narrative", None) or
                    getattr(res, "advisory", None) or
                    getattr(res, "message", None)
                )
            else:
                care_type = res.get("care_type")
                flags     = res.get("flags", [])
                scores    = res.get("scores", {})
                reasons   = res.get("reasons", [])
                narrative = res.get("narrative") or res.get("advisory") or res.get("message")

            st.session_state.planner_results[pid] = {
                "care_type": care_type or "in_home",
                "flags": set(flags),
                "scores": scores,
                "reasons": reasons,
                "advisory": narrative or "",
            }

            # Next person or recommendations
            st.session_state[f"qidx_{pid}"] = 0
            if i + 1 < len(people):
                st.session_state.current_person = i + 1
                st.session_state.next_person_name = people[i+1]["display_name"]
                st.session_state.step = "person_transition"
            else:
                st.session_state.step = "recommendations"
            st.rerun()


# ---------- Interstitial between people ----------
elif st.session_state.step == "person_transition":
    next_name = st.session_state.get("next_person_name", "the next person")
    st.header("Great — that completes the first set of questions.")
    st.markdown(f"Now let’s assess **{next_name}**’s care plan.")
    if st.button(f"Start {next_name}'s questions"):
        st.session_state.step = "planner"; st.rerun()


# ---------- Recommendations ----------
elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without redoing questions.")

    for p in st.session_state.get("people", []):
        pid  = p["id"]
        name = p["display_name"]
        rec  = st.session_state.planner_results.get(pid, {}) or {}

        care_type = rec.get("care_type", "in_home")
        header_ct = pretty_care(care_type)

        st.subheader(f"{name}: {header_ct} (recommended)")

        # Bulleted reasons (if any)
        for r in rec.get("reasons", []):
            st.write("• " + str(r))

        # Narrative
        narrative = narrative_from_result(rec)
        if narrative:
            # Inject name politely if template had {name}
            try:
                narrative = narrative.replace("{name}", name)
            except Exception:
                pass
            st.info(narrative)

        # Override
        choices = [("none", "No care needed"), ("in_home", "In-home Care"),
                   ("assisted_living", "Assisted Living"), ("memory_care", "Memory Care")]
        labels = [lbl for _k, lbl in choices]
        keys   = [key for key, _lbl in choices]
        try_idx = keys.index(care_type) if care_type in keys else 1
        sel_lbl = st.selectbox(f"Care scenario for {name}", labels, index=try_idx, key=f"override_{pid}",
                               help="Compare a different scenario without repeating questions.")
        st.session_state.care_overrides[pid] = keys[labels.index(sel_lbl)]

        with st.expander(f"Show details for {name}", expanded=False):
            # make JSON-like dict for viewing
            view = {
                "care_type": rec.get("care_type"),
                "flags": list(rec.get("flags", [])),
                "scores": rec.get("scores", {}),
                "reasons": rec.get("reasons", []),
                "narrative": narrative or "",
            }
            st.json(view)

        st.divider()

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back to questions"):
            # jump to first person
            st.session_state.current_person = 0
            st.session_state.step = "planner"; st.rerun()
    with c2:
        if st.button("See Costs"):
            st.session_state.step = "calculator"; st.rerun()


# ---------- Cost Planner ----------
elif st.session_state.step == "calculator":
    st.header("Cost Planner")

    # state factor (if your calculator uses it)
    state = st.selectbox("Location", ["National", "Washington", "California", "Texas", "Florida"],
                         help="Adjusts for typical market rates in the selected state.")

    total = 0
    for p in st.session_state.get("people", []):
        pid  = p["id"]
        name = p["display_name"]
        rec  = st.session_state.planner_results.get(pid, {}) or {}
        care_type = st.session_state.get("care_overrides", {}).get(pid, rec.get("care_type", "in_home"))

        st.subheader(f"{name} — Scenario: {pretty_care(care_type)} "
                     f"(recommended: {pretty_care(rec.get('care_type', 'in_home'))})")

        # Mobility carryover from planner answers (simple heuristic: look for a 'mobility' question)
        mobility_prefill = "Independent"
        # Look through saved answers (if the planner marked mobility index)
        # Fallback mapping: 1=Independent, 2/3=Assisted, 4=Non-ambulatory
        ans = st.session_state.answers.get(pid, {})
        # Try to find mobility via text in QA
        qa = planner.qa or {}
        mob_idx = None
        for idx, q in enumerate(qa.get("questions", []), start=1):
            if "mobility" in q.get("question", "").lower():
                mob_idx = idx
                break
        if mob_idx is not None:
            raw = ans.get(f"q{mob_idx}")
            try:
                raw = int(raw)
            except Exception:
                raw = None
            if raw in (2, 3):
                mobility_prefill = "Assisted"
            elif raw == 4:
                mobility_prefill = "Non-ambulatory"

        care_level_default = "High" if (("severe_cognitive_decline" in rec.get("flags", set())) or (care_type == "memory_care")) else "Medium"
        care_level = st.selectbox("Care Level (staffing intensity)", ["Low", "Medium", "High"],
                                  index=["Low", "Medium", "High"].index(care_level_default),
                                  key=f"{pid}_care_level")

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
                                      index=mobility_options.index(prefill_label),
                                      key=f"{pid}_mobility")
        mobility = {
            mobility_options[0]: "Independent",
            mobility_options[1]: "Assisted",
            mobility_options[2]: "Non-ambulatory"
        }[mobility_label]

        chronic_options = [
            "None (no ongoing conditions)",
            "Some (1–2 manageable conditions)",
            "Multiple/Complex (several or complex needs)"
        ]
        default_chronic_label = chronic_options[2] if "severe_cognitive_decline" in rec.get("flags", set()) else chronic_options[1]
        chronic_label = st.selectbox("Chronic Conditions", chronic_options,
                                     index=chronic_options.index(default_chronic_label),
                                     key=f"{pid}_chronic")
        chronic = {
            chronic_options[0]: "None",
            chronic_options[1]: "Some",
            chronic_options[2]: "Multiple/Complex"
        }[chronic_label]

        # Build inputs
        inp = make_inputs(state=state, care_type=care_type, care_level=care_level,
                          mobility=mobility, chronic=chronic)

        if care_type in ["assisted_living", "memory_care"]:
            # clear in-home fields if present
            for k in [f"{pid}_hours", f"{pid}_days"]:
                if k in st.session_state: del st.session_state[k]
            room = st.selectbox("Room Type", ["Studio", "1 Bedroom", "Shared"], key=f"{pid}_room")
            setattr(inp, "room_type", room)
        else:
            if f"{pid}_room" in st.session_state: del st.session_state[f"{pid}_room"]
            hours = st.slider("In-home care hours per day", 0, 24, 4, 1, key=f"{pid}_hours")
            days  = st.slider("Days of care per month", 0, 31, 20, 1, key=f"{pid}_days")
            setattr(inp, "in_home_hours_per_day", int(hours))
            setattr(inp, "in_home_days_per_month", int(days))

        # Compute
        try:
            if hasattr(calculator, "monthly_cost"):
                monthly = calculator.monthly_cost(inp)
            elif hasattr(calculator, "estimate"):
                monthly = calculator.estimate(getattr(inp, "care_type", "in_home"))
            else:
                monthly = 0
        except Exception:
            st.error("CalculatorEngine failed while computing monthly cost.")
            st.code(traceback.format_exc())
            monthly = 0

        st.metric("Estimated Monthly Cost", fmt_money(monthly))
        st.session_state.setdefault("person_costs", {})[pid] = int(monthly)
        total += int(monthly)
        st.divider()

    st.subheader("Combined Total")
    st.metric("Estimated Combined Monthly Cost", fmt_money(total))

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back to recommendations"):
            st.session_state.step = "recommendations"; st.rerun()
    with c2:
        if st.button("Add Household & Assets"):
            st.session_state.step = "household"; st.rerun()


# ---------- Household & Budget ----------
elif st.session_state.step == "household":
    people = st.session_state.get("people", [])
    names = [p["display_name"] for p in people]
    nameA = names[0] if names else "Person A"
    nameB = names[1] if len(names) > 1 else "Person B"

    st.header("Household & Budget (optional)")
    st.markdown("Add income, benefits, home decisions, assets, and other costs to see affordability.")

    # ---- Monthly Income — Individual
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
        st.metric("Subtotal — Individual income", fmt_money((a1+a2+a3)+(b1+b2+b3)))

    # ---- Monthly Income — Household (shared)
    with st.expander("Monthly Income — Household (shared)", expanded=False):
        r   = money("Rental income", "hh_rent", 0)
        an  = money("Annuity income", "hh_annuity", 0)
        inv = money("Dividends/interest (joint)", "hh_invest", 0)
        tr  = money("Trust distributions", "hh_trust", 0)
        oth = money("Other household income", "hh_other", 0)
        st.metric("Subtotal — Household income", fmt_money(r+an+inv+tr+oth))

    # ---- VA / LTC wizard
    with st.expander("Benefits (VA, Long-Term Care insurance)", expanded=True):
        names_local = [p["display_name"] for p in people]
        nA = names_local[0] if names_local else "Person A"
        nB = names_local[1] if len(names_local) > 1 else "Person B"

        # default schedules if missing on calculator
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

        def va_block(prefix: str, person_name: str) -> dict:
            st.write(f"**{person_name}**")
            choice = st.radio(
                f"Choose an option for {person_name}:",
                ["Not a veteran / No VA pension",
                 "I already receive or qualify for VA pension/Aid & Attendance",
                 "I served, but I’m not sure if I qualify"],
                index=0, key=f"{prefix}_va_path",
            )

            result = {"monthly": 0, "detail": "No VA pension"}

            if choice.startswith("I already receive"):
                tier = st.selectbox("Select status", list(va_mapr.keys()), key=f"{prefix}_va_tier",
                                    help="Monthly caps from VA MAPR. Enter your actual payment if you know it.")
                cap = int(va_mapr[tier])
                st.caption(f"Estimated monthly cap for this tier: {fmt_money(cap)}.")
                amt = st.number_input("Monthly VA payment (enter actual if known; otherwise use cap)",
                                      min_value=0, step=25, value=cap, key=f"{prefix}_va_actual")
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
        st.metric("Subtotal — Benefits (VA + LTC add-ons)", fmt_money(benefits_total))

    # ---- Home decision
    with st.expander("Home decision (keep, sell, HELOC, reverse mortgage)", expanded=True):
        decision = st.selectbox("What do you plan to do with the home?",
                                ["Keep", "Sell", "HELOC", "Reverse mortgage"],
                                help="Pick the path you’re evaluating.")
        apply_proceeds = st.checkbox("Apply net proceeds to assets summary", value=True, key="apply_proceeds_assets")

        if decision == "Keep":
            c1, c2, c3 = st.columns(3)
            with c1: mort = money("Monthly mortgage/HELOC payment", "home_mort", 0)
            with c2: tax  = money("Monthly property taxes", "home_tax", 0)
            with c3: ins  = money("Monthly homeowners insurance", "home_ins", 0)
            c4, c5 = st.columns(2)
            with c4: hoa  = money("Monthly HOA/maintenance", "home_hoa", 0)
            with c5: util = money("Monthly utilities (avg.)", "home_util", 0)
            home_monthly = mort + tax + ins + hoa + util
            st.session_state["home_monthly_total"] = home_monthly
            st.metric("Subtotal — Home monthly costs", fmt_money(home_monthly))

        elif decision == "Sell":
            c1, c2, c3 = st.columns(3)
            with c1: sale = money("Estimated sale price", "home_sale_price", 0, step=1000)
            with c2: pay  = money("Principal payoff at sale", "home_payoff", 0, step=1000)
            with c3:
                fee = st.slider("Typical fees (realtor/closing) — percent", 4.0, 8.0, 6.0, 0.25, key="home_fee_pct")
                st.caption(f"You chose {fee:.2f}%")
            fees_amt = int(round(sale * (fee / 100.0)))
            net_proceeds = max(0, sale - pay - fees_amt)
            st.session_state["home_sale_net_proceeds"] = net_proceeds if st.session_state.get("apply_proceeds_assets") else 0
            st.metric("Estimated net proceeds", fmt_money(net_proceeds))
            st.session_state["home_monthly_total"] = 0
            st.metric("Subtotal — Home monthly costs", fmt_money(0))

        elif decision == "HELOC":
            c1, c2, c3 = st.columns(3)
            with c1: heloc = money("Monthly HELOC payment", "home_heloc", 0)
            with c2: tax   = money("Monthly property taxes", "home_tax", 0)
            with c3: ins   = money("Monthly homeowners insurance", "home_ins", 0)
            c4, c5 = st.columns(2)
            with c4: hoa   = money("Monthly HOA/maintenance", "home_hoa", 0)
            with c5: util  = money("Monthly utilities (avg.)", "home_util", 0)
            home_monthly = heloc + tax + ins + hoa + util
            st.session_state["home_monthly_total"] = home_monthly
            st.metric("Subtotal — Home monthly costs", fmt_money(home_monthly))

        else:  # Reverse mortgage — keep simple
            c1, c2 = st.columns(2)
            with c1: tax = money("Monthly property taxes", "home_tax", 0)
            with c2: ins = money("Monthly homeowners insurance", "home_ins", 0)
            c3, c4 = st.columns(2)
            with c3: hoa = money("Monthly HOA/maintenance", "home_hoa", 0)
            with c4: util = money("Monthly utilities (avg.)", "home_util", 0)
            home_monthly = tax + ins + hoa + util
            st.session_state["home_monthly_total"] = home_monthly
            st.metric("Subtotal — Home monthly costs", fmt_money(home_monthly))

    # ---- Home modifications
    with st.expander("Home modifications (grab bars, ramps, bath, etc.)", expanded=False):
        pay_method = st.radio("Payment method", ["Amortize monthly", "Pay upfront (one-time)"],
                              index=0, key="mods_pay_method",
                              help="Choose whether to spread the cost over months or pay upfront.")
        finish = st.selectbox("Finish level", ["Budget", "Standard", "Custom"], index=1,
                              help="Budget ≈ 0.8×, Standard = 1.0×, Custom ≈ 1.35×")
        mult = {"Budget": 0.8, "Standard": 1.0, "Custom": 1.35}[finish]

        items = [
            ("mods_grab",        "Grab bars & railings (avg $800)",              800),
            ("mods_door",        "Widen doorways (avg $2,500)",                  2500),
            ("mods_shower",      "Bathroom walk-in shower conversion (avg $12,000)", 12000),
            ("mods_ramp",        "Ramp installation (avg $3,500)",               3500),
            ("mods_stair",       "Stair lift (avg $4,500)",                      4500),
            ("mods_sensors",     "Smart home monitoring/sensors (avg $1,200)",   1200),
            ("mods_lighting",    "Lighting & fall-risk improvements (avg $1,500)", 1500),
        ]

        total_cost = 0
        colL, colR = st.columns(2)
        for idx, (key, label, base) in enumerate(items):
            target = colL if idx % 2 == 0 else colR
            with target:
                checked = st.checkbox(label, key=f"{key}_chk", value=False)
                if checked:
                    qty = st.number_input("Qty", min_value=1, step=1, value=1, key=f"{key}_qty")
                    total_cost += int(base * mult * int(qty))

        if pay_method == "Amortize monthly":
            months = st.slider("Amortize over (months)", 6, 60, 12, 1, key="mods_months")
            monthly = int(round(total_cost / max(1, months)))
            st.session_state["mods_monthly_total"] = monthly
            st.session_state["mods_upfront_total"] = 0
            st.metric("Subtotal — Home mods (amortized monthly)", fmt_money(monthly))
        else:
            st.session_state["mods_monthly_total"] = 0
            st.session_state["mods_upfront_total"] = total_cost
            deduct = st.checkbox("Deduct upfront cost from assets summary", value=True, key="mods_deduct_assets")
            st.metric("Upfront cost — Home mods", fmt_money(total_cost))

    # ---- Other monthly costs
    with st.expander("Other monthly costs (meds, insurance, misc.)", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        with c1: meds   = money("Medications", "oth_meds", 0)
        with c2: med    = money("Medicare/health insurance", "oth_med", 0)
        with c3: dental = money("Dental insurance", "oth_dent", 0)
        with c4: other  = money("Other recurring", "oth_other", 0)
        other_monthly = meds + med + dental + other
        st.session_state["other_monthly_total"] = other_monthly
        st.metric("Subtotal — Other monthly costs", fmt_money(other_monthly))

    # ---- Assets — Common
    with st.expander("Assets — Common", expanded=False):
        cols = st.columns(3)
        with cols[0]: checking = money("Checking", "as_checking", 0, step=500)
        with cols[1]: savings  = money("Savings", "as_savings", 0, step=500)
        with cols[2]: brokerage= money("Brokerage (taxable)", "as_brokerage", 0, step=500)
        cols = st.columns(3)
        with cols[0]: cds      = money("CDs / Money Market", "as_cds", 0, step=500)
        with cols[1]: retire   = money("Retirement (IRA/401k)", "as_retire", 0, step=500)
        with cols[2]: hsa      = money("HSA", "as_hsa", 0, step=500)
        assets_common = checking + savings + brokerage + cds + retire + hsa
        st.session_state["assets_common_total"] = assets_common
        st.metric("Subtotal — Common assets", fmt_money(assets_common))

    # ---- Assets — Detailed
    with st.expander("Assets — Detailed", expanded=False):
        cols = st.columns(3)
        with cols[0]: annuities = money("Annuities (current value)", "as_ann", 0, step=500)
        with cols[1]: vehicles  = money("Vehicles (equity)", "as_veh", 0, step=500)
        with cols[2]: other     = money("Other assets", "as_other_assets", 0, step=500)
        assets_detailed = annuities + vehicles + other
        st.session_state["assets_detailed_total"] = assets_detailed
        st.metric("Subtotal — Detailed assets", fmt_money(assets_detailed))

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Back to Costs"):
            st.session_state.step = "calculator"; st.rerun()
    with c2:
        if st.button("View Detailed Breakdown"):
            st.session_state.step = "breakdown"; st.rerun()
    with c3:
        if st.button("Finish"):
            st.session_state.step = "intro"; st.rerun()


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

    # Home & other monthly costs
    home_monthly   = int(s.get("home_monthly_total", 0))
    mods_monthly   = int(s.get("mods_monthly_total", 0))
    other_monthly  = int(s.get("other_monthly_total", 0))
    addl_costs     = home_monthly + mods_monthly + other_monthly

    # Assets
    assets_common  = int(s.get("assets_common_total", 0))
    assets_detail  = int(s.get("assets_detailed_total", 0))
    sale_proceeds  = int(s.get("home_sale_net_proceeds", 0))
    mods_upfront   = int(s.get("mods_upfront_total", 0))
    deduct_upfront = bool(s.get("mods_deduct_assets", False))
    assets_total   = assets_common + assets_detail + sale_proceeds - (mods_upfront if deduct_upfront else 0)

    # Totals
    income_total = inc_A + inc_B + inc_house + va_A + va_B
    monthly_need = care_total + addl_costs
    gap = monthly_need - income_total

    c1, c2, c3 = st.columns(3)
    c1.metric("Monthly Care + Selected Costs", fmt_money(monthly_need))
    c2.metric("Total Monthly Income (incl. VA)", fmt_money(income_total))
    c3.metric("Estimated Monthly Gap", fmt_money(gap))

    years = 0.0
    if gap > 0 and assets_total > 0:
        years = round(assets_total / max(gap, 1), 1)
    st.subheader(f"Estimated runway from assets: {years} years")

    st.markdown("### Per-person care costs")
    if people:
        if len(people) > 1:
            cA, cB = st.columns(2)
            with cA: st.write(f"**{nameA}**: {fmt_money(care_A)}/mo")
            with cB: st.write(f"**{nameB}**: {fmt_money(care_B)}/mo")
        else:
            st.write(f"**{nameA}**: {fmt_money(care_A)}/mo")

    st.markdown("### Income breakdown")
    st.write({
        "Individual A": inc_A,
        "Individual B": inc_B,
        "Household": inc_house,
        "VA benefits": va_A + va_B,
    })

    st.markdown("### Additional monthly costs")
    st.write({
        "Home (mortgage/tax/ins/HOA/util)": home_monthly,
        "Home modifications (amortized)": mods_monthly,
        "Other recurring": other_monthly,
    })

    st.markdown("### Assets summary")
    st.write({
        "Common assets": assets_common,
        "Detailed assets": assets_detail,
        "Home sale net proceeds (applied)": sale_proceeds,
        "Mods upfront (deducted)": (mods_upfront if deduct_upfront else 0),
        "Total assets": assets_total,
    })

    # Optional Altair donuts
    try:
        if HAVE_ALTAIR:
            import pandas as pd
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
                    alt.Chart(inc_df).mark_arc(innerRadius=60).encode(
                        theta="Amount", color="Category", tooltip=["Category", "Amount"]
                    ),
                    use_container_width=True
                )
            with colB:
                st.caption("Costs composition")
                st.altair_chart(
                    alt.Chart(cost_df).mark_arc(innerRadius=60).encode(
                        theta="Amount", color="Category", tooltip=["Category", "Amount"]
                    ),
                    use_container_width=True
                )
    except Exception:
        pass

    st.divider()
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Back to Household"):
            st.session_state.step = "household"; st.rerun()
    with b2:
        if st.button("Back to Costs"):
            st.session_state.step = "calculator"; st.rerun()