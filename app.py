# app.py — Senior Navigator (Planner → Recommendations → Costs → Household → Breakdown → PFMA)
from __future__ import annotations

import os
from pathlib import Path
import traceback
import streamlit as st
import pandas as pd
from streamlit.components.v1 import html

from cost_controls import (
    render_location_control,
    render_costs_for_active_recommendations,
    CONDITION_OPTIONS,
)
from pfma_controls import render_pfma

# Feature flag for gamification
ENABLE_PFMA_GAMIFICATION = os.environ.get("ENABLE_PFMA_GAMIFICATION", "true").lower() in {"true", "1", "yes"}

st.set_page_config(page_title="Senior Navigator • Planner + Cost", page_icon="🧭", layout="wide")

# CSS for confirm buttons, gamification animations, and chart styling
st.markdown("""
    <style>
    .stButton > button[kind="primary"] {
        background-color: #4CAF50;
        color: white;
        border-radius: 5px;
        padding: 10px 20px;
        font-weight: bold;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #45a049;
    }
    .stAlert {
        animation: fadeIn 0.5s;
    }
    .badge {
        animation: fadeIn 0.5s;
    }
    @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
    }
    </style>
""", unsafe_allow_html=True)

ROOT = Path(__file__).resolve().parent
QA_PATH = ROOT / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = ROOT / "recommendation_logic_FINAL_MASTER_UPDATED.json"

try:
    from engines import PlannerEngine, CalculatorEngine, PlannerResult
except Exception:
    st.error("Failed to import engines.py")
    st.code(traceback.format_exc())
    st.stop()

try:
    import asset_engine
except Exception:
    asset_engine = None

# ---------------- Utilities ----------------
def reset_all():
    for k in list(st.session_state.keys()):
        if not k.startswith("_"):
            del st.session_state[k]
    st.session_state.step = "intro"

def _is_intlike(x) -> bool:
    try:
        int(str(x)); return True
    except Exception:
        return False

def order_answer_map(amap: dict[str, str]) -> tuple[list[str], list[str]]:
    if not isinstance(amap, dict) or not amap:
        return [], []
    keys = list(amap.keys())
    if not all(isinstance(k, str) for k in keys): return [], []
    if not all(isinstance(amap[k], str) for k in keys): return [], []
    if all(_is_intlike(k) for k in keys):
        ordered_keys = [str(k) for k in sorted(int(str(k)) for k in keys)]
    else:
        ordered_keys = [str(k) for k in keys]
    labels = [amap[k] for k in ordered_keys]
    return ordered_keys, labels

def radio_from_answer_map(label, amap, *, key, default_key=None) -> str | None:
    if not isinstance(amap, dict) or not amap:
        return default_key
    keys, labels = order_answer_map(amap)
    if not labels:
        return default_key
    idx = keys.index(str(default_key)) if default_key is not None and str(default_key) in keys else 0
    sel_label = st.radio(label, labels, index=idx, key=key)
    return keys[labels.index(sel_label)]

def money(n: int | float) -> str:
    try: return f"${int(round(float(n))):,}"
    except Exception: return "$0"

# ---------------- Data files present? ----------------
missing = [p for p in (QA_PATH, REC_PATH) if not p.exists()]
if missing:
    st.error("Missing required JSON files:\\n" + "\\n".join(f"• {m.name}" for m in missing))
    st.stop()
try:
    planner = PlannerEngine(str(QA_PATH), str(REC_PATH))
except Exception:
    st.error("PlannerEngine failed to initialize.")
    st.code(traceback.format_exc())
    st.stop()
try:
    calculator = CalculatorEngine()
except Exception:
    st.error("CalculatorEngine failed to initialize.")
    st.code(traceback.format_exc())
    st.stop()
if "step" not in st.session_state:
    st.session_state.step = "intro"
# Sidebar
st.sidebar.title("Senior Navigator")
st.sidebar.caption("Planner → Recommendations → Costs → Household")
st.sidebar.button("Start over", on_click=reset_all, key="start_over_btn")
if st.sidebar.button("Schedule with an Advisor", use_container_width=True, key="pfma_sidebar"):
    st.session_state.step = "pfma"; st.rerun()
