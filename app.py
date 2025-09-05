# app.py — Senior Navigator (full app)
# Flow: Intro → Audience → Spouse interstitial → Q&A → Person transition (if 2) → Recommendations
#       → Calculator → Household & Budget → Breakdown
# Notes:
# - Uses safe radio helpers to avoid KeyError on non 1..N answer keys
# - Stores Q&A answers as INT when possible so JSON triggers match
# - Shows fully-rendered recommendation narrative (from PlannerEngine)
# - Restores drawers (VA/LTC wizard, Home decision, Home modifications, Other monthly costs, Assets)
# - In-home days/month slider affects cost via inputs sent to calculator

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import traceback
import streamlit as st

# ---------- Page config ----------
st.set_page_config(page_title="Senior Navigator • Planner + Cost", page_icon="🧭", layout="centered")

# ---------- Paths (root) ----------
ROOT = Path(__file__).resolve().parent
QA_PATH  = ROOT / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = ROOT / "recommendation_logic_FINAL_MASTER_UPDATED.json"

# ---------- Optional charts dependency ----------
try:
    import altair as alt  # for donuts on breakdown (optional)
    HAVE_ALTAIR = True
except Exception:
    HAVE_ALTAIR = False

# ---------- Engines ----------
try:
    from engines import PlannerEngine, CalculatorEngine
except Exception:
    st.error("Failed to import engines.py")
    st.code(traceback.format_exc())
    st.stop()

for p in (QA_PATH, REC_PATH):
    if not p.exists():
        st.error(f"Missing required JSON file: {p.name}")
        st.stop()

# Init engines
try:
    planner = PlannerEngine(str(QA_PATH), str(REC_PATH))
except Exception:
    st.error("PlannerEngine() failed to initialize.")
    st.code(traceback.format_exc()); st.stop()

try:
    calculator = CalculatorEngine()
except Exception:
    st.error("CalculatorEngine() failed to initialize.")
    st.code(traceback.format_exc()); st.stop()


# ---------- Helpers ----------
def make_inputs(**kwargs):
    """Create a simple inputs object engines.CalculatorEngine can read."""
    obj = SimpleNamespace()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj

def reset_all():
    for k in list(st.session_state.keys()):
        if not k.startswith("_"):
            del st.session_state[k]
    st.session_state.step = "intro"

# Safe ordering for answer maps (prevents KeyError)
def _order_answer_items(amap: dict) -> list[tuple[str, str]]:
    """
    Return list of (key, label) pairs in a stable order.
    Numeric keys sort numerically; otherwise preserve JSON insertion order.
    """
    if not isinstance(amap, dict):
        return []
    keys = list(amap.keys())
    try:
        keys_sorted = sorted(keys, key=lambda k: int(str(k)))
    except Exception:
        keys_sorted = keys  # keep insertion order
    return [(str(k), amap[k]) for k in keys_sorted]

def radio_from_answer_map(label: str, amap: dict, *, key: str, help_text: str | None = None,
                          default_key: str | None = None) -> str:
    items = _order_answer_items(amap)
    labels = [v for (_k, v) in items]
    keys   = [k for (k, _v) in items]
    if not labels:
        return default_key if default_key is not None else ""
    if default_key in keys:
        idx = keys.index(default_key)
    else:
        idx = 0
    choice = st.radio(label, labels, index=idx, key=key, help=help_text)
    sel_idx = labels.index(choice) if choice in labels else idx
    return keys[sel_idx]

# A light "money" helper: returns int value from a widget without forcing session_state
def money_input(label, key, default=0, step=50):
    v = st.number_input(label, min_value=0, step=step, value=int(st.session_state.get(key, default) or default), key=key)
    try:
        return int(v)
    except Exception:
        return 0


# ---------- Session init ----------
if "step" not in st.session_state:
    st.session_state.step = "intro"

st.sidebar.title("Senior Navigator")
st.sidebar.caption("Planner → Costs → Budget → Breakdown")
st.sidebar.button("Start over", on_click=reset_all)


# ===================== Steps =====================

