# pages/Plan_for_My_Advisor.py
import streamlit as st

CONDITION_OPTIONS = [
    "Dementia / memory loss",
    "Parkinson's",
    "Stroke history",
    "Diabetes",
    "CHF / heart disease",
    "COPD / breathing issues",
    "Cancer (active)",
    "Depression / anxiety",
    "Other",
]

def _canon_condition(val: str | None) -> str | None:
    if not val:
        return None
    v = str(val).strip().replace("’", "'").lower()
    direct = {
        "parkinsons": "Parkinson's",
        "parkinson's": "Parkinson's",
        "parkinson’s": "Parkinson's",
        "diabetes": "Diabetes",
        "stroke": "Stroke history",
        "stroke history": "Stroke history",
        "chf": "CHF / heart disease",
        "heart disease": "CHF / heart disease",
        "heart failure": "CHF / heart disease",
        "copd": "COPD / breathing issues",
        "breathing issues": "COPD / breathing issues",
        "respiratory": "COPD / breathing issues",
        "cancer": "Cancer (active)",
        "depression": "Depression / anxiety",
        "anxiety": "Depression / anxiety",
        "none": None,
        "complex": None,
        "other": "Other",
    }
    if v in direct:
        return direct[v]
    if "alzheimer" in v or "dementia" in v or "memory" in v:
        return "Dementia / memory loss"
    if "parkinson" in v:
        return "Parkinson's"
    if "stroke" in v:
        return "Stroke history"
    if "diab" in v:
        return "Diabetes"
    if "heart" in v or "cardio" in v or "chf" in v:
        return "CHF / heart disease"
    if "copd" in v or "breath" in v or "respir" in v:
        return "COPD / breathing issues"
    if "cancer" in v:
        return "Cancer (active)"
    if "depress" in v or "anx" in v:
        return "Depression / anxiety"
    return None

def _merge_conditions() -> list[str]:
    """
    Prefer per-person canonical keys written by cost_controls:
      - conditions_{pid}
    Also merge any panel keys and legacy single-selects, then canonicalize.
    """
    s = st.session_state
    merged: list[str] = []
    seen = set()

    def add(vals):
        for raw in vals or []:
            lab = _canon_condition(raw)
            if lab and lab not in seen:
                merged.append(lab); seen.add(lab)

    # 1) Canonical per-person keys (highest priority)
    for p in s.get("people", []):
        pid = p.get("id")
        add(s.get(f"conditions_{pid}", []))

    # 2) Panel multiselects
    for p in s.get("people", []):
        pid = p.get("id")
        for k in (f"al_conditions_{pid}", f"mc_conditions_{pid}", f"ih_conditions_{pid}"):
            v = s.get(k)
            add(v if isinstance(v, list) else [v] if isinstance(v, str) else [])

    # 3) Legacy single-selects
    for p in s.get("people", []):
        pid = p.get("id")
        for k in (f"{pid}_al_chronic", f"{pid}_mc_chronic", f"{pid}_ih_chronic"):
            v = s.get(k)
            add([v] if isinstance(v, str) else [])

    # 4) Unscoped leftovers
    for k in ("al_conditions", "mc_conditions", "ih_conditions"):
        v = s.get(k)
        add(v if isinstance(v, list) else [v] if isinstance(v, str) else [])

    return merged

def _detect_ltc_va_defaults():
    s = st.session_state
    va = any([s.get("a_va_monthly", 0), s.get("b_va_monthly", 0), s.get("va_monthly", 0)])
    ltc = False
    for k in ("ltc_insurance", "has_ltc_insurance", "household_ltc", "ltc_policy"):
        v = s.get(k, False)
        if bool(v) and str(v).lower() not in ("false", "0", "", "none", "no"):
            ltc = True; break
    if not ltc:
        for k, v in s.items():
            if "ltc" in str(k).lower() and bool(v) and str(v).lower() not in ("false","0","","none","no"):
                ltc = True; break
    return ltc, va

