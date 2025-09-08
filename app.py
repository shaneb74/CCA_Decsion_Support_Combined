# app.py — Orchestrator. Engines hold all logic; UI just conducts.
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import traceback
import streamlit as st

st.set_page_config(page_title="Senior Navigator", page_icon="🧭", layout="centered")

ROOT = Path(__file__).resolve().parent
QA_PATH = ROOT / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = ROOT / "recommendation_logic_FINAL_MASTER_UPDATED.json"

try:
    from engines import PlannerEngine, CalculatorEngine, PlannerResult
except Exception:
    st.error("Failed to import engines.")
    st.code(traceback.format_exc())
    st.stop()

try:
    import cost_controls
except Exception:
    cost_controls = None

def make_inputs(**kw):
    obj = SimpleNamespace()
    for k,v in kw.items():
        setattr(obj, k, v)
    return obj

def reset():
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.session_state.step = "intro"

if "step" not in st.session_state:
    st.session_state.step = "intro"

st.sidebar.button("Start over", on_click=reset)

try:
    planner = PlannerEngine(str(QA_PATH), str(REC_PATH))
    calculator = CalculatorEngine()
except Exception:
    st.error("Engine init failed.")
    st.code(traceback.format_exc())
    st.stop()

if st.session_state.step == "intro":
    st.title("Let’s take this one step at a time")
    st.markdown("1) Quick questions → 2) Recommendation → 3) Costs → 4) Household")
    if st.button("Start"):
        st.session_state.step = "audience"
        st.rerun()

elif st.session_state.step == "audience":
    st.header("Who is this plan for?")
    role = st.radio("Select one:", ["My parent", "Both parents", "Myself", "My spouse/partner", "Someone else"], index=0)
    people = []
    if role == "Both parents":
        c1,c2 = st.columns(2)
        with c1: n1 = st.text_input("Parent 1", "Mom")
        with c2: n2 = st.text_input("Parent 2", "Dad")
        people = [{"id":"A","display_name":n1,"relationship":"parent"},
                  {"id":"B","display_name":n2,"relationship":"parent"}]
    else:
        default = {"My parent":"Mom","Myself":"Me","My spouse/partner":"Partner","Someone else":"Care Recipient"}[role]
        n = st.text_input("Name", default)
        rel = {"My parent":"parent","Myself":"self","My spouse/partner":"spouse","Someone else":"other"}[role]
        people = [{"id":"A","display_name":n,"relationship":rel}]
    if st.button("Continue"):
        st.session_state.people = people
        st.session_state.current_person = 0
        st.session_state.results = {}
        st.session_state.step = "planner"
        st.rerun()

elif st.session_state.step == "planner":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if i >= len(people):
        st.session_state.step = "recommendations"
        st.rerun()
    person = people[i]
    pid, name = person["id"], person["display_name"]

    st.header(f"Care Assessment — {name}")
    answers = {}
    for idx, q in enumerate(planner.qa.get("questions", []), start=1):
        amap = q.get("answers", {})
        if not isinstance(amap, dict) or not amap:
            continue
        keys = list(amap.keys())
        try:
            ordered = [str(k) for k in sorted(int(k) for k in keys)]
        except Exception:
            ordered = list(keys)
        labels = [amap[k] for k in ordered]
        sel = st.radio(q["question"], labels, key=f"{pid}_q{idx}")
        answers[f"q{idx}"] = int(ordered[labels.index(sel)])

    if st.button("Finish"):
        try:
            res = planner.run(answers, name=name)
        except Exception:
            st.error("PlannerEngine.run failed.")
            st.code(traceback.format_exc())
            st.stop()
        st.session_state.results[pid] = res
        st.session_state.current_person = i + 1
        if st.session_state.current_person >= len(people):
            st.session_state.step = "recommendations"
        else:
            st.session_state.step = "person_transition"
        st.rerun()

elif st.session_state.step == "person_transition":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    name = people[i]["display_name"]
    st.header("Great — first plan saved.")
    st.info(f"Now let’s assess **{name}**.")
    if st.button(f"Start {name}'s care plan"):
        st.session_state.step = "planner"
        st.rerun()

elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("You can start with the recommended scenario or switch and continue.")

    overrides = st.session_state.get("care_overrides", {})
    for p in st.session_state.get("people", []):
        pid = p["id"]; name = p["display_name"]
        res = st.session_state.results.get(pid)
        if not isinstance(res, PlannerResult):
            st.error(f"No result for {name}")
            continue

        nice = {"none":"None","in_home":"In-home Care","assisted_living":"Assisted Living","memory_care":"Memory Care"}
        st.subheader(f"{name}: {nice.get(res.care_type, res.care_type).title()} (recommended)")
        if res.reasons:
            with st.expander("Why this recommendation", expanded=False):
                for r in res.reasons:
                    st.write("• " + str(r))
        if res.narrative:
            st.info(res.narrative)

        options = ["none","in_home","assisted_living","memory_care"]
        idx = options.index(res.care_type) if res.care_type in options else 0
        label = st.selectbox(f"Care scenario for {name}", [nice[o] for o in options], index=idx, key=f"ov_{pid}")
        reverse = {v:k for k,v in nice.items()}
        overrides[pid] = reverse[label]
    st.session_state.care_overrides = overrides

    c1,c2 = st.columns(2)
    with c1:
        if st.button("Back"):
            st.session_state.step = "planner"
            st.rerun()
    with c2:
        if st.button("See Costs"):
            st.session_state.step = "calculator"
            st.rerun()

elif st.session_state.step == "calculator":
    st.header("Cost Planner")
    if not cost_controls:
        st.error("cost_controls.py missing.")
        st.stop()

    cost_controls.render_location_control()  # single shared control
    total = cost_controls.render_costs_for_active_recommendations(planner=planner, calculator=calculator)

    st.subheader("Combined Total")
    st.metric("Estimated Combined Monthly Cost", f"${total:,.0f}")

    c1,c2,c3 = st.columns(3)
    with c1:
        if st.button("Back to recommendations"):
            st.session_state.step = "recommendations"
            st.rerun()
    with c2:
        if st.button("Add Household & Assets"):
            st.session_state.step = "household"
            st.rerun()
    with c3:
        if st.button("Finish"):
            st.session_state.step = "intro"
            st.rerun()

elif st.session_state.step == "household":
    st.header("Household & Budget (optional)")
    st.write("Handled by asset_engine in your repo.")

else:
    reset()
    st.rerun()
