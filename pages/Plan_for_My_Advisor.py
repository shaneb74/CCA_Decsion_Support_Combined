# pages/Plan_for_My_Advisor.py — collision-safe, no own back button
import streamlit as st

def render_pfma():
    st.title("Plan for My Advisor")
    st.caption("Schedule a time with an advisor. We'll only ask what we need right now.")

    # Context pulled from session if present (safe defaults)
    gc = st.session_state.get("gc_summary", {})
    calc = st.session_state.get("calculator_snapshot")

    with st.expander("Your current plan summary", expanded=True):
        if gc:
            st.subheader("Recommendation")
            st.markdown(f"**Suggested path:** {gc.get('care_path','—')}")
            flags = gc.get("flags") or []
            if flags:
                cols = st.columns(min(4, max(1, len(flags))))
                for i, f in enumerate(flags):
                    with cols[i % len(cols)]:
                        st.markdown(
                            f"<div style='display:inline-block;padding:6px 10px;border-radius:999px;"
                            "border:1px solid #e5e7eb;font-size:0.85rem;background:#fafafa;'>"
                            f"🛈 {str(f).replace('_',' ').title()}</div>",
                            unsafe_allow_html=True
                        )
        else:
            st.info("No Guided Care Plan found. You can still book now.")

        if calc:
            st.subheader("Budget snapshot")
            c1, c2, c3 = st.columns(3)
            try:
                c1.metric("Est. Monthly Cost", f"${float(calc.get('monthly_cost', 0)):,.0f}")
            except Exception:
                c1.metric("Est. Monthly Cost", calc.get('monthly_cost', '—'))
            try:
                c2.metric("Monthly Gap", f"${float(calc.get('monthly_gap', 0)):,.0f}")
            except Exception:
                c2.metric("Monthly Gap", calc.get('monthly_gap', '—'))
            yf = calc.get("years_funded")
            c3.metric("Years Funded", f"{float(yf):.1f}" if isinstance(yf,(int,float)) else "—")
        else:
            st.info("No Cost Planner data yet. You can add numbers later or try the calculator after booking.")

    st.divider()

    # ---------------- Booking (minimal) ----------------
    with st.form("pfma_booking"):
        st.subheader("Booking details")

        name = st.text_input("Your name", value=st.session_state.get("user_name",""), key="pfma_name")
        relationship = st.selectbox(
            "Your relationship to the care recipient",
            ["Self","Spouse/Partner","Adult Child","POA/Representative","Other"],
            index=0, key="pfma_relationship"
        )
        phone = st.text_input("Best phone number", value=st.session_state.get("user_phone",""), placeholder="+1 (___) ___-____", key="pfma_phone")
        email = st.text_input("Email (optional)", value=st.session_state.get("user_email",""), key="pfma_email")
        zipcode = st.text_input("ZIP code for care search", value=(gc.get("zip","") if isinstance(gc, dict) else ""), key="pfma_zip")
        urgency = st.select_slider("When do you need support?",
            options=["Exploring (3+ months)","Planning (1–3 months)","Soon (2–4 weeks)","ASAP (0–7 days)"],
            value="Planning (1–3 months)", key="pfma_urgency")
        constraints = st.text_area("Any must-haves or constraints? (optional)",
            placeholder="Pets allowed, near daughter in Seattle, budget cap, wheelchair accessible...", key="pfma_constraints")

        if calc and calc.get("payer_hint"):
            payer_hint = st.selectbox("Primary payer (you can adjust)",
                ["Private Pay","LTC Insurance","VA Aid & Attendance","Medicaid"],
                index=["Private Pay","LTC Insurance","VA Aid & Attendance","Medicaid"].index(calc["payer_hint"]), key="pfma_payer_hint_known")
        else:
            payer_hint = st.selectbox("Primary payer (optional)",
                ["Prefer not to say","Private Pay","LTC Insurance","VA Aid & Attendance","Medicaid"],
                index=0, key="pfma_payer_hint_optional")

        slot = st.text_input("Appointment time", placeholder="Select from scheduler widget", key="pfma_slot")
        consent = st.checkbox("I agree to be contacted by an advisor", value=False, key="pfma_consent")

        submitted = st.form_submit_button("Schedule appointment", type="primary", use_container_width=True)
        if submitted:
            if not name or not phone or not zipcode or not slot or not consent:
                st.error("Please complete the required fields (name, phone, ZIP, appointment time, consent).")
            else:
                st.success("Appointment scheduled! You're on the calendar.")
                st.session_state["pfma_step"] = "optional"
                st.session_state["pfma_booking"] = {
                    "name": name, "relationship": relationship, "phone": phone, "email": email,
                    "zipcode": zipcode, "urgency": urgency, "constraints": constraints,
                    "payer_hint": payer_hint, "slot": slot, "consent": consent
                }

    # ---------------- Optional enrichment ----------------
    if st.session_state.get("pfma_step") == "optional":
        st.success("Share a bit more so we can prepare. Totally optional.")

        with st.expander("Financial snapshot (optional)"):
            if calc:
                st.caption("We already have your Cost Planner details. Advisors will review them with you.")
                st.json({
                    "payer_hint": calc.get("payer_hint"),
                    "income_keys": list((calc.get("income") or {}).keys()),
                    "has_assets": bool(calc.get("assets")),
                })
            else:
                budget = st.select_slider("Do you know your realistic monthly care budget?",
                    options=["<$3,000","$3,000–$5,000","$5,000–$8,000",">$8,000"],
                    value="$3,000–$5,000", key="pfma_budget_band")
                income_sources = st.text_area("Main sources of monthly income (SS, pensions, annuities)",
                    placeholder="Social Security ~$2,100; Pension ~$600", key="pfma_income_sources")
                benefits = st.multiselect("Benefits that may help with costs",
                    ["VA Aid & Attendance","LTC Insurance","Medicaid"], key="pfma_benefits")
                assets = st.text_area("Any assets or savings that may help cover costs",
                    placeholder="Savings ~$25k; Home equity ~—", key="pfma_assets")
                st.caption("Prefer a full breakdown? Try the Cost Planner for detailed numbers and an affordability timeline.")
                st.session_state["pfma_optional_finance"] = {
                    "budget_band": budget, "income_sources": income_sources,
                    "benefits": benefits, "assets": assets
                }

        with st.expander("Health & care (optional)"):
            st.text_area("Tell us about any health conditions or diagnoses we should know about.",
                placeholder="e.g., Parkinson's, diabetes, memory changes...", key="pfma_health_conditions")
            st.text_area("Are there daily activities where support would help?",
                placeholder="Bathing, dressing, meals, medication, mobility, continence...", key="pfma_adls")
            st.text_input("Any mobility equipment or oxygen use?",
                placeholder="Walker, wheelchair, cane, oxygen (L/min)", key="pfma_mobility")
            st.text_input("Any dietary needs or restrictions?",
                placeholder="Diabetic, low sodium, vegetarian, other", key="pfma_diet")

        with st.expander("Lifestyle & environment (optional)"):
            st.text_area("What activities or hobbies are important to keep in your life?",
                placeholder="Gardening, church, bingo, walking group...", key="pfma_activities")
            st.text_input("Comfort with pets or children around?",
                placeholder="Loves small dogs; enjoys kids around in common areas", key="pfma_pets_kids")
            st.text_input("Preferred location(s)",
                placeholder="ZIPs or neighborhoods, proximity to family", key="pfma_location_pref")

        with st.expander("Current living situation (optional)"):
            st.selectbox("Where are you living right now?",
                ["Home","Hospital","Rehab","Skilled Nursing Facility","Other"], key="pfma_living_now")
            st.text_input("Any upcoming discharge or transition dates?",
                placeholder="e.g., Hospital discharge 2025-10-05", key="pfma_discharge")

        if st.button("Save optional details", key="pfma_save_optional"):
            st.success("Details saved. Your advisor will review them before your call.")
            st.balloons()
