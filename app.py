
from pathlib import Path
from types import SimpleNamespace
import traceback
import streamlit as st

from engines import PlannerEngine, CalculatorEngine, make_inputs

# ----- Paths -----
ROOT = Path(__file__).resolve().parent
QA_PATH = ROOT / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = ROOT / "recommendation_logic_FINAL_MASTER_UPDATED.json"

# ----- Init -----
try:
    planner = PlannerEngine(str(QA_PATH), str(REC_PATH))
    calculator = CalculatorEngine()
except Exception as e:
    st.error("Failed to initialize engines.")
    st.code(traceback.format_exc())
    st.stop()

st.set_page_config(page_title="Senior Navigator • Planner + Cost", page_icon="🧭", layout="centered")
st.title("Senior Navigator")

# ----- Session -----
def reset_all():
    for k in list(st.session_state.keys()):
        if not k.startswith("_"):
            del st.session_state[k]
    st.session_state.step = "intro"

if "step" not in st.session_state:
    st.session_state.step = "intro"

st.sidebar.button("Start over", on_click=reset_all)

# ================= Steps =================

# Intro
if st.session_state.step == "intro":
    st.markdown("""
Choosing senior living or in-home support can feel overwhelming. This tool breaks it down:
1) Guided Care Plan → we recommend a care type
2) Costs → estimate monthly costs for the scenario
3) Optional Household → income, VA, assets
4) Breakdown → a clear summary
""")
    if st.button("Start"):
        st.session_state.step = "audience"
        st.rerun()

# Audience
elif st.session_state.step == "audience":
    st.header("Who is this plan for?")
    role = st.radio("Select one:", ["Myself", "My spouse/partner", "My parent", "Both parents", "Someone else"])

    if role == "Both parents":
        c1, c2 = st.columns(2)
        with c1:
            n1 = st.text_input("Parent 1 name", value="Mom", key="p1_name", placeholder="Enter name")
        with c2:
            n2 = st.text_input("Parent 2 name", value="Dad", key="p2_name", placeholder="Enter name")
        if st.button("Continue"):
            st.session_state.people = [
                {"id": "A", "display_name": n1 or "Parent 1", "relationship": "parent"},
                {"id": "B", "display_name": n2 or "Parent 2", "relationship": "parent"},
            ]
            st.session_state.current_person = 0
            st.session_state.step = "both_parents_intro"
            st.rerun()
    else:
        default = "Alex" if role != "My parent" else "Mom"
        n = st.text_input("Name", value=default, key="p_name", placeholder="Enter name")
        map_rel = {"Myself": "self", "My spouse/partner": "spouse", "My parent": "parent", "Someone else": "other"}
        if st.button("Continue"):
            st.session_state.people = [{"id": "A", "display_name": n or default, "relationship": map_rel.get(role, "other")}]
            st.session_state.current_person = 0
            st.session_state.role = role
            # Single-person flow gets the spouse interstitial
            st.session_state.step = "partner_context" if role in ("Myself", "My parent", "My spouse/partner") else "planner"
            st.rerun()

# Interstitial: both parents context
elif st.session_state.step == "both_parents_intro":
    names = [p["display_name"] for p in st.session_state.get("people", [])]
    a = names[0] if names else "Parent 1"
    b = names[1] if len(names) > 1 else "Parent 2"
    st.header("We’ll plan for both parents")
    st.markdown(f"We’ll start with **{a}**, then **{b}**. After both care plans, we’ll review household costs together.")
    if st.button("Start care questions"):
        st.session_state.step = "planner"
        st.rerun()

# Interstitial: optional spouse for single-person flow
elif st.session_state.step == "partner_context":
    people = st.session_state.get("people", [])
    primary = people[0]["display_name"] if people else "Person A"
    st.header("Before we begin")
    st.markdown(f"""
If **{primary}** needs assisted living or memory care, their spouse/partner may also need in‑home help.
Would you like to include a simple support plan for them so the household picture is complete?
""")
    add = st.checkbox("Yes, include a spouse/partner", value=False, key="care_partner_add")
    if add:
        st.text_input("Spouse/partner name", value="", placeholder="Enter spouse/partner name", key="care_partner_name")
    c1, c2 = st.columns(2)
    with c1:
        if st.button(f"No, just plan for **{primary}**"):
            st.session_state.step = "planner"
            st.rerun()
    with c2:
        if st.button("Add spouse/partner and continue", disabled=not st.session_state.get("care_partner_add", False)):
            st.session_state.people.append({
                "id": "B",
                "display_name": st.session_state.get("care_partner_name") or "Spouse/Partner",
                "relationship": "spouse"
            })
            st.session_state.step = "planner"
            st.rerun()

