
import streamlit as st
from pathlib import Path
from engines import PlannerEngine, CalculatorEngine, PlannerResult, CalcInputs
import math

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
            'combined_monthly_cost','household_values','mobility_raw','care_overrides',
            'va_cache','care_partner_add'
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
        st.session_state.care_overrides = {}
        st.session_state.step = 'care_partner_context'  # interstitial before planner
        st.rerun()

# ---------- Care Partner Interstitial ----------
elif st.session_state.step == 'care_partner_context':
    people = st.session_state.get('people', [])
    single = len(people) == 1
    primary = people[0]['display_name'] if people else 'Person A'

    st.header('Before we begin the care plan')
    st.markdown(f"""
Many families find that when **{primary}** needs assisted living or memory care, their spouse or partner also needs some support at home.
If that could be your situation, you can add a simple in-home care plan for the spouse/partner now. It helps you see the **whole household** picture without redoing anything later.
""")
    add_partner = False
    partner_name = ''
    if single:
        add_partner = st.checkbox("Also create a support plan for the spouse/partner", value=False, key='care_partner_add')
        if add_partner:
            partner_name = st.text_input("Spouse/partner name", value="Spouse/Partner", key='care_partner_name')

    cols = st.columns(2)
    with cols[0]:
        if st.button('Skip, start care questions'):
            st.session_state.step = 'planner'
            st.rerun()
    with cols[1]:
        if st.button('Add spouse/partner and continue'):
            if single and st.session_state.get('care_partner_add'):
                # Append a simple second person
                new_id = 'B'
                name = st.session_state.get('care_partner_name') or 'Spouse/Partner'
                st.session_state.people.append({'id': new_id, 'display_name': name, 'relationship': 'spouse'})
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
                # go back to interstitial instead of audience
                st.session_state.step = 'care_partner_context'
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

# ---------- Recommendations ----------
elif st.session_state.step == 'recommendations':
    st.header('Our Recommendation')
    st.caption('You can proceed with the recommended option, or explore another scenario without redoing questions.')

    for p in st.session_state.people:
        rec = st.session_state.planner_results[p['id']]
        default = rec['care_type']
        st.subheader(f"{p['display_name']}: {default.replace('_',' ').title()} (recommended)")
        for r in rec.get('reasons', []):
            st.write('• ' + r)
        if rec.get('advisory'):
            st.info(rec['advisory'])

        # Scenario override selector
        care_choices = ['in_home','assisted_living','memory_care']
        pretty = {'in_home':'In-home Care','assisted_living':'Assisted Living','memory_care':'Memory Care'}
        choice = st.selectbox(f"Care scenario for {p['display_name']}",
                              [pretty[c] for c in care_choices],
                              index=care_choices.index(default),
                              key=f"override_{p['id']}",
                              help='Start with the recommendation, or choose a different scenario to compare.')
        # Save override as raw key
        rev = {v:k for k,v in pretty.items()}
        st.session_state.care_overrides[p['id']] = rev[choice]

        st.divider()

    if st.button('See Costs'):
        st.session_state.step = 'calculator'
        st.rerun()

