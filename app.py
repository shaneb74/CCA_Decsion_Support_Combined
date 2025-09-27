# app.py — Senior Navigator (single-file: Planner → Recommendations → Costs → Household → Breakdown → PFMA)
from __future__ import annotations

from pathlib import Path
import traceback
import streamlit as st

# Helpers from your repo
from cost_controls import (
    render_location_control,
    render_costs_for_active_recommendations,
    CONDITION_OPTIONS,
)

st.set_page_config(page_title="Senior Navigator • Planner + Cost", page_icon="🧭", layout="centered")

ROOT = Path(__file__).resolve().parent
QA_PATH = ROOT / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = ROOT / "recommendation_logic_FINAL_MASTER_UPDATED.json"

# Engines
try:
    from engines import PlannerEngine, CalculatorEngine, PlannerResult
except Exception:
    st.error("Failed to import engines.py")
    st.code(traceback.format_exc())
    st.stop()

# Household drawers optional
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
    keys, labels = order_answer_map(amap)
    if not labels:
        return default_key
    idx = keys.index(str(default_key)) if default_key is not None and str(default_key) in keys else 0
    sel_label = st.radio(label, labels, index=idx, key=key)
    return keys[labels.index(sel_label)]

def money(n: int | float) -> str:
    try: return f"${int(round(float(n))):,}"
    except Exception: return "$0"

# -------- PFMA helpers (prefill + carry-over) --------
def _prefill_pfma_defaults():
    s = st.session_state
    if "pfma_defaults_applied" in s:
        return
    s.pfma_name = s.get("pfma_name", "Taylor Morgan")
    s.pfma_phone = s.get("pfma_phone", "(555) 201-8890")
    s.pfma_email = s.get("pfma_email", "taylor@example.com")
    s.pfma_zip = s.get("pfma_zip", "94110")
    s.pfma_when = s.get("pfma_when", "Planning (1–3 months)")
    s.pfma_best_time = s.get("pfma_best_time", "Weekday mornings")
    s.pfma_relationship = s.get("pfma_relationship", "Self")
    s.pfma_payer = s.get("pfma_payer", "Prefer not to say")
    s.pfma_notes = s.get("pfma_notes", "")
    s.pfma_age_band = s.get("pfma_age_band", "65–74")
    s.pfma_booked = s.get("pfma_booked", False)
    s.pfma_defaults_applied = True

def _merge_canon_conditions() -> list[str]:
    """Collect any condition lists stored by cost_controls into a single de-duplicated list."""
    s = st.session_state
    canon = list(dict.fromkeys(s.get("canon_conditions", []) or []))  # unique while preserving order
    # One last sweep for per-person fields if canon missing
    if not canon:
        for key, val in s.items():
            if key.endswith("_conditions") and isinstance(val, list):
                for item in val:
                    if item and item not in canon:
                        canon.append(item)
        # Also check per-person AL/MC keys of the form 'al_conditions_{pid}' etc.
        for key, val in s.items():
            if key.endswith("_conditions_A") or key.endswith("_conditions_B"):
                if isinstance(val, list):
                    for item in val:
                        if item and item not in canon:
                            canon.append(item)
    # Filter to options we actually support to avoid MultiSelect default errors
    canon = [c for c in canon if c in CONDITION_OPTIONS]
    return canon

def _compute_pfma_badges() -> list[str]:
    s = st.session_state
    badges = []
    if s.get("pfma_booked"):
        badges.append("Booked ✓")
    if s.get("pfma_conditions") or s.get("pfma_adls") or s.get("pfma_why"):
        badges.append("Care needs ✓")
    if s.get("pfma_settings") or s.get("pfma_visited"):
        badges.append("Preferences ✓")
    if s.get("pfma_va") or s.get("pfma_ltc") or s.get("pfma_medicaid"):
        badges.append("Benefits ✓")
    return badges

