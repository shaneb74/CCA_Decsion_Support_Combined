
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
    if single:
        add_partner = st.checkbox("Also create a support plan for the spouse/partner", value=False, key='care_partner_add')
        if add_partner:
            st.text_input("Spouse/partner name", value="Spouse/Partner", key='care_partner_name')

    cols = st.columns(2)
    with cols[0]:
        if st.button('Skip, start care questions'):
            st.session_state.step = 'planner'
            st.rerun()
    with cols[1]:
        if st.button('Add spouse/partner and continue'):
            if single and st.session_state.get('care_partner_add'):
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

        care_choices = ['in_home','assisted_living','memory_care']
        pretty = {'in_home':'In-home Care','assisted_living':'Assisted Living','memory_care':'Memory Care'}
        choice = st.selectbox(f"Care scenario for {p['display_name']}",
                              [pretty[c] for c in care_choices],
                              index=care_choices.index(default),
                              key=f"override_{p['id']}",
                              help='Start with the recommendation, or choose a different scenario to compare.')
        rev = {v:k for k,v in pretty.items()}
        st.session_state.care_overrides[p['id']] = rev[choice]

        st.divider()

    if st.button('See Costs'):
        st.session_state.step = 'calculator'
        st.rerun()

# ---------- Calculator ----------
elif st.session_state.step == 'calculator':
    st.header('Cost Planner')
    state = st.selectbox('Location', ['National','Washington','California','Texas','Florida'],
                         help='State averages adjust typical market rates.')

    total = 0
    for p in st.session_state.people:
        rec = st.session_state.planner_results[p['id']]
        pid = p['id']
        care_type = st.session_state.get('care_overrides', {}).get(pid, rec['care_type'])

        st.subheader(f"{p['display_name']} — Scenario: {care_type.replace('_',' ').title()} (recommendation: {rec['care_type'].replace('_',' ').title()})")

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
            for k in [f"{pid}_room", f"{pid}_hours", f"{pid}_days"]:
                if k in st.session_state: del st.session_state[k]
            care_type = care_type_new

        raw_mob = st.session_state.get('mobility_raw', {}).get(pid)
        mobility_prefill = 'Independent'
        if raw_mob in (2, 3): mobility_prefill = 'Assisted'
        if raw_mob == 4: mobility_prefill = 'Non-ambulatory'

        default_care_level = 'High' if ('severe_cognitive_decline' in rec['flags'] or care_type=='memory_care') else 'Medium'
        care_level = st.selectbox('Care Level (staffing intensity)',
                                  ['Low','Medium','High'],
                                  index=['Low','Medium','High'].index(default_care_level),
                                  key=f"{pid}_care_level",
                                  help='Higher care levels reflect more hands-on support and supervision.')

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

        if care_type in ['assisted_living','memory_care']:
            for k in [f"{pid}_hours", f"{pid}_days"]:
                if k in st.session_state: del st.session_state[k]
            room = st.selectbox('Room Type', ['Studio','1 Bedroom','Shared'],
                                key=f"{pid}_room",
                                help='Typical base rates vary by room size and privacy.')
            inp.room_type = room
        else:
            if f"{pid}_room" in st.session_state: del st.session_state[f"{pid}_room"]
            hours = st.slider('In-home care hours per day', 0, 24, 4, 1,
                              key=f"{pid}_hours",
                              help='Total paid caregiver hours per day.')
            days = st.slider('Days of care per month', 0, 31, 20, 1,
                             key=f"{pid}_days",
                             help='How many days per month caregivers are scheduled.')
            # Normalize days so engines that only read hours/day still reflect days effect
            effective_hours_per_day = int(round((hours * max(days, 0)) / 30.0)) if days is not None else int(hours)
            try:
                inp.in_home_hours_per_day = int(effective_hours_per_day)
            except Exception:
                try:
                    setattr(inp, 'in_home_hours_per_day', int(effective_hours_per_day))
                except Exception:
                    pass
            # Also pass days if engine supports it
            try:
                setattr(inp, 'in_home_days_per_month', int(days))
            except Exception:
                pass

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