# Intro
if st.session_state.step == "intro":
    st.title("Let’s take this one step at a time")
    st.markdown("""
Choosing senior living or in-home support can feel overwhelming.  
This tool breaks it into clear steps:

1. Answer quick care questions → we recommend a care type.  
2. Review costs for that scenario (you can switch it).  
3. Add income, benefits, and assets to see affordability.  
4. View a detailed breakdown you can save or revisit.
""")
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
        map_rel = {"Myself": "self", "My spouse/partner": "spouse", "My parent": "parent", "Someone else": "other"}
        people = [{"id": "A", "display_name": n, "relationship": map_rel.get(role, "other")}]

    st.caption("Next, we’ll ask short care questions for each person.")

    # Spouse / partner interstitial only if a single person is being planned
    primary = people[0]["display_name"] if people else "Person A"
    single = len(people) == 1

    if single:
        st.subheader("Before we begin")
        st.markdown(
            f"If **{primary}** needs to leave the home for assisted living or memory care, "
            "their spouse/partner may also need to consider some in-home help. "
            "You can include a simple support plan for them now so the household picture is complete."
        )
        add = st.checkbox("Yes, I want to evaluate a plan for a spouse/partner", value=False, key="care_partner_add")
        if add:
            st.text_input("Spouse/partner name", value="", placeholder="Enter spouse/partner name", key="care_partner_name")

        c1, c2 = st.columns(2)
        with c1:
            if st.button(f"No, let's just plan for **{primary}**"):
                st.session_state.people = people
                st.session_state.current_person = 0
                st.session_state.answers = {}
                st.session_state.planner_results = {}
                st.session_state.step = "planner"
                st.rerun()
        with c2:
            btn_disabled = not st.session_state.get("care_partner_add", False)
            if st.button("Add spouse/partner and continue", disabled=btn_disabled):
                people.append({
                    "id": "B",
                    "display_name": (st.session_state.get("care_partner_name") or "Spouse/Partner"),
                    "relationship": "spouse",
                })
                st.session_state.people = people
                st.session_state.current_person = 0
                st.session_state.answers = {}
                st.session_state.planner_results = {}
                st.session_state.step = "planner"
                st.rerun()
    else:
        if st.button("Continue"):
            st.session_state.people = people
            st.session_state.current_person = 0
            st.session_state.answers = {}
            st.session_state.planner_results = {}
            st.session_state.step = "planner"
            st.rerun()

# Planner (Q&A)
elif st.session_state.step == "planner":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if not people:
        reset_all(); st.rerun()
    person = people[i]
    name = person["display_name"]

    st.header(f"Care Plan Questions for {name}")
    qa = planner.qa or {}
    answers = st.session_state.answers.get(person["id"], {})

    for idx, q in enumerate(qa.get("questions", []), start=1):
        amap = q.get("answers", {})
        label = q.get("question", f"Question {idx}")
        sel_key = radio_from_answer_map(
            label, amap,
            key=f"{person['id']}_q{idx}",
            help_text=q.get("help")
        )
        # store INT if possible (critical for triggers)
        try:
            answers[f"q{idx}"] = int(sel_key)
        except Exception:
            answers[f"q{idx}"] = sel_key

    st.session_state.answers[person["id"]] = answers

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back"):
            if i == 0:
                st.session_state.step = "audience"
            else:
                st.session_state.current_person = i - 1
            st.rerun()
    with c2:
        if st.button("Finish"):
            try:
                res = planner.run(answers, name=name)
            except Exception:
                st.error("PlannerEngine.run failed.")
                st.code(traceback.format_exc()); st.stop()

            st.session_state.planner_results[person["id"]] = {
                "care_type": res.care_type,
                "flags": res.flags,
                "scores": res.scores,
                "reasons": res.reasons,
                "advisory": res.narrative,  # rendered narrative
                "raw_rule": getattr(res, "raw_rule", None),
            }

            # Interstitial if another person remains
            if i + 1 < len(people):
                st.session_state.next_person_name = people[i+1]["display_name"]
                st.session_state.current_person = i + 1
                st.session_state.step = "person_transition"
                st.rerun()
            else:
                st.session_state.step = "recommendations"
                st.rerun()

# Interstitial between persons
elif st.session_state.step == "person_transition":
    next_name = st.session_state.get("next_person_name", "the next person")
    st.header("Great — that completes the first set of questions.")
    st.markdown(f"Now let’s assess **{next_name}**’s care plan.")
    if st.button(f"Start {next_name}'s questions"):
        st.session_state.step = "planner"
        st.rerun()

