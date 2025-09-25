# pages/Plan_for_My_Advisor.py — PFMA prototype (prefill + structured Optional; best-time-to-call)
from __future__ import annotations
import streamlit as st
from datetime import date

# ---------- Fake defaults for fast prototyping (overridden by upstream session if present) ----------
FAKE_DEFAULTS = {
    "name": "Pat Sample",
    "phone": "555-123-9876",
    "email": "pat.sample@example.com",
    "zip": "94107",
    "best_time": "Weekday mornings",
}

# ---------- tiny helpers ----------
def _first_truthy(*vals, fallback: str = "") -> str:
    for v in vals:
        if v is not None and str(v).strip() != "":
            return str(v).strip()
    return fallback

def _prefill(field: str, fallback: str) -> str:
    # prefer app-level session values; treat empty strings as missing
    if field == "name":
        return _first_truthy(st.session_state.get("user_name"), fallback, fallback=fallback)
    if field == "phone":
        return _first_truthy(st.session_state.get("user_phone"), fallback, fallback=fallback)
    if field == "email":
        return _first_truthy(st.session_state.get("user_email"), fallback, fallback=fallback)
    if field == "zip":
        gc = st.session_state.get("gc_summary") or {}
        return _first_truthy(gc.get("zip"), fallback, fallback=fallback)
    return fallback