# Planner (one question at a time, per person)
elif st.session_state.step == "planner":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if not people or i >= len(people):
        st.session_state.step = "recommendations"
        st.rerun()

    person = people[i]
    pid = person["id"]
    name = person["display_name"]
    st.header(f"Care Plan Questions for {name}")

    # Wizard state per person
    ws_key = f"wiz_{pid}"
    ws = st.session_state.get(ws_key) or {"idx": 0, "answers": {}}
    st.session_state[ws_key] = ws

    questions = planner.questions
    total_q = len(questions)
    idx = max(0, min(int(ws.get("idx", 0)), total_q - 1))

    # Render one question
    q = questions[idx]
    ak = f"{pid}_{q.get('id', f'q{idx+1}')}"
    a_map = q.get("answers") or {}
    # Build options in indexed order if using numbered keys, otherwise use values list
    if isinstance(a_map, dict) and a_map:
        try:
            ordered_keys = [str(n) for n in sorted(map(int, a_map.keys()))]
            options = [a_map[k] for k in ordered_keys]
        except Exception:
            options = list(a_map.values())
    else:
        options = q.get("options") or []

    answer_label = st.radio(q.get("question") or q.get("text") or f"Question {idx+1}", options, key=ak)
    ws["answers"][q.get("id", f"q{idx+1}")] = answer_label
    st.progress((idx + 1) / max(1, total_q))

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Back", disabled=(idx == 0)):
            ws["idx"] = max(0, idx - 1); st.rerun()
    with c2:
        if st.button("Next", disabled=(idx >= total_q - 1)):
            ws["idx"] = min(total_q - 1, idx + 1); st.rerun()
    with c3:
        if st.button("Finish this person", disabled=(idx < total_q - 1)):
            # Attach meta for personalization
            ws["answers"]["_person_name"] = name
            try:
                res = planner.run(ws["answers"])
            except Exception:
                st.error("PlannerEngine.run failed."); st.stop()
            st.session_state.setdefault("planner_results", {})[pid] = {
                "care_type": res.care_type,
                "flags": sorted(list(res.flags)),
                "scores": res.scores,
                "reasons": res.reasons,
                "advisory": res.narrative,
            }
            # Move to next person or recommendations with interstitial between people
            if i + 1 < len(people):
                st.session_state["current_person"] = i + 1
                st.session_state["next_person_name"] = people[i + 1]["display_name"]
                st.session_state.step = "person_switch"
            else:
                st.session_state.step = "recommendations"
            st.rerun()

# Interstitial between people
elif st.session_state.step == "person_switch":
    nxt = st.session_state.get("next_person_name", "Next person")
    st.header("Great — first care plan complete")
    st.markdown(f"Next we’ll assess **{nxt}**. This will take just a few minutes.")
    if st.button("Start next care plan"):
        st.session_state.step = "planner"
        st.rerun()

# Recommendations
elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without redoing questions.")
    choices = ["in_home", "assisted_living", "memory_care", "none"]
    labels = {"in_home": "In-home Care", "assisted_living": "Assisted Living", "memory_care": "Memory Care", "none": "No Care Needed"}

    for p in st.session_state.get("people", []):
        rec = st.session_state.get("planner_results", {}).get(p["id"], {})
        default = rec.get("care_type", "in_home")
        st.subheader(f"{p['display_name']}: {labels.get(default, default.replace('_',' ').title())} (recommended)")

        for r in rec.get("reasons", []):
            st.write("• " + str(r))

        narrative = rec.get("advisory") or rec.get("message_rendered") or rec.get("message") or rec.get("narrative")
        if narrative:
            st.info(narrative)

        idx = choices.index(default) if default in choices else 0
        sel = st.selectbox(f"Care scenario for {p['display_name']}", [labels[c] for c in choices], index=idx, key=f"override_{p['id']}")
        # Store override back as canonical key
        rev = {v: k for k, v in labels.items()}
        st.session_state.setdefault("care_overrides", {})[p["id"]] = rev.get(sel, default)

    if st.button("See Costs"):
        st.session_state.step = "calculator"
        st.rerun()

# Calculator (very light; your real calculator UI lives elsewhere)
elif st.session_state.step == "calculator":
    st.header("Cost Planner")
    total = 0
    for p in st.session_state.get("people", []):
        pid = p["id"]
        name = p["display_name"]
        care_type = st.session_state.get("care_overrides", {}).get(pid) or st.session_state.get("planner_results", {}).get(pid, {}).get("care_type", "in_home")
        st.subheader(f"{name} — {care_type.replace('_',' ').title()}")

        inp = make_inputs(care_type=care_type)
        if care_type == "in_home":
            h = st.slider(f"In-home care hours per day — {name}", 0, 24, 4, 1, key=f"{pid}_hours")
            d = st.slider(f"Days of care per month — {name}", 0, 31, 20, 1, key=f"{pid}_days")
            setattr(inp, "in_home_hours_per_day", int(h))
            setattr(inp, "in_home_days_per_month", int(d))

        # Compute monthly
        try:
            monthly = calculator.monthly_cost(inp)
        except Exception:
            st.error("CalculatorEngine failed."); st.stop()
        st.metric("Estimated Monthly Cost", f"${int(monthly):,}")
        total += int(monthly)
        st.divider()

    st.subheader("Combined Total")
    st.metric("Estimated Combined Monthly Cost", f"${total:,.0f}")
    if st.button("Back to recommendations"):
        st.session_state.step = "recommendations"; st.rerun()