# Recommendations
elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without redoing questions.")

    for p in st.session_state.people:
        name = p["display_name"]
        rec  = st.session_state.planner_results.get(p["id"], {})
        default = rec.get("care_type", "in_home")

        st.subheader(f"{name}: {default.replace('_', ' ').title()} (recommended)")

        # bullets (optional)
        for r in rec.get("reasons", []):
            st.write("• " + str(r))

        # Show rendered narrative (advisory) if present
        narrative = rec.get("advisory") or rec.get("message") or rec.get("narrative")
        if narrative:
            st.info(narrative)

        # Allow override; keep values
        labels = {
            "none": "No care needed",
            "in_home": "In-home Care",
            "assisted_living": "Assisted Living",
            "memory_care": "Memory Care",
        }
        keys_order = ["none", "in_home", "assisted_living", "memory_care"]
        idx = keys_order.index(default) if default in keys_order else 0
        sel_label = st.selectbox(
            f"Care scenario for {name}",
            [labels[k] for k in keys_order],
            index=idx,
            key=f"override_{p['id']}",
        )
        reverse = {v: k for k, v in labels.items()}
        chosen = reverse[sel_label]
        st.session_state.planner_results[p["id"]]["care_type"] = chosen

        st.divider()

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back to questions"):
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
        pid = p["id"]; name = p["display_name"]
        rec = st.session_state.planner_results.get(pid, {})
        care_type = rec.get("care_type", "in_home")

        st.subheader(f"{name} — Scenario: {care_type.replace('_',' ').title()}")

        # Simple inputs that CalculatorEngine may use
        care_level = st.selectbox("Care Level (staffing intensity)", ["Low", "Medium", "High"], key=f"{pid}_care_level")

        mobility_options = [
            "Independent (no device)",
            "Assisted (cane/walker or needs help)",
            "Non-ambulatory (wheelchair/bedbound)"
        ]
        mobility_label = st.selectbox("Mobility", mobility_options, key=f"{pid}_mobility")
        mobility_map_out = {
            "Independent (no device)": "Independent",
            "Assisted (cane/walker or needs help)": "Assisted",
            "Non-ambulatory (wheelchair/bedbound)": "Non-ambulatory"
        }
        mobility = mobility_map_out[mobility_label]

        chronic_options = [
            "None (no ongoing conditions)",
            "Some (1–2 manageable conditions)",
            "Multiple/Complex (several or complex needs)"
        ]
        chronic_label = st.selectbox("Chronic Conditions", chronic_options, key=f"{pid}_chronic")
        chronic_map_out = {
            chronic_options[0]: "None",
            chronic_options[1]: "Some",
            chronic_options[2]: "Multiple/Complex"
        }
        chronic = chronic_map_out[chronic_label]

        inp = make_inputs(state=state, care_type=care_type, care_level=care_level, mobility=mobility, chronic=chronic)

        if care_type in ["assisted_living", "memory_care"]:
            room = st.selectbox("Room Type", ["Studio", "1 Bedroom", "Shared"], key=f"{pid}_room")
            setattr(inp, "room_type", room)
        else:
            # In-home sliders (both affect cost)
            hours = st.slider("In-home care hours per day", 0, 24, 4, 1, key=f"{pid}_hours")
            days  = st.slider("Days of care per month", 0, 31, 20, 1, key=f"{pid}_days")
            setattr(inp, "in_home_hours_per_day", int(hours))
            setattr(inp, "in_home_days_per_month", int(days))

        try:
            monthly = calculator.monthly_cost(inp)
        except Exception:
            st.error("CalculatorEngine failed while computing monthly cost.")
            st.code(traceback.format_exc())
            monthly = 0

        st.metric("Estimated Monthly Cost", f"${int(monthly):,}")
        st.session_state.setdefault("person_costs", {})[pid] = int(monthly)
        total += int(monthly)

        st.divider()

    st.subheader("Combined Total")
    st.session_state.combined_monthly_cost = total
    st.metric("Estimated Combined Monthly Cost", f"${total:,.0f}")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Back to recommendations"):
            st.session_state.step = "recommendations"
            st.rerun()
    with c2:
        if st.button("Add Household & Budget"):
            st.session_state.step = "household"
            st.rerun()
    with c3:
        if st.button("View Detailed Breakdown"):
            st.session_state.step = "breakdown"
            st.rerun()

