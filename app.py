
# app.py
import streamlit as st
from pathlib import Path
from engines import PlannerEngine, CalculatorEngine, PlannerResult, CalcInputs

# Engines
planner = PlannerEngine()
calculator = CalculatorEngine()

# Setup
DATA_DIR = Path(__file__).resolve().parent / "data"
st.set_page_config(page_title='Senior Navigator • Planner + Cost', page_icon='🧭', layout='centered')
if not DATA_DIR.exists():
    st.error("Missing required `data/` folder with JSON files.")
    st.stop()

def reset_all():
    for k in ['step','people','answers','planner_results','current_person','combined_monthly_cost','household_values','mobility_raw']:
        if k in st.session_state:
            del st.session_state[k]

if 'step' not in st.session_state:
    st.session_state.step = 'intro'

st.sidebar.title('Senior Navigator')
st.sidebar.caption('Planner → Costs')
st.sidebar.button('Start over', on_click=reset_all)

# ---------- Step 0: Intro ----------
if st.session_state.step == 'intro':
    st.title('Let\'s take this one step at a time')
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

# ---------- Step 1: Audiencing ----------
elif st.session_state.step == 'audience':
    st.header('Who are we creating this plan for?')
    st.markdown('To give you the best recommendation, we need to know who this plan is for.')

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

    st.caption('When you\'re ready, we\'ll move into the care plan questions.')
    if st.button('Continue'):
        st.session_state.people = people
        st.session_state.current_person = 0
        st.session_state.answers = {}
        st.session_state.planner_results = {}
        st.session_state.mobility_raw = {}  # per-person raw mobility answer index
        st.session_state.step = 'planner'
        st.rerun()

# ---------- Step 2: Guided Care Plan ----------
elif st.session_state.step == 'planner':
    people = st.session_state.get('people', [])
    i = st.session_state.get('current_person', 0)
    person = people[i]

    st.header(f"Care Plan Questions for {person['display_name']}")
    st.caption(f"Person {i+1} of {len(people)}")
    st.markdown("These questions help us understand daily routines, health, and support. Answer as best you can.")

    answers = st.session_state.answers.get(person['id'], {})
    qa = planner.qa

    mobility_q_index = None
    for idx, q in enumerate(qa.get('questions', []), start=1):
        # Detect the mobility question by name
        if 'mobility' in q.get('question','').lower():
            mobility_q_index = idx

        val = answers.get(f'q{idx}')
        sel = st.radio(
            q['question'],
            options=[1,2,3,4],
            format_func=lambda n, q=q: q['answers'][str(n)],
            index=(val-1) if val else 0,
            key=f"{person['id']}_q{idx}"
        )
        answers[f'q{idx}'] = sel

    # Store raw mobility answer for calculator defaults
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
                                      key=f"{person['id']}_q9")

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

# ---------- Step 3: Recommendation Summary ----------
elif st.session_state.step == 'recommendations':
    st.header('Our Recommendation')
    for p in st.session_state.people:
        rec = st.session_state.planner_results[p['id']]
        st.subheader(f"{p['display_name']}: {rec['care_type'].replace('_',' ').title()}")
        for r in rec.get('reasons', []):
            st.write('• ' + r)
        st.success('This is a starting point. You’ll be able to adjust details next.')
        st.divider()

    st.markdown('Next, we’ll walk through costs step by step, so you can see what this care might mean for your household budget.')
    if st.button('See Costs'):
        st.session_state.step = 'calculator'
        st.rerun()