# ---------- main render ----------
def render_pfma():
    st.title("Plan for My Advisor")
    st.caption("Schedule a time with an advisor. We'll only ask what we need right now.")

    # Context pulled from session if present (safe defaults)
    gc = st.session_state.get("gc_summary", {})
    calc = st.session_state.get("calculator_snapshot")

    with st.expander("Your current plan summary", expanded=True):
        if gc:
            st.subheader("Recommendation")
            st.markdown(f"**Suggested path:** {gc.get('care_path', '—')}")
            flags = gc.get("flags") or []
            if flags:
                st.caption("Flags")
                st.write(", ".join(str(f).replace("_", " ").title() for f in flags))
        else:
            st.info("No Guided Care Plan found. You can still book now.")

        if calc:
            st.subheader("Budget snapshot")
            cols = st.columns(3)
            try:
                cols[0].metric("Est. Monthly Cost", f"${float(calc.get('monthly_cost', 0)):,.0f}")
            except Exception:
                cols[0].metric("Est. Monthly Cost", calc.get("monthly_cost", "—"))
            try:
                cols[1].metric("Monthly Gap", f"${float(calc.get('monthly_gap', 0)):,.0f}")
            except Exception:
                cols[1].metric("Monthly Gap", calc.get("monthly_gap", "—"))
            yf = calc.get("years_funded")
            cols[2].metric("Years Funded", f"{float(yf):.1f}" if isinstance(yf, (int, float)) else "—")
        else:
            st.info("No Cost Planner data yet. You can add numbers later or try the calculator after booking.")

    st.divider()

    # -------------- Booking (prefilled) --------------
    # Seed widget state to ensure prefill even if widgets were mounted earlier
    st.session_state.setdefault("pfma_name", _prefill("name", FAKE_DEFAULTS["name"]))
    st.session_state.setdefault("pfma_phone", _prefill("phone", FAKE_DEFAULTS["phone"]))
    st.session_state.setdefault("pfma_email", _prefill("email", FAKE_DEFAULTS["email"]))
    st.session_state.setdefault("pfma_zip", _prefill("zip", FAKE_DEFAULTS["zip"]))
    st.session_state.setdefault("pfma_best_time", FAKE_DEFAULTS["best_time"])

    with st.form("pfma_booking_form"):
        st.subheader("Booking details")

        name = st.text_input("Your name", value=st.session_state["pfma_name"], key="pfma_name")
        relationship = st.selectbox(
            "Your relationship to the care recipient",
            ["Self", "Spouse/Partner", "Adult Child", "POA/Representative", "Other"],
            index=0,
            key="pfma_relationship",
        )
        phone = st.text_input(
            "Best phone number",
            value=st.session_state["pfma_phone"],
            placeholder="+1 (___) ___-____",
            key="pfma_phone",
        )
        email = st.text_input("Email (optional)", value=st.session_state["pfma_email"], key="pfma_email")
        zipcode = st.text_input("ZIP code for care search", value=st.session_state["pfma_zip"], key="pfma_zip")

        urgency = st.selectbox(
            "When do you need support?",
            ["Exploring (3+ months)", "Planning (1–3 months)", "Soon (2–4 weeks)", "ASAP (0–7 days)"],
            index=1,
            key="pfma_urgency",
        )

        constraints = st.text_area(
            "Any must-haves or constraints? (optional)",
            placeholder="Pets allowed, near daughter in Seattle, budget cap, wheelchair accessible...",
            key="pfma_constraints",
        )

        payer_options = ["Prefer not to say", "Private Pay", "LTC Insurance", "VA Aid & Attendance", "Medicaid"]
        payer_idx = 0
        if calc and calc.get("payer_hint") in payer_options:
            payer_idx = payer_options.index(calc["payer_hint"])
        payer_hint = st.selectbox("Primary payer (optional)", payer_options, index=payer_idx, key="pfma_payer_hint")

        best_time = st.text_input(
            "Best time to call",
            value=st.session_state["pfma_best_time"],
            placeholder="E.g., weekday mornings, afternoons after 2pm",
            key="pfma_best_time",
        )

        consent = st.checkbox("I agree to be contacted by an advisor", value=True, key="pfma_consent")

        submitted = st.form_submit_button("Schedule call", type="primary", use_container_width=True)
        if submitted:
            if not name or not phone or not zipcode:
                st.error("Please complete the required fields (name, phone, ZIP).")
            else:
                st.success(f"Call request submitted. We'll try to reach you around: {best_time}.")
                st.session_state["pfma_step"] = "optional"
                st.session_state["pfma_booking_data"] = {
                    "name": name,
                    "relationship": relationship,
                    "phone": phone,
                    "email": email,
                    "zipcode": zipcode,
                    "urgency": urgency,
                    "constraints": constraints,
                    "payer_hint": payer_hint,
                    "best_time": best_time,
                    "consent": consent,
                }

    # -------------- Optional enrichment (structured; intake-complete) --------------
    if st.session_state.get("pfma_step") == "optional":
        st.success("Share a bit more so we can prepare. Totally optional.")

        # Option sets
        DIAG_PRIMARY = [
            "Alzheimer’s / Dementia", "Parkinson’s", "Stroke / TIA history", "Heart failure / CAD",
            "COPD / Emphysema", "Diabetes — oral meds", "Diabetes — insulin",
            "Kidney disease", "Cancer (active)", "Depression / Anxiety",
            "Schizophrenia / Bipolar", "Arthritis / Osteoporosis",
        ]
        BEHAVIORS = [
            "Wandering / exit seeking", "Aggression", "Sundowning",
            "Delusions / hallucinations", "Fall risk", "Sleep disturbance / night wandering",
        ]
        NURSING_TASKS = ["Catheter", "Wound care", "Injections", "Ostomy", "Hoyer lift transfers"]
        ADLS = ["Bathing", "Dressing", "Grooming", "Toileting", "Continence", "Transferring", "Eating/Feeding"]
        IADLS = [
            "Medication management", "Meal preparation", "Housekeeping", "Laundry", "Shopping",
            "Transportation", "Managing finances", "Phone/computer use",
        ]
        ASSIST_LEVELS = ["Independent", "Stand-by assist", "One-person assist", "Two-person assist", "Hoyer"]
        MOBILITY_DEVICES = ["Wheelchair", "Walker", "Cane", "None"]
        WEIGHT_BEARING = ["WBAT", "Partial", "Non-weight-bearing", "Other"]
        INCONTINENCE = ["Fully continent", "Bladder", "Bowel", "Both"]
        DIETS = ["Regular", "Vegetarian", "Diabetic", "Low sodium", "Renal", "Texture-modified", "Other"]

        # Financial snapshot (compact)
        with st.expander("Financial snapshot (optional)", expanded=False):
            if calc:
                bullets = []
                if calc.get("payer_hint"):
                    bullets.append(f"Primary payer: {calc['payer_hint']}")
                inc = calc.get("income") or {}
                if inc:
                    bullets.append(f"Income sources: {', '.join(inc.keys())}")
                if calc.get("assets"):
                    bullets.append("Assets on file")
                st.write("\n".join(f"- {b}" for b in bullets) or "We have some planner data on file.")
            else:
                budget_band = st.select_slider(
                    "Realistic monthly care budget",
                    options=["<$3,000", "$3,000–$5,000", "$5,000–$8,000", ">$8,000"],
                    value="$3,000–$5,000",
                    key="pfma_budget_band",
                )
                benefits = st.multiselect(
                    "Benefits that may help with costs", ["VA Aid & Attendance", "LTC Insurance", "Medicaid"],
                    key="pfma_benefits",
                )
                months_private = st.number_input(
                    "If Medicaid is expected later, how many months of private pay first?",
                    min_value=0, max_value=120, value=0, step=1, key="pfma_months_private_pay",
                )
                st.caption("Prefer a full breakdown? Try the Cost Planner for detailed numbers and an affordability timeline.")

        # Health & care
        with st.expander("Health & care (optional)", expanded=False):
            dx = st.multiselect("Primary diagnoses (select all that apply)", DIAG_PRIMARY, key="pfma_dx")
            dx_other = st.text_input("Other diagnosis (optional)", key="pfma_dx_other")

            behaviors = st.multiselect("Behaviors / risks", BEHAVIORS, key="pfma_behaviors")

            col_o2a, col_o2b = st.columns([1, 1])
            with col_o2a:
                uses_o2 = st.checkbox("Oxygen use", key="pfma_o2_use")
            with col_o2b:
                liters = st.number_input(
                    "Liters per minute", min_value=0.0, max_value=15.0, value=2.0, step=0.5,
                    key="pfma_o2_liters", disabled=not uses_o2,
                )

            swallow = st.checkbox("Swallowing concerns", key="pfma_swallow")
            nursing = st.multiselect("Special nursing procedures", NURSING_TASKS, key="pfma_nursing")
            nursing_other = st.text_input("Other nursing procedure (optional)", key="pfma_nursing_other")

            col_eyes, col_ears = st.columns(2)
            with col_eyes:
                vision_issue = st.checkbox("Vision issues", key="pfma_vision")
            with col_ears:
                hearing_issue = st.checkbox("Hearing issues", key="pfma_hearing")
            vh_notes = st.text_input("Vision/hearing notes (optional)", key="pfma_vh_notes")

            # Vitals & nutrition
            col_ht, col_wt, col_change = st.columns([1, 1, 1])
            with col_ht:
                height = st.text_input("Height (ft/in or cm)", key="pfma_height")
            with col_wt:
                weight = st.text_input("Weight (lb or kg)", key="pfma_weight")
            with col_change:
                wt_change = st.selectbox(">10 lb change in 6 months", ["No", "Yes"], key="pfma_wt_change")

            diet = st.multiselect("Dietary restrictions / texture", DIETS, default=[], key="pfma_diet")
            eat_help = st.multiselect(
                "Eating support", ["None", "Prompting", "Setup", "Hands-on assistance"],
                default=[], key="pfma_eating_help",
            )

            smoke = st.selectbox("Smoking", ["No", "Yes"], key="pfma_smoking")
            drink = st.selectbox("Alcohol", ["No", "Yes"], key="pfma_alcohol")
            sleep = st.selectbox("Sleep pattern", ["Typical", "Fragmented", "Day-night reversal", "Other"], key="pfma_sleep")

            cognition = st.selectbox(
                "Cognition", ["Intact", "Mild impairment", "Moderate impairment", "Severe impairment"],
                key="pfma_cognition",
            )
            hospice_disc = st.selectbox("Recently discharged from hospice", ["No", "Yes"], key="pfma_hospice_disc")

            # PCP & meds (lightweight)
            pcp = st.text_input("Primary doctor / clinic / phone", key="pfma_pcp")
            med_allergies = st.text_input("Medication allergies (comma separated)", key="pfma_med_allergies")
            med_summary = st.text_area(
                "Medication summary (optional)", placeholder="E.g., insulin; diuretic; anticoagulant",
                key="pfma_med_summary",
            )

        # Daily activities
        with st.expander("Daily activities (ADLs/IADLs)", expanded=False):
            adls = st.multiselect("ADLs needing support", ADLS, key="pfma_adls")
            iadls = st.multiselect("IADLs needing support", IADLS, key="pfma_iadls")

            col_mob1, col_mob2, col_mob3 = st.columns([1, 1, 1])
            with col_mob1:
                device = st.selectbox("Mobility device", MOBILITY_DEVICES, key="pfma_mobility_device")
            with col_mob2:
                wb = st.selectbox("Weight-bearing status", WEIGHT_BEARING, key="pfma_weight_bearing")
            with col_mob3:
                transfer = st.selectbox("Transfer ability", ASSIST_LEVELS, key="pfma_transfer")

            incont = st.selectbox("Incontinence", INCONTINENCE, index=0, key="pfma_incontinence")
            toilet_notes = st.text_input("Toileting notes (optional)", key="pfma_toileting_notes")

            col_bath, col_groom = st.columns(2)
            with col_bath:
                bath_freq = st.selectbox(
                    "Preferred bathing/shower frequency",
                    ["Daily", "Every other day", "2x/week", "Weekly", "Other"],
                    key="pfma_bath_freq",
                )
            with col_groom:
                grooming = st.selectbox("Grooming assistance", ASSIST_LEVELS, key="pfma_grooming")

        # Current setting & timing
        with st.expander("Current setting & timing", expanded=False):
            living_now = st.selectbox(
                "Current living arrangement",
                ["Home", "Hospital", "Rehab", "Skilled Nursing Facility", "Other"],
                key="pfma_living_now",
            )
            col_fac, col_room = st.columns([2, 1])
            with col_fac:
                facility = st.text_input("Facility (if not home)", key="pfma_facility")
            with col_room:
                room = st.text_input("Room # (optional)", key="pfma_room")

            col_admit, col_discharge = st.columns(2)
            with col_admit:
                admit_dt = st.date_input("Initial admit date (if applicable)", value=date.today(), key="pfma_admit_dt")
            with col_discharge:
                discharge_dt = st.date_input("Expected discharge date (if applicable)", value=date.today(), key="pfma_discharge_dt")

            reason_stay = st.text_input("If hospital/SNF, reason for stay (optional)", key="pfma_reason_stay")

            loc_pref = st.text_input("Preferred location(s) (ZIPs, neighborhoods, near family)", key="pfma_location_pref")

        # Social & environment
        with st.expander("Social & environment", expanded=False):
            likes_kids = st.selectbox("Enjoys being around children", ["No", "Yes"], key="pfma_likes_kids")
            likes_pets = st.selectbox("Likes/has pets", ["No", "Yes"], key="pfma_likes_pets")
            activities = st.text_input("Activities enjoyed (comma separated)", key="pfma_activities")
            prejudice = st.selectbox("Known prejudices that could affect placement", ["No", "Yes"], key="pfma_prejudice")
            prejudice_note = st.text_input(
                "If yes, brief note", key="pfma_prejudice_note", disabled=(prejudice == "No")
            )

        # Contacts & legal
        with st.expander("Contacts & legal", expanded=False):
            marital = st.selectbox("Marital status", ["Single", "Married", "Widowed", "Divorced", "Partnered"], key="pfma_marital")
            poa = st.selectbox("POA/DPOA", ["None", "POA", "DPOA"], key="pfma_poa")

            st.markdown("**Representative / POA**")
            col_r1, col_r2 = st.columns(2)
            with col_r1:
                rep_name = st.text_input("Name", key="pfma_rep_name")
                rep_phone = st.text_input("Phone", key="pfma_rep_phone")
            with col_r2:
                rep_rel = st.text_input("Relationship", key="pfma_rep_rel")
                rep_email = st.text_input("Email", key="pfma_rep_email")

            st.markdown("**Alternate contact**")
            col_a1, col_a2 = st.columns(2)
            with col_a1:
                alt_name = st.text_input("Alt contact name", key="pfma_alt_name")
                alt_phone = st.text_input("Alt contact phone", key="pfma_alt_phone")
            with col_a2:
                alt_rel = st.text_input("Alt contact relationship", key="pfma_alt_rel")
                alt_email = st.text_input("Alt contact email", key="pfma_alt_email")

            st.markdown("**Referral source**")
            col_ref1, col_ref2 = st.columns(2)
            with col_ref1:
                ref_name = st.text_input("Referral name", key="pfma_ref_name")
                ref_phone = st.text_input("Referral phone", key="pfma_ref_phone")
            with col_ref2:
                ref_email = st.text_input("Referral email", key="pfma_ref_email")

        # Save
        if st.button("Save optional details", key="pfma_save_optional"):
            st.success("Details saved. Your advisor will review them before your call.")
            st.balloons()

# Local dev convenience
if __name__ == "__main__":
    render_pfma()