# Household & Budget
elif st.session_state.step == "household":
    people = st.session_state.get("people", [])
    names = [p["display_name"] for p in people]
    nameA = names[0] if names else "Person A"
    nameB = names[1] if len(names) > 1 else "Person B"

    st.header("Household & Budget")
    st.markdown("Add income, benefits, assets, and housing choices to see affordability.")

    # Monthly Income — Individual
    with st.expander("Monthly Income — Individual", expanded=True):
        if len(people) > 1:
            a_ss, a_pn, a_oth = st.columns(3)
            with a_ss: a1 = money_input(f"Social Security — {nameA}", "a_ss", 0)
            with a_pn: a2 = money_input(f"Pension — {nameA}", "a_pn", 0)
            with a_oth: a3 = money_input(f"Other — {nameA}", "a_other", 0)

            b_ss, b_pn, b_oth = st.columns(3)
            with b_ss: b1 = money_input(f"Social Security — {nameB}", "b_ss", 0)
            with b_pn: b2 = money_input(f"Pension — {nameB}", "b_pn", 0)
            with b_oth: b3 = money_input(f"Other — {nameB}", "b_other", 0)
        else:
            a1 = money_input(f"Social Security — {nameA}", "a_ss", 0)
            a2 = money_input(f"Pension — {nameA}", "a_pn", 0)
            a3 = money_input(f"Other — {nameA}", "a_other", 0)
            b1 = b2 = b3 = 0
        individual_income = (a1+a2+a3) + (b1+b2+b3)
        st.metric("Subtotal — Individual income", f"${individual_income:,}")

    # Monthly Income — Household (shared)
    with st.expander("Monthly Income — Household (shared)", expanded=False):
        r   = money_input("Rental income", "hh_rent", 0)
        an  = money_input("Annuity income", "hh_annuity", 0)
        inv = money_input("Dividends/interest (joint)", "hh_invest", 0)
        tr  = money_input("Trust distributions", "hh_trust", 0)
        oth = money_input("Other household income", "hh_other", 0)
        household_income = r + an + inv + tr + oth
        st.metric("Subtotal — Household income", f"${household_income:,}")

    # Benefits (VA / LTC)
    with st.expander("Benefits (VA, Long-Term Care insurance)", expanded=True):
        # Simple VA MAPR caps for selection (adjust as needed)
        va_mapr = {
            "Veteran (no dependents) — A&A": 2358,
            "Veteran + 1 dependent — A&A": 2795,
            "Two veterans married, one A&A": 2795,
            "Surviving spouse — A&A": 1515,
            "Surviving spouse + 1 child — A&A": 1808,
        }
        def va_block(prefix: str, person_name: str):
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
                amt = st.number_input("Monthly VA payment (enter actual if known; otherwise use cap)",
                                      min_value=0, step=25, value=cap, key=f"{prefix}_va_actual")
                result = {"monthly": int(amt), "detail": tier}
            elif choice.startswith("I served"):
                st.info("Quick check (not exhaustive):")
                st.checkbox("Served during a wartime period", key=f"{prefix}_wartime")
                st.checkbox("65+ or permanently and totally disabled", key=f"{prefix}_age_dis")
                st.checkbox("Discharge not dishonorable", key=f"{prefix}_discharge")
                st.checkbox("Needs help with daily activities or housebound", key=f"{prefix}_need_aa")
                st.checkbox("Net worth under VA limit", key=f"{prefix}_networth")
                result["detail"] = "Wizard: eligibility uncertain"
            return result

        col1, col2 = st.columns(2)
        with col1:
            a_res = va_block("a", nameA)
        with col2:
            if len(people) > 1:
                b_res = va_block("b", nameB)
            else:
                b_res = {"monthly": 0, "detail": "No VA pension"}

        lc1, lc2 = st.columns(2)
        with lc1:
            a_ltc = st.selectbox(f"Long-Term Care insurance — {nameA}", ["No", "Yes"], key="a_ltc")
        with lc2:
            if len(people) > 1:
                b_ltc = st.selectbox(f"Long-Term Care insurance — {nameB}", ["No", "Yes"], key="b_ltc")
            else:
                st.selectbox("Long-Term Care insurance — (n/a)", ["No"], key="b_ltc_disabled", disabled=True)
                b_ltc = "No"

        # Store benefits to session (monthly)
        a_va = int(a_res.get("monthly", 0))
        b_va = int(b_res.get("monthly", 0)) if len(people) > 1 else 0
        st.session_state["a_va_monthly"] = a_va
        st.session_state["b_va_monthly"] = b_va
        ltc_add = 1800  # crude add for LTC policy, adjust as needed
        benefits_total = (a_va + (ltc_add if a_ltc == "Yes" else 0)) + (b_va + (ltc_add if b_ltc == "Yes" else 0))
        st.metric("Subtotal — Benefits (VA + LTC add-ons)", f"${benefits_total:,.0f}")

    # Home decision
    with st.expander("Home decision (keep, sell, HELOC, reverse mortgage)", expanded=True):
        choice = st.selectbox("What do you plan to do with the home?", ["Keep", "Sell", "HELOC", "Reverse mortgage"])
        st.checkbox("Apply net proceeds to assets summary", key="apply_proceeds_assets", value=True)

        if choice == "Keep":
            m = money_input("Monthly mortgage/HELOC payment", "keep_mortgage", 0)
            t = money_input("Monthly property taxes", "keep_taxes", 0)
            i = money_input("Monthly homeowners insurance", "keep_ins", 0)
            hoa = money_input("Monthly HOA/maintenance", "keep_hoa", 0)
            util = money_input("Monthly utilities (avg.)", "keep_util", 0)
            home_monthly = m + t + i + hoa + util
            st.metric("Subtotal — Home monthly costs", f"${home_monthly:,}")
            st.session_state["home_monthly_total"] = int(home_monthly)

        elif choice == "Sell":
            sale = money_input("Estimated sale price", "sell_price", 500000, step=1000)
            payoff = money_input("Principal payoff at sale", "sell_payoff", 120000, step=1000)
            fee = st.slider("Typical fees (realtor/closing) — %", 0.0, 10.0, 4.5, 0.25, key="sell_fee_pct")
            net = max(0, int(round(sale - payoff - (sale * (fee / 100.0)))))
            st.caption(f"Estimated net proceeds: ${net:,}")
            st.session_state["home_monthly_total"] = 0
            st.session_state["home_net_proceeds"] = net

        else:  # HELOC / Reverse mortgage (simple placeholders)
            pmt = money_input("Monthly payment / draw impact", "heloc_rev_pmt", 0)
            st.metric("Subtotal — Home monthly costs", f"${pmt:,}")
            st.session_state["home_monthly_total"] = int(pmt)

    # Home modifications
    with st.expander("Home modifications (grab bars, ramps, bath, etc.)", expanded=True):
        # Finish level impacts cost
        finish_multiplier = {
            "Budget": 0.8,
            "Standard": 1.0,
            "Custom": 1.3
        }
        finish = st.selectbox("Finish level", ["Standard", "Budget", "Custom"])
        mult = finish_multiplier[finish]

        # Items
        st.caption("Select applicable projects. Costs are averages; scale by level. Choose quantity as needed.")
        cols_l, cols_r = st.columns(2)
        total_mods = 0

        # Left side
        with cols_l:
            g1 = st.checkbox("Grab bars & railings (avg $800)", key="mod_grab")
            qty_g1 = st.number_input("Qty", min_value=1, value=2, key="qty_grab", disabled=not g1)
            r1 = st.checkbox("Ramp installation (avg $3,500)", key="mod_ramp")
            qty_r1 = st.number_input("Qty", min_value=1, value=1, key="qty_ramp", disabled=not r1)
            s1 = st.checkbox("Stair lift (avg $4,500)", key="mod_stair")
            qty_s1 = st.number_input("Qty", min_value=1, value=1, key="qty_stair", disabled=not s1)
            sm = st.checkbox("Smart home monitoring/sensors (avg $1,200)", key="mod_smart")
            qty_sm = st.number_input("Qty", min_value=1, value=1, key="qty_smart", disabled=not sm)

        # Right side
        with cols_r:
            w1 = st.checkbox("Widen doorways (avg $2,500)", key="mod_widen")
            qty_w1 = st.number_input("Qty", min_value=1, value=1, key="qty_widen", disabled=not w1)
            b1 = st.checkbox("Bathroom walk-in shower conversion (avg $12,000)", key="mod_bath")
            qty_b1 = st.number_input("Qty", min_value=1, value=1, key="qty_bath", disabled=not b1)
            l1 = st.checkbox("Lighting & fall-risk improvements (avg $1,500)", key="mod_light")
            qty_l1 = st.number_input("Qty", min_value=1, value=1, key="qty_light", disabled=not l1)

        def add_if(on, avg, qty):
            return (avg * qty) if on else 0

        total_mods += add_if(g1, 800, qty_g1)
        total_mods += add_if(r1, 3500, qty_r1)
        total_mods += add_if(s1, 4500, qty_s1)
        total_mods += add_if(sm, 1200, qty_sm)
        total_mods += add_if(w1, 2500, qty_w1)
        total_mods += add_if(b1, 12000, qty_b1)
        total_mods += add_if(l1, 1500, qty_l1)

        total_mods = int(round(total_mods * mult))

        st.divider()
        pm = st.radio("Payment method", ["Amortize monthly", "Pay upfront (one-time)"], horizontal=True, key="mod_pay_method")
        if pm == "Amortize monthly":
            months = st.slider("Amortize over (months)", 6, 60, 12, 1, key="mod_months")
            monthly_mods = int(round(total_mods / max(1, months)))
            st.metric("Subtotal — Home mods (amortized monthly)", f"${monthly_mods:,}")
            st.session_state["mods_monthly_total"] = monthly_mods
            st.session_state["mods_upfront_total"] = 0
        else:
            st.metric("Upfront cost — Home mods", f"${total_mods:,}")
            st.checkbox("Deduct upfront cost from assets summary", key="mods_deduct_assets", value=True)
            st.session_state["mods_monthly_total"] = 0
            st.session_state["mods_upfront_total"] = total_mods

    # Other monthly costs
    with st.expander("Other monthly costs (meds, insurance, etc.)", expanded=False):
        meds = money_input("Medications", "oc_meds", 0)
        med_sup = money_input("Medicare supplement / health insurance", "oc_medins", 0)
        dental = money_input("Dental insurance", "oc_dental", 0)
        other  = money_input("Other recurring", "oc_other", 0)
        other_monthly = meds + med_sup + dental + other
        st.metric("Subtotal — Other monthly costs", f"${other_monthly:,}")
        st.session_state["other_monthly_total"] = other_monthly

    # Assets
    with st.expander("Assets — common (quick)", expanded=False):
        cash = money_input("Cash / checking / savings", "as_cash", 0, step=500)
        invest = money_input("Investments / brokerage (est.)", "as_invest", 0, step=500)
        cd = money_input("CDs / money market", "as_cd", 0, step=500)
        common_assets = cash + invest + cd
        st.metric("Subtotal — Common assets", f"${common_assets:,}")
        st.session_state["assets_common_total"] = common_assets

    with st.expander("Assets — detailed (optional)", expanded=False):
        ira = money_input("Traditional / Roth IRA", "as_ira", 0, step=500)
        k401 = money_input("401(k) / 403(b)", "as_401k", 0, step=500)
        hsa = money_input("HSA balance", "as_hsa", 0, step=200)
        life = money_input("Life insurance cash value", "as_life", 0, step=200)
        vehicle = money_input("Vehicle sale value (if planning to sell)", "as_vehicle", 0, step=200)
        detailed_assets = ira + k401 + hsa + life + vehicle

        # Apply home sale proceeds if selected
        proceeds = int(st.session_state.get("home_net_proceeds", 0))
        if st.session_state.get("apply_proceeds_assets", False):
            detailed_assets += proceeds

        # Deduct upfront mods if selected
        if st.session_state.get("mods_deduct_assets", False):
            detailed_assets -= int(st.session_state.get("mods_upfront_total", 0))

        detailed_assets = max(0, detailed_assets)
        st.metric("Subtotal — Detailed assets", f"${detailed_assets:,}")
        st.session_state["assets_detailed_total"] = detailed_assets

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

    home_monthly   = int(s.get("home_monthly_total", 0))
    mods_monthly   = int(s.get("mods_monthly_total", 0))
    other_monthly  = int(s.get("other_monthly_total", 0))
    addl_costs     = home_monthly + mods_monthly + other_monthly

    assets_common  = int(s.get("assets_common_total", 0))
    assets_detail  = int(s.get("assets_detailed_total", 0))
    assets_total   = assets_common + assets_detail

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
        "Total assets": assets_total,
    })

    # Optional donuts
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
                alt.Chart(inc_df).mark_arc(innerRadius=60).encode(theta="Amount", color="Category",
                                                                 tooltip=["Category","Amount"]),
                use_container_width=True
            )
        with colB:
            st.caption("Costs composition")
            st.altair_chart(
                alt.Chart(cost_df).mark_arc(innerRadius=60).encode(theta="Amount", color="Category",
                                                                   tooltip=["Category","Amount"]),
                use_container_width=True
            )

    st.divider()
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Back to Household"):
            st.session_state.step = "household"; st.rerun()
    with b2:
        if st.button("Back to Costs"):
            st.session_state.step = "calculator"; st.rerun()