# ---------- Step 4: Calculator ----------
elif st.session_state.step == 'calculator':
    st.header('Cost Planner')
    state = st.selectbox('Location', ['National','Washington','California','Texas','Florida'])

    total = 0
    for p in st.session_state.people:
        rec = st.session_state.planner_results[p['id']]
        care_type = rec['care_type']

        st.subheader(f"{p['display_name']} — Recommended: {care_type.replace('_',' ').title()}")

        # Pull explicit mobility defaults from planner Q
        raw_mob = st.session_state.get('mobility_raw', {}).get(p['id'])
        # Mapping based on your instruction
        # 1: best/independent, 2: cane/walker, 3: assistance most movement, 4: mostly immobile/wheelchair
        mobility_prefill = 'Independent'
        if raw_mob in (2, 3):
            mobility_prefill = 'Assisted'
        if raw_mob == 4:
            mobility_prefill = 'Non-ambulatory'

        # Care level as dropdown (not slider)
        default_care_level = 'High' if ('severe_cognitive_decline' in rec['flags'] or care_type=='memory_care') else 'Medium'
        care_level = st.selectbox('Care Level', ['Low','Medium','High'],
                                  index=['Low','Medium','High'].index(default_care_level),
                                  key=f"{p['id']}_care_level")

        # Mobility dropdown with prefill from planner
        mobility = st.selectbox('Mobility', ['Independent','Assisted','Non-ambulatory'],
                                index=['Independent','Assisted','Non-ambulatory'].index(mobility_prefill),
                                key=f"{p['id']}_mobility")

        # Chronic conditions dropdown
        default_chronic = 'Multiple/Complex' if 'severe_cognitive_decline' in rec['flags'] else 'Some'
        chronic = st.selectbox('Chronic Conditions', ['None','Some','Multiple/Complex'],
                               index=['None','Some','Multiple/Complex'].index(default_chronic),
                               key=f"{p['id']}_chronic")

        inp = CalcInputs(state=state, care_type=care_type, care_level=care_level, mobility=mobility, chronic=chronic)

        if care_type in ['assisted_living','memory_care']:
            room = st.selectbox('Room Type', ['Studio','1 Bedroom','Shared'], key=f"{p['id']}_room")
            inp.room_type = room
        else:
            # In-home hours slider 0..24 step 1
            hours = st.slider('In-home care hours per day', 0, 24, 6, 1, key=f"{p['id']}_hours")
            inp.in_home_hours_per_day = int(hours)

        monthly = calculator.monthly_cost(inp)
        st.metric('Estimated Monthly Cost', f"${monthly:,.0f}")
        total += monthly
        st.divider()

    st.subheader('Combined Total')
    st.session_state.combined_monthly_cost = total
    st.metric('Estimated Combined Monthly Cost', f"${total:,.0f}")
    st.info('Remember, these are estimates to help you plan. You can explore different scenarios.')

    if st.button('Add Household & Assets (optional)'):
        st.session_state.step = 'household'
        st.rerun()

