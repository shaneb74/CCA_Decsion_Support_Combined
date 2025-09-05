import os
import json
import streamlit as st
from engines import PlannerEngine, CalculatorEngine, make_inputs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QA_PATH = os.path.join(BASE_DIR, "question_answer_logic_FINAL_UPDATED.json")
REC_PATH = os.path.join(BASE_DIR, "recommendation_logic_FINAL_MASTER_UPDATED.json")

planner = PlannerEngine(str(QA_PATH), str(REC_PATH))
calculator = CalculatorEngine()

st.set_page_config(page_title="CCA Decision Support", layout="centered")
st.title("Care Planning Tool")

if "step" not in st.session_state:
    st.session_state.step = "audience"
if "people" not in st.session_state:
    st.session_state.people = []
if "planner_results" not in st.session_state:
    st.session_state.planner_results = {}
if "calc_inputs" not in st.session_state:
    st.session_state.calc_inputs = {}

if st.session_state.step == "audience":
    st.header("Before we begin")
    primary = st.text_input("Who are we planning care for?", value="Person A")
    if st.button("Continue"):
        st.session_state.people = [{"id": "A","display_name": primary,"relationship": "self"}]
        st.session_state.primary_name = primary
        st.session_state.step = "add_spouse"
        st.rerun()

elif st.session_state.step == "add_spouse":
    primary = st.session_state.primary_name
    st.markdown(f"""
    If **{primary}** needs to leave the home for assisted living or memory care, 
    their spouse/partner may also need to consider some in-home help.  

    Would you like to evaluate a care support plan for a spouse or partner now so the household picture is complete.
    """)
    add = st.checkbox("Yes, I want to evaluate a plan for a spouse/partner",value=False,key="care_partner_add")
    if add:
        st.text_input("Spouse/partner name",value="",placeholder="Enter spouse/partner name",key="care_partner_name")
    c1, c2 = st.columns(2)
    with c1:
        if st.button(f"No, let's just plan for **{primary}**"):
            st.session_state.step = "planner"; st.rerun()
    with c2:
        btn_disabled = not st.session_state.get("care_partner_add", False)
        if st.button("Add spouse/partner and continue", disabled=btn_disabled):
            st.session_state.people.append({"id": "B","display_name": st.session_state.get("care_partner_name") or "Spouse/Partner","relationship": "spouse"})
            st.session_state.step = "planner"; st.rerun()

elif st.session_state.step == "planner":
    st.header("Care Plan")
    for person in st.session_state.people:
        st.subheader(f"{person['display_name']}")
        questions = planner.questions; answers = {}
        for q in questions:
            key = f"{person['id']}_{q['id']}"
            if q["type"] == "radio": answers[q["id"]] = st.radio(q["text"], q["options"], key=key)
            elif q["type"] == "selectbox": answers[q["id"]] = st.selectbox(q["text"], q["options"], key=key)
            elif q["type"] == "text": answers[q["id"]] = st.text_input(q["text"], key=key)
        if st.button(f"Finish {person['display_name']}’s Care Plan"):
            res = planner.run(answers)
            if hasattr(res, "__dict__"):
                care_type = getattr(res,"care_type",None); flags=set(getattr(res,"flags",set()) or set())
                scores = getattr(res,"scores",{}) or {}; reasons=list(getattr(res,"reasons",[]) or [])
                narrative=(getattr(res,"message_rendered",None)or getattr(res,"message",None)or getattr(res,"advisory",None)or getattr(res,"narrative",None))
            else:
                care_type=res.get("care_type"); flags=set(res.get("flags",[]))
                scores=res.get("scores",{}) or {}; reasons=list(res.get("reasons",[]))
                narrative=(res.get("message_rendered")or res.get("message")or res.get("advisory")or res.get("narrative"))
            st.session_state.planner_results[person["id"]]={"care_type": care_type,"flags": sorted(list(flags)),"scores": scores,"reasons": reasons,"advisory": narrative}
            st.session_state.step="recommendations"; st.rerun()

elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without redoing questions.")
    for p in st.session_state.people:
        rec = st.session_state.planner_results.get(p["id"], {})
        default = rec.get("care_type", "in_home")
        st.subheader(f"{p['display_name']}: {default.replace('_',' ').title()} (recommended)")
        for r in rec.get("reasons", []) or []: st.write("• " + str(r))
        narrative=(rec.get("advisory") or rec.get("message_rendered") or rec.get("message") or rec.get("narrative"))
        if narrative: st.info(narrative)
        st.selectbox(f"Care scenario for {p['display_name']}",["In-home Care","Assisted Living","Memory Care","No Care Needed"],index=["in_home","assisted_living","memory_care","none"].index(default) if default in ["in_home","assisted_living","memory_care","none"] else 0,key=f"scenario_{p['id']}")
    if st.button("See Costs"): st.session_state.step="calculator"; st.rerun()

elif st.session_state.step == "calculator":
    st.header("Cost Calculator"); st.caption("Estimate costs based on care type and household inputs.")
    inputs = make_inputs(**st.session_state.calc_inputs); res = calculator.run(inputs)
    st.write("### Estimated Monthly Cost"); st.metric("Monthly", f"${res['monthly_cost']:,.0f}"); st.metric("Annual", f"${res['annual_cost']:,.0f}")
    if st.button("Back to Recommendations"): st.session_state.step="recommendations"; st.rerun()
