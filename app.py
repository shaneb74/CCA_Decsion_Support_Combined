# app.py (hardened imports + safe CalcInputs)
import sys, traceback
from types import SimpleNamespace
from pathlib import Path
import streamlit as st

# Try matplotlib for donuts; fall back to Altair if not installed
USE_MPL = True
try:
    import matplotlib.pyplot as plt  # noqa
except Exception:
    USE_MPL = False
    import altair as alt  # noqa

st.set_page_config(page_title='Senior Navigator • Planner + Cost', page_icon='🧭', layout='centered')

# ---------- import engines defensively ----------
try:
    import engines  # your repo module
except Exception:
    st.error("Failed to import `engines.py`. See trace below.")
    st.code(traceback.format_exc())
    st.stop()

# pull only what we truly need
PlannerEngine = getattr(engines, "PlannerEngine", None)
CalculatorEngine = getattr(engines, "CalculatorEngine", None)
CalcInputsClass = getattr(engines, "CalcInputs", None)

if PlannerEngine is None or CalculatorEngine is None:
    st.error("`engines.py` must define PlannerEngine and CalculatorEngine.")
    st.stop()

# helper: build a CalcInputs-like object even if the class is missing
def make_inputs(**kwargs):
    if CalcInputsClass is not None:
        try:
            return CalcInputsClass(**kwargs)
        except TypeError:
            # some versions use attributes instead of kwargs
            obj = CalcInputsClass()
            for k, v in kwargs.items():
                setattr(obj, k, v)
            return obj
    # fallback: SimpleNamespace that exposes attributes the engine reads
    return SimpleNamespace(**kwargs)

# ---------- init engines with visible error if they fail ----------
try:
    planner = PlannerEngine()
except Exception:
    st.error("PlannerEngine() initialization failed.")
    st.code(traceback.format_exc())
    st.stop()

try:
    calculator = CalculatorEngine()
except Exception:
    st.error("CalculatorEngine() initialization failed.")
    st.code(traceback.format_exc())
    st.stop()

# ---------- data dir check ----------
DATA_DIR = Path(__file__).resolve().parent / "data"
if not DATA_DIR.exists():
    st.warning("Missing `data/` folder. The app may not load JSON settings.")
    # don't stop; engines might resolve paths internally

# -------------------- helpers --------------------
def reset_all():
    for k in list(st.session_state.keys()):
        if k.startswith(("A_", "B_")) or k in (
            'step','people','answers','planner_results','current_person',
            'combined_monthly_cost','household_values','mobility_raw','care_overrides',
            'va_cache','care_partner_add','home_mods','summary_cache'
        ):
            del st.session_state[k]

def donut_altair(labels, values, title):
    import pandas as pd
    total = sum(values) or 1
    df = pd.DataFrame({'label': labels, 'value': values})
    base = alt.Chart(df).encode(theta='value:Q', color='label:N', tooltip=['label','value'])
    ring = base.mark_arc(innerRadius=60)
    text = base.mark_text(radius=90).encode(text='label:N')
    return (ring + text).properties(title=title, width=360, height=360)

def get_home_mod_catalog():
    s = getattr(calculator, "settings", {}) or {}
    catalog = s.get('home_modifications_catalog')
    if isinstance(catalog, list) and catalog:
        return catalog
    return [
        {'key':'ramp', 'label':'Exterior ramp (installed)', 'avg':3500},
        {'key':'widen_doors', 'label':'Widen doorways (per doorway)', 'avg':900},
        {'key':'bath_grab', 'label':'Bathroom grab bars (pair installed)', 'avg':300},
        {'key':'roll_in_shower', 'label':'Convert tub to roll-in shower', 'avg':8500},
        {'key':'raised_toilet', 'label':'Raised-height toilet', 'avg':600},
        {'key':'stair_lift', 'label':'Stair lift (single flight)', 'avg':4500},
        {'key':'platform_lift', 'label':'Vertical platform lift', 'avg':12000},
        {'key':'handrails', 'label':'Handrails along hallways (per 10 ft)', 'avg':250},
        {'key':'lighting', 'label':'Lighting upgrades & switches', 'avg':800},
        {'key':'bedroom_reloc', 'label':'Relocate bedroom to main floor', 'avg':3000},
        {'key':'kitchen_adj', 'label':'Kitchen accessibility adjustments', 'avg':4000}
    ]

