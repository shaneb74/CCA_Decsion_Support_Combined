# app.py — Senior Navigator (Planner → Recommendation → Costs → Household → Breakdown)
from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
import traceback
import streamlit as st

try:
    import altair as alt
    HAVE_ALTAIR = True
except Exception:
    HAVE_ALTAIR = False

# ---------- Paths ----------
ROOT = Path(__file__).resolve().parent
QA_PATH  = ROOT / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = ROOT / "recommendation_logic_FINAL_MASTER_UPDATED.json"

# ---------- Engines ----------
try:
    from engines import PlannerEngine, CalculatorEngine
except Exception:
    st.error("Failed to import engines.py"); st.code(traceback.format_exc()); st.stop()

missing = [p for p in (QA_PATH, REC_PATH) if not p.exists()]
if missing:
    st.error("Missing required JSON files:\n" + "\n".join(f"• {m}" for m in missing)); st.stop()

try:
    planner = PlannerEngine(str(QA_PATH), str(REC_PATH))
except Exception:
    st.error("PlannerEngine() failed."); st.code(traceback.format_exc()); st.stop()

try:
    calculator = CalculatorEngine()
except Exception:
    st.error("CalculatorEngine() failed."); st.code(traceback.format_exc()); st.stop()

# NEW: import the isolated Household/Assets engine
from asset_engine import IncomeAssetsEngine
assets_engine = IncomeAssetsEngine(calculator=calculator)

# ---------- Helpers ----------
st.set_page_config(page_title="Senior Navigator • Planner + Cost", page_icon="🧭", layout="centered")

def reset_all():
    for k in list(st.session_state.keys()):
        if not k.startswith("_"):
            del st.session_state[k]
    st.session_state.step = "intro"

def fmt_money(x: int | float) -> str:
    try: return f"${int(x):,}"
    except Exception: return "$0"

def make_inputs(**kwargs):
    obj = SimpleNamespace()
    for k, v in kwargs.items(): setattr(obj, k, v)
    return obj

def order_answer_map(amap):
    if not isinstance(amap, dict) or not amap: return [], []
    keys = list(amap.keys())
    def _is_intlike(x):
        try: int(str(x)); return True
        except Exception: return False
    if all(_is_intlike(k) for k in keys):
        ordered_keys = [str(k) for k in sorted(int(str(k)) for k in keys)]
    else:
        ordered_keys = [str(k) for k in sorted(map(str, keys))]
    ordered_labels = [amap[k] for k in ordered_keys]
    return ordered_keys, ordered_labels

def radio_from_answer_map(label, amap, *, key, help_text=None, default_key=None):
    ordered_keys, ordered_labels = order_answer_map(amap)
    if not ordered_labels: return default_key
    if default_key is not None and str(default_key) in ordered_keys:
        idx = ordered_keys.index(str(default_key))
    else:
        idx = 0
    sel_label = st.radio(label, options=ordered_labels, index=idx, key=key, help=help_text)
    return ordered_keys[ordered_labels.index(sel_label)]

def narrative_from_result(rec: dict) -> str | None:
    return (
        rec.get("advisory")
        or rec.get("message")
        or rec.get("narrative")
        or rec.get("message_rendered")
        or rec.get("message_template")
    )

def clamp(v, lo, hi):
    try: return max(lo, min(hi, v))
    except Exception: return lo

# ---------- Sidebar ----------
if "step" not in st.session_state:
    st.session_state.step = "intro"
st.sidebar.title("Senior Navigator")
st.sidebar.caption("Planner → Costs → Budget → Breakdown")
st.sidebar.button("Start over", on_click=reset_all)

# ===================== FLOW =====================

# Intro
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

