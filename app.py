
import streamlit as st
from pathlib import Path
from engines import PlannerEngine, CalculatorEngine, PlannerResult, CalcInputs

planner = PlannerEngine()
calculator = CalculatorEngine()

st.set_page_config(page_title='Senior Navigator • Planner + Cost', page_icon='🧭', layout='centered')

DATA_DIR = Path(__file__).resolve().parent / "data"
if not DATA_DIR.exists():
    st.error("Missing required `data/` folder with JSON files.")
    st.stop()

def reset_all():
    for k in list(st.session_state.keys()):
        if k.startswith("A_") or k.startswith("B_") or k in (
            'step','people','answers','planner_results','current_person',
            'combined_monthly_cost','household_values','mobility_raw','care_overrides'
        ):
            del st.session_state[k]

if 'step' not in st.session_state:
    st.session_state.step = 'intro'

st.sidebar.title('Senior Navigator')
st.sidebar.caption('Planner → Costs')
st.sidebar.button('Start over', on_click=reset_all)

# ---------- Intro ----------
if st.session_state.step == 'intro':
    st.title("Let's take this one step at a time")
    st.markdown("""
Choosing senior living or in-home support can feel overwhelming.  
This tool is here to make it easier.

It's based on years of experience helping families make these decisions.  
We'll start with a few simple questions about you or your loved one,  
then we'll recommend a care option and walk through the costs.

**There are no right or wrong answers. Just answer as best you can.**  
We'll guide you every step of the way.
""")
    st.info('This process usually takes about 10–15 minutes. You can pause at any point.')
    if st.button('Start'):
        st.session_state.step = 'audience'
        st.rerun()

# ---------- Audiencing ----------
elif st.session_state.step == 'audience':
    st.header('Who are we creating this plan for?')
    choice = st.radio('Select one:', ['Myself','My spouse/partner','My parent','Both parents','Someone else'])

    people = []
    if choice == 'Both parents':
        c1, c2 = st.columns(2)
        with c1:
            name1 = st.text_input('Parent 1 name', value='Mom', key='p1_name')
            _ = st.selectbox('Parent 1 age', ['65–74','75–84','85+'], key='p1_age')
        with c2:
            name2 = st.text_input('Parent 2 name', value='Dad', key='p2_name')
            _ = st.selectbox('Parent 2 age', ['65–74','75–84','85+'], key='p2_age')
        people = [
            {'id':'A','display_name':name1,'relationship':'parent'},
            {'id':'B','display_name':name2,'relationship':'parent'}
        ]
    else:
        default = 'Alex' if choice != 'My parent' else 'Mom'
        name = st.text_input('Name', value=default, key='p_name')
        _ = st.selectbox('Approximate age', ['65–74','75–84','85+'], key='p_age')
        rel_map = {'Myself':'self','My spouse/partner':'spouse','My parent':'parent','Someone else':'other'}
        people = [{'id':'A','display_name':name,'relationship':rel_map.get(choice,'other')}]

    st.caption("When you're ready, we'll move into the care plan questions.")
    if st.button('Continue'):
        st.session_state.people = people
        st.session_state.current_person = 0
        st.session_state.answers = {}
        st.session_state.planner_results = {}
        st.session_state.mobility_raw = {}
        st.session_state.care_overrides = {}  # per-person override of care type
        st.session_state.step = 'planner'
        st.rerun()

# ---------- Planner ----------
elif st.session_state.step == 'planner':
    people = st.session_state.get('people', [])
    i = st.session_state.get('current_person', 0)
    person = people[i]
    name = person['display_name']

    st.header(f"Care Plan Questions for {name}")
    st.caption(f"Person {i+1} of {len(people)}")
    st.markdown(f"Answer the following for **{name}**.")

    answers = st.session_state.answers.get(person['id'], {})
    qa = planner.qa

    mobility_q_index = None
    for idx, q in enumerate(qa.get('questions', []), start=1):
        if 'mobility' in q.get('question','').lower():
            mobility_q_index = idx
        val = answers.get(f'q{idx}')
        label = f"{q['question']} (for {name})"
        sel = st.radio(
            label,
            options=[1,2,3,4],
            format_func=lambda n, q=q: q['answers'][str(n)],
            index=(val-1) if val else 0,
            key=f"{person['id']}_q{idx}",
            help=q.get('help')
        )
        answers[f'q{idx}'] = sel

    if mobility_q_index is not None:
        st.session_state.mobility_raw[person['id']] = answers.get(f"q{mobility_q_index}")

    # Conditional
    def infer_flags(ans: dict) -> set:
        f = set()
        for idx, q in enumerate(qa.get('questions', []), start=1):
            a = ans.get(f'q{idx}')
            if a is None: continue
            for _, rules in q.get('trigger', {}).items():
                for rule in rules:
                    if rule.get('answer') == a:
                        f.add(rule.get('flag'))
        return f

    flags = infer_flags(answers)
    conditional_answer = None
    if 'severe_cognitive_decline' in flags and qa.get('conditional_questions'):
        cq = qa['conditional_questions'][0]
        st.warning('It looks like 24/7 supervision may be needed.')
        conditional_answer = st.radio(cq['question'], options=[1,2],
                                      format_func=lambda n: cq['answers'][str(n)],
                                      key=f"{person['id']}_q9",
                                      help=cq.get('help'))

    st.session_state.answers[person['id']] = answers

    c1, c2 = st.columns(2)
    with c1:
        if st.button('Back'):
            if i == 0:
                st.session_state.step = 'audience'
            else:
                st.session_state.current_person = i-1
            st.rerun()
    with c2:
        if st.button('Next'):
            result: PlannerResult = planner.run(answers, conditional_answer=conditional_answer)
            st.session_state.planner_results[person['id']] = {
                'care_type': result.care_type,
                'flags': result.flags,
                'scores': result.scores,
                'reasons': result.reasons,
                'advisory': result.advisory
            }
            if i+1 < len(people):
                st.session_state.current_person = i+1
                st.rerun()
            else:
                st.session_state.step = 'recommendations'
                st.rerun()