def monthlyize_capex(total_capex: int, months: int):
    months = max(1, int(months))
    return int(round(total_capex / months))

# -------------------- app state --------------------
if 'step' not in st.session_state:
    st.session_state.step = 'intro'

st.sidebar.title('Senior Navigator')
st.sidebar.caption('Planner → Costs')
st.sidebar.button('Start over', on_click=reset_all)

# ---------- Intro ----------
if st.session_state.step == 'intro':
    st.title("Let’s take this one step at a time")
    st.markdown("""
Choosing senior living or in-home support can feel overwhelming.  
This tool guides you through it.

We’ll start with a few simple questions, recommend a care option,  
and then help you plan the costs. There are no right or wrong answers.
""")
    st.info('Typical time to complete: 10–15 minutes. You can stop anytime.')
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

    st.caption("Next, we’ll ask a few care questions for each person.")
    if st.button('Continue'):
        st.session_state.people = people
        st.session_state.current_person = 0
        st.session_state.answers = {}
        st.session_state.planner_results = {}
        st.session_state.mobility_raw = {}
        st.session_state.care_overrides = {}
        st.session_state.step = 'care_partner_context'
        st.rerun()

# ---------- Care Partner Interstitial ----------
elif st.session_state.step == 'care_partner_context':
    people = st.session_state.get('people', [])
    single = len(people) == 1
    primary = people[0]['display_name'] if people else 'Person A'

    st.header('Before we begin the care plan')
    st.markdown(f"""
When **{primary}** needs assisted living or memory care, the spouse/partner often needs some in-home help too.
If that might be your situation, you can include a simple support plan for them now so the household picture is complete.
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
                st.session_state.people.append({
                    'id': 'B',
                    'display_name': st.session_state.get('care_partner_name') or 'Spouse/Partner',
                    'relationship': 'spouse'
                })
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

    answers = st.session_state.answers.get(person['id'], {})
    qa = getattr(planner, "qa", {})

    mobility_q_index = None
    for idx, q in enumerate(qa.get('questions', []), start=1):
        if 'mobility' in q.get('question','').lower():
            mobility_q_index = idx
        prev = answers.get(f'q{idx}')
        label = f"{q['question']} (for {name})"
        sel = st.radio(
            label,
            options=[1,2,3,4],
            format_func=lambda n, q=q: q['answers'][str(n)],
            index=(prev-1) if prev else 0,
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
            if a is None: 
                continue
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
        conditional_answer = st.radio(
            cq['question'], options=[1,2],
            format_func=lambda n: cq['answers'][str(n)],
            key=f"{person['id']}_q9",
            help=cq.get('help')
        )

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
            try:
                result = planner.run(answers, conditional_answer=conditional_answer)
            except Exception:
                st.error("PlannerEngine.run failed.")
                st.code(traceback.format_exc())
                st.stop()
            # result may be dataclass or dict; normalize
            care_type = getattr(result, "care_type", None) or result.get("care_type")
            flags_out = getattr(result, "flags", None) or result.get("flags", [])
            scores = getattr(result, "scores", None) or result.get("scores", {})
            reasons = getattr(result, "reasons", None) or result.get("reasons", [])
            advisory = getattr(result, "advisory", None) or result.get("advisory")

            st.session_state.planner_results[person['id']] = {
                'care_type': care_type,
                'flags': set(flags_out) if isinstance(flags_out, (set, list, tuple)) else set(),
                'scores': scores,
                'reasons': reasons,
                'advisory': advisory
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
    st.caption('Start with the recommendation, or explore another scenario without redoing questions.')

    for p in st.session_state.people:
        rec = st.session_state.planner_results[p['id']]
        default = rec['care_type'] or 'in_home'
        st.subheader(f"{p['display_name']}: {default.replace('_',' ').title()} (recommended)")
        for r in rec.get('reasons', []):
            st.write('• ' + str(r))
        if rec.get('advisory'):
            st.info(rec['advisory'])

        care_choices = ['in_home','assisted_living','memory_care']
        pretty = {'in_home':'In-home Care','assisted_living':'Assisted Living','memory_care':'Memory Care'}
        idx = care_choices.index(default) if default in care_choices else 0
        choice = st.selectbox(
            f"Care scenario for {p['display_name']}",
            [pretty[c] for c in care_choices],
            index=idx,
            key=f"override_{p['id']}",
            help='Change the scenario here if you want to compare a different path.'
        )
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
                         help='Adjusts for typical market rates in the selected state.')

    total = 0
    for p in st.session_state.people:
        rec = st.session_state.planner_results[p['id']]
        pid = p['id']
        care_type = st.session_state.get('care_overrides', {}).get(pid, rec['care_type'] or 'in_home')

        st.subheader(f"{p['display_name']} — Scenario: {care_type.replace('_',' ').title()} (recommendation: {rec['care_type'].replace('_',' ').title() if rec.get('care_type') else 'In-home Care'})")

        care_choices = ['in_home','assisted_living','memory_care']
        pretty = {'in_home':'In-home Care','assisted_living':'Assisted Living','memory_care':'Memory Care'}
        scenario_label = st.selectbox(
            f"Care scenario for {p['display_name']} (adjust here if needed)",
            [pretty[c] for c in care_choices],
            index=care_choices.index(care_type) if care_type in care_choices else 0,
            key=f"calc_override_{pid}",
            help='Change the scenario without redoing questions.'
        )
        care_type_new = {v:k for k,v in pretty.items()}[scenario_label]
        if care_type_new != care_type:
            st.session_state.care_overrides[pid] = care_type_new
            for k in [f"{pid}_room", f"{pid}_hours", f"{pid}_days"]:
                if k in st.session_state: 
                    del st.session_state[k]
            care_type = care_type_new

        # Mobility carryover
        raw_mob = st.session_state.get('mobility_raw', {}).get(pid)
        mobility_prefill = 'Independent'
        if raw_mob in (2, 3): 
            mobility_prefill = 'Assisted'
        if raw_mob == 4: 
            mobility_prefill = 'Non-ambulatory'

        default_care_level = 'High' if ('severe_cognitive_decline' in rec.get('flags', set()) or care_type=='memory_care') else 'Medium'
        care_level = st.selectbox('Care Level (staffing intensity)',
                                  ['Low','Medium','High'],
                                  index=['Low','Medium','High'].index(default_care_level),
                                  key=f"{pid}_care_level",
                                  help='Higher levels reflect more hands-on support and supervision.')

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
                                      help='Mobility impacts staffing and environment.')
        mobility = mobility_map_out[mobility_label]

        chronic_options = ['None (no ongoing conditions)',
                           'Some (1–2 manageable conditions)',
                           'Multiple/Complex (several or complex needs)']
        chronic_map_out = {
            chronic_options[0]:'None',
            chronic_options[1]:'Some',
            chronic_options[2]:'Multiple/Complex'
        }
        default_chronic_label = chronic_options[2] if 'severe_cognitive_decline' in rec.get('flags', set()) else chronic_options[1]
        chronic_label = st.selectbox('Chronic Conditions', chronic_options,
                                     index=chronic_options.index(default_chronic_label),
                                     key=f"{pid}_chronic",
                                     help='Pick the closest description.')
        chronic = chronic_map_out[chronic_label]

        inp = make_inputs(state=state, care_type=care_type, care_level=care_level, mobility=mobility, chronic=chronic)

        if care_type in ['assisted_living','memory_care']:
            for k in [f"{pid}_hours", f"{pid}_days"]:
                if k in st.session_state: del st.session_state[k]
            room = st.selectbox('Room Type', ['Studio','1 Bedroom','Shared'],
                                key=f"{pid}_room",
                                help='Base rates vary by room size and privacy.')
            try:
                setattr(inp, 'room_type', room)
            except Exception:
                pass
        else:
            if f"{pid}_room" in st.session_state: del st.session_state[f"{pid}_room"]
            hours = st.slider('In-home care hours per day', 0, 24, 4, 1,
                              key=f"{pid}_hours",
                              help='Total paid caregiver hours per day.')
            days = st.slider('Days of care per month', 0, 31, 20, 1,
                             key=f"{pid}_days",
                             help='How many days per month caregivers are scheduled.')
            effective_hours_per_day = int(round((hours * max(days, 0)) / 30.0)) if days is not None else int(hours)
            try:
                setattr(inp, 'in_home_hours_per_day', int(effective_hours_per_day))
                setattr(inp, 'in_home_days_per_month', int(days))
            except Exception:
                pass

        try:
            monthly = calculator.monthly_cost(inp)
        except Exception:
            st.error("CalculatorEngine.monthly_cost failed.")
            st.code("Inputs passed:\n" + str(vars(inp)))
            st.code(traceback.format_exc())
            st.stop()

        st.metric('Estimated Monthly Cost', f"${monthly:,.0f}")
        st.session_state.setdefault('va_cache', {}).setdefault(pid, {})['care_cost'] = monthly
        total += monthly
        st.divider()

    st.subheader('Combined Total')
    st.session_state.combined_monthly_cost = total
    st.metric('Estimated Combined Monthly Cost', f"${total:,.0f}")
    st.info('These are planning estimates. Adjust settings to explore scenarios.')

    if st.button('Add Household & Assets (optional)'):
        st.session_state.step = 'household'
        st.rerun()

# ---------- Household & Budget ----------
elif st.session_state.step == 'household':
    people = st.session_state.get('people', [])
    names = [p['display_name'] for p in people]
    nameA = names[0] if names else 'Person A'
    nameB = names[1] if len(names) > 1 else 'Person B'

    st.header('Household & Budget (optional)')
    st.markdown("These fields help you see affordability. You can skip if you don’t have details handy.")

    values = st.session_state.get('household_values', {})

    def currency_input(label, key, default=0):
        val = int(values.get(key, default))
        v = st.number_input(label, min_value=0, step=50, value=val, key=key)
        st.session_state[key] = v
        return v

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

    # Benefits (VA + LTC)
    with st.expander('Benefits (VA, Long-Term Care insurance)', expanded=True):
        st.markdown('**VA benefits**')
        settings = getattr(calculator, "settings", {}) or {}
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
                    help='Monthly caps from VA MAPR. Actual payment equals MAPR minus income for VA purposes.'
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

        col1, col2 = st.columns(2)
        with col1:
            a_res = va_block('a', nameA)
        with col2:
            if len(st.session_state.people) > 1:
                b_res = va_block('b', nameB)
            else:
                b_res = {'monthly': 0, 'detail': 'No VA pension'}

        ltc1, ltc2 = st.columns(2)
        with ltc1:
            a_ltc = st.selectbox(f'Long-Term Care insurance — {nameA}', ['No','Yes'],
                                 index=0 if st.session_state.get('household_values', {}).get('a_ltc','No')=='No' else 1,
                                 key='a_ltc')
        with ltc2:
            b_ltc = st.selectbox(f'Long-Term Care insurance — {nameB}', ['No','Yes'],
                                 index=0 if st.session_state.get('household_values', {}).get('b_ltc','No')=='No' else 1,
                                 key='b_ltc')

        _settings = getattr(calculator, "settings", {}) or {}
        _ltc_add = int(_settings.get('ltc_monthly_add', 1800))

        a_va = int(a_res['monthly']); st.session_state['a_va_monthly'] = a_va
        b_va = int(b_res['monthly']); st.session_state['b_va_monthly'] = b_va

        benefits_total = (a_va + (_ltc_add if a_ltc=='Yes' else 0)) + (b_va + (_ltc_add if b_ltc=='Yes' else 0))
        st.metric('Subtotal — Benefits (VA + LTC add-ons)', f"${benefits_total:,.0f}")

    # Home decision
    with st.expander('Home decision', expanded=False):
        decision = st.selectbox('What will you do with the home?', ['Keep','Sell','HELOC','Reverse mortgage'],
                                index=['Keep','Sell','HELOC','Reverse mortgage'].index(values.get('home_decision','Keep')),
                                key='home_decision',
                                help='Pick one option; related fields will appear below.')

            # monthly carrying cost and/or asset effects
        home_monthly = 0
        household_other = st.session_state.get('hh_dummy', 0)  # placeholder to keep later math simple
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
            st.session_state['auto_net_proceeds'] = auto_net_proceeds

        elif decision == 'HELOC':
            st.info('Enter the monthly HELOC payment and the remaining available equity.')
            heloc_payment = currency_input('Monthly HELOC payment', 'heloc_payment_monthly', 0)
            remaining_equity = currency_input('Remaining available equity (adds to assets)', 'heloc_remaining_equity', 0)
            home_monthly = heloc_payment
            st.metric('Subtotal — HELOC monthly payment', f"${home_monthly:,.0f}")
            st.metric('Available equity added to assets', f"{remaining_equity:,.0f}")
            st.session_state['auto_net_proceeds'] = remaining_equity

        else:  # Reverse mortgage
            st.info('Enter the expected monthly draw and any upfront fees.')
            reverse_draw = currency_input('Monthly reverse mortgage draw (adds to income)', 'reverse_monthly_draw', 0)
            reverse_fees = currency_input('Upfront fees (reduce equity)', 'reverse_fees_upfront', 0)
            st.metric('Subtotal — Reverse monthly draw', f"${reverse_draw:,.0f}")

    # Home modifications
    with st.expander('Home modifications (if receiving in-home care)', expanded=False):
        any_in_home = any(st.session_state.planner_results[p['id']]['care_type']=='in_home' for p in st.session_state.people)
        if not any_in_home:
            st.caption('Modifications are typically most relevant when receiving in-home care. You can still record them here.')

        colg1, colg2, colg3 = st.columns([1,1,1])
        with colg1:
            level = st.selectbox('Solution level', ['Budget','Standard','Custom'], index=1, help='Scales project costs.')
        with colg2:
            amort_months = st.number_input('Spread costs over (months)', min_value=1, max_value=120, value=36, step=1,
                                           help='We convert total project costs into a monthly planning estimate.')
        with colg3:
            show_adv = st.checkbox('Show quantities', value=False)

        mult = {'Budget':0.8, 'Standard':1.0, 'Custom':1.5}[level]

        catalog = get_home_mod_catalog()
        if 'home_mods' not in st.session_state:
            st.session_state.home_mods = {item['key']: {'selected': False, 'qty': 1} for item in catalog}

        total_capex = 0
        for item in catalog:
            state_item = st.session_state.home_mods[item['key']]
            cols = st.columns([0.06, 0.62, 0.32])
            with cols[0]:
                sel = st.checkbox('', value=state_item['selected'], key=f"hm_sel_{item['key']}")
            with cols[1]:
                st.write(f"**{item['label']}**  · avg ${item['avg']:,}")
                if show_adv:
                    qty = st.number_input('Qty', min_value=1, max_value=20, value=state_item['qty'], key=f"hm_qty_{item['key']}")
                else:
                    qty = 1
            with cols[2]:
                est = int(round(item['avg'] * mult * (state_item['qty'] if show_adv else 1)))
                st.write(f"Est. cost: **${est:,}**")

            st.session_state.home_mods[item['key']]['selected'] = sel
            st.session_state.home_mods[item['key']]['qty'] = qty
            if sel:
                total_capex += int(round(item['avg'] * mult * qty))

        monthly_mod_cost = monthlyize_capex(total_capex, amort_months)
        st.metric('Subtotal — Modifications monthly estimate', f"${monthly_mod_cost:,.0f}")
        st.caption(f"Projects total: ${total_capex:,} · spread over {amort_months} months at {int(mult*100)}% of averages.")
        st.session_state['home_mods_monthly'] = monthly_mod_cost

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
        detailed_assets_total = other_real_estate + vehicles + valuables + trusts + annuity_sv + business + gifts
        st.metric('Subtotal — Detailed/other assets', f"${detailed_assets_total:,.0f}")

    total_assets = common_assets_total + detailed_assets_total

    # Settings
    _settings = getattr(calculator, "settings", {}) or {}
    _ltc_add = int(_settings.get('ltc_monthly_add', 1800))
    _cap_years = int(_settings.get('display_cap_years_funded', 30))

    # Income math
    monthly_income_individuals = (a_ss + a_pn + a_other) + (b_ss + b_pn + b_other)
    monthly_income_benefits = (st.session_state.get('a_va_monthly',0) + (_ltc_add if st.session_state.get('a_ltc','No')=='Yes' else 0)) + \
                              (st.session_state.get('b_va_monthly',0) + (_ltc_add if st.session_state.get('b_ltc','No')=='Yes' else 0))
    monthly_income_household = household_other + st.session_state.get('reverse_monthly_draw', 0)
    monthly_income = monthly_income_individuals + monthly_income_benefits + monthly_income_household

    combined_cost = st.session_state.get('combined_monthly_cost', 0)
    home_monthly_local = locals().get('home_monthly', 0)
    mods_monthly = st.session_state.get('home_mods_monthly', 0)
    optional_costs = home_monthly_local + mods_monthly + other_total
    overall_monthly = combined_cost + optional_costs

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric('Monthly Care + Selected Costs', f"${overall_monthly:,.0f}")
        years = '∞' if max(overall_monthly - monthly_income,0) == 0 else f"{min(_cap_years, round((total_assets / max(overall_monthly - monthly_income,1)) / 12, 1))} years"
        st.metric('Years Funded (assets ÷ gap)', years)
    with c2:
        st.metric('Total Monthly Income', f"${monthly_income:,.0f}")
    with c3:
        gap = max(overall_monthly - monthly_income, 0)
        st.metric('Estimated Monthly Gap', f"${gap:,.0f}")

    st.session_state.summary_cache = {
        'per_person_costs': {p['display_name']: st.session_state.get('va_cache', {}).get(p['id'],{}).get('care_cost',0) for p in st.session_state.people},
        'household_assets_total': total_assets,
        'income_individuals': monthly_income_individuals,
        'income_benefits': monthly_income_benefits,
        'income_household': monthly_income_household,
        'costs_home': home_monthly_local,
        'costs_mods': mods_monthly,
        'costs_other': other_total,
        'combined_care_costs': st.session_state.get('combined_monthly_cost',0)
    }

    cols = st.columns(2)
    with cols[0]:
        if st.button('Back to Costs'):
            st.session_state.step = 'calculator'
            st.rerun()
    with cols[1]:
        if st.button('View detailed breakdown'):
            st.session_state.step = 'details'
            st.rerun()

# ---------- Details (donut charts) ----------
elif st.session_state.step == 'details':
    st.header('Detailed breakdown')
    s = st.session_state.get('summary_cache', {})

    st.subheader('Care costs by person (monthly)')
    for name, cost in s.get('per_person_costs', {}).items():
        st.write(f"• **{name}**: ${int(cost):,}")

    # Costs donut
    cost_labels = ['Care (combined)', 'Home carrying', 'Home mods amortized', 'Other monthly']
    cost_values = [
        s.get('combined_care_costs',0),
        s.get('costs_home',0),
        s.get('costs_mods',0),
        s.get('costs_other',0)
    ]
    if USE_MPL:
        fig1, ax1 = plt.subplots()
        ax1.pie(cost_values, labels=cost_labels, wedgeprops=dict(width=0.4))
        ax1.set(aspect="equal")
        st.pyplot(fig1)
    else:
        st.altair_chart(donut_altair(cost_labels, cost_values, 'Costs (monthly)'), use_container_width=False)

    # Income donut
    inc_labels = ['Individual income', 'Benefits (VA + LTC add-ons)', 'Household income']
    inc_values = [s.get('income_individuals',0), s.get('income_benefits',0), s.get('income_household',0)]
    if USE_MPL:
        fig2, ax2 = plt.subplots()
        ax2.pie(inc_values, labels=inc_labels, wedgeprops=dict(width=0.4))
        ax2.set(aspect="equal")
        st.pyplot(fig2)
    else:
        st.altair_chart(donut_altair(inc_labels, inc_values, 'Income (monthly)'), use_container_width=False)

    # Assets donut
    assets_total = s.get('household_assets_total',0)
    if USE_MPL:
        fig3, ax3 = plt.subplots()
        ax3.pie([assets_total], labels=[f'Household assets (${int(assets_total):,})'], wedgeprops=dict(width=0.4))
        ax3.set(aspect="equal")
        st.pyplot(fig3)
    else:
        st.altair_chart(donut_altair(['Household assets'], [assets_total], 'Assets (total)'), use_container_width=False)

    st.caption('Charts update as you adjust values in Household & Budget.')

    cols = st.columns(2)
    with cols[0]:
        if st.button('Back to summary'):
            st.session_state.step = 'household'
            st.rerun()
    with cols[1]:
        if st.button('Back to start'):
            reset_all()
            st.rerun()