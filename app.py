# app.py — Senior Navigator (Planner → Recommendations → Costs → Household → Breakdown → PFMA)
from __future__ import annotations

import os
from pathlib import Path
import traceback
import streamlit as st

from cost_controls import (
    render_location_control,
    render_costs_for_active_recommendations,
    CONDITION_OPTIONS,
)

# Feature flag for gamification
ENABLE_PFMA_GAMIFICATION = os.environ.get("ENABLE_PFMA_GAMIFICATION", "true").lower() in {"true", "1", "yes"}

st.set_page_config(page_title="Senior Navigator • Planner + Cost", page_icon="🧭", layout="centered")

ROOT = Path(__file__).resolve().parent
QA_PATH = ROOT / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = ROOT / "recommendation_logic_FINAL_MASTER_UPDATED.json"

try:
    from engines import PlannerEngine, CalculatorEngine, PlannerResult
except Exception:
    st.error("Failed to import engines.py")
    st.code(traceback.format_exc())
    st.stop()

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
    if not isinstance(amap, dict) or not amap:
        return default_key
    keys, labels = order_answer_map(amap)
    if not labels:
        return default_key
    idx = keys.index(str(default_key)) if default_key is not None and str(default_key) in keys else 0
    sel_label = st.radio(label, labels, index=idx, key=key)
    return keys[labels.index(sel_label)]

def money(n: int | float) -> str:
    try: return f"${int(round(float(n))):,}"
    except Exception: return "$0"

# ---------------- PFMA Utilities ----------------
def _merge_conditions_from_cost_planner() -> list[str]:
    """Gather conditions from canon and per-person saved keys. Sanitize to valid options."""
    valid = set(CONDITION_OPTIONS)
    merged = []
    for c in st.session_state.get("canon_conditions", []) or []:
        if c in valid and c not in merged:
            merged.append(c)
    for p in st.session_state.get("people", []):
        pid = p["id"]
        for kind in ("al", "mc"):
            vals = st.session_state.get(f"{kind}_conditions_saved_{pid}")
            if isinstance(vals, list):
                for c in vals:
                    if c in valid and c not in merged:
                        merged.append(c)
        for k in (f"{pid}_al_chronic", f"{pid}_mc_chronic"):
            val = st.session_state.get(k)
            if val in ("Diabetes", "Parkinson's") and val not in merged:
                merged.append(val)
    return merged

def _derive_adls_from_flags(pid: str) -> list[str]:
    """Map Guided Care Plan flags and Cost Planner data to ADLs for prefilling pfma_adls."""
    adls = []
    res = st.session_state.get("planner_results", {}).get(pid)
    flags = set(getattr(res, "flags", []) if res else [])
    if "moderate_dependence" in flags or "high_dependence" in flags:
        adls.extend(["Bathing", "Dressing", "Eating / meals"])
    if "high_mobility_dependence" in flags or "moderate_mobility" in flags:
        adls.append("Transferring / mobility")
    if "limited_support" in flags or "no_support" in flags:
        adls.append("Companionship / safety checks")
    if "moderate_cognitive_decline" in flags or "severe_cognitive_risk" in flags:
        adls.append("Medication management")
    if "moderate_safety_concern" in flags or "high_safety_concern" in flags:
        adls.append("Companionship / safety checks")
    if "low_access" in flags or "very_low_access" in flags:
        adls.append("Transportation")
    for kind in ("al", "mc"):
        care_level = st.session_state.get(f"{kind}_care_level_{pid}", st.session_state.get(f"{kind}_care_level"))
        if care_level in ("Moderate", "High"):
            adls.extend(["Bathing", "Dressing", "Toileting"])
    if st.session_state.get(f"ih_hours_per_day_{pid}", st.session_state.get("ih_hours_per_day", 0)) > 4:
        adls.extend(["Bathing", "Dressing", "Eating / meals"])
    return list(set(adls))