# ---------- Household & Assets ----------
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

    # Individual Monthly Income
    with st.expander('Monthly Income — Individual', expanded=True):
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
        # Subtotal
        ind_total = (a_ss + a_pn + a_other) + (b_ss + b_pn + b_other)
        st.metric('Subtotal — Individual monthly income', f"${ind_total:,.0f}")

    # Household Monthly Income (shared)
    with st.expander('Monthly Income — Household (shared)', expanded=False):
        st.caption('Household-level income typically tied to shared assets.')
        hh_rent = currency_input('Rental property income', 'hh_rental_income', 0)
        hh_annuity = currency_input('Annuity income (household-owned)', 'hh_annuity_income', 0)
        hh_invest = currency_input('Dividends/interest (joint investments)', 'hh_investment_income', 0)
        hh_trust = currency_input('Trust distributions (household)', 'hh_trust_income', 0)
        hh_other = currency_input('Other household income', 'hh_other_income', 0)
        household_other = hh_rent + hh_annuity + hh_invest + hh_trust + hh_other
        st.metric('Subtotal — Household monthly income', f"${household_other:,.0f}")

    # Benefits: VA Wizard + LTC (aligned rows)
    with st.expander('Benefits (VA, Long-Term Care insurance)', expanded=True):
        st.markdown('**VA benefits**')
        settings = calculator.settings
        va_mapr = settings.get('va_mapr_2025', {
            'Veteran (no dependents) — A&A': 2358,
            'Veteran + 1 dependent — A&A': 2795,
            'Two veterans married, one A&A': 2795,
            'Surviving spouse — A&A': 1515,
            'Surviving spouse + 1 child — A&A': 1808
        })

        def va_block(tag_prefix, person_name):
            st.write(f'**{person_name}**')
            va_path = st.radio(
                f'Choose an option for {person_name}:',
                ['Not a veteran / No VA pension',
                 'I already receive or qualify for VA pension/Aid & Attendance',
                 'I served, but I’m not sure if I qualify'],
                index=0,
                key=f'{tag_prefix}_va_path'
            )
            result = {'monthly': 0, 'detail': 'No VA pension'}
            if va_path.startswith('I already receive'):
                tier = st.selectbox(
                    'Select status',
                    list(va_mapr.keys()),
                    key=f'{tag_prefix}_va_tier',
                    help='Monthly caps converted from VA MAPR. Actual payment equals MAPR minus your income for VA purposes.'
                )
                max_monthly = int(va_mapr[tier])
                st.caption(f'Estimated monthly cap for this tier: ${max_monthly:,}.')
                result['monthly'] = st.number_input('Monthly VA payment (enter actual if known; otherwise use cap)',
                                                    min_value=0, step=25, value=max_monthly, key=f'{tag_prefix}_va_actual')
                result['detail'] = tier
            elif va_path.startswith('I served'):
                st.info('Quick check (not exhaustive):')
                wartime = st.checkbox('Served during a wartime period', key=f'{tag_prefix}_wartime')
                age_or_dis = st.checkbox('65+ or permanently and totally disabled', key=f'{tag_prefix}_age_dis')
                discharge = st.checkbox('Discharge not dishonorable', key=f'{tag_prefix}_discharge')
                need_aa = st.checkbox('Needs help with daily activities or housebound', key=f'{tag_prefix}_need_aa')
                below_networth = st.checkbox('Net worth under VA limit', key=f'{tag_prefix}_networth')
                likely = wartime and age_or_dis and discharge and below_networth
                if likely:
                    st.success('You may qualify for VA pension; Aid & Attendance may apply if daily help/housebound.')
                    result['detail'] = 'Wizard: likely eligible'
                else:
                    st.warning('Based on these answers, VA pension may not apply. You can still check with a VSO.')
                    result['detail'] = 'Wizard: uncertain'
            return result

        # Row 1: VA sections (two columns)
        col1, col2 = st.columns(2)
        with col1:
            a_res = va_block('a', nameA)
        with col2:
            if len(st.session_state.people) > 1:
                b_res = va_block('b', nameB)
            else:
                b_res = {'monthly': 0, 'detail': 'No VA pension'}

        # Row 2: LTC selectors (always visible and aligned)
        ltc1, ltc2 = st.columns(2)
        with ltc1:
            a_ltc = st.selectbox(f'Long-Term Care insurance — {nameA}', ['No','Yes'],
                                 index=0 if st.session_state.get('household_values', {}).get('a_ltc','No')=='No' else 1,
                                 key='a_ltc')
        with ltc2:
            b_ltc = st.selectbox(f'Long-Term Care insurance — {nameB}', ['No','Yes'],
                                 index=0 if st.session_state.get('household_values', {}).get('b_ltc','No')=='No' else 1,
                                 key='b_ltc')

        _settings = calculator.settings
        _ltc_add = int(_settings.get('ltc_monthly_add', 1800))

        a_va = int(a_res['monthly'])
        b_va = int(b_res['monthly'])
        # Subtotal
        benefits_total = (a_va + (_ltc_add if a_ltc=='Yes' else 0)) + (b_va + (_ltc_add if b_ltc=='Yes' else 0))
        st.metric('Subtotal — Benefits (VA + LTC add-ons)', f"${benefits_total:,.0f}")

    # Home decision
    with st.expander('Home decision', expanded=False):
        decision = st.selectbox('What will you do with the home?', ['Keep','Sell','HELOC','Reverse mortgage'],
                                index=['Keep','Sell','HELOC','Reverse mortgage'].index(values.get('home_decision','Keep')),
                                key='home_decision',
                                help='Pick one option; related fields will appear below.')

        home_monthly = 0
        reverse_draw = 0
        auto_net_proceeds = 0

        if decision == 'Keep':
            st.info('If you keep the home, include carrying costs.')
            mortgage = currency_input('Mortgage', 'mortgage', 0)
            taxes = currency_input('Property taxes', 'property_taxes', 0)
            ins = currency_input('Home insurance', 'home_insurance', 0)
            hoa = currency_input('HOA', 'hoa', 0)
            utils = currency_input('Utilities', 'utilities', 0)
            maint = currency_input('Maintenance', 'maintenance', 0)
            heloc = currency_input('HELOC payment (if applicable)', 'heloc_payment_monthly', 0)
            home_monthly = mortgage + taxes + ins + hoa + utils + maint + heloc
            st.metric('Subtotal — Home carrying costs (monthly)', f"${home_monthly:,.0f}")

        elif decision == 'Sell':
            st.info('We’ll estimate net proceeds to add to assets.')
            value = currency_input('Estimated sale price', 'home_value_estimate', 0)
            payoff = currency_input('Mortgage payoff (principal remaining)', 'home_payoff', 0)
            fee_pct_label = st.select_slider('Estimated selling fees (%)', options=list(range(5,11)), value=7, key='selling_fee_pct',
                                             help='Typical combined agent and closing costs range 6–8% in many markets.')
            fee_pct = fee_pct_label / 100.0
            auto_net_proceeds = max(int(value - payoff - value*fee_pct), 0)
            st.metric('Estimated net proceeds to assets', f"${auto_net_proceeds:,.0f}")

        elif decision == 'HELOC':
            st.info('Enter the monthly HELOC payment and the remaining available equity.')
            heloc_payment = currency_input('Monthly HELOC payment', 'heloc_payment_monthly', 0)
            remaining_equity = currency_input('Remaining available equity (adds to assets)', 'heloc_remaining_equity', 0)
            home_monthly = heloc_payment
            auto_net_proceeds = remaining_equity
            st.metric('Subtotal — HELOC monthly payment', f"${home_monthly:,.0f}")
            st.metric('Available equity added to assets', f"${auto_net_proceeds:,.0f}")

        else:  # Reverse mortgage
            st.info('Enter the expected monthly draw and any upfront fees.')
            reverse_draw = currency_input('Monthly reverse mortgage draw (adds to income)', 'reverse_monthly_draw', 0)
            reverse_fees = currency_input('Upfront fees (reduce equity)', 'reverse_fees_upfront', 0)
            st.metric('Subtotal — Reverse monthly draw', f"${reverse_draw:,.0f}")

    # Home modifications
    with st.expander('Home modifications (if receiving in-home care)', expanded=False):
        any_in_home = any(st.session_state.planner_results[p['id']]['care_type']=='in_home' for p in st.session_state.people)
        if not any_in_home:
            st.caption('Modifications are typically most relevant when receiving in-home care.')
        mods = currency_input('Home modifications (monthlyized estimate)', 'home_modifications_monthly', 0)
        st.metric('Subtotal — Home modifications (monthly)', f"${mods:,.0f}")

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
        other_total = medicare + dvh + debts + phone + personal + travel + auto + auto_ins + pets + other_opt
        st.metric('Subtotal — Other monthly costs', f"${other_total:,.0f}")

    # Assets — Common
    with st.expander('Assets — Common', expanded=False):
        st.caption('Liquid or near-liquid assets most families use first.')
        cash_chk = currency_input('Checking/Savings', 'asset_cash_savings', 0)
        cds = currency_input('CDs / Money Market', 'asset_cds', 0)
        brokerage = currency_input('Brokerage (stocks/bonds/ETFs)', 'asset_brokerage', 0)
        ira = currency_input('Retirement accounts (IRA/401k/403b)', 'asset_retirement', 0)
        hsa = currency_input('HSA balance', 'asset_hsa', 0)
        li_cv = currency_input('Life insurance cash value', 'asset_life_ins_cash', 0)
        common_assets_total = cash_chk + cds + brokerage + ira + hsa + li_cv
        st.metric('Subtotal — Common assets', f"${common_assets_total:,.0f}")

    # Assets — Detailed/Other
    with st.expander('Assets — Detailed/Other', expanded=False):
        st.caption('Less common or less liquid sources.')
        other_real_estate = currency_input('Other real estate equity (non-primary)', 'asset_other_real_estate', 0)
        vehicles = currency_input('Vehicles (net sale value)', 'asset_vehicles', 0)
        valuables = currency_input('Valuables/collectibles (saleable)', 'asset_valuables', 0)
        trusts = currency_input('Trust principal available', 'asset_trusts', 0)
        annuity_sv = currency_input('Annuities (surrender value)', 'asset_annuity_sv', 0)
        business = currency_input('Business interest (sale value)', 'asset_business', 0)
        gifts = currency_input('Family support / gifts anticipated', 'asset_family_support', 0)
        st.write(f"Auto-added from Home decision: ${auto_net_proceeds:,.0f}")
        detailed_assets_total = other_real_estate + vehicles + valuables + trusts + annuity_sv + business + gifts + auto_net_proceeds
        st.metric('Subtotal — Detailed/other assets', f"${detailed_assets_total:,.0f}")

    total_assets = common_assets_total + detailed_assets_total

    # Settings
    _settings = calculator.settings
    _ltc_add = int(_settings.get('ltc_monthly_add', 1800))
    _cap_years = int(_settings.get('display_cap_years_funded', 30))

    # Income math
    monthly_income_individuals = (a_ss + a_pn + a_other) + (b_ss + b_pn + b_other)
    monthly_income_benefits = (a_va + (_ltc_add if a_ltc=='Yes' else 0)) + (b_va + (_ltc_add if b_ltc=='Yes' else 0))
    monthly_income_household = household_other + reverse_draw
    monthly_income = monthly_income_individuals + monthly_income_benefits + monthly_income_household

    combined_cost = st.session_state.get('combined_monthly_cost', 0)
    optional_costs = (home_monthly if 'home_monthly' in locals() else 0) + medicare + dvh + mods + debts + phone + personal + travel + auto + auto_ins + pets + other_opt
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

    # Detailed per-person breakdown
    st.subheader('Breakdown by person')
    for p in st.session_state.people:
        pid = p['id']
        pname = p['display_name']
        care_cost = st.session_state.get('va_cache', {}).get(pid, {}).get('care_cost', 0)
        if pid == 'A':
            person_income = a_ss + a_pn + a_other + (a_va + (_ltc_add if a_ltc=='Yes' else 0))/2
        else:
            person_income = b_ss + b_pn + b_other + (b_va + (_ltc_add if b_ltc=='Yes' else 0))/2
        st.write(f"**{pname}**")
        st.write(f"Care costs (monthly): ${care_cost:,.0f}")
        st.write(f"Individual income incl. VA/LTC (approx): ${person_income:,.0f}")
        st.divider()

    cols = st.columns(2)
    with cols[0]:
        if st.button('Back to Costs'):
            st.session_state.step = 'calculator'
            st.rerun()
    with cols[1]:
        st.success('Adjust any values above to explore different scenarios.')