# Audience
elif st.session_state.step == "audience":
    st.header("Who is this plan for?")
    role = st.radio("Select one:", ["Myself", "My spouse/partner", "My parent", "Both parents", "Someone else"])
    if role == "Both parents":
        c1, c2 = st.columns(2)
        with c1:
            n1 = st.text_input("Parent 1 name", value="Mom", key="p1_name", placeholder="Name")
        with c2:
            n2 = st.text_input("Parent 2 name", value="Dad", key="p2_name", placeholder="Name")
        people = [{"id":"A","display_name":n1,"relationship":"parent"},
                  {"id":"B","display_name":n2,"relationship":"parent"}]
        single = False
    else:
        default = "Alex" if role != "My parent" else "Mom"
        n = st.text_input("Name", value=default, key="p_name", placeholder="Name")
        map_rel = {"Myself":"self","My spouse/partner":"spouse","My parent":"parent","Someone else":"other"}
        people = [{"id":"A","display_name":n,"relationship":map_rel.get(role,"other")}]
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

# Partner interstitial
elif st.session_state.step == "partner_context":
    people = st.session_state.get("people",[])
    single = len(people)==1
    primary = people[0]["display_name"] if people else "Person A"
    st.header("Before we begin")
    st.markdown(
        f"If **{primary}** needs to leave the home for assisted living or memory care, "
        "their spouse/partner may also need some in-home help. "
        "You can include a simple support plan for them now so the household picture is complete."
    )
    add = st.checkbox("Yes, I want to evaluate a plan for a spouse/partner", value=False, key="care_partner_add")
    if add:
        st.text_input("Spouse/partner name", value="", placeholder="Enter spouse/partner name", key="care_partner_name")
    c1, c2 = st.columns(2)
    with c1:
        if st.button(f"No, let's just plan for **{primary}**"):
            st.session_state.step = "planner"; st.rerun()
    with c2:
        btn_disabled = not st.session_state.get("care_partner_add", False)
        if st.button("Add spouse/partner and continue", disabled=btn_disabled):
            if single and st.session_state.get("care_partner_add"):
                st.session_state.people.append({
                    "id":"B",
                    "display_name": st.session_state.get("care_partner_name") or "Spouse/Partner",
                    "relationship":"spouse"
                })
            st.session_state.step = "planner"; st.rerun()

# Planner (one at a time)
elif st.session_state.step == "planner":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if not people: reset_all(); st.rerun()
    person = people[i]; pid = person["id"]; name = person["display_name"]

    st.header(f"Care Plan — {name}")
    qa = planner.qa or {}; questions = qa.get("questions", []); total_q = len(questions)

    idx_key = f"qidx_{pid}"
    if idx_key not in st.session_state: st.session_state[idx_key] = 0
    idx = clamp(st.session_state[idx_key], 0, max(0,total_q-1)); st.session_state[idx_key] = idx

    answers = st.session_state.answers.get(pid,{})
    st.caption(f"Question {idx+1} of {total_q}")
    st.progress((idx+1)/max(1,total_q))

    if total_q>0:
        q = questions[idx]; amap = q.get("answers",{})
        label = q.get("question", f"Question {idx+1}")
        sel_key = radio_from_answer_map(label, amap, key=f"{pid}_q{idx+1}", help_text=q.get("help"))
        try: answers[f"q{idx+1}"] = int(sel_key)
        except Exception: answers[f"q{idx+1}"] = sel_key
        st.session_state.answers[pid] = answers

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Back", disabled=(idx==0)):
            st.session_state[idx_key] = max(0, idx-1); st.rerun()
    with c2:
        if st.button("Next", disabled=(idx>=total_q-1)):
            st.session_state[idx_key] = min(total_q-1, idx+1); st.rerun()
    with c3:
        if st.button("Finish", disabled=(idx<total_q-1)):
            try:
                res = planner.run(answers)
            except Exception:
                st.error("PlannerEngine.run failed."); st.code(traceback.format_exc()); st.stop()

            if hasattr(res, "__dict__"):
                care_type = getattr(res,"care_type",None)
                flags     = getattr(res,"flags",None) or []
                scores    = getattr(res,"scores",None) or {}
                reasons   = getattr(res,"reasons",None) or []
                narrative = (getattr(res,"narrative",None)
                             or getattr(res,"advisory",None)
                             or getattr(res,"message",None))
            else:
                care_type = res.get("care_type")
                flags     = res.get("flags",[])
                scores    = res.get("scores",{})
                reasons   = res.get("reasons",[])
                narrative = (res.get("narrative") or res.get("advisory") or res.get("message"))

            st.session_state.planner_results[pid] = {
                "care_type": care_type or "in_home",
                "flags": set(flags),
                "scores": scores,
                "reasons": reasons,
                "advisory": narrative or "",
            }

            st.session_state[f"qidx_{pid}"] = 0
            if i+1 < len(people):
                st.session_state.current_person = i+1
                st.session_state.next_person_name = people[i+1]["display_name"]
                st.session_state.step = "person_transition"
            else:
                st.session_state.step = "recommendations"
            st.rerun()

