# pfma_controls.py — Plan for My Advisor (PFMA) question rendering and utilities
from __future__ import annotations
import streamlit as st

# Feature flag for gamification (imported from app.py to avoid duplication)
ENABLE_PFMA_GAMIFICATION = os.environ.get("ENABLE_PFMA_GAMIFICATION", "true").lower() in {"true", "1", "yes"}

def _merge_conditions_from_cost_planner(condition_options: list[str]) -> dict[str, list[str]]:
    """Gather conditions per person from canon and saved keys. Sanitize to valid options."""
    valid = set(condition_options)
    merged = {}
    for p in st.session_state.get("people", []):
        pid = p["id"]
        conditions = []
        for c in st.session_state.get("canon_conditions", []) or []:
            if c in valid and c not in conditions:
                conditions.append(c)
        for kind in ("al", "mc", "ih"):
            vals = st.session_state.get(f"{kind}_conditions_saved_{pid}")
            if isinstance(vals, list):
                for c in vals:
                    if c in valid and c not in conditions:
                        conditions.append(c)
        for k in (f"{pid}_al_chronic", f"{pid}_mc_chronic", f"{pid}_ih_chronic"):
            val = st.session_state.get(k)
            if val in ("Diabetes", "Parkinson's") and val not in conditions:
                conditions.append(val)
        merged[pid] = conditions
    return merged

def _derive_adls_and_others(pid: str) -> dict[str, any]:
    """Map Guided Care Plan flags and Cost Planner data to ADLs, mental health, cognition, dietary, settings, why, and mobility."""
    result = {
        "adls": [],
        "mental_health": "",
        "cognition": "Intact",
        "dietary": [],
        "settings": [],
        "why": "Planning ahead",
        "mobility": "None"
    }
    res = st.session_state.get("planner_results", {}).get(pid)
    flags = set(getattr(res, "flags", []) if res else [])
    # ADLs
    if "moderate_dependence" in flags or "high_dependence" in flags:
        result["adls"].extend(["Bathing", "Dressing", "Eating / meals"])
        result["why"] = "Care needs increased"
    if "high_mobility_dependence" in flags:
        result["adls"].append("Transferring / mobility")
        result["mobility"] = "Wheelchair"
    elif "moderate_mobility" in flags:
        result["adls"].append("Transferring / mobility")
        result["mobility"] = "Walker"
    if "limited_support" in flags or "no_support" in flags:
        result["adls"].append("Companionship / safety checks")
    if "moderate_cognitive_decline" in flags or "severe_cognitive_risk" in flags:
        result["adls"].append("Medication management")
        result["why"] = "Memory decline"
    if "moderate_safety_concern" in flags or "high_safety_concern" in flags:
        result["adls"].append("Companionship / safety checks")
        result["why"] = "Recent fall / hospitalization"
    if "low_access" in flags or "very_low_access" in flags:
        result["adls"].append("Transportation")
    for kind in ("al", "mc"):
        care_level = st.session_state.get(f"{kind}_care_level_{pid}", st.session_state.get(f"{kind}_care_level"))
        if care_level in ("Moderate", "High"):
            result["adls"].extend(["Bathing", "Dressing", "Toileting"])
            result["why"] = "Care needs increased"
        if kind == "mc" and care_level:
            result["why"] = "Memory decline"
    if st.session_state.get(f"ih_hours_per_day_{pid}", st.session_state.get("ih_hours_per_day", 0)) > 4:
        result["adls"].extend(["Bathing", "Dressing", "Eating / meals"])
        result["why"] = "Care needs increased"
    result["adls"] = list(set(result["adls"]))
    # Mental Health
    if "mental_health_concern" in flags:
        result["mental_health"] = "Possible depression or isolation"
    # Cognition
    if "severe_cognitive_risk" in flags:
        result["cognition"] = "Severe impairment"
    elif "moderate_cognitive_decline" in flags:
        result["cognition"] = "Moderate impairment"
    elif "mild_cognitive_decline" in flags:
        result["cognition"] = "Mild impairment"
    # Dietary
    conditions = st.session_state.get("pfma_conditions", {}).get(pid, _merge_conditions_from_cost_planner(condition_options).get(pid, []))
    if "Diabetes" in conditions:
        result["dietary"].append("Diabetic")
    # Settings
    if "open_to_move" in flags:
        result["settings"].extend(["Assisted Living", "Memory Care"])
    elif "prefers_home" in flags or "strongly_prefers_home" in flags:
        result["settings"].extend(["In-home care", "Not sure"])
    # Why (additional checks)
    if "needs_financial_assistance" in flags:
        result["why"] = "Finances / affordability"
    # Mobility from Cost Planner
    for kind in ("al", "mc", "ih"):
        mobility = st.session_state.get(f"{kind}_mobility_{pid}", st.session_state.get(f"{kind}_mobility"))
        if mobility in ("None", "Walker", "Wheelchair"):
            result["mobility"] = mobility
            break
    return result