# Flow
if st.session_state.step == "intro":
    st.title("Let’s take this one step at a time")
    st.markdown(
        """
Choosing senior living or in-home support can feel overwhelming.
**What happens next**
1. Answer quick care questions → we recommend a care type.
2. Review costs for that scenario (you can switch).
3. Add income, benefits, assets, and home decisions.
4. See a detailed breakdown and adjust anything.
"""
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Start", key="intro_start"):
            st.session_state.step = "audience"; st.rerun()
    with c2:
        if st.button("Open Advisor Prototype", key="intro_pfma_btn"):
            st.session_state.step = "pfma"; st.rerun()
elif st.session_state.step == "audience":
    st.header("Who is this plan for?")
    role = st.radio("Select one:", ["Myself", "My spouse/partner", "My parent", "Both parents", "Someone else"], key="aud_role")
    people = []
    if role == "Both parents":
        c1, c2 = st.columns(2)
        with c1: n1 = st.text_input("Parent 1 name", value="Mom", key="p1_name", placeholder="Name")
        with c2: n2 = st.text_input("Parent 2 name", value="Dad", key="p2_name", placeholder="Name")
        people += [{"id":"A","display_name":n1,"relationship":"parent"}, {"id":"B","display_name":n2,"relationship":"parent"}]
    else:
        default = "Alex" if role != "My parent" else "Mom"
        n = st.text_input("Name", value=default, key="p_name", placeholder="Name")
        rel = {"Myself":"self","My spouse/partner":"spouse","My parent":"parent","Someone else":"other"}[role]
        people.append({"id":"A","display_name":n,"relationship":rel})
    if st.button("Continue", key="aud_continue"):
        st.session_state.people = people
        st.session_state.current_person = 0
        st.session_state.planner_results = {}
        st.session_state.person_costs = {}
        st.session_state.step = "spouse_interstitial" if role != "Both parents" else "planner"
        st.rerun()
elif st.session_state.step == "spouse_interstitial":
    st.header("Add Spouse or Partner?")
    st.markdown("Would you like to include a spouse or partner in this plan?")
    add = st.checkbox("Yes, include a spouse/partner", key="care_partner_add", value=False)
    if add:
        st.text_input("Spouse/Partner name", value="", placeholder="Enter spouse/partner name", key="care_partner_name")
    c1, c2 = st.columns(2)
    with c1:
        primary = st.session_state.people[0]["display_name"]
        if st.button(f"No, just plan for **{primary}**", key="spouse_no"):
            st.session_state.step = "planner"; st.rerun()
    with c2:
        if st.button("Add spouse/partner and continue", key="spouse_yes", disabled=not st.session_state.get("care_partner_add", False)):
            st.session_state.people.append({"id":"B","display_name":st.session_state.get("care_partner_name") or "Spouse/Partner","relationship":"spouse"})
            st.session_state.step = "planner"; st.rerun()
elif st.session_state.step == "planner":
    s = st.session_state
    people = s.get("people", [])
    i = s.get("current_person", 0)
    p = people[i]
    pid, name = p["id"], p["display_name"]
    st.header(f"Care Assessment for {name}")
    st.markdown("Answer these quick questions to get a personalized recommendation.")
    answers = {}
    for q_idx, q in enumerate(PlannerEngine(str(QA_PATH), str(REC_PATH)).qa.get("questions", []), start=1):
        label = q["question"]; amap = q.get("answers", {})
        if not amap or not isinstance(amap, dict):
            continue
        key = f"q{q_idx}_{pid}"
        ans = radio_from_answer_map(label, amap, key=key)
        if ans is not None: answers[f"q{q_idx}"] = int(ans)
    if st.button("Save and continue", key="planner_save"):
        if not answers:
            st.error("Please answer at least one question.")
        else:
            try:
                result = planner.run(answers, name=name)
            except Exception:
                st.error("PlannerEngine.run failed."); st.code(traceback.format_exc()); st.stop()
            s.planner_results = s.get("planner_results", {}); s.planner_results[pid] = result
            s.current_person += 1
            s.step = "recommendations" if s.current_person >= len(people) else "person_transition"
            st.rerun()
elif st.session_state.step == "person_transition":
    s = st.session_state
    people = s.get("people", [])
    i = s.get("current_person", 0)
    if i >= len(people):
        s.step = "recommendations"; st.rerun()
    name = people[i]["display_name"]
    st.header("Great — first plan saved."); st.info(f"Now let’s assess **{name}**.")
    if st.button(f"Start {name}'s care plan", key="trans_start"):
        s.step = "planner"; st.rerun()
elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without redoing questions.")
    s = st.session_state
    for p in s.get("people", []):
        pid = p["id"]; name = p["display_name"]
        rec = s.get("planner_results", {}).get(pid, PlannerResult("in_home", [], {}, [], "", None))
        care_type = rec.care_type; reasons = rec.reasons; narrative = rec.narrative
        nice = {"none":"None","in_home":"In-home Care","assisted_living":"Assisted Living","memory_care":"Memory Care"}
        st.subheader(f"{name}: {nice.get(care_type, care_type).title()} (recommended)")
        for r in reasons or []: st.write("• " + str(r))
        if narrative: st.info(narrative)
        options = ["none","in_home","assisted_living","memory_care"]
        idx = options.index(care_type) if care_type in options else 1
        label = st.selectbox(f"Care scenario for {name}", [nice[o] for o in options], index=idx, key=f"override_{pid}")
        reverse = {v:k for k,v in nice.items()}
        s.care_overrides = s.get("care_overrides", {}); s.care_overrides[pid] = reverse[label]
        st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Back to questions", key="rec_back_questions"):
            st.session_state.step = "planner"; st.rerun()
    with c2:
        if st.button("See Costs", key="rec_see_costs"):
            st.session_state.step = "calculator"; st.rerun()
    with c3:
        if st.button("Finish", key="rec_finish"):
            st.session_state.step = "intro"; st.rerun()
elif st.session_state.step == "calculator":
    st.header("Cost Planner")
    render_location_control()
    combined_total = render_costs_for_active_recommendations(planner=planner, calculator=calculator)
    st.subheader("Combined Total"); st.metric("Estimated Combined Monthly Cost", f"${combined_total:,.0f}")
    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Back to recommendations", key="calc_back_rec"):
            st.session_state.step = "recommendations"; st.rerun()
    with c2:
        if st.button("Add Household & Assets", key="calc_household"):
            st.session_state.step = "household"; st.rerun()
    with c3:
        if st.button("Schedule with an Advisor", key="calc_pfma_btn"):
            st.session_state.step = "pfma"; st.rerun()
elif st.session_state.step == "household":
    st.header("Household & Budget")
    st.caption("Add income, benefits, assets, home decisions, and other costs to see affordability. You can skip this.")
    if asset_engine is None:
        st.warning("The household budgeting feature is unavailable because asset_engine.py is missing or failed to load.")
    else:
        try:
            people = st.session_state.get("people", [])
            if hasattr(asset_engine, "IncomeAssetsEngine"):
                engine = asset_engine.IncomeAssetsEngine(calculator=calculator)
                result = engine.render(people)
            else:
                st.warning("The household budgeting feature is unavailable because asset_engine.py lacks a recognized render function.")
                result = None
        except Exception:
            st.error("Household drawers failed."); st.code(traceback.format_exc()); result = None
        if result is not None and hasattr(result, "as_dict"):
            with st.expander("Details (for debugging)", expanded=False):
                st.json(result.as_dict())
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Back to Costs", key="hh_back_costs"):
            st.session_state.step = "calculator"; st.rerun()
    with c2:
        if st.button("View Detailed Breakdown", key="hh_breakdown"):
            st.session_state.step = "breakdown"; st.rerun()
    with c3:
        if st.button("Finish", key="hh_finish"):
            st.session_state.step = "intro"; st.rerun()
elif st.session_state.step == "breakdown":
    st.header("Detailed Breakdown")
    s = st.session_state
    people = s.get("people", [])
    person_costs: dict = s.get("person_costs", {})
    st.subheader("Care Costs by Person")
    care_rows = []; care_total = 0
    for p in people:
        pid = p["id"]; name = p["display_name"]
        rec = s.get("planner_results", {}).get(pid, None)
        default_care = getattr(rec, "care_type", None) if rec else None
        scenario = s.get("care_overrides", {}).get(pid, default_care) or "none"
        cost = int(person_costs.get(pid, 0))
        def pick(base): return s.get(f"{base}_{pid}") or s.get(base) or "—"
        if scenario == "assisted_living":
            cond = s.get(f"al_conditions_saved_{pid}", s.get("al_conditions"))
            cond_str = ", ".join(cond) if isinstance(cond, list) else (cond or "—")
            detail = ", ".join([f"Care: {pick('al_care_level')}", f"Room: {pick('al_room_type')}", f"Mobility: {pick('al_mobility')}", f"Conditions: {cond_str}"])
        elif scenario == "memory_care":
            cond = s.get(f"mc_conditions_saved_{pid}", s.get("mc_conditions"))
            cond_str = ", ".join(cond) if isinstance(cond, list) else (cond or "—")
            detail = ", ".join([f"Care: {pick('mc_level')}", f"Mobility: {pick('mc_mobility')}", f"Conditions: {cond_str}"])
        elif scenario == "in_home":
            hrs = s.get(f"ih_hours_per_day_{pid}", s.get("ih_hours_per_day", 4)); days = s.get(f"ih_days_per_month_{pid}", s.get("ih_days_per_month", 20))
            ctype = s.get(f"ih_caregiver_type_{pid}", s.get("ih_caregiver_type", "Agency")).title()
            cond = s.get(f"ih_conditions_saved_{pid}", s.get("ih_conditions"))
            cond_str = ", ".join(cond) if isinstance(cond, list) else (cond or "—")
            detail = f"{hrs} hrs/day × {days} days/mo, Caregiver: {ctype}, Conditions: {cond_str}"
        else:
            detail = "—"
        care_rows.append({"Person": name, "Scenario": scenario.replace('_',' ').title(), "Details": detail, "Monthly Cost": money(cost)})
        care_total += cost
    if care_rows: st.table(care_rows)
    else: st.info("No care costs yet. Choose a scenario in the Cost Planner.")
    st.subheader("Additional Monthly Costs (Selected)")
    home_monthly = int(s.get("home_monthly_total", 0))
    mods_monthly = int(s.get("mods_monthly_total", 0))
    other_monthly = int(s.get("other_monthly_total", 0))
    addl_total = home_monthly + mods_monthly + other_monthly
    st.table([
        {"Category":"Home decisions", "Monthly":money(home_monthly)},
        {"Category":"Home modifications", "Monthly":money(mods_monthly)},
        {"Category":"Other monthly costs", "Monthly":money(other_monthly)},
        {"Category":"Subtotal (additional)", "Monthly":money(addl_total)},
    ])
    # Monthly Costs Bar Chart
    st.subheader("Monthly Costs Breakdown")
    monthly_costs_data = {
        "Category": ["Care Costs", "Home Decisions", "Home Modifications", "Other Monthly"],
        "Amount": [care_total, home_monthly, mods_monthly, other_monthly]
    }
    if any(amount > 0 for amount in monthly_costs_data["Amount"]):
        df = pd.DataFrame(monthly_costs_data)
        st.bar_chart(df.set_index("Category")["Amount"], color="#4CAF50")
    else:
        st.info("No monthly costs entered yet.")
    st.subheader("Monthly Income")
    inc_A = int(s.get("a_ss",0)) + int(s.get("a_pn",0)) + int(s.get("a_other",0))
    inc_B = int(s.get("b_ss",0)) + int(s.get("b_pn",0)) + int(s.get("b_other",0))
    inc_house = int(s.get("hh_rent",0)) + int(s.get("hh_annuity",0)) + int(s.get("hh_invest",0)) + int(s.get("hh_trust",0)) + int(s.get("hh_other",0))
    va_A = int(s.get("a_va_monthly",0)); va_B = int(s.get("b_va_monthly",0))
    income_total = inc_A + inc_B + inc_house + va_A + va_B
    st.table([
        {"Source":"Individual A (SS + Pension + Other)","Monthly":money(inc_A)},
        {"Source":"Individual B (SS + Pension + Other)","Monthly":money(inc_B)},
        {"Source":"Household / Shared (rent, annuity, investments, trust, other)","Monthly":money(inc_house)},
        {"Source":"VA — A","Monthly":money(va_A)},
        {"Source":"VA — B","Monthly":money(va_B)},
        {"Source":"Total Income","Monthly":money(income_total)},
    ])
    # Income Sources Pie Chart
    st.subheader("Income Sources Breakdown")
    income_data = {
        "Source": ["Individual A", "Individual B", "Household", "VA A", "VA B"],
        "Amount": [inc_A, inc_B, inc_house, va_A, va_B]
    }
    income_data_filtered = {
        "Source": [source for source, amount in zip(income_data["Source"], income_data["Amount"]) if amount > 0],
        "Amount": [amount for amount in income_data["Amount"] if amount > 0]
    }
    if income_data_filtered["Amount"]:
        chart_id = "income_pie_chart"
        chart_html = f"""
        <canvas id="{chart_id}" style="max-height: 300px;"></canvas>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script>
        const ctx = document.getElementById('{chart_id}').getContext('2d');
        new Chart(ctx, {{
            type: 'pie',
            data: {{
                labels: {income_data_filtered["Source"]},
                datasets: [{{
                    data: {income_data_filtered["Amount"]},
                    backgroundColor: ["#4CAF50", "#2196F3", "#FF9800", "#F44336", "#9C27B0"],
                    borderColor: ["#388E3C", "#1976D2", "#F57C00", "#D32F2F", "#7B1FA2"],
                    borderWidth: 1
                }}]
            }},
            options: {{
                plugins: {{
                    legend: {{ position: 'bottom' }},
                    title: {{ display: true, text: 'Income Sources ($)' }}
                }}
            }}
        }});
        </script>
        """
        html(chart_html, height=350)
    else:
        st.info("No income sources entered yet.")
    st.subheader("Assets")
    assets_common = int(s.get("assets_common_total", 0))
    assets_detail = int(s.get("assets_detailed_total", 0))
    home_sale_proceeds = int(s.get("home_sale_net_proceeds", 0))
    mods_deduct = s.get("mods_deduct_assets", False)
    mods_upfront = int(s.get("mods_upfront_total", 0))
    assets_total = assets_common + assets_detail + (home_sale_proceeds if not mods_deduct else max(0, home_sale_proceeds - mods_upfront))
    # Debug home sale proceeds
    st.write(f"Debug: Home Sale Proceeds = {money(home_sale_proceeds)}, Mods Deduct = {mods_deduct}, Mods Upfront = {money(mods_upfront)}")
    st.table([
        {"Category": "Common Assets", "Amount": money(assets_common)},
        {"Category": "Detailed Assets", "Amount": money(assets_detail)},
        {"Category": "Home Sale Proceeds", "Amount": money(home_sale_proceeds)},
        {"Category": "Total Assets", "Amount": money(assets_total)},
    ])
    # Assets Pie Chart
    st.subheader("Assets Breakdown")
    assets_data = {
        "Category": ["Common Assets", "Detailed Assets", "Home Sale Proceeds"],
        "Amount": [assets_common, assets_detail, home_sale_proceeds]
    }
    assets_data_filtered = {
        "Category": [cat for cat, amount in zip(assets_data["Category"], assets_data["Amount"]) if amount > 0],
        "Amount": [amount for amount in assets_data["Amount"] if amount > 0]
    }
    if assets_data_filtered["Amount"]:
        chart_id = "assets_pie_chart"
        chart_html = f"""
        <canvas id="{chart_id}" style="max-height: 300px;"></canvas>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script>
        const ctx = document.getElementById('{chart_id}').getContext('2d');
        new Chart(ctx, {{
            type: 'pie',
            data: {{
                labels: {assets_data_filtered["Category"]},
                datasets: [{{
                    data: {assets_data_filtered["Amount"]},
                    backgroundColor: ["#4CAF50", "#2196F3", "#FF9800"],
                    borderColor: ["#388E3C", "#1976D2", "#F57C00"],
                    borderWidth: 1
                }}]
            }},
            options: {{
                plugins: {{
                    legend: {{ position: 'bottom' }},
                    title: {{ display: true, text: 'Assets Breakdown ($)' }}
                }}
            }}
        }});
        </script>
        """
        html(chart_html, height=350)
    else:
        st.info("No assets entered yet.")
    st.subheader("Totals")
    monthly_need = care_total + addl_total
    gap = monthly_need - income_total
    col1, col2, col3 = st.columns(3)
    col1.metric("Monthly Care + Selected Costs", money(monthly_need))
    col2.metric("Total Monthly Income (incl. VA)", money(income_total))
    col3.metric("Estimated Monthly Gap", money(gap))
    if gap > 0 and assets_total > 0:
        months = int(assets_total // max(gap, 1)); years = months // 12; rem = months % 12
        msg = f"Estimated runway from assets: {years} years, {rem} months" if years > 0 else f"Estimated runway from assets: {rem} months"
    else:
        msg = "Estimated runway from assets: Indefinite (monthly surplus)" if gap <= 0 else "Estimated runway from assets: 0 months"
    st.subheader(msg)
    st.divider()
    cta1, cta2 = st.columns(2)
    with cta1:
        if st.button("Back to Household", key="bd_back_house"): st.session_state.step = "household"; st.rerun()
    with c2:
        if st.button("Schedule with an Advisor", key="bd_pfma_btn"): st.session_state.step = "pfma"; st.rerun()
elif st.session_state.step == "pfma":
    render_pfma()