# ---------------- PFMA render ----------------
def render_pfma():
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
    # Prefill chronic conditions from cost planner if PFMA is empty
    if not s.get("pfma_conditions"):
        merged = _merge_conditions_from_cost_planner()
        if merged:
            s.pfma_conditions = merged
    st.divider()
    st.subheader("Optional details for your advisor")
    st.caption("These optional details help your advisor prepare for your consultation, saving time and focusing on your care options. Complete as much as you’re comfortable with!")
    if ENABLE_PFMA_GAMIFICATION:
        # Gamification: Progress and Badges
        optional_sections = [
            {"key": "pfma_care_type", "label": "Confirm Guided Care Plan"},
            {"key": "pfma_conditions", "label": "Confirm Cost Planner"},
            {"key": "pfma_symptoms", "label": "Care Needs & Daily Support"},
            {"key": "pfma_settings", "label": "Care Preferences"},
            {"key": "pfma_marital", "label": "Household & Legal Basics"},
            {"key": "pfma_ltc", "label": "Benefits & Coverage"},
            {"key": "pfma_name", "label": "Personal Information"},
        ]
        filled_count = 0
        total_sections = 6 if s.get("pfma_relationship") != "Self" else 7
        for section in optional_sections:
            if section["key"] == "pfma_name" and s.get("pfma_relationship") != "Self":
                continue
            val = s.get(section["key"])
            if val or (isinstance(val, list) and len(val) > 0):
                filled_count += 1
        progress = filled_count / total_sections
        st.progress(progress, text=f"Progress: {filled_count}/{total_sections} sections completed – You’re helping us tailor your care plan!")
    with st.expander("Confirm Guided Care Plan"):
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
            default_adls = _derive_adls_from_flags(pid)
            st.multiselect(
                f"Confirm activities needing support for {name}",
                [
                    "Bathing", "Dressing", "Toileting", "Transferring / mobility", "Eating / meals",
                    "Medication management", "Transportation", "Housekeeping / laundry",
                    "Finances / bills", "Companionship / safety checks"
                ],
                default=default_adls,
                key=f"pfma_adls_{pid}",
            )
        if st.button("Confirm Guided Care Plan", key="pfma_guided_confirm"):
            for p in people:
                pid = p["id"]
                s.pfma_care_type = {**s.get("pfma_care_type", {}), pid: s[f"pfma_care_type_{pid}"]}
                s.pfma_adls = {**s.get("pfma_adls", {}), pid: s[f"pfma_adls_{pid}"]}
            st.success("Guided Care Plan details confirmed!")
    with st.expander("Confirm Cost Planner"):
        st.write("Based on your Cost Planner, we’ve pre-filled your health and mobility details. If you haven’t completed it yet, please add these details to ensure we have the right information. Review and confirm or edit to make sure it’s right.")
        for p in people:
            pid, name = p["id"], p["display_name"]
            default_conditions = s.get("pfma_conditions", []) or _merge_conditions_from_cost_planner()
            st.multiselect(
                f"Confirm chronic conditions for {name}",
                CONDITION_OPTIONS,
                default=default_conditions,
                key=f"pfma_conditions_{pid}",
                on_change=lambda: st.rerun(),
            )
            if "Diabetes" in s.get(f"pfma_conditions_{pid}", []):
                st.selectbox(
                    f"Diabetes control for {name}",
                    ["Oral meds", "Insulin", "Diet-controlled", "Other"],
                    key=f"pfma_diabetes_control_{pid}",
                )
            mobility = s.get(f"al_mobility_{pid}", s.get(f"mc_mobility_{pid}", s.get(f"ih_mobility_{pid}", "None")))
            st.selectbox(
                f"Confirm mobility needs for {name}",
                ["None", "Walker", "Wheelchair"],
                index=["None", "Walker", "Wheelchair"].index(mobility),
                key=f"pfma_mobility_{pid}",
            )
        if st.button("Confirm Cost Planner", key="pfma_cost_confirm"):
            for p in people:
                pid = p["id"]
                s.pfma_conditions = {**s.get("pfma_conditions", {}), pid: s[f"pfma_conditions_{pid}"]}
                s.pfma_mobility = {**s.get("pfma_mobility", {}), pid: s[f"pfma_mobility_{pid}"]}
                if "Diabetes" in s[f"pfma_conditions_{pid}"]:
                    s.pfma_diabetes_control = {**s.get("pfma_diabetes_control", {}), pid: s[f"pfma_diabetes_control_{pid}"]}
            st.success("Cost Planner details confirmed!")
    with st.expander("Care Needs & Daily Support"):
        st.write("Help us tailor your care plan by sharing any additional health or daily support needs. These details can make a big difference in finding the right fit.")
        st.multiselect(
            "Symptoms or behaviors",
            ["Wandering", "Aggression", "Other"],
            key="pfma_symptoms",
        )
        st.text_area(
            "Mental health concerns",
            key="pfma_mental_health",
            placeholder="E.g., anxiety, depression",
        )
        st.multiselect(
            "Dietary restrictions or special needs",
            ["Vegetarian", "Diabetic", "Low Sodium", "Other"],
            key="pfma_dietary",
        )
        st.selectbox(
            "Cognition",
            ["Intact", "Mild impairment", "Moderate impairment", "Severe impairment"],
            key="pfma_cognition",
        )
        st.checkbox("Discharging on hospice", key="pfma_hospice")
        with st.expander("Additional Care Details (Very Optional)"):
            st.selectbox("Vision issues", ["No", "Yes"], key="pfma_vision")
            st.selectbox("Hearing issues", ["No", "Yes"], key="pfma_hearing")
            st.selectbox(
                "Weight-bearing status",
                ["Independent", "Needs assistance", "Non-weight-bearing"],
                key="pfma_weight",
            )
            st.selectbox(
                "Incontinence",
                ["Fully continent", "Bladder", "Bowel", "Both"],
                key="pfma_incont",
            )
            st.selectbox(
                "Sleeping pattern (typical night)",
                ["Sleeps through", "Up 1–2 times", "Up 3–5 times", "Frequent / hourly"],
                key="pfma_sleep",
            )
    with st.expander("Care Preferences"):
        st.write("Share your lifestyle and care preferences to help us find options that feel like home.")
        st.multiselect(
            "Settings you’re open to",
            ["In-home care", "Assisted Living", "Memory Care", "Not sure"],
            key="pfma_settings",
        )
        st.selectbox(
            "Why seeking care now?",
            [
                "Care needs increased", "Caregiver burnout", "Recent fall / hospitalization",
                "Memory decline", "Planning ahead", "Finances / affordability", "Other"
            ],
            key="pfma_why",
        )
        st.checkbox("Enjoys being around children", key="pfma_enjoys_children")
        st.text_area(
            "Scheduled activities resident enjoys",
            key="pfma_activities",
            placeholder="E.g., reading, gardening, social events",
        )
        st.selectbox(
            "Preferred search radius for care facilities",
            ["5 miles", "10 miles", "25 miles", "50 miles", "No preference"],
            key="pfma_radius",
        )
    with st.expander("Household & Legal Basics"):
        st.write("Tell us about your living situation, habits, and legal arrangements to ensure we recommend the right environment.")
        st.selectbox(
            "Marital status",
            ["Single", "Married", "Widowed", "Divorced", "Partnered"],
            key="pfma_marital",
        )
        st.checkbox("Do you have pets?", key="pfma_pets")
        st.selectbox(
            "Current living situation",
            ["Own home", "Renting", "Living with family", "Assisted living", "Other"],
            key="pfma_living_situation",
        )
        st.selectbox("Smoking", ["No", "Yes"], key="pfma_smoking")
        st.selectbox("Alcohol use", ["No", "Yes"], key="pfma_alcohol")
        st.selectbox("POA / DPOA", ["None", "POA", "DPOA"], key="pfma_poa_type")
        if s.get("pfma_poa_type") in ("POA", "DPOA"):
            st.text_input("POA/DPOA name", key="pfma_poa_name", placeholder="E.g., John Smith")
    with st.expander("Benefits & Coverage"):
        st.write("Let us know about your budget and benefits to ensure affordable and suitable options.")
        st.selectbox(
            "Realistic monthly care budget",
            ["<$3,000", "$3,000–$5,000", "$5,000–$8,000", ">$8,000"],
            key="pfma_budget",
        )
        st.selectbox(
            "Primary payer",
            ["Private pay", "Long-term care insurance", "Medicaid (or waiver)", "VA benefit", "Other / mixed"],
            key="pfma_primary_payer",
        )
        st.checkbox("Long-term care insurance", key="pfma_ltc", value=s.get("pfma_ltc", False))
        st.checkbox("VA benefit (or potential eligibility)", key="pfma_va", value=s.get("pfma_va", False))
        st.checkbox("Medicaid or waiver interest", key="pfma_medicaid")
    if s.get("pfma_relationship") == "Self":
        with st.expander("Personal Information"):
            st.write("Please review and confirm your contact details so we can reach you to discuss your care plan.")
            st.text_input("Your name", key="pfma_name_confirm", value=s.get("pfma_name", ""), placeholder="E.g., Taylor Morgan")
            st.text_input("Best phone number", key="pfma_phone_confirm", value=s.get("pfma_phone", ""), placeholder="E.g., (555) 123-4567")
            st.text_input("Email (optional)", key="pfma_email_confirm", value=s.get("pfma_email", ""), placeholder="E.g., taylor@example.com")
            st.text_input("Referral name (optional)", key="pfma_referral_name_confirm", value=s.get("pfma_referral_name", ""), placeholder="E.g., doctor, friend, or organization")
            if st.button("Confirm Personal Information", key="pfma_personal_confirm"):
                s.pfma_name = s.pfma_name_confirm
                s.pfma_phone = s.pfma_phone_confirm
                s.pfma_email = s.pfma_email_confirm
                s.pfma_referral_name = s.pfma_referral_name_confirm
                st.success("Personal details confirmed!")
    st.divider()
    if st.button("Save optional details", key="pfma_optional_save"):
        s.pfma_optional = {
            "care_type": s.get("pfma_care_type", {}),
            "adls": s.get("pfma_adls", {}),
            "conditions": s.get("pfma_conditions", {}),
            "diabetes_control": s.get("pfma_diabetes_control", {}),
            "mobility": s.get("pfma_mobility", {}),
            "symptoms": s.get("pfma_symptoms", []),
            "mental_health": s.get("pfma_mental_health", ""),
            "dietary": s.get("pfma_dietary", []),
            "cognition": s.get("pfma_cognition"),
            "hospice": s.get("pfma_hospice", False),
            "vision": s.get("pfma_vision"),
            "hearing": s.get("pfma_hearing"),
            "weight": s.get("pfma_weight"),
            "incontinence": s.get("pfma_incont"),
            "sleep": s.get("pfma_sleep"),
            "settings": s.get("pfma_settings", []),
            "why": s.get("pfma_why"),
            "enjoys_children": s.get("pfma_enjoys_children", False),
            "activities": s.get("pfma_activities", ""),
            "radius": s.get("pfma_radius"),
            "marital": s.get("pfma_marital"),
            "pets": s.get("pfma_pets", False),
            "living_situation": s.get("pfma_living_situation"),
            "smoking": s.get("pfma_smoking"),
            "alcohol": s.get("pfma_alcohol"),
            "poa_type": s.get("pfma_poa_type"),
            "poa_name": s.get("pfma_poa_name", ""),
            "budget": s.get("pfma_budget"),
            "primary_payer": s.get("pfma_primary_payer"),
            "has_ltc": s.get("pfma_ltc", False),
            "has_va": s.get("pfma_va", False),
            "medicaid_interest": s.get("pfma_medicaid", False),
        }
        if s.get("pfma_relationship") == "Self":
            s.pfma_optional.update({
                "name": s.get("pfma_name", ""),
                "phone": s.get("pfma_phone", ""),
                "email": s.get("pfma_email", ""),
                "referral_name": s.get("pfma_referral_name", ""),
            })
        st.success("Optional details saved.")
    if ENABLE_PFMA_GAMIFICATION:
        st.subheader("Your Badges 🎉")
        badges = []
        if any(s.get(k) for k in ["pfma_care_type", "pfma_adls"]):
            badges.append(("Care Plan Confirmer 📋", "Awarded for confirming your care plan details!"))
        if any(s.get(k) for k in ["pfma_conditions", "pfma_mobility", "pfma_diabetes_control"]):
            badges.append(("Cost Planner Confirmer 💡", "Thanks for verifying your health and mobility!"))
        if any(s.get(k) for k in ["pfma_symptoms", "pfma_mental_health", "pfma_dietary", "pfma_cognition", "pfma_hospice", "pfma_vision", "pfma_hearing", "pfma_weight", "pfma_incont", "pfma_sleep"]):
            badges.append(("Care Needs Expert 🩺", "Great job sharing health and support needs!"))
        if any(s.get(k) for k in ["pfma_settings", "pfma_why", "pfma_enjoys_children", "pfma_activities", "pfma_radius"]):
            badges.append(("Preferences Pro ⭐", "Thanks for detailing your care preferences!"))
        if any(s.get(k) for k in ["pfma_marital", "pfma_pets", "pfma_living_situation", "pfma_smoking", "pfma_alcohol", "pfma_poa_type", "pfma_poa_name"]):
            badges.append(("Household Hero 🏠", "Awesome work on household and legal details!"))
        if any(s.get(k) for k in ["pfma_budget", "pfma_primary_payer", "pfma_ltc", "pfma_va", "pfma_medicaid"]):
            badges.append(("Benefits Boss 💰", "Thanks for sharing budget and benefits info!"))
        if s.get("pfma_relationship") == "Self" and any(s.get(k) for k in ["pfma_name", "pfma_phone", "pfma_email", "pfma_referral_name"]):
            badges.append(("Personal Info Star 🌟", "Great job confirming your contact details!"))
        if badges:
            cols = st.columns(len(badges))
            for idx, (badge_text, badge_help) in enumerate(badges):
                with cols[idx]:
                    st.write(f"**{badge_text}**", help=badge_help)
        else:
            st.info("Complete sections to unlock badges and help your advisor!")
        if filled_count == total_sections:
            st.success("All sections complete! You’ve provided everything needed for a stellar consultation.")