def render_pfma():
    """Render the Plan for My Advisor (PFMA) questions and gamification."""
    def money(n: int | float) -> str:
        try: return f"${int(round(float(n))):,}"
        except Exception: return "$0"

    st.header("Plan for My Advisor")
    st.caption("Schedule a time with an advisor. We’ll only ask what we need right now.")

    s = st.session_state
    people = s.get("people", [])
    recs = s.get("planner_results", {})
    overrides = s.get("care_overrides", {})

    with st.expander("Your current plan summary", expanded=True):
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

    # Booking section
    st.subheader("Get Connected to Expert Advice")
    if "pfma_defaults_applied" not in s:
        s.pfma_name = "Taylor Morgan"
        s.pfma_phone = "(555) 201-8890"
        s.pfma_email = "taylor@example.com"
        s.pfma_zip = "94110"
        s.pfma_when = "Planning (1–3 months)"
        s.pfma_best_time = "Weekday mornings"
        s.pfma_relationship = "Self"
        s.pfma_age_band = "65–74"
        s.pfma_referral_name = ""
        s.pfma_booked = False
        s.pfma_defaults_applied = True

    c1, c2 = st.columns(2)
    with c1:
        st.text_input("Your name", key="pfma_name", placeholder="E.g., Taylor Morgan")
        st.selectbox(
            "Your relationship to the care recipient",
            ["Self", "Spouse/Partner", "Adult child", "Relative", "Friend/Neighbor", "Other"],
            key="pfma_relationship",
        )
        st.text_input("Best phone number", key="pfma_phone", placeholder="E.g., (555) 123-4567")
        st.text_input("Email (optional)", key="pfma_email", placeholder="E.g., taylor@example.com")
        st.text_input("ZIP code for care search", key="pfma_zip", placeholder="E.g., 94110")
        st.selectbox(
            "Approximate age range of care recipient (optional)",
            ["<65", "65–74", "75–84", "85–89", "90+"],
            key="pfma_age_band",
        )
    with c2:
        st.selectbox(
            "When do you need support?",
            ["Exploring (3–6+ months)", "Planning (1–3 months)", "Soon (2–4 weeks)", "ASAP / urgent"],
            key="pfma_when",
        )
        st.selectbox(
            "Best time to call",
            ["Weekday mornings", "Weekday afternoons", "Weekday evenings", "Weekend"],
            key="pfma_best_time",
        )
        st.text_area(
            "Any must-haves or constraints? (optional)",
            key="pfma_notes",
            placeholder="E.g., near Pasadena, small community, pet-friendly",
        )
        st.text_input("Referral name (optional)", key="pfma_referral_name", placeholder="E.g., doctor, friend, or organization")
    st.divider()
    colA, colB, colC = st.columns([1, 1, 1])
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
                "referral_name": s.pfma_referral_name.strip(),
            }
            s.pfma_booked = True
            st.success("Appointment request submitted. An advisor will reach out at your preferred time.")
            st.info("Add any optional details below to help your advisor prepare. Totally optional.")
    with colC:
        st.button("Finish", key="pfma_finish", type="secondary", on_click=lambda: s.update(step="intro"))
    # Optional details gate
    if not s.get("pfma_booked", False):
        st.caption("Optional questions will appear after you book.")
        return
    # Prefill LTC / VA once, based on household drawer state
    if "pfma_va" not in s:
        s.pfma_va = bool(s.get("a_va_monthly", 0) or s.get("b_va_monthly", 0) or s.get("va_monthly", 0))
    if "pfma_ltc" not in s:
        ltc_keys = ("a_ltc", "b_ltc", "ltc_insurance", "has_ltc_insurance", "household_ltc", "ltc_policy")
        s.pfma_ltc = any(str(s.get(k, "")).lower() in ("yes", "true", "1") for k in ltc_keys)
    # Prefill chronic conditions as a dictionary per person
    if not s.get("pfma_conditions"):
        s.pfma_conditions = _merge_conditions_from_cost_planner(CONDITION_OPTIONS)
    # Initialize confirmed sections for gamification
    if "pfma_confirmed_sections" not in s:
        s.pfma_confirmed_sections = {}
    st.divider()
    st.subheader("Optional details for your advisor")
    st.caption("These optional details help your advisor prepare for your consultation, saving time and focusing on your care options. Complete as much as you’re comfortable with!")
    if ENABLE_PFMA_GAMIFICATION:
        optional_sections = [
            {"key": "pfma_care_type", "label": "Confirm Guided Care Plan", "badge": "Care Plan Confirmer 📋"},
            {"key": "pfma_conditions", "label": "Confirm Cost Planner", "badge": "Cost Planner Confirmer 💡"},
            {"key": "pfma_symptoms", "label": "Care Needs & Daily Support", "badge": "Care Needs Expert 🩺"},
            {"key": "pfma_settings", "label": "Care Preferences", "badge": "Preferences Pro ⭐"},
            {"key": "pfma_marital", "label": "Household & Legal Basics", "badge": "Household Hero 🏠"},
            {"key": "pfma_ltc", "label": "Benefits & Coverage", "badge": "Benefits Boss 💰"},
            {"key": "pfma_name_confirm", "label": "Personal Information", "badge": "Personal Info Star 🌟"},
        ]
        filled_count = sum(1 for section in optional_sections if section["key"] in s.pfma_confirmed_sections and s.pfma_confirmed_sections[section["key"]])
        total_sections = 6 if s.get("pfma_relationship") != "Self" else 7
        st.write(f"Badges Earned: {filled_count}/{total_sections} 🏅")
        progress = filled_count / total_sections
        st.progress(progress, text=f"Progress: {filled_count}/{total_sections} sections completed – You’re helping us tailor your care plan!")
        # Visual progress indicators
        cols = st.columns(len(optional_sections))
        for idx, section in enumerate(optional_sections):
            if section["key"] == "pfma_name_confirm" and s.get("pfma_relationship") != "Self":
                continue
            with cols[idx]:
                icon = "✅" if section["key"] in s.pfma_confirmed_sections else "⚪"
                if st.button(f"{icon} {section['label']}", key=f"nav_{section['key']}", help=f"Go to {section['label']}"):
                    s[f"expander_{section['key']}"] = True
                    st.rerun()
        # Uncompleted sections prompt
        uncompleted = [section["label"] for section in optional_sections if section["key"] not in s.pfma_confirmed_sections and (section["key"] != "pfma_name_confirm" or s.get("pfma_relationship") == "Self")]
        if uncompleted:
            st.caption(f"Next steps: Complete {', '.join(uncompleted)} to earn more badges!")
    with st.expander("Confirm Guided Care Plan", expanded=s.get("expander_pfma_care_type", False)):
        st.write("Based on your Guided Care Plan, we’ve pre-filled your care type and daily needs. If you haven’t completed it yet, please fill in these details to help us tailor your care plan. Review and confirm or edit to ensure accuracy.")
        for p in people:
            pid, name = p["id"], p["display_name"]
            rec = recs.get(pid)
            care_type = s.get("care_overrides", {}).get(pid, getattr(rec, "care_type", "none")) if rec else "none"
            nice = {"none":"None","in_home":"In-home Care","assisted_living":"Assisted Living","memory_care":"Memory Care"}
            st.selectbox(
                f"Care type for {name}",
                ["None", "In-home Care", "Assisted Living", "Memory Care"],
                index=["None", "In-home Care", "Assisted Living", "Memory Care"].index(nice.get(care_type, "None")),
                key=f"pfma_care_type_{pid}",
            )
            derived = _derive_adls_and_others(pid)
            st.multiselect(
                f"Confirm activities needing support for {name}",
                [
                    "Bathing", "Dressing", "Toileting", "Transferring / mobility", "Eating / meals",
                    "Medication management", "Transportation", "Housekeeping / laundry",
                    "Finances / bills", "Companionship / safety checks"
                ],
                default=derived["adls"],
                key=f"pfma_adls_{pid}",
            )
        if st.button("Confirm Guided Care Plan", key="pfma_guided_confirm", type="primary"):
            s.pfma_confirmed_sections["pfma_care_type"] = True
            for p in people:
                pid = p["id"]
                s.pfma_care_type = {**s.get("pfma_care_type", {}), pid: s[f"pfma_care_type_{pid}"]}
                s.pfma_adls = {**s.get("pfma_adls", {}), pid: s[f"pfma_adls_{pid}"]}
            st.session_state.pfma_confirmed_sections = s.pfma_confirmed_sections
            st.success("You just earned the Care Plan Confirmer badge! Keep going!")
            st.rerun()
    with st.expander("Confirm Cost Planner", expanded=s.get("expander_pfma_conditions", False)):
        st.write("Based on your Cost Planner, we’ve pre-filled your health and mobility details. If you haven’t completed it yet, please add these details to ensure we have the right information. Review and confirm or edit to make sure it’s right.")
        for p in people:
            pid, name = p["id"], p["display_name"]
            default_conditions = s.get("pfma_conditions", {}).get(pid, _merge_conditions_from_cost_planner(CONDITION_OPTIONS).get(pid, []))
            st.multiselect(
                f"Confirm chronic conditions for {name}",
                CONDITION_OPTIONS,
                default=default_conditions,
                key=f"pfma_conditions_{pid}",
            )
            if "Diabetes" in s.get(f"pfma_conditions_{pid}", []):
                st.selectbox(
                    f"Diabetes control for {name}",
                    ["Oral meds", "Insulin", "Diet-controlled", "Other"],
                    key=f"pfma_diabetes_control_{pid}",
                )
            derived = _derive_adls_and_others(pid)
            st.selectbox(
                f"Confirm mobility needs for {name}",
                ["None", "Walker", "Wheelchair"],
                index=["None", "Walker", "Wheelchair"].index(derived["mobility"]),
                key=f"pfma_mobility_{pid}",
            )
        if st.button("Confirm Cost Planner", key="pfma_cost_confirm", type="primary"):
            s.pfma_confirmed_sections["pfma_conditions"] = True
            for p in people:
                pid = p["id"]
                s.pfma_conditions = {**s.get("pfma_conditions", {}), pid: s[f"pfma_conditions_{pid}"]}
                s.pfma_mobility = {**s.get("pfma_mobility", {}), pid: s[f"pfma_mobility_{pid}"]}
                if "Diabetes" in s[f"pfma_conditions_{pid}"]:
                    s.pfma_diabetes_control = {**s.get("pfma_diabetes_control", {}), pid: s[f"pfma_diabetes_control_{pid}"]}
            st.session_state.pfma_confirmed_sections = s.pfma_confirmed_sections
            st.success("You just earned the Cost Planner Confirmer badge! Keep going!")
            st.rerun()
    with st.expander("Care Needs & Daily Support", expanded=s.get("expander_pfma_symptoms", False)):
        st.write("Help us tailor your care plan by sharing additional health or daily support needs. These details are optional but can make a big difference in finding the right fit.")
        for p in people:
            pid, name = p["id"], p["display_name"]
            derived = _derive_adls_and_others(pid)
            st.multiselect(
                f"Symptoms or behaviors for {name}",
                ["Wandering", "Aggression", "Elopement", "Exit-seeking", "Confusion", "Agitation", "Other"],
                key=f"pfma_symptoms_{pid}",
                help="E.g., wandering at night can affect care needs"
            )
            st.text_area(
                f"Mental health concerns for {name}",
                value=derived["mental_health"],
                key=f"pfma_mental_health_{pid}",
                placeholder="E.g., anxiety, depression",
                help="This helps us recommend supportive activities"
            )
            st.multiselect(
                f"Dietary restrictions or special needs for {name}",
                ["Vegetarian", "Diabetic", "Low Sodium", "Other"],
                default=derived["dietary"],
                key=f"pfma_dietary_{pid}",
                help="Dietary needs guide meal planning"
            )
            st.selectbox(
                f"Cognition for {name}",
                ["Intact", "Mild impairment", "Moderate impairment", "Severe impairment"],
                index=["Intact", "Mild impairment", "Moderate impairment", "Severe impairment"].index(derived["cognition"]),
                key=f"pfma_cognition_{pid}",
                help="This helps tailor memory support"
            )
            st.selectbox(
                f"Vision issues for {name}",
                ["No", "Yes"],
                key=f"pfma_vision_{pid}",
                help="Vision issues can affect reading or safety"
            )
            st.selectbox(
                f"Hearing issues for {name}",
                ["No", "Yes"],
                key=f"pfma_hearing_{pid}",
                help="Hearing issues may require communication support"
            )
            st.selectbox(
                f"Weight-bearing status for {name}",
                ["Independent", "Needs assistance", "Non-weight-bearing"],
                key=f"pfma_weight_{pid}",
                help="This impacts mobility support"
            )
            st.selectbox(
                f"Incontinence for {name}",
                ["Fully continent", "Bladder", "Bowel", "Both"],
                key=f"pfma_incont_{pid}",
                help="This helps plan personal care"
            )
            st.selectbox(
                f"Sleeping pattern for {name} (typical night)",
                ["Sleeps through", "Up 1–2 times", "Up 3–5 times", "Frequent / hourly"],
                key=f"pfma_sleep_{pid}",
                help="Sleep patterns guide nighttime care"
            )
        if st.button("Confirm Care Needs & Daily Support", key="pfma_needs_confirm", type="primary"):
            s.pfma_confirmed_sections["pfma_symptoms"] = True
            for p in people:
                pid = p["id"]
                s.pfma_symptoms = {**s.get("pfma_symptoms", {}), pid: s[f"pfma_symptoms_{pid}"]}
                s.pfma_mental_health = {**s.get("pfma_mental_health", {}), pid: s[f"pfma_mental_health_{pid}"]}
                s.pfma_dietary = {**s.get("pfma_dietary", {}), pid: s[f"pfma_dietary_{pid}"]}
                s.pfma_cognition = {**s.get("pfma_cognition", {}), pid: s[f"pfma_cognition_{pid}"]}
                s.pfma_vision = {**s.get("pfma_vision", {}), pid: s[f"pfma_vision_{pid}"]}
                s.pfma_hearing = {**s.get("pfma_hearing", {}), pid: s[f"pfma_hearing_{pid}"]}
                s.pfma_weight = {**s.get("pfma_weight", {}), pid: s[f"pfma_weight_{pid}"]}
                s.pfma_incont = {**s.get("pfma_incont", {}), pid: s[f"pfma_incont_{pid}"]}
                s.pfma_sleep = {**s.get("pfma_sleep", {}), pid: s[f"pfma_sleep_{pid}"]}
            st.session_state.pfma_confirmed_sections = s.pfma_confirmed_sections
            st.success("You just earned the Care Needs Expert badge! Keep going!")
            st.rerun()
    with st.expander("Care Preferences", expanded=s.get("expander_pfma_settings", False)):
        st.write("Share your lifestyle and care preferences to help us find options that feel like home.")
        for p in people:
            pid, name = p["id"], p["display_name"]
            derived = _derive_adls_and_others(pid)
            st.multiselect(
                f"Settings you’re open to for {name}",
                ["In-home care", "Assisted Living", "Memory Care", "Not sure"],
                default=derived["settings"],
                key=f"pfma_settings_{pid}",
                help="Not sure? We’ll discuss options with you"
            )
            st.selectbox(
                f"Why seeking care now for {name}?",
                [
                    "Care needs increased", "Caregiver burnout", "Recent fall / hospitalization",
                    "Memory decline", "Planning ahead", "Finances / affordability", "Other"
                ],
                index=["Care needs increased", "Caregiver burnout", "Recent fall / hospitalization", "Memory decline", "Planning ahead", "Finances / affordability", "Other"].index(derived["why"]),
                key=f"pfma_why_{pid}",
                help="This helps us understand your urgency"
            )
            st.checkbox(f"Enjoys being around children for {name}", key=f"pfma_enjoys_children_{pid}", help="This ensures a family-friendly environment")
            st.checkbox(f"Do you have pets for {name}?", key=f"pfma_pets_{pid}", help="This helps find pet-friendly communities")
            st.text_area(
                f"Scheduled activities {name} enjoys",
                key=f"pfma_activities_{pid}",
                placeholder="E.g., reading, gardening, social events",
                help="This personalizes your daily routine"
            )
            st.selectbox(
                f"Preferred search radius for care facilities for {name}",
                ["5 miles", "10 miles", "25 miles", "50 miles", "No preference"],
                key=f"pfma_radius_{pid}",
                help="This narrows down care locations"
            )
        if st.button("Confirm Care Preferences", key="pfma_preferences_confirm", type="primary"):
            s.pfma_confirmed_sections["pfma_settings"] = True
            for p in people:
                pid = p["id"]
                s.pfma_settings = {**s.get("pfma_settings", {}), pid: s[f"pfma_settings_{pid}"]}
                s.pfma_why = {**s.get("pfma_why", {}), pid: s[f"pfma_why_{pid}"]}
                s.pfma_enjoys_children = {**s.get("pfma_enjoys_children", {}), pid: s[f"pfma_enjoys_children_{pid}"]}
                s.pfma_pets = {**s.get("pfma_pets", {}), pid: s[f"pfma_pets_{pid}"]}
                s.pfma_activities = {**s.get("pfma_activities", {}), pid: s[f"pfma_activities_{pid}"]}
                s.pfma_radius = {**s.get("pfma_radius", {}), pid: s[f"pfma_radius_{pid}"]}
            st.session_state.pfma_confirmed_sections = s.pfma_confirmed_sections
            st.success("You just earned the Preferences Pro badge! Keep going!")
            st.rerun()
    with st.expander("Household & Legal Basics", expanded=s.get("expander_pfma_marital", False)):
        st.write("Tell us about your living situation and legal arrangements to ensure we recommend the right environment.")
        for p in people:
            pid, name = p["id"], p["display_name"]
            st.selectbox(
                f"Marital status for {name}",
                ["Single", "Married", "Widowed", "Divorced", "Partnered"],
                key=f"pfma_marital_{pid}",
                help="This impacts housing and care planning"
            )
            st.selectbox(
                f"Current living situation for {name}",
                ["Own home", "Renting", "Living with family", "Assisted living", "Other"],
                key=f"pfma_living_situation_{pid}",
                help="This helps us understand your current home"
            )
            st.selectbox(
                f"Smoking for {name}",
                ["No", "Yes"],
                key=f"pfma_smoking_{pid}",
                help="Some communities have smoking policies"
            )
            st.selectbox(
                f"Alcohol use for {name}",
                ["No", "Yes"],
                key=f"pfma_alcohol_{pid}",
                help="This informs community fit"
            )
            st.selectbox(
                f"POA / DPOA for {name}",
                ["None", "POA", "DPOA"],
                key=f"pfma_poa_type_{pid}",
                help="This helps with legal coordination if needed"
            )
            if s.get(f"pfma_poa_type_{pid}") in ("POA", "DPOA"):
                st.text_input(
                    f"POA/DPOA name for {name}",
                    key=f"pfma_poa_name_{pid}",
                    placeholder="E.g., John Smith",
                    help="Provide the name of your POA/DPOA"
                )
        if st.button("Confirm Household & Legal Basics", key="pfma_household_confirm", type="primary"):
            s.pfma_confirmed_sections["pfma_marital"] = True
            for p in people:
                pid = p["id"]
                s.pfma_marital = {**s.get("pfma_marital", {}), pid: s[f"pfma_marital_{pid}"]}
                s.pfma_living_situation = {**s.get("pfma_living_situation", {}), pid: s[f"pfma_living_situation_{pid}"]}
                s.pfma_smoking = {**s.get("pfma_smoking", {}), pid: s[f"pfma_smoking_{pid}"]}
                s.pfma_alcohol = {**s.get("pfma_alcohol", {}), pid: s[f"pfma_alcohol_{pid}"]}
                s.pfma_poa_type = {**s.get("pfma_poa_type", {}), pid: s[f"pfma_poa_type_{pid}"]}
                s.pfma_poa_name = {**s.get("pfma_poa_name", {}), pid: s.get(f"pfma_poa_name_{pid}", "")}
            st.session_state.pfma_confirmed_sections = s.pfma_confirmed_sections
            st.success("You just earned the Household Hero badge! Keep going!")
            st.rerun()
    with st.expander("Benefits & Coverage", expanded=s.get("expander_pfma_ltc", False)):
        st.write("Let us know about your budget and benefits to ensure affordable and suitable options.")
        st.selectbox(
            "Realistic monthly care budget",
            ["<$3,000", "$3,000–$5,000", "$5,000–$8,000", ">$8,000"],
            key="pfma_budget",
            help="This guides affordable care options"
        )
        st.selectbox(
            "How will care primarily be paid for?",
            ["Private pay", "Long-term care insurance", "Medicaid (or waiver)", "VA benefit", "Other / mixed"],
            key="pfma_primary_payer",
            help="This helps your advisor explore funding options, even if most payers don’t cover senior living"
        )
        st.selectbox(
            "Health care insurance company (optional)",
            ["Humana", "Aetna", "United Healthcare", "Cigna", "Blue Cross Blue Shield", "Other"],
            key="pfma_insurance_company",
            help="This helps your advisor understand your coverage"
        )
        if s.get("pfma_insurance_company") == "Other":
            st.text_input(
                "Specify other insurance company",
                key="pfma_insurance_company_other",
                placeholder="E.g., Kaiser Permanente"
            )
        st.checkbox("Long-term care insurance", key="pfma_ltc", value=s.get("pfma_ltc", False), help="Check if you have an LTC policy")
        st.checkbox("VA benefit (or potential eligibility)", key="pfma_va", value=s.get("pfma_va", False), help="Check if you’re a veteran or eligible spouse")
        st.checkbox("Medicaid or waiver interest", key="pfma_medicaid", help="Check if you’re interested in Medicaid support")
        if st.button("Confirm Benefits & Coverage", key="pfma_benefits_confirm", type="primary"):
            s.pfma_confirmed_sections["pfma_ltc"] = True
            s.pfma_optional = s.get("pfma_optional", {})
            s.pfma_optional.update({
                "budget": s.get("pfma_budget", ""),
                "primary_payer": s.get("pfma_primary_payer", ""),
                "insurance_company": s.get("pfma_insurance_company_other", s.get("pfma_insurance_company", "")),
                "has_ltc": s.get("pfma_ltc", False),
                "has_va": s.get("pfma_va", False),
                "medicaid_interest": s.get("pfma_medicaid", False),
            })
            st.session_state.pfma_confirmed_sections = s.pfma_confirmed_sections
            st.success("You just earned the Benefits Boss badge! Keep going!")
            st.rerun()
    if s.get("pfma_relationship") == "Self":
        with st.expander("Personal Information", expanded=s.get("expander_pfma_name_confirm", False)):
            st.write("Please review and confirm your contact details so we can reach you to discuss your care plan.")
            st.text_input("Your name", key="pfma_name_confirm", value=s.get("pfma_name", ""), placeholder="E.g., Taylor Morgan", help="We only use this to contact you")
            st.text_input("Best phone number", key="pfma_phone_confirm", value=s.get("pfma_phone", ""), placeholder="E.g., (555) 123-4567", help="We’ll call at your preferred time")
            st.text_input("Email (optional)", key="pfma_email_confirm", value=s.get("pfma_email", ""), placeholder="E.g., taylor@example.com", help="Optional for email communication")
            st.text_input("Referral name (optional)", key="pfma_referral_name_confirm", value=s.get("pfma_referral_name", ""), placeholder="E.g., doctor, friend, or organization", help="Who referred you to us?")
            if st.button("Confirm Personal Information", key="pfma_personal_confirm", type="primary"):
                s.pfma_confirmed_sections["pfma_name_confirm"] = True
                s.pfma_optional = s.get("pfma_optional", {})
                s.pfma_optional.update({
                    "confirmed_name": s.get("pfma_name_confirm", ""),
                    "confirmed_phone": s.get("pfma_phone_confirm", ""),
                    "confirmed_email": s.get("pfma_email_confirm", ""),
                    "confirmed_referral_name": s.get("pfma_referral_name_confirm", ""),
                })
                st.session_state.pfma_confirmed_sections = s.pfma_confirmed_sections
                st.success("You just earned the Personal Info Star badge! Keep going!")
                st.rerun()
    st.divider()
    if st.button("Save optional details", key="pfma_optional_save", type="primary"):
        s.pfma_optional = {
            "care_type": s.get("pfma_care_type", {}),
            "adls": s.get("pfma_adls", {}),
            "conditions": s.get("pfma_conditions", {}),
            "diabetes_control": s.get("pfma_diabetes_control", {}),
            "mobility": s.get("pfma_mobility", {}),
            "symptoms": s.get("pfma_symptoms", {}),
            "mental_health": s.get("pfma_mental_health", {}),
            "dietary": s.get("pfma_dietary", {}),
            "cognition": s.get("pfma_cognition", {}),
            "vision": s.get("pfma_vision", {}),
            "hearing": s.get("pfma_hearing", {}),
            "weight": s.get("pfma_weight", {}),
            "incontinence": s.get("pfma_incont", {}),
            "sleep": s.get("pfma_sleep", {}),
            "settings": s.get("pfma_settings", {}),
            "why": s.get("pfma_why", {}),
            "enjoys_children": s.get("pfma_enjoys_children", {}),
            "pets": s.get("pfma_pets", {}),
            "activities": s.get("pfma_activities", {}),
            "radius": s.get("pfma_radius", {}),
            "marital": s.get("pfma_marital", {}),
            "living_situation": s.get("pfma_living_situation", {}),
            "smoking": s.get("pfma_smoking", {}),
            "alcohol": s.get("pfma_alcohol", {}),
            "poa_type": s.get("pfma_poa_type", {}),
            "poa_name": s.get("pfma_poa_name", {}),
            "budget": s.get("pfma_budget", ""),
            "primary_payer": s.get("pfma_primary_payer", ""),
            "insurance_company": s.get("pfma_insurance_company_other", s.get("pfma_insurance_company", "")),
            "has_ltc": s.get("pfma_ltc", False),
            "has_va": s.get("pfma_va", False),
            "medicaid_interest": s.get("pfma_medicaid", False),
        }
        if s.get("pfma_relationship") == "Self":
            s.pfma_optional.update({
                "confirmed_name": s.get("pfma_name_confirm", s.get("pfma_name", "")),
                "confirmed_phone": s.get("pfma_phone_confirm", s.get("pfma_phone", "")),
                "confirmed_email": s.get("pfma_email_confirm", s.get("pfma_email", "")),
                "confirmed_referral_name": s.get("pfma_referral_name_confirm", s.get("pfma_referral_name", "")),
            })
        st.success("Optional details saved.")
    if ENABLE_PFMA_GAMIFICATION:
        st.subheader("Your Badges 🎉")
        badges = []
        if "pfma_care_type" in s.pfma_confirmed_sections:
            badges.append(("Care Plan Confirmer 📋", "Awarded for confirming your care plan details!"))
        if "pfma_conditions" in s.pfma_confirmed_sections:
            badges.append(("Cost Planner Confirmer 💡", "Thanks for verifying your health and mobility!"))
        if "pfma_symptoms" in s.pfma_confirmed_sections:
            badges.append(("Care Needs Expert 🩺", "Great job sharing health and support needs!"))
        if "pfma_settings" in s.pfma_confirmed_sections:
            badges.append(("Preferences Pro ⭐", "Thanks for detailing your care preferences!"))
        if "pfma_marital" in s.pfma_confirmed_sections:
            badges.append(("Household Hero 🏠", "Awesome work on household and legal details!"))
        if "pfma_ltc" in s.pfma_confirmed_sections:
            badges.append(("Benefits Boss 💰", "Thanks for sharing budget and benefits info!"))
        if s.get("pfma_relationship") == "Self" and "pfma_name_confirm" in s.pfma_confirmed_sections:
            badges.append(("Personal Info Star 🌟", "Great job confirming your contact details!"))
        if badges:
            cols = st.columns(len(badges))
            for idx, (badge_text, badge_help) in enumerate(badges):
                with cols[idx]:
                    st.markdown(f"<div class='badge'>**{badge_text}**</div>", unsafe_allow_html=True, help=badge_help)
        else:
            st.info("Complete sections to unlock badges and help your advisor!")
        if filled_count == total_sections:
            st.success(f"Great job, {s.get('pfma_name', 'User')}! You’ve earned all {total_sections} badges and are ready for your consultation!")