# ------------- PFMA (inline page) -------------
def render_pfma():
    s = st.session_state
    _prefill_pfma_defaults()

    st.header("Plan for My Advisor")
    st.caption("Schedule a time with an advisor. We’ll only ask what we need right now.")

    # Summary
    with st.expander("Your current plan summary", expanded=True):
        people = s.get("people", [])
        recs = s.get("planner_results", {})
        overrides = s.get("care_overrides", {})
        if people and recs:
            nice = {"none":"None","in_home":"In-home Care","assisted_living":"Assisted Living","memory_care":"Memory Care"}
            for p in people:
                pid, name = p["id"], p["display_name"]
                rec = recs.get(pid)
                scenario = overrides.get(pid, getattr(rec, "care_type", "in_home"))
                st.write(f"**{name}:** {nice.get(scenario, scenario).title()}")
        else:
            st.info("No Guided Care Plan found. You can still book now.")
        if s.get("person_costs"):
            total = sum(int(v) for v in s["person_costs"].values())
            st.write(f"**Estimated current monthly care total:** {money(total)}")
        else:
            st.info("No Cost Planner data yet.")

    # Carry-over: VA / LTC
    va_detected = any([s.get("a_va_monthly", 0), s.get("b_va_monthly", 0), s.get("va_monthly", 0)])
    if "pfma_va" not in s: s.pfma_va = bool(va_detected)

    ltc_detected = False
    for k in ("a_ltc", "b_ltc", "ltc_insurance", "has_ltc_insurance", "household_ltc", "ltc_policy"):
        v = s.get(k)
        if str(v).lower() in ("yes", "true", "1"):
            ltc_detected = True; break
    if "pfma_ltc" not in s: s.pfma_ltc = bool(ltc_detected)

    # Carry-over: chronic conditions canon from Cost Planner
    canon_conditions = _merge_canon_conditions()
    if canon_conditions and not s.get("pfma_conditions"):
        s.pfma_conditions = canon_conditions

    # ------------- Booking first -------------
    st.subheader("Get Connected to Expert Advice")
    c1, c2 = st.columns(2)
    with c1:
        st.text_input("Your name", key="pfma_name")
        st.selectbox("Your relationship to the care recipient",
                     ["Self","Spouse/Partner","Adult child","Relative","Friend/Neighbor","Other"],
                     key="pfma_relationship")
        st.text_input("Best phone number", key="pfma_phone")
        st.text_input("Email (optional)", key="pfma_email")
        st.text_input("ZIP code for care search", key="pfma_zip")
        st.selectbox("Approximate age range of care recipient (optional)",
                     ["<65","65–74","75–84","85–89","90+"], key="pfma_age_band")
    with c2:
        st.selectbox("When do you need support?",
                     ["Exploring (3–6+ months)","Planning (1–3 months)","Soon (2–4 weeks)","ASAP / urgent"],
                     key="pfma_when")
        st.selectbox("Best time to call",
                     ["Weekday mornings","Weekday afternoons","Weekday evenings","Weekend"],
                     key="pfma_best_time")
        st.text_area("Any must-haves or constraints? (optional)",
                     key="pfma_notes",
                     placeholder="e.g., near Pasadena, small community, pet-friendly")
        st.selectbox("Primary payer (optional)",
                     ["Prefer not to say","Private pay","Long-term care insurance","Medicaid (or waiver)","VA benefit","Other / mixed"],
                     key="pfma_payer")

    st.divider()
    colA, colB, colC = st.columns([1,1,1])
    with colA:
        if st.button("Back to Home", key="pfma_back_home", type="secondary"):
            s.step = "intro"
            st.rerun()
    with colB:
        if st.button("Book appointment", key="pfma_book_btn", type="primary"):
            s.pfma_booking = {
                "name": s.pfma_name.strip(),
                "relationship": s.pfma_relationship,
                "phone": s.pfma_phone.strip(),
                "email": s.pfma_email.strip(),
                "zip": s.pfma_zip.strip(),
                "age_band": s.pfma_age_band,
                "when": s.pfma_when,
                "best_time": s.pfma_best_time,
                "notes": s.pfma_notes.strip(),
                "payer": s.pfma_payer,
            }
            s.pfma_booked = True
            st.success("Appointment request submitted. An advisor will reach out at your preferred time.")
            st.info("Add any optional details below to help your advisor prepare. Totally optional.")
    with colC:
        st.button("Finish", key="pfma_finish", type="secondary", on_click=lambda: s.update(step="intro"))

    # ---------- OPTIONAL AFTER BOOKING ----------
    st.divider()
    st.subheader("Optional details for your advisor")
    st.caption("These help your advisor prepare so your call stays focused on solutions, not data entry. Fill what you can; skip what isn’t relevant.")

    # Gamified badges (lightweight)
    badges = _compute_pfma_badges()
    if badges:
        st.write("".join([f"🟢 **{b}**   " for b in badges]))

    # Group 1: Care needs & daily support
    with st.expander("Care needs & daily support"):
        tabs = st.tabs(["Conditions", "Daily activities", "Supervision"])
        with tabs[0]:
            st.multiselect(
                "Chronic conditions (check all that apply)",
                CONDITION_OPTIONS,
                key="pfma_conditions",
                default=st.session_state.get("pfma_conditions", []),
                help="Facilities provide different levels of care; these help us match the right fit."
            )
            # Diabetes control appears if Diabetes chosen
            if "Diabetes" in st.session_state.get("pfma_conditions", []):
                st.selectbox("Diabetes is controlled by",
                             ["Not applicable","Diet only","Oral meds","Insulin (1x/day)","Insulin (2+ times/day)"],
                             key="pfma_diabetes_control")
            c1, c2 = st.columns(2)
            with c1:
                st.selectbox("Eyesight issues", ["No","Yes"], key="pfma_eyesight")
                if st.session_state.get("pfma_eyesight") == "Yes":
                    st.text_input("Eyesight notes (optional)", key="pfma_eyesight_notes")
                st.selectbox("Hearing issues", ["No","Yes"], key="pfma_hearing")
                if st.session_state.get("pfma_hearing") == "Yes":
                    st.text_input("Hearing notes (optional)", key="pfma_hearing_notes")
            with c2:
                st.selectbox("Weight-bearing status", ["Independent","Needs assist","Non-weight-bearing"], key="pfma_weight_bearing")
                st.selectbox("Incontinence", ["Fully continent","Bladder","Bowel","Both"], key="pfma_incontinence")
        with tabs[1]:
            st.multiselect(
                "Activities that need support (ADLs/IADLs)",
                [
                    "Bathing","Dressing","Toileting","Transferring / mobility","Eating / meals",
                    "Medication management","Transportation","Housekeeping / laundry",
                    "Finances / bills","Companionship / safety checks",
                ],
                key="pfma_adls",
            )
        with tabs[2]:
            st.multiselect(
                "Special supervision needed",
                ["Wandering risk","Exit seeking","Elopement risk","Nighttime supervision","Behavioral support","None"],
                key="pfma_supervision",
            )
            st.selectbox(
                "Why are you seeking care now?",
                [
                    "Care needs increased","Caregiver burnout","Recent fall / hospitalization",
                    "Memory decline","Planning ahead","Finances / affordability","Other",
                ],
                key="pfma_why",
            )

    # Group 2: Care preferences
    with st.expander("Care preferences"):
        st.caption("Different communities offer different setups and amenities. Your preferences help us personalize the search.")
        st.multiselect(
            "Settings you’re open to",
            ["In-home care","Assisted Living","Memory Care","Not sure"],
            key="pfma_settings",
        )
        st.checkbox("I’m open to speaking with multiple communities", key="pfma_open_multi", value=True)
        st.multiselect(
            "Communities already visited (optional)",
            ["Atria","Brookdale","Sunrise","Holiday","Avamere","MBK","Oakmont","Local boutique","Other"],
            key="pfma_visited",
        )

    # Group 3: Household & legal basics
    with st.expander("Household & legal basics"):
        c1, c2 = st.columns(2)
        with c1:
            st.selectbox("Marital status", ["Prefer not to say","Single","Married","Widowed","Divorced","Partnered"], key="pfma_marital")
            st.selectbox("Smokes tobacco", ["No","Yes"], key="pfma_smoking")
            st.selectbox("Alcohol use", ["No","Yes"], key="pfma_drinking")
        with c2:
            st.selectbox("Sleeping pattern", ["Sleeps through night","Up 1–2 times/night","Up 3–5 times/night","Frequent nighttime wandering"], key="pfma_sleep")
            st.selectbox("POA / DPOA in place", ["None","POA","DPOA","Both"], key="pfma_poa_type")
            if st.session_state.get("pfma_poa_type") != "None":
                st.text_input("POA / DPOA name", key="pfma_poa_name")

    # Group 4: Benefits & coverage
    with st.expander("Benefits & coverage"):
        st.caption("We can research opportunities inside your current coverage and potential programs.")
        st.checkbox("Long-term care insurance", key="pfma_ltc", value=st.session_state.get("pfma_ltc", False))
        st.checkbox("VA benefit (or potential eligibility)", key="pfma_va", value=st.session_state.get("pfma_va", False))
        st.checkbox("Medicaid or waiver interest", key="pfma_medicaid", value=st.session_state.get("pfma_medicaid", False))
        st.selectbox("Primary payer", ["Private pay","Long-term care insurance","Medicaid (or waiver)","VA benefit","Other / mixed"], key="pfma_primary_payer")
        st.text_input("Health insurance provider (optional)", key="pfma_ins_provider")
        st.text_input("Other coverage notes (optional)", key="pfma_coverage_notes")

    st.divider()
    if st.button("Save optional details", key="pfma_optional_save"):
        s.pfma_optional = {
            "conditions": s.get("pfma_conditions", []),
            "diabetes_control": s.get("pfma_diabetes_control"),
            "eyesight": s.get("pfma_eyesight"),
            "eyesight_notes": s.get("pfma_eyesight_notes",""),
            "hearing": s.get("pfma_hearing"),
            "hearing_notes": s.get("pfma_hearing_notes",""),
            "weight_bearing": s.get("pfma_weight_bearing"),
            "incontinence": s.get("pfma_incontinence"),
            "adls": s.get("pfma_adls", []),
            "supervision": s.get("pfma_supervision", []),
            "why_now": s.get("pfma_why"),
            "settings": s.get("pfma_settings", []),
            "open_multi": s.get("pfma_open_multi", True),
            "visited": s.get("pfma_visited", []),
            "marital": s.get("pfma_marital"),
            "smoking": s.get("pfma_smoking"),
            "drinking": s.get("pfma_drinking"),
            "sleep": s.get("pfma_sleep"),
            "poa_type": s.get("pfma_poa_type"),
            "poa_name": s.get("pfma_poa_name","").strip(),
            "has_ltc": s.get("pfma_ltc", False),
            "has_va": s.get("pfma_va", False),
            "medicaid_interest": s.get("pfma_medicaid", False),
            "primary_payer": s.get("pfma_primary_payer"),
            "ins_provider": s.get("pfma_ins_provider","").strip(),
            "coverage_notes": s.get("pfma_coverage_notes","").strip(),
        }
        st.success("Optional details saved.")