# ---------- Step 5: Household & Assets ----------
elif st.session_state.step == 'household':
    people = st.session_state.get('people', [])
    names = [p['display_name'] for p in people]
    nameA = names[0] if names else 'Person A'
    nameB = names[1] if len(names) > 1 else 'Person B'

    st.header('Household & Budget (optional)')
    st.markdown("These fields help you see affordability. If you don't have the details handy, you can skip this part.")

    values = st.session_state.get('household_values', {})

    def currency_input(label, key, default=0):
        return st.number_input(label, min_value=0, step=50, value=int(values.get(key, default)), key=key)

    # Monthly Income (expander)
    with st.expander('Monthly Income', expanded=True):
        if len(people) > 1:
            colA, colB = st.columns(2)
            with colA:
                a_ss = currency_input(f'Social Security — {nameA}', 'a_social_security', 0)
                a_pn = currency_input(f'Pension — {nameA}', 'a_pension', 0)
                a_other = currency_input(f'Other income — {nameA}', 'a_other_income', 0)
            with colB:
                b_ss = currency_input(f'Social Security — {nameB}', 'b_social_security', 0)
                b_pn = currency_input(f'Pension — {nameB}', 'b_pension', 0)
                b_other = currency_input(f'Other income — {nameB}', 'b_other_income', 0)
        else:
            a_ss = currency_input(f'Social Security — {nameA}', 'a_social_security', 0)
            a_pn = currency_input(f'Pension — {nameA}', 'a_pension', 0)
            a_other = currency_input(f'Other income — {nameA}', 'a_other_income', 0)
            b_ss = b_pn = b_other = 0

        household_other = currency_input('Household income (e.g., annuities, rental, investment)', 'household_income', 0)

    # Benefits
    with st.expander('Benefits (VA, Long-Term Care insurance)', expanded=False):
        if len(people) > 1:
            col1, col2 = st.columns(2)
            with col1:
                a_va = currency_input(f'VA benefit — {nameA}', 'a_va', 0)
                a_ltc = st.selectbox(f'Long-Term Care insurance — {nameA}', ['No','Yes'],
                                     index=0 if values.get('a_ltc','No')=='No' else 1, key='a_ltc')
            with col2:
                b_va = currency_input(f'VA benefit — {nameB}', 'b_va', 0)
                b_ltc = st.selectbox(f'Long-Term Care insurance — {nameB}', ['No','Yes'],
                                     index=0 if values.get('b_ltc','No')=='No' else 1, key='b_ltc')
        else:
            a_va = currency_input(f'VA benefit — {nameA}', 'a_va', 0)
            a_ltc = st.selectbox(f'Long-Term Care insurance — {nameA}', ['No','Yes'],
                                 index=0 if values.get('a_ltc','No')=='No' else 1, key='a_ltc')
            b_va = 0
            b_ltc = 'No'

    # Home decision
    with st.expander('Home decision', expanded=False):
        decision = st.selectbox('What will you do with the home?', ['Keep','Sell','HELOC','Reverse mortgage'], key='home_decision')
        st.session_state.household_values = st.session_state.get('household_values', {})
        st.session_state.household_values['home_decision'] = decision
        if decision == 'Keep':
            st.info('If you keep the home, include carrying costs below.')
        elif decision == 'Sell':
            st.info('If you sell the home, enter expected net proceeds under Assets.')
        elif decision == 'HELOC':
            st.info('If using a HELOC, include the monthly HELOC payment below and add remaining equity under Assets.')
        else:
            st.info('If using a reverse mortgage, include the monthly draw and/or fees as appropriate.')

    # Home carrying costs
    with st.expander('Home carrying costs', expanded=(st.session_state.get('household_values', {}).get('home_decision') == 'Keep')):
        mortgage = currency_input('Mortgage', 'mortgage', 0)
        taxes = currency_input('Property taxes', 'property_taxes', 0)
        ins = currency_input('Home insurance', 'home_insurance', 0)
        hoa = currency_input('HOA', 'hoa', 0)
        utils = currency_input('Utilities', 'utilities', 0)
        maint = currency_input('Maintenance', 'maintenance', 0)
        heloc = currency_input('HELOC payment (if applicable)', 'heloc_payment_monthly', 0)
        home_monthly = mortgage + taxes + ins + hoa + utils + maint + heloc

    # Home modifications
    with st.expander('Home modifications (if receiving in-home care)', expanded=False):
        any_in_home = any(st.session_state.planner_results[p['id']]['care_type']=='in_home' for p in st.session_state.people)
        if not any_in_home:
            st.caption('Modifications are typically most relevant when receiving in-home care.')
        mods = currency_input('Home modifications (monthlyized estimate)', 'home_modifications_monthly', 0)

    # Other monthly costs
    with st.expander('Other monthly costs (common)', expanded=False):
        medicare = currency_input('Medicare premiums', 'medicare_premiums', 0)
        dvh = currency_input('Dental/Vision/Hearing', 'dental_vision_hearing', 0)
        debts = currency_input('Other debts', 'other_debts_monthly', 0)
        phone = currency_input('Phone/Internet', 'optional_phone_internet', 0)
        personal = currency_input('Personal care', 'optional_personal_care', 0)
        travel = currency_input('Family travel', 'optional_family_travel', 0)
        auto = currency_input('Auto', 'optional_auto', 0)
        auto_ins = currency_input('Auto insurance', 'optional_auto_insurance', 0)
        pets = currency_input('Pet care', 'pet_care', 0)
        other_opt = currency_input('Other (optional)', 'optional_other', 0)
        optional_costs = home_monthly + medicare + dvh + mods + debts + phone + personal + travel + auto + auto_ins + pets + other_opt

    # Assets
    with st.expander('Assets', expanded=False):
        st.caption('Common liquid assets first, then less common items.')
        other_assets = currency_input('Other liquid assets (cash, savings, investments)', 'other_assets', 0)
        home_equity = currency_input('Home equity / net proceeds (if selling)', 'home_equity', 0)
        less_common = currency_input('Less common assets (e.g., annuities surrender value)', 'less_common_assets', 0)
        total_assets = other_assets + home_equity + less_common

    # Calculations
    _settings = calculator.settings
    _ltc_add = int(_settings.get('ltc_monthly_add', 1800))
    _cap_years = int(_settings.get('display_cap_years_funded', 30))

    monthly_income_individuals = (a_ss + a_pn + a_other) + (b_ss + b_pn + b_other)
    monthly_income_benefits = (a_va + ( _ltc_add if a_ltc=='Yes' else 0)) + (b_va + (_ltc_add if b_ltc=='Yes' else 0))
    monthly_income_household = household_other
    monthly_income = monthly_income_individuals + monthly_income_benefits + monthly_income_household

    combined_cost = st.session_state.get('combined_monthly_cost', 0)
    overall_monthly = combined_cost + optional_costs

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric('Monthly Care + Selected Costs', f"${overall_monthly:,.0f}")
    with c2:
        st.metric('Total Monthly Income', f"${monthly_income:,.0f}")
    with c3:
        gap = max(overall_monthly - monthly_income, 0)
        st.metric('Estimated Monthly Gap', f"${gap:,.0f}")

    years_funded = float('inf') if gap == 0 else min(_cap_years, round((total_assets / max(gap,1)) / 12, 1))
    st.metric('Years Funded (assets ÷ gap)', '∞' if gap == 0 else f"{years_funded} years")

    cols = st.columns(2)
    with cols[0]:
        if st.button('Back to Costs'):
            st.session_state.step = 'calculator'
            st.rerun()
    with cols[1]:
        st.success('You can adjust any values above to explore different scenarios.')
