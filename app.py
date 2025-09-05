# app.py — Senior Navigator (Planner → Recommendation → Costs → Household → Breakdown)
# Production build: parity features, mobile-friendly, robust thresholds, VA wizard, home mods, assets.
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import re
import traceback

import streamlit as st

# ---------------- Page config & light CSS ----------------
st.set_page_config(page_title="Senior Navigator • Planner + Costs", page_icon="🧭", layout="centered")

# mobile readability + button/layout polish
st.markdown(
    """
    <style>
      /* Larger radios/labels for mobile */
      .stRadio label, .stSelectbox label, .stNumberInput label, .stSlider label { font-size: 1.0rem; }
      .stMarkdown p, .stMarkdown li { font-size: 1.0rem; }
      /* Make primary/secondary actions look horizontal on wide, stack on small */
      .btn-row { display:flex; gap:0.75rem; flex-wrap: wrap; }
      @media (min-width: 800px) {
        .btn-row { justify-content:flex-end; }
      }
      .btn-row > div { flex: 1 0 200px; }
      /* Tighten expander header weight slightly */
      summary { font-weight:600 !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------- Feature flags ----------------
ENABLE_PARTNER_INTERSTITIAL = True
ENABLE_TWO_PERSON_HANDOFF = True
ENABLE_REC_OVERRIDE = True
ENABLE_INHOME_DAYS_PER_MONTH = True
ENABLE_MOBILITY_CARRYOVER = True
ENABLE_HOME_DECISION = True
ENABLE_HOME_MODS = True
ENABLE_VA_WIZARD = True
ENABLE_ASSETS_COMMON = True
ENABLE_ASSETS_DETAILED = True
ENABLE_OTHER_MONTHLY = True
ENABLE_DETAILS_PAGE = True
ENABLE_CHARTS = False  # keep False unless Altair is available in your environment

# optional charts dep
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

# ---------------- Helpers ----------------
def make_inputs(**kwargs):
    try:
        return SimpleNamespace(**kwargs)
    except Exception:
        obj = SimpleNamespace()
        for k, v in kwargs.items():
            setattr(obj, k, v)
        return obj

def scroll_top():
    st.markdown("<script>window.scrollTo({top: 0, behavior: 'instant'});</script>", unsafe_allow_html=True)

def money(label, key, default=0):
    v0 = int(st.session_state.get(key, default) or 0)
    v = st.number_input(label, min_value=0, step=50, value=v0, key=key)
    try:
        st.session_state[key] = int(v)
        return int(v)
    except Exception:
        return 0

def _intish(x, fallback=0) -> int:
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return int(x)
    if isinstance(x, str):
        m = re.search(r"-?\d+", x)
        if m:
            try:
                return int(m.group(0))
            except Exception:
                pass
    return int(fallback)

def reset_all():
    for k in list(st.session_state.keys()):
        if not k.startswith("_"):
            del st.session_state[k]
    st.session_state.step = "intro"

# ---------------- Session init ----------------
if "step" not in st.session_state:
    st.session_state.step = "intro"

st.sidebar.title("Senior Navigator")
st.sidebar.caption("Planner → Costs → Budget → Breakdown")
st.sidebar.button("Start over", on_click=reset_all)

# =============================================================================
#                                   STEPS
# =============================================================================

# ---------------- Intro ----------------
if st.session_state.step == "intro":
    st.title("Let’s take this one step at a time")
    st.markdown(
        """
This can be stressful. These tools were built from real-world concierge senior-living work and thousands of placements.
We’ll keep it simple and supportive.

**What you’ll do**
1. Answer short care questions → we recommend a care type.  
2. See costs for that scenario (you can switch scenarios).  
3. Optionally add income, benefits, assets and home details.  
4. Get a clear breakdown you can save or revisit.
        """
    )
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
            n1 = st.text_input("Parent 1 name", value="", placeholder="Mom", key="p1_name")
            st.selectbox("Parent 1 age", ["65–74", "75–84", "85+"], key="p1_age")
        with c2:
            n2 = st.text_input("Parent 2 name", value="", placeholder="Dad", key="p2_name")
            st.selectbox("Parent 2 age", ["65–74", "75–84", "85+"], key="p2_age")
        people = [
            {"id": "A", "display_name": n1.strip() or "Mom", "relationship": "parent"},
            {"id": "B", "display_name": n2.strip() or "Dad", "relationship": "parent"},
        ]
    else:
        placeholder = "Alex" if role != "My parent" else "Mom"
        n = st.text_input("Name", value="", placeholder=placeholder, key="p_name")
        st.selectbox("Approximate age", ["65–74", "75–84", "85+"], key="p_age")
        map_rel = {"Myself": "self", "My spouse/partner": "spouse", "My parent": "parent", "Someone else": "other"}
        people = [{"id": "A", "display_name": n.strip() or placeholder, "relationship": map_rel.get(role, "other")}]

    # educational interstitial about partner impact
    if ENABLE_PARTNER_INTERSTITIAL:
        st.divider()
        st.markdown(
            """
If a spouse/partner will remain at home, they may also need some help (in-home hours or safety updates).
We’ll show an option for them as you go so the household picture makes sense.
            """
        )

    if st.button("Continue"):
        st.session_state.people = people
        st.session_state.current_person = 0
        st.session_state.answers = {}
        st.session_state.planner_results = {}
        st.session_state.mobility_raw = {}
        st.session_state.care_overrides = {}
        st.session_state.person_costs = {}
        st.session_state.step = "planner"
        scroll_top()
        st.rerun()

# ---------------- Planner (Q-by-Q wizard; show all toggle) ----------------
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
    total_qs = len(qa.get("questions", []))

    # desktop reviewers: show-all toggle
    show_all = st.toggle("Show all questions (desktop reviewers)", value=False, help="For quick review only.")

    # keep progress and answers in state
    key_prefix = f"{person['id']}_"
    answers = st.session_state.answers.get(person["id"], {})
    st.session_state.setdefault(f"{key_prefix}idx", 0)
    cur_idx = st.session_state[f"{key_prefix}idx"]

    def render_one(qi: int):
        q = qa["questions"][qi]
        opts_map = q.get("answers", {})
        ordered_keys = [str(n) for n in sorted(map(int, opts_map.keys()))]
        prev = answers.get(f"q{qi+1}")
        label = f"{q.get('question', f'Question {qi+1}')} (for {name})"
        sel_label = st.radio(
            label,
            options=[opts_map[k] for k in ordered_keys],
            index=(ordered_keys.index(str(prev)) if prev in ordered_keys else 0),
            key=f"{key_prefix}q{qi+1}",
            help=q.get("help"),
        )
        sel_key = ordered_keys[[opts_map[k] for k in ordered_keys].index(sel_label)]
        answers[f"q{qi+1}"] = int(sel_key)

    # show all or one-at-a-time with progress
    if show_all:
        for qi in range(total_qs):
            render_one(qi)
    else:
        st.progress((cur_idx + 1) / max(total_qs, 1), f"Question {cur_idx+1} of {total_qs}")
        render_one(cur_idx)

        # navigation
        nav = st.container()
        with nav:
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Back", disabled=(cur_idx == 0)):
                    st.session_state[f"{key_prefix}idx"] = max(0, cur_idx - 1)
                    st.rerun()
            with c2:
                if st.button("Next", disabled=(cur_idx >= total_qs - 1)):
                    st.session_state[f"{key_prefix}idx"] = min(total_qs - 1, cur_idx + 1)
                    st.rerun()

    # conditional Q9 (only when severe cognitive trigger applies)
    conditional_answer = None
    cond_cfg = qa.get("conditional_questions") or []
    if cond_cfg:
        cq = cond_cfg[0]
        # generic dependency support
        show_conditional = False
        depends = cq.get("depends_on")
        if depends and isinstance(depends, dict):
            qn = depends.get("question_index")
            expected = set(str(x) for x in depends.get("answer_keys", []))
            if isinstance(qn, int) and qn >= 1:
                got = str(answers.get(f"q{qn}", ""))
                if got in expected:
                    show_conditional = True
        # specific fallback for your dataset: show only if “severe cognitive issues” option chosen earlier
        if not show_conditional:
            # heuristics: if any answer text mentions "severe cognitive" or "significant memory"
            for k, v in qa.get("questions", [{}])[0].get("answers", {}).items():
                pass  # generic fallback disabled
        if show_conditional:
            label = cq.get("question", "Additional question")
            amap = cq.get("answers", {"1": "Yes", "2": "No"})
            ordered_ckeys = [str(n) for n in sorted(map(int, amap.keys()))]
            sel = st.radio(label, options=[amap[k] for k in ordered_ckeys], key=f"{key_prefix}cond")
            for k, v in amap.items():
                if v == sel:
                    conditional_answer = k
                    break

    st.session_state.answers[person["id"]] = answers

    # finish area — generates recommendation and moves to next person or handoff
    fin = st.container()
    with fin:
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Back to start"):
                st.session_state.step = "audience"
                scroll_top()
                st.rerun()
        with c2:
            if st.button("Finish"):
                try:
                    res = planner.run(answers, conditional_answer=conditional_answer)
                except Exception:
                    st.error("PlannerEngine.run failed.")
                    st.code(traceback.format_exc())
                    st.stop()

                care_type = getattr(res, "care_type", None) or res.get("care_type") or "in_home"
                flags = set(getattr(res, "flags", None) or res.get("flags", []))
                scores = getattr(res, "scores", None) or res.get("scores", {})
                reasons = getattr(res, "reasons", None) or res.get("reasons", [])
                advisory = getattr(res, "advisory", None) or res.get("advisory")

                st.session_state.planner_results[person["id"]] = {
                    "care_type": care_type,
                    "flags": list(flags),
                    "scores": scores,
                    "reasons": reasons,
                    "advisory": advisory,
                }

                # carry over mobility raw selection for calculator defaults
                # try to locate mobility question index by name
                mob_idx = None
                for idx, q in enumerate(qa.get("questions", []), start=1):
                    if "mobility" in q.get("question", "").lower():
                        mob_idx = idx
                        break
                if mob_idx:
                    st.session_state.mobility_raw[person["id"]] = answers.get(f"q{mob_idx}")

                # two-person handoff screen
                if ENABLE_TWO_PERSON_HANDOFF and (st.session_state.get("current_person", 0) + 1) < len(people):
                    st.session_state.step = "handoff"
                    st.session_state["__handoff_from__"] = name
                    st.session_state["current_person"] += 1
                    scroll_top()
                    st.rerun()
                else:
                    st.session_state.step = "recommendations"
                    scroll_top()
                    st.rerun()

# ---------------- Handoff (only when 2nd person exists) ----------------
elif st.session_state.step == "handoff":
    prev_name = st.session_state.get("__handoff_from__", "Person 1")
    i = st.session_state.get("current_person", 1)
    next_name = (st.session_state.get("people") or [{}])[i].get("display_name", "Person 2")
    st.success(f"Great — we finished questions for **{prev_name}**.")
    st.header(f"Now let’s assess **{next_name}**.")
    st.caption("You’ll see the same short questions, focused on their needs.")
    if st.button("Continue"):
        st.session_state.step = "planner"
        scroll_top()
        st.rerun()

# ---------------- Recommendations + override ----------------
elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without re-doing questions.")

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
                help="Compare a different scenario without repeating the questions.",
            )
            reverse = {v: k for k, v in labels.items()}
            st.session_state.care_overrides[p['id']] = reverse[label_sel]

        st.divider()

    # two buttons only — keep breakdown for final stage
    actions = st.container()
    with actions:
        st.markdown('<div class="btn-row">', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Back to Care Plan"):
                st.session_state.step = "planner"
                st.rerun()
        with c2:
            if st.button("See Costs"):
                st.session_state.step = "calculator"
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

# ---------------- Calculator ----------------
elif st.session_state.step == "calculator":
    st.header("Cost Planner")

    state = st.selectbox(
        "Location",
        ["National", "Washington", "California", "Texas", "Florida"],
        help="Adjusts for typical market rates in the selected state.",
    )

    total = 0
    for p in st.session_state.people:
        pid = p["id"]
        name = p["display_name"]
        rec = st.session_state.planner_results.get(pid, {})
        care_type = st.session_state.get("care_overrides", {}).get(pid, rec.get("care_type", "in_home"))

        st.subheader(
            f"{name} — Scenario: {care_type.replace('_', ' ').title()} "
            f"(recommended: {rec.get('care_type', 'in_home').replace('_', ' ').title()})"
        )

        # Mobility carryover
        mobility_prefill = "Independent"
        if ENABLE_MOBILITY_CARRYOVER:
            raw_mob = st.session_state.get("mobility_raw", {}).get(pid)
            # map numeric answers 2/3→Assisted; 4→Non-ambulatory by your earlier mapping
            if raw_mob in (2, 3):
                mobility_prefill = "Assisted"
            if raw_mob == 4:
                mobility_prefill = "Non-ambulatory"

        care_level_default = "High" if ("severe_cognitive_decline" in set(rec.get("flags", []))
                                        or care_type == "memory_care") else "Medium"
        care_level = st.selectbox(
            "Care Level (staffing intensity)", ["Low", "Medium", "High"],
            index=["Low", "Medium", "High"].index(care_level_default),
            key=f"{pid}_care_level"
        )

        mobility_options = [
            "Independent (no device)",
            "Assisted (cane/walker or needs help)",
            "Non-ambulatory (wheelchair/bedbound)",
        ]
        mobility_map_out = {
            "Independent (no device)": "Independent",
            "Assisted (cane/walker or needs help)": "Assisted",
            "Non-ambulatory (wheelchair/bedbound)": "Non-ambulatory",
        }
        prefill_label = {
            "Independent": "Independent (no device)",
            "Assisted": "Assisted (cane/walker or needs help)",
            "Non-ambulatory": "Non-ambulatory (wheelchair/bedbound)",
        }[mobility_prefill]
        mobility_label = st.selectbox(
            "Mobility",
            mobility_options,
            index=mobility_options.index(prefill_label),
            key=f"{pid}_mobility"
        )
        mobility = mobility_map_out[mobility_label]

        chronic_options = [
            "None (no ongoing conditions)",
            "Some (1–2 manageable conditions)",
            "Multiple/Complex (several or complex needs)",
        ]
        chronic_map_out = {
            chronic_options[0]: "None",
            chronic_options[1]: "Some",
            chronic_options[2]: "Multiple/Complex",
        }
        default_chronic_label = chronic_options[2] if "severe_cognitive_decline" in set(rec.get("flags", [])) else chronic_options[1]
        chronic_label = st.selectbox(
            "Chronic Conditions",
            chronic_options,
            index=chronic_options.index(default_chronic_label),
            key=f"{pid}_chronic"
        )
        chronic = chronic_map_out[chronic_label]

        inp = make_inputs(state=state, care_type=care_type, care_level=care_level, mobility=mobility, chronic=chronic)

        if care_type in ["assisted_living", "memory_care"]:
            for k in [f"{pid}_hours", f"{pid}_days"]:
                if k in st.session_state:
                    del st.session_state[k]
            room = st.selectbox("Room Type", ["Studio", "1 Bedroom", "Shared"], key=f"{pid}_room")
            setattr(inp, "room_type", room)
        else:
            if f"{pid}_room" in st.session_state:
                del st.session_state[f"{pid}_room"]
            hours = st.slider("In-home care hours per day", 0, 24, 4, 1, key=f"{pid}_hours")
            days = st.slider(
                "Days of care per month",
                0, 31, 20, 1, key=f"{pid}_days",
                disabled=not ENABLE_INHOME_DAYS_PER_MONTH
            )
            setattr(inp, "in_home_hours_per_day", int(hours))
            setattr(inp, "in_home_days_per_month", int(days))

            # friendly nudge to consider home mods if staying home
            st.info("Since this scenario is in-home care, consider safety updates in the **Home modifications** section below.")

        # Compute monthly cost
        try:
            monthly = calculator.monthly_cost(inp)
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

    st.markdown('<div class="btn-row">', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back to Recommendations"):
            st.session_state.step = "recommendations"
            scroll_top()
            st.rerun()
    with c2:
        if st.button("Add Household & Assets"):
            st.session_state.step = "household"
            scroll_top()
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

# ---------------- Household (income, benefits, home decision, mods, assets) ----------------
elif st.session_state.step == "household":
    people = st.session_state.get("people", [])
    names = [p["display_name"] for p in people]
    nameA = names[0] if names else "Person A"
    nameB = names[1] if len(names) > 1 else "Person B"

    st.header("Household & Budget")
    st.markdown("Add income, benefits, home details and assets to see affordability. You can skip sections you don’t need.")

    # Monthly Income — Individual
    with st.expander("Monthly Income — Individual", expanded=False):
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

    # Home decision (keep / sell / HELOC / reverse)
    if ENABLE_HOME_DECISION:
        with st.expander("Home decision (keep, sell, HELOC, reverse mortgage)", expanded=False):
            plan = st.selectbox(
                "What do you plan to do with the home?",
                ["Keep", "Sell", "HELOC", "Reverse mortgage"],
            )
            apply_proceeds = st.checkbox("Apply net proceeds to assets summary", value=True, key="home_apply_assets")

            monthly_carry = 0
            upfront_delta = 0  # positive adds to assets, negative reduces

            if plan == "Keep":
                m = money("Monthly mortgage/HELOC payment", "home_keep_mort", 0)
                t = money("Monthly property taxes", "home_keep_taxes", 0)
                ins = money("Monthly homeowners insurance", "home_keep_ins", 0)
                hoa = money("Monthly HOA/maintenance", "home_keep_hoa", 0)
                util = money("Monthly utilities", "home_keep_utils", 0)
                monthly_carry = m + t + ins + hoa + util

            elif plan == "Sell":
                sale = money("Estimated sale price", "home_sell_price", 500_000)
                payoff = money("Principal payoff at sale", "home_sell_payoff", 120_000)
                fee_pct = st.slider("Typical fees (realtor/closing) %", 6.0, 8.0, 6.0, 0.5, key="home_sell_fee_pct")
                fees = int(round(sale * (fee_pct / 100.0)))
                net = max(0, sale - payoff - fees)
                st.caption(f"Estimated net proceeds: **${net:,.0f}**")
                upfront_delta = net  # added to assets

            elif plan == "HELOC":
                draw = money("Monthly HELOC payment", "home_heloc_pay", 0)
                t = money("Monthly property taxes", "home_heloc_taxes", 0)
                ins = money("Monthly homeowners insurance", "home_heloc_ins", 0)
                hoa = money("Monthly HOA/maintenance", "home_heloc_hoa", 0)
                util = money("Monthly utilities", "home_heloc_utils", 0)
                monthly_carry = draw + t + ins + hoa + util

            elif plan == "Reverse mortgage":
                t = money("Monthly property taxes", "home_rev_taxes", 0)
                ins = money("Monthly homeowners insurance", "home_rev_ins", 0)
                hoa = money("Monthly HOA/maintenance", "home_rev_hoa", 0)
                util = money("Monthly utilities", "home_rev_utils", 0)
                stipend = money("Monthly reverse mortgage stipend (if any)", "home_rev_stipend", 0)
                monthly_carry = max(0, (t + ins + hoa + util) - stipend)

            st.metric("Subtotal — Home monthly costs", f"${monthly_carry:,.0f}")
            st.session_state["home_monthly_total"] = monthly_carry

            if plan == "Sell" and apply_proceeds:
                # store for assets summary
                st.session_state["home_upfront_delta"] = int(upfront_delta)
            else:
                st.session_state["home_upfront_delta"] = 0

    # Home modifications
    if ENABLE_HOME_MODS:
        with st.expander("Home modifications (grab bars, ramps, bath, etc.)", expanded=False):
            st.caption("Select applicable projects. Costs are averages; finish level scales totals.")

            # finish level first
            finish = st.selectbox("Finish level", ["Budget", "Standard", "Premium"], index=1)
            mult = {"Budget": 0.85, "Standard": 1.0, "Premium": 1.25}[finish]

            # projects (avg costs)
            projects = [
                ("Grab bars & railings", 800, "mods_grab"),
                ("Widen doorways", 2500, "mods_door"),
                ("Bathroom walk-in shower conversion", 12000, "mods_shower"),
                ("Ramp installation", 3500, "mods_ramp"),
                ("Stair lift", 4500, "mods_stair"),
                ("Smart home monitoring/sensors", 1200, "mods_sensors"),
                ("Lighting & fall-risk improvements", 1500, "mods_light"),
            ]

            # two columns with checkbox + qty input
            colL, colR = st.columns(2)
            running_cost = 0
            selected = {}
            for idx, (label, avg, key) in enumerate(projects):
                col = colL if idx % 2 == 0 else colR
                with col:
                    checked = st.checkbox(f"{label} (avg ${avg:,})", key=f"{key}_chk")
                    qty = st.number_input("Qty", min_value=1, step=1, value=1, key=f"{key}_qty", disabled=not checked)
                    if checked:
                        cost = int(avg * mult) * int(qty)
                        running_cost += cost
                        selected[key] = cost

            # payment method at bottom near totals
            pay = st.radio(
                "Payment method",
                ["Amortize monthly", "Pay upfront (one-time)"],
                horizontal=False,
                index=0,
                key="mods_pay_method"
            )

            monthly_impact = 0
            upfront_cost = running_cost
            if pay.startswith("Amortize"):
                months = st.slider("Amortize over (months)", 6, 60, 12, 1, key="mods_months")
                monthly_impact = int(round(upfront_cost / max(months, 1)))
                st.metric("Subtotal — Home mods (amortized monthly)", f"${monthly_impact:,}")
                st.session_state["mods_monthly_total"] = monthly_impact
                st.session_state["mods_upfront_delta"] = 0
            else:
                deduct = st.checkbox("Deduct upfront cost from assets summary", value=True, key="mods_deduct_assets")
                if deduct:
                    st.session_state["mods_upfront_delta"] = -int(upfront_cost)
                else:
                    st.session_state["mods_upfront_delta"] = 0
                st.metric("Upfront cost — Home mods", f"${upfront_cost:,}")
                st.caption("Monthly impact: $0 (paid upfront)")
                st.session_state["mods_monthly_total"] = 0

    # Benefits (VA + LTC)
    if ENABLE_VA_WIZARD:
        with st.expander("Benefits (VA, Long-Term Care insurance)", expanded=False):
            people_local = st.session_state.get("people", [])
            names_local = [p["display_name"] for p in people_local]
            nA = names_local[0] if names_local else "Person A"
            nB = names_local[1] if len(names_local) > 1 else "Person B"

            settings = getattr(calculator, "settings", {}) or {}
            settings.setdefault("va_mapr_2025", {
                "Veteran (no dependents) — A&A": 2358,
                "Veteran + 1 dependent — A&A": 2795,
                "Two veterans married, one A&A": 2795,
                "Surviving spouse — A&A": 1515,
                "Surviving spouse + 1 child — A&A": 1808,
            })
            settings.setdefault("ltc_monthly_add", 1800)
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

    # Assets (common)
    if ENABLE_ASSETS_COMMON:
        with st.expander("Assets — Common", expanded=False):
            cash = money("Checking/Savings", "as_cash", 0)
            cd = money("CDs / Money market", "as_cd", 0)
            inv = money("Brokerage (stocks/bonds/ETFs)", "as_brokerage", 0)
            ira = money("Retirement (IRA/401k)", "as_retire", 0)
            life = money("Cash-value life insurance", "as_life", 0)
            tot = cash + cd + inv + ira + life
            # include home deltas
            tot += int(st.session_state.get("home_upfront_delta", 0))
            tot += int(st.session_state.get("mods_upfront_delta", 0))
            st.metric("Subtotal — Common assets", f"${tot:,}")
            st.session_state["assets_common_total"] = tot

    # Assets (detailed)
    if ENABLE_ASSETS_DETAILED:
        with st.expander("Assets — Detailed (optional)", expanded=False):
            bus = money("Business interests", "as_bus", 0)
            real = money("Other real estate (not primary)", "as_real", 0)
            trust = money("Trust principal (accessible)", "as_trust_p", 0)
            other = money("Other assets", "as_other_assets", 0)
            dtot = bus + real + trust + other
            st.metric("Subtotal — Detailed assets", f"${dtot:,}")
            st.session_state["assets_detailed_total"] = dtot

    # Other Monthly Costs
    if ENABLE_OTHER_MONTHLY:
        with st.expander("Other Monthly Costs (meds, insurance, recurring)", expanded=False):
            meds   = money("Prescription medications", "omc_meds", 0)
            medic  = money("Medicare/health insurance premiums", "omc_medic", 0)
            dental = money("Dental insurance/premiums", "omc_dental", 0)
            supp   = money("Medical supplies/OTC", "omc_supplies", 0)
            trans  = money("Transportation/ride services", "omc_transport", 0)
            misc   = money("Other recurring costs", "omc_other", 0)
            subtotal = meds + medic + dental + supp + trans + misc
            st.metric("Subtotal — Other recurring monthly costs", f"${subtotal:,}")
            st.session_state["other_monthly_total"] = subtotal

    st.divider()
    st.markdown('<div class="btn-row">', unsafe_allow_html=True)
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Back to Costs"):
            st.session_state.step = "calculator"
            scroll_top()
            st.rerun()
    with b2:
        if ENABLE_DETAILS_PAGE and st.button("View Detailed Breakdown"):
            st.session_state.step = "breakdown"
            scroll_top()
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

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

    # Income — individual + household
    s = st.session_state
    inc_A = int(s.get("a_ss", 0)) + int(s.get("a_pn", 0)) + int(s.get("a_other", 0))
    inc_B = (int(s.get("b_ss", 0)) + int(s.get("b_pn", 0)) + int(s.get("b_other", 0))) if len(people) > 1 else 0
    inc_house = int(s.get("hh_rent", 0)) + int(s.get("hh_annuity", 0)) + int(s.get("hh_invest", 0)) + int(s.get("hh_trust", 0)) + int(s.get("hh_other", 0))

    # Benefits (from VA wizard)
    va_A = int(s.get("a_va_monthly", 0))
    va_B = int(s.get("b_va_monthly", 0)) if len(people) > 1 else 0

    # Other monthly costs
    home_monthly   = int(s.get("home_monthly_total", 0))
    mods_monthly   = int(s.get("mods_monthly_total", 0))
    other_monthly  = int(s.get("other_monthly_total", 0))
    addl_costs     = home_monthly + mods_monthly + other_monthly

    # Assets (sum common + detailed, including deltas already applied)
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

    # Composition (numeric + optional donuts)
    st.markdown("### Income breakdown")
    inc_dict = {
        "Individual A": inc_A,
        "Individual B": inc_B,
        "Household": inc_house,
        "VA benefits": va_A + va_B,
    }
    st.write(inc_dict)

    st.markdown("### Additional monthly costs")
    st.write({
        "Home (carry, taxes, insurance, etc.)": home_monthly,
        "Home modifications (amortized)": mods_monthly,
        "Other recurring": other_monthly,
    })

    st.markdown("### Assets summary")
    st.write({
        "Common assets": assets_common,
        "Detailed assets": assets_detail,
        "Total assets": assets_total,
    })

    try:
        if ENABLE_CHARTS and HAVE_ALTAIR:
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
    st.markdown('<div class="btn-row">', unsafe_allow_html=True)
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Back to Household"):
            st.session_state.step = "household"
            scroll_top()
            st.rerun()
    with b2:
        if st.button("Finish & Restart"):
            reset_all()
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)