# ------------- Data files present? -------------
missing = [p for p in (QA_PATH, REC_PATH) if not p.exists()]
if missing:
    st.error("Missing required JSON files:\\n" + "\\n".join(f"• {m.name}" for m in missing))
    st.stop()

# ------------- Engines -------------
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

# ------------- Session init -------------
if "step" not in st.session_state:
    st.session_state.step = "intro"

# ------------- Sidebar -------------
st.sidebar.title("Senior Navigator")
st.sidebar.caption("Planner → Recommendations → Costs → Household")
st.sidebar.button("Start over", on_click=reset_all, key="start_over_btn")
if st.sidebar.button("Schedule with an Advisor", use_container_width=True, key="pfma_sidebar"):
    st.session_state.step = "pfma"; st.rerun()

# ------------- Flow -------------
if st.session_state.step == "intro":
    st.title("Let’s take this one step at a time")
    st.markdown(
        """
Choosing senior living or in-home support can feel overwhelming.

**What happens next**
1. Answer quick care questions → we recommend a care type.  
2. Review costs for that scenario (you can switch).  
3. (Optional) Add income, benefits, assets, and home decisions.  
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
    for q_idx, q in enumerate(planner.qa.get("questions", []), start=1):
        label = q["question"]; amap = q.get("answers", {})
        if not amap or not isinstance(amap, dict):
            st.warning(f"Skipping question '{label}' due to invalid answers"); continue
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
    st.header("Household & Budget (optional)")
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
            cond = s.get(f"al_conditions_{pid}", s.get("al_conditions"))
            cond_str = ", ".join(cond) if isinstance(cond, list) else (cond or "—")
            detail = ", ".join([f"Care: {pick('al_care_level')}", f"Room: {pick('al_room_type')}", f"Mobility: {pick('al_mobility')}", f"Conditions: {cond_str}"])
        elif scenario == "memory_care":
            cond = s.get(f"mc_conditions_{pid}", s.get("mc_conditions"))
            cond_str = ", ".join(cond) if isinstance(cond, list) else (cond or "—")
            detail = ", ".join([f"Care: {pick('mc_care_level')}", f"Mobility: {pick('mc_mobility')}", f"Conditions: {cond_str}"])
        elif scenario == "in_home":
            hrs = s.get(f"ih_hours_per_day_{pid}", s.get("ih_hours_per_day", 4)); days = s.get(f"ih_days_per_month_{pid}", s.get("ih_days_per_month", 20))
            ctype = s.get(f"ih_caregiver_type_{pid}", s.get("ih_caregiver_type", "Agency")).title()
            detail = f"{hrs} hrs/day × {days} days/mo, Caregiver: {ctype}"
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

    st.subheader("Totals")
    monthly_need = care_total + addl_total
    gap = monthly_need - income_total
    assets_common = int(s.get("assets_common_total", 0))
    assets_detail = int(s.get("assets_detailed_total", 0))
    assets_total = assets_common + assets_detail
    col1, col2, col3 = st.columns(3)
    col1.metric("Monthly Care + Selected Costs", money(monthly_need))
    col2.metric("Total Monthly Income (incl. VA)", money(income_total))
    col3.metric("Estimated Monthly Gap", money(gap))
    if gap > 0 and assets_total > 0:
        months = int(assets_total // max(gap, 1)); years = months // 12; rem = months % 12
        msg = f"Estimated runway from assets: {years} years, {rem} months" if years > 0 else f"Estimated runway from assets: {rem} months"
    else:
        msg = "Estimated runway from assets: 0 months"
    st.subheader(msg)

    with st.expander("Assets (for context)"):
        st.table([
            {"Assets":"Common assets (cash, investments, etc.)","Amount":money(assets_common)},
            {"Assets":"Detailed assets (home sale, etc.)","Amount":money(assets_detail)},
            {"Assets":"Total assets","Amount":money(assets_total)},
        ])

    st.divider()
    cta1, cta2 = st.columns(2)
    with cta1:
        if st.button("Back to Household", key="bd_back_house"): st.session_state.step = "household"; st.rerun()
    with cta2:
        if st.button("Schedule with an Advisor", key="bd_pfma_btn"): st.session_state.step = "pfma"; st.rerun()

elif st.session_state.step == "pfma":
    render_pfma()