def main():
    st.header("Plan for My Advisor")
    st.caption("Schedule a time with an advisor. We'll only ask what we need right now.")

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
            st.write(f"**Estimated current monthly care total:** ${total:,.0f}")
        else:
            st.info("No Cost Planner data yet.")

    # Always sync conditions on render
    merged = _merge_conditions()
    if merged:
        s.pfma_conditions = merged
    ltc, va = _detect_ltc_va_defaults()
    if "pfma_ltc" not in s:
        s.pfma_ltc = bool(ltc)
    if "pfma_va" not in s:
        s.pfma_va = bool(va)

    # One-time prototype defaults
    if "pfma_defaults_applied" not in s:
        s.pfma_name = "Taylor Morgan"
        s.pfma_phone = "(555) 201-8890"
        s.pfma_email = "taylor@example.com"
        s.pfma_zip = "94110"
        s.pfma_when = "Planning (1–3 months)"
        s.pfma_best_time = "Weekday mornings"
        s.pfma_relationship = "Self"
        s.pfma_payer = "Prefer not to say"
        s.pfma_notes = ""
        s.pfma_age_band = "65–74"
        s.pfma_booked = False
        s.pfma_defaults_applied = True

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
        if st.button("Back to Home", key="pfma_back_home"):
            s.step = "intro"; st.rerun()
    with colB:
        if st.button("Book appointment", key="pfma_book_btn"):
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
            st.success("✅ Appointment request submitted. An advisor will reach out at your preferred time.")
            st.info("Add any optional details below to help your advisor prepare. Totally optional.")
            st.balloons()
    with colC:
        st.button("Finish", key="pfma_finish", on_click=lambda: s.update(step="intro"))

    if not s.get("pfma_booked", False):
        st.caption("Optional questions will appear after you book.")
        return

    st.divider()
    st.subheader("Optional details for your advisor")

    with st.expander("Care needs & daily support"):
        col1, col2 = st.columns(2)
        with col1:
            st.multiselect(
                "Chronic conditions (check all that apply)",
                CONDITION_OPTIONS,
                key="pfma_conditions",
                default=s.get("pfma_conditions", []),
            )
            st.multiselect(
                "Activities that need support (ADLs/IADLs)",
                [
                    "Bathing","Dressing","Toileting","Transferring / mobility","Eating / meals",
                    "Medication management","Transportation","Housekeeping / laundry",
                    "Finances / bills","Companionship / safety checks",
                ],
                key="pfma_adls",
            )
        with col2:
            st.multiselect(
                "Special supervision needed",
                ["Wandering risk","Exit seeking","Elopement risk","Nighttime supervision","Behavioral support","None"],
                key="pfma_supervision",
            )
            st.selectbox(
                "Why are you seeking care now?",
                ["Care needs increased","Caregiver burnout","Recent fall / hospitalization","Memory decline","Planning ahead","Finances / affordability","Other"],
                key="pfma_why",
            )

    with st.expander("Care preferences"):
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

    with st.expander("Home & logistics"):
        st.selectbox(
            "Current living situation",
            ["Own home","Rented home/apartment","With family","Independent Living","Assisted Living","Other"],
            key="pfma_living_situation",
        )
        st.multiselect(
            "Mobility aids used",
            ["Cane","Walker","Wheelchair","Scooter","None","Other"],
            key="pfma_mobility_aids",
        )
        st.selectbox(
            "Preferred search radius",
            ["Within 5 miles","Within 10 miles","Within 25 miles","Flexible"],
            key="pfma_radius",
        )
        st.checkbox("Has pets to consider", key="pfma_pets", value=False)

    with st.expander("Benefits & coverage"):
        st.checkbox("Long-term care insurance", key="pfma_ltc", value=s.get("pfma_ltc", False))
        st.checkbox("VA benefit (or potential eligibility)", key="pfma_va", value=s.get("pfma_va", False))
        st.checkbox("Medicaid or waiver interest", key="pfma_medicaid", value=s.get("pfma_medicaid", False))
        st.text_input("Other coverage or notes (optional)", key="pfma_coverage_notes")

    st.divider()
    if st.button("Save optional details", key="pfma_optional_save"):
        s.pfma_optional = {
            "conditions": s.get("pfma_conditions", []),
            "adls": s.get("pfma_adls", []),
            "supervision": s.get("pfma_supervision", []),
            "why_now": s.get("pfma_why"),
            "settings": s.get("pfma_settings", []),
            "open_multi": s.get("pfma_open_multi", True),
            "visited": s.get("pfma_visited", []),
            "living_situation": s.get("pfma_living_situation"),
            "mobility_aids": s.get("pfma_mobility_aids", []),
            "search_radius": s.get("pfma_radius"),
            "has_pets": s.get("pfma_pets", False),
            "has_ltc": s.get("pfma_ltc", False),
            "has_va": s.get("pfma_va", False),
            "medicaid_interest": s.get("pfma_medicaid", False),
            "coverage_notes": s.get("pfma_coverage_notes", "").strip(),
        }
        st.success("Optional details saved.")

if __name__ == "__main__":
    main()