# ---------- Calculator (same as prior build) ----------
elif st.session_state.step == 'calculator':
    st.header('Cost Planner')
    state = st.selectbox('Location', ['National','Washington','California','Texas','Florida'],
                         help='State averages adjust typical market rates.')

    total = 0
    for p in st.session_state.people:
        rec = st.session_state.planner_results[p['id']]
        pid = p['id']
        # Use override if set
        care_type = st.session_state.get('care_overrides', {}).get(pid, rec['care_type'])

        st.subheader(f"{p['display_name']} — Scenario: {care_type.replace('_',' ').title()} (recommendation: {rec['care_type'].replace('_',' ').title()})")

        # Allow switching scenario here too
        care_choices = ['in_home','assisted_living','memory_care']
        pretty = {'in_home':'In-home Care','assisted_living':'Assisted Living','memory_care':'Memory Care'}
        scenario_label = st.selectbox(f"Care scenario for {p['display_name']} (adjust here if needed)",
                                      [pretty[c] for c in care_choices],
                                      index=care_choices.index(care_type),
                                      key=f"calc_override_{pid}",
                                      help='Change the scenario without redoing questions.')
        care_type_new = {v:k for k,v in pretty.items()}[scenario_label]
        if care_type_new != care_type:
            st.session_state.care_overrides[pid] = care_type_new
            for k in [f"{pid}_room", f"{pid}_hours"]:
                if k in st.session_state: del st.session_state[k]
            care_type = care_type_new

        # Map planner mobility to default
        raw_mob = st.session_state.get('mobility_raw', {}).get(pid)
        mobility_prefill = 'Independent'
        if raw_mob in (2, 3): mobility_prefill = 'Assisted'
        if raw_mob == 4: mobility_prefill = 'Non-ambulatory'

        # Care Level dropdown
        default_care_level = 'High' if ('severe_cognitive_decline' in rec['flags'] or care_type=='memory_care') else 'Medium'
        care_level = st.selectbox('Care Level (staffing intensity)',
                                  ['Low','Medium','High'],
                                  index=['Low','Medium','High'].index(default_care_level),
                                  key=f"{pid}_care_level",
                                  help='Higher care levels reflect more hands-on support and supervision.')

        # Mobility dropdown with parenthetical
        mobility_options = ['Independent (no device)',
                            'Assisted (cane/walker or needs help)',
                            'Non-ambulatory (wheelchair/bedbound)']
        mobility_map_out = {
            'Independent (no device)':'Independent',
            'Assisted (cane/walker or needs help)':'Assisted',
            'Non-ambulatory (wheelchair/bedbound)':'Non-ambulatory'
        }
        prefill_label = {'Independent':'Independent (no device)',
                         'Assisted':'Assisted (cane/walker or needs help)',
                         'Non-ambulatory':'Non-ambulatory (wheelchair/bedbound)'}[mobility_prefill]
        mobility_label = st.selectbox('Mobility', mobility_options,
                                      index=mobility_options.index(prefill_label),
                                      key=f"{pid}_mobility",
                                      help='Mobility affects staffing and environmental needs.')
        mobility = mobility_map_out[mobility_label]

        # Chronic conditions with context
        chronic_options = ['None (no ongoing conditions)',
                           'Some (1–2 manageable conditions)',
                           'Multiple/Complex (several or complex needs)']
        chronic_map_out = {
            chronic_options[0]:'None',
            chronic_options[1]:'Some',
            chronic_options[2]:'Multiple/Complex'
        }
        default_chronic_label = chronic_options[2] if 'severe_cognitive_decline' in rec['flags'] else chronic_options[1]
        chronic_label = st.selectbox('Chronic Conditions', chronic_options,
                                     index=chronic_options.index(default_chronic_label),
                                     key=f"{pid}_chronic",
                                     help='Select the best description of ongoing medical conditions.')
        chronic = chronic_map_out[chronic_label]

        inp = CalcInputs(state=state, care_type=care_type, care_level=care_level, mobility=mobility, chronic=chronic)

        # Room vs hours, with help text and state clearing
        if care_type in ['assisted_living','memory_care']:
            if f"{pid}_hours" in st.session_state: del st.session_state[f"{pid}_hours"]
            room = st.selectbox('Room Type', ['Studio','1 Bedroom','Shared'],
                                key=f"{pid}_room",
                                help='Typical base rates vary by room size and privacy.')
            inp.room_type = room
        else:
            if f"{pid}_room" in st.session_state: del st.session_state[f"{pid}_room"]
            hours = st.slider('In-home care hours per day', 0, 24, 6, 1,
                              key=f"{pid}_hours",
                              help='Total paid caregiver hours per day.')
            inp.in_home_hours_per_day = int(hours)

        monthly = calculator.monthly_cost(inp)
        st.metric('Estimated Monthly Cost', f"${monthly:,.0f}")
        if 'va_cache' not in st.session_state: st.session_state.va_cache = {}
        st.session_state.va_cache[pid] = {'care_cost': monthly}
        total += monthly
        st.divider()

    st.subheader('Combined Total')
    st.session_state.combined_monthly_cost = total
    st.metric('Estimated Combined Monthly Cost', f"${total:,.0f}")
    st.info('These are planning estimates. Adjust settings to explore scenarios.')

    if st.button('Add Household & Assets (optional)'):
        st.session_state.step = 'household'
        st.rerun()

# ---------- Household & Assets (VA wizard retained from prior build) ----------
elif st.session_state.step == 'household':
    st.write("Household & VA wizard unchanged here; use previous VA build file if needed.")