# ---------------- Data files present? ----------------
missing = [p for p in (QA_PATH, REC_PATH) if not p.exists()]
if missing:
    st.error("Missing required JSON files:\\n" + "\\n".join(f"• {m.name}" for m in missing))
    st.stop()
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
if "step" not in st.session_state:
    st.session_state.step = "intro"
# Sidebar
st.sidebar.title("Senior Navigator")
st.sidebar.caption("Planner → Recommendations → Costs → Household")
st.sidebar.button("Start over", on_click=reset_all, key="start_over_btn")
if st.sidebar.button("Schedule with an Advisor", use_container_width=True, key="pfma_sidebar"):
    st.session_state.step = "pfma"; st.rerun()
# Flow
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
    for q_idx, q in enumerate(PlannerEngine(str(QA_PATH), str(REC_PATH)).qa.get("questions", []), start=1):
        label = q["question"]; amap = q.get("answers", {})
        if not amap or not isinstance(amap, dict):
            continue
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
            cond = s.get(f"al_conditions_saved_{pid}", s.get("al_conditions"))
            cond_str = ", ".join(cond) if isinstance(cond, list) else (cond or "—")
            detail = ", ".join([f"Care: {pick('al_care_level')}", f"Room: {pick('al_room_type')}", f"Mobility: {pick('al_mobility')}", f"Conditions: {cond_str}"])
        elif scenario == "memory_care":
            cond = s.get(f"mc_conditions_saved_{pid}", s.get("mc_conditions"))
            cond_str = ", ".join(cond) if isinstance(cond, list) else (cond or "—")
            detail = ", ".join([f"Care: {pick('mc_level')}", f"Mobility: {pick('mc_mobility')}", f"Conditions: {cond_str}"])
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
    st.divider()
    cta1, cta2 = st.columns(2)
    with cta1:
        if st.button("Back to Household", key="bd_back_house"): st.session_state.step = "household"; st.rerun()
    with cta2:
        if st.button("Schedule with an Advisor", key="bd_pfma_btn"): st.session_state.step = "pfma"; st.rerun()
elif st.session_state.step == "pfma":
    render_pfma()