# Between people
elif st.session_state.step == "person_transition":
    next_name = st.session_state.get("next_person_name","the next person")
    st.header("Great — that completes the first set of questions.")
    st.markdown(f"Now let’s assess **{next_name}**’s care plan.")
    if st.button(f"Start {next_name}'s questions"):
        st.session_state.step = "planner"; st.rerun()

# Recommendations
elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without redoing questions.")
    for p in st.session_state.get("people", []):
        pid=p["id"]; name=p["display_name"]
        rec = st.session_state.planner_results.get(pid,{}) or {}
        care_type = rec.get("care_type","in_home")
        label = {"none":"No care needed","in_home":"In-home Care","assisted_living":"Assisted Living","memory_care":"Memory Care"}.get(care_type, care_type)

        st.subheader(f"{name}: {label} (recommended)")
        for r in rec.get("reasons", []):
            st.write("• " + str(r))
        narrative = narrative_from_result(rec)
        if narrative:
            try: narrative = narrative.replace("{name}", name)
            except Exception: pass
            st.info(narrative)

        choices = [("none","No care needed"),("in_home","In-home Care"),("assisted_living","Assisted Living"),("memory_care","Memory Care")]
        labels = [lbl for _k,lbl in choices]; keys=[k for k,_l in choices]
        idx = keys.index(care_type) if care_type in keys else 1
        sel = st.selectbox(f"Care scenario for {name}", labels, index=idx, key=f"override_{pid}")
        st.session_state.care_overrides[pid] = keys[labels.index(sel)]
        st.divider()

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back to questions"):
            st.session_state.current_person = 0
            st.session_state.step = "planner"; st.rerun()
    with c2:
        if st.button("See Costs"):
            st.session_state.step = "calculator"; st.rerun()

# Cost planner
elif st.session_state.step == "calculator":
    st.header("Cost Planner")
    state = st.selectbox("Location", ["National","Washington","California","Texas","Florida"])
    total = 0
    for p in st.session_state.get("people", []):
        pid=p["id"]; name=p["display_name"]
        rec = st.session_state.planner_results.get(pid,{}) or {}
        care_type = st.session_state.get("care_overrides",{}).get(pid, rec.get("care_type","in_home"))
        st.subheader(f"{name} — Scenario: { {'none':'No care needed','in_home':'In-home Care','assisted_living':'Assisted Living','memory_care':'Memory Care'}.get(care_type, care_type)} "
                     f"(recommended: { {'none':'No care needed','in_home':'In-home Care','assisted_living':'Assisted Living','memory_care':'Memory Care'}.get(rec.get('care_type','in_home'), 'In-home Care')})")

        # carryover mobility (simple heuristic)
        mobility_prefill = "Independent"
        qa = planner.qa or {}
        ans = st.session_state.answers.get(pid,{})
        mob_idx=None
        for ii, qq in enumerate(qa.get("questions", []), start=1):
            if "mobility" in qq.get("question","").lower(): mob_idx=ii; break
        if mob_idx is not None:
            raw = ans.get(f"q{mob_idx}")
            try: raw=int(raw)
            except Exception: raw=None
            if raw in (2,3): mobility_prefill = "Assisted"
            elif raw == 4:   mobility_prefill = "Non-ambulatory"

        care_level_default = "High" if (("severe_cognitive_decline" in rec.get("flags", set())) or (care_type=="memory_care")) else "Medium"
        care_level = st.selectbox("Care Level (staffing intensity)", ["Low","Medium","High"],
                                  index=["Low","Medium","High"].index(care_level_default), key=f"{pid}_care_level")

        mobility_options = ["Independent (no device)","Assisted (cane/walker or needs help)","Non-ambulatory (wheelchair/bedbound)"]
        pre = {"Independent":"Independent (no device)","Assisted":"Assisted (cane/walker or needs help)","Non-ambulatory":"Non-ambulatory (wheelchair/bedbound)"}[mobility_prefill]
        mob_label = st.selectbox("Mobility", mobility_options, index=mobility_options.index(pre), key=f"{pid}_mobility")
        mobility = {"Independent (no device)":"Independent","Assisted (cane/walker or needs help)":"Assisted","Non-ambulatory (wheelchair/bedbound)":"Non-ambulatory"}[mob_label]

        chronic_options = ["None (no ongoing conditions)","Some (1–2 manageable conditions)","Multiple/Complex (several or complex needs)"]
        default_chronic_label = chronic_options[2] if "severe_cognitive_decline" in rec.get("flags", set()) else chronic_options[1]
        chronic_label = st.selectbox("Chronic Conditions", chronic_options,
                                     index=chronic_options.index(default_chronic_label), key=f"{pid}_chronic")
        chronic = {"None (no ongoing conditions)":"None","Some (1–2 manageable conditions)":"Some","Multiple/Complex (several or complex needs)":"Multiple/Complex"}[chronic_label]

        inp = make_inputs(state=state, care_type=care_type, care_level=care_level, mobility=mobility, chronic=chronic)

        if care_type in ["assisted_living","memory_care"]:
            for k in [f"{pid}_hours", f"{pid}_days"]:
                if k in st.session_state: del st.session_state[k]
            room = st.selectbox("Room Type", ["Studio","1 Bedroom","Shared"], key=f"{pid}_room")
            setattr(inp, "room_type", room)
        elif care_type == "none":
            setattr(inp, "in_home_hours_per_day", 0)
            setattr(inp, "in_home_days_per_month", 0)
        else:
            if f"{pid}_room" in st.session_state: del st.session_state[f"{pid}_room"]
            hours = st.slider("In-home care hours per day", 0, 24, 4, 1, key=f"{pid}_hours")
            days  = st.slider("Days of care per month", 0, 31, 20, 1, key=f"{pid}_days")
            setattr(inp, "in_home_hours_per_day", int(hours))
            setattr(inp, "in_home_days_per_month", int(days))

        try:
            if hasattr(calculator, "monthly_cost"):
                monthly = calculator.monthly_cost(inp)
            elif hasattr(calculator, "estimate"):
                monthly = calculator.estimate(getattr(inp,"care_type","in_home"))
            else:
                monthly = 0
        except Exception:
            st.error("CalculatorEngine failed."); st.code(traceback.format_exc()); monthly = 0

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

# Household & Budget — now delegated to the engine
elif st.session_state.step == "household":
    result = assets_engine.render(st.session_state.get("people", []))

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
    nameB = people[1]["display_name"] if len(people)>1 else "Person B"

    care_A = int(costs.get("A",0))
    care_B = int(costs.get("B",0)) if len(people)>1 else 0
    care_total = care_A + care_B

    s = st.session_state
    inc_A = int(s.get("a_ss",0))+int(s.get("a_pn",0))+int(s.get("a_other",0))
    inc_B = int(s.get("b_ss",0))+int(s.get("b_pn",0))+int(s.get("b_other",0)) if len(people)>1 else 0
    inc_house = int(s.get("hh_rent",0))+int(s.get("hh_annuity",0))+int(s.get("hh_invest",0))+int(s.get("hh_trust",0))+int(s.get("hh_other",0))
    va_A = int(s.get("a_va_monthly",0)); va_B = int(s.get("b_va_monthly",0)) if len(people)>1 else 0

    home_monthly = int(s.get("home_monthly_total",0))
    mods_monthly = int(s.get("mods_monthly_total",0))
    other_monthly = int(s.get("other_monthly_total",0))
    addl_costs = home_monthly + mods_monthly + other_monthly

    assets_common = int(s.get("assets_common_total",0))
    assets_detail = int(s.get("assets_detailed_total",0))
    sale_proceeds = int(s.get("home_sale_net_proceeds",0))
    mods_upfront  = int(s.get("mods_upfront_total",0))
    deduct_upfront = bool(s.get("mods_deduct_assets", False))
    assets_total = assets_common + assets_detail + sale_proceeds - (mods_upfront if deduct_upfront else 0)

    income_total = inc_A + inc_B + inc_house + va_A + va_B
    monthly_need = care_total + addl_costs
    gap = monthly_need - income_total

    c1, c2, c3 = st.columns(3)
    c1.metric("Monthly Care + Selected Costs", fmt_money(monthly_need))
    c2.metric("Total Monthly Income (incl. VA)", fmt_money(income_total))
    c3.metric("Estimated Monthly Gap", fmt_money(gap))

    years = 0.0
    if gap > 0 and assets_total > 0:
        years = round(assets_total / max(gap,1), 1)
    st.subheader(f"Estimated runway from assets: {years} years")

    st.markdown("### Per-person care costs")
    if people:
        if len(people)>1:
            cA, cB = st.columns(2)
            with cA: st.write(f"**{nameA}**: {fmt_money(care_A)}/mo")
            with cB: st.write(f"**{nameB}**: {fmt_money(care_B)}/mo")
        else:
            st.write(f"**{nameA}**: {fmt_money(care_A)}/mo")

    st.markdown("### Income breakdown")
    st.write({"Individual A": inc_A,"Individual B": inc_B,"Household": inc_house,"VA benefits": va_A+va_B})

    st.markdown("### Additional monthly costs")
    st.write({"Home (mort/tax/ins/HOA/util)": home_monthly,"Home modifications (amortized)": mods_monthly,"Other recurring": other_monthly})

    st.markdown("### Assets summary")
    st.write({"Common assets": assets_common,"Detailed assets": assets_detail,
              "Home sale net proceeds (applied)": sale_proceeds,
              "Mods upfront (deducted)": (mods_upfront if deduct_upfront else 0),
              "Total assets": assets_total})

    try:
        if HAVE_ALTAIR:
            import pandas as pd
            inc_df = pd.DataFrame([
                {"Category":"Indiv A","Amount":inc_A},
                {"Category":"Indiv B","Amount":inc_B},
                {"Category":"Household","Amount":inc_house},
                {"Category":"VA","Amount":va_A+va_B},
            ])
            cost_df = pd.DataFrame([
                {"Category":"Care","Amount":care_total},
                {"Category":"Home/Mods/Other","Amount":addl_costs},
            ])
            colA, colB = st.columns(2)
            with colA:
                st.caption("Income composition")
                st.altair_chart(alt.Chart(inc_df).mark_arc(innerRadius=60).encode(theta="Amount", color="Category", tooltip=["Category","Amount"]), use_container_width=True)
            with colB:
                st.caption("Costs composition")
                st.altair_chart(alt.Chart(cost_df).mark_arc(innerRadius=60).encode(theta="Amount", color="Category", tooltip=["Category","Amount"]), use_container_width=True)
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