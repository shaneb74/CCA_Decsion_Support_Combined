# app.py — Senior Navigator (Planner → Recommendations → Costs → Household → Breakdown → PFMA)
from __future__ import annotations

# --- PFMA Tools (minimal & safe) ---
EXPORT_ENABLED = True if 'EXPORT_ENABLED' not in globals() else EXPORT_ENABLED
AI_HANDOFF_ENABLED = True if 'AI_HANDOFF_ENABLED' not in globals() else AI_HANDOFF_ENABLED

def _safe_money(n):
    try: return f"${int(n):,}"
    except Exception:
        try: return f"${float(n):,.0f}"
        except Exception: return str(n)

def _payload_from_state():
    # Prefer compute_totals if present
    if 'compute_totals' in globals():
        t = compute_totals(st.session_state)
        inc = {
            "individual_A": t.get("inc_A",0),
            "individual_B": t.get("inc_B",0),
            "household": t.get("inc_house",0),
            "va_A": t.get("va_A",0),
            "va_B": t.get("va_B",0),
            "reverse_mortgage_monthly": t.get("rm_monthly",0),
            "total": t.get("income_total",0),
        }
        cst = {
            "care": t.get("care_total",0),
            "home": t.get("home_monthly",0),
            "mods_monthly": t.get("mods_monthly",0),
            "other": t.get("other_monthly",0),
            "total": t.get("monthly_costs_total",0),
        }
        ast = {
            "common": t.get("assets_common",0),
            "less_common": t.get("assets_detail",0),
            "home_sale_proceeds_applied": t.get("sale_proceeds",0),
            "reverse_mortgage_lump_applied": t.get("rm_lump",0),
            "rm_fees_out_of_pocket": t.get("rm_fees_oop",0),
            "mods_upfront_deducted": t.get("mods_upfront",0) if t.get("mods_deduct",False) else 0,
            "total_effective": t.get("assets_total_effective",0),
        }
        pic = {
            "gap": t.get("gap",0),
            "runway_years": t.get("years",0),
            "runway_months_remainder": t.get("rem",0),
            "runway_months": t.get("months_runway",0),
        }
    else:
        s = st.session_state
        _int = lambda k: int(str(s.get(k,0)).replace(",","").replace("$","") or 0) if str(s.get(k,0)) != "" else 0
        inc = {"individual_A":_int("a_ss")+_int("a_pn")+_int("a_other"),
               "individual_B":_int("b_ss")+_int("b_pn")+_int("b_other"),
               "household":_int("hh_rent")+_int("hh_annuity")+_int("hh_invest")+_int("hh_trust")+_int("hh_other"),
               "va_A":_int("a_va_monthly"),
               "va_B":_int("b_va_monthly"),
               "reverse_mortgage_monthly":_int("rm_monthly_income"),}
        inc["total"] = sum(inc.values())
        cst = {"care":_int("care_monthly_total"),
               "home":_int("home_monthly_total"),
               "mods_monthly":_int("mods_monthly_total"),
               "other":_int("other_monthly_total")}
        cst["total"] = sum(cst.values())
        ast = {"common":_int("assets_common_total"),
               "less_common":_int("assets_detailed_total"),
               "home_sale_proceeds_applied":_int("home_sale_net_proceeds"),
               "reverse_mortgage_lump_applied":_int("rm_lump_applied"),
               "rm_fees_out_of_pocket":_int("rm_fees_oop_total"),
               "mods_upfront_deducted":_int("mods_upfront_total") if bool(s.get("mods_deduct_assets", False)) else 0}
        ast["total_effective"] = ast["common"]+ast["less_common"]+ast["home_sale_proceeds_applied"]+ast["reverse_mortgage_lump_applied"]-ast["rm_fees_out_of_pocket"]-ast["mods_upfront_deducted"]
        pic_gap = cst["total"] - inc["total"]
        pic = {"gap": pic_gap,
               "runway_months": (ast["total_effective"] // pic_gap) if (pic_gap>0 and ast["total_effective"]>0) else 0,
               "runway_years":0,"runway_months_remainder":0}
        if pic["runway_months"]>0:
            pic["runway_years"] = pic["runway_months"]//12
            pic["runway_months_remainder"] = pic["runway_months"]%12
    meta = {"home_decision": st.session_state.get("home_decision",""),
            "rm_plan": st.session_state.get("rm_plan","")}
    return inc, cst, ast, pic, meta

def _render_pfma_tools_block():
    try:
        if not (EXPORT_ENABLED or AI_HANDOFF_ENABLED):
            return
        inc, cst, ast, pic, meta = _payload_from_state()
        colA, colB = st.columns(2)
        with colA:
            st.subheader("Exports")
            # CSV
            buf = StringIO()
            w = csv.writer(buf)
            w.writerow(["Section","Item","Amount"])
            for k,v in inc.items(): w.writerow(["Income",k,v])
            for k,v in cst.items(): w.writerow(["Costs",k,v])
            for k,v in ast.items(): w.writerow(["Assets",k,v])
            w.writerow(["Picture","gap", pic["gap"]])
            w.writerow(["Picture","runway_months", pic["runway_months"]])
            st.download_button("Export CSV", data=buf.getvalue().encode("utf-8"), file_name="senior_navigator_export.csv", mime="text/csv", key="pfma_csv")
            st.caption("CSV for spreadsheets.")
            # HTML
            def row(k,v): return f"<tr><td>{k}</td><td>{_safe_money(v)}</td></tr>"
            html = ['<html><head><meta charset="utf-8"><title>Senior Navigator Export</title>',
                    '<style>body{font-family:Arial, sans-serif;margin:24px} table{border-collapse:collapse;margin-bottom:18px} th,td{border:1px solid #ddd;padding:8px} th{background:#f7f7f7}</style></head><body>']
            html.append('<h2>Financial Breakdown</h2>')
            html.append('<h3>Monthly Income</h3><table><tr><th>Source</th><th>Monthly</th></tr>')
            html += [row("Individual A", inc["individual_A"]), row("Individual B", inc["individual_B"]), row("Household", inc["household"]), row("VA — A", inc["va_A"]), row("VA — B", inc["va_B"]), row("Reverse mortgage (monthly)", inc["reverse_mortgage_monthly"]), f"<tr><th>Total</th><th>{_safe_money(inc['total'])}</th></tr>", "</table>"]
            html.append('<h3>Monthly Costs</h3><table><tr><th>Category</th><th>Monthly</th></tr>')
            html += [row("Care", cst["care"]), row("Home", cst["home"]), row("Home modifications", cst["mods_monthly"]), row("Other", cst["other"]), f"<tr><th>Total</th><th>{_safe_money(cst['total'])}</th></tr>", "</table>"]
            html.append('<h3>Assets</h3><table><tr><th>Assets</th><th>Amount</th></tr>')
            html += [row("Common", ast["common"]), row("Less common", ast["less_common"]), row("Home sale net proceeds (applied)", ast["home_sale_proceeds_applied"]), row("Reverse mortgage lump (applied)", ast["reverse_mortgage_lump_applied"]), f"<tr><td>RM fees out-of-pocket (deducted)</td><td>- {_safe_money(ast['rm_fees_out_of_pocket'])}</td></tr>", f"<tr><th>Assets Total (effective)</th><th>{_safe_money(ast['total_effective'])}</th></tr>", "</table>"]
            html.append("</body></html>")
            st.download_button("Export Print View (HTML)", data=("\n".join(html)).encode("utf-8"), file_name="senior_navigator_export.html", mime="text/html", key="pfma_html")
            st.caption("Print-friendly; use your browser to save as PDF.")
        with colB:
            st.subheader("AI Agent handoff")
            preset = st.selectbox("Prompt preset", ["Close the funding gap","Compare housing options","Maximize benefits","Explain my numbers","Tune in-home care hours"], key="pfma_preset")
            preview = {"goal": preset, "context": {"income_total": inc["total"], "costs_total": cst["total"], "gap": pic["gap"], "assets_total_effective": ast["total_effective"], "home_decision": meta.get("home_decision",""), "rm_plan": meta.get("rm_plan","")}, "request": "Suggest 3 concrete options with pros/cons and a first step."}
            st.text_area("Prompt that would be sent", value=json.dumps(preview, indent=2), height=180, key="pfma_prompt")
            if st.button("Send to AI Agent (mock)", key="pfma_send"):
                opener = f"I see total monthly income {_safe_money(inc['total'])} and costs {_safe_money(cst['total'])}. "
                if pic["gap"] <= 0:
                    opener += f"You have a monthly surplus of {_safe_money(-pic['gap'])}. We can explore quality upgrades, reserves, or pacing asset use."
                else:
                    # Compute simple runway text
                    yrs = pic.get("runway_years",0)
                    rem = pic.get("runway_months_remainder",0)
                    if yrs or rem:
                        opener += f"You have a monthly gap of {_safe_money(pic['gap'])}. Effective assets {_safe_money(ast['total_effective'])} cover about {yrs}y {rem}m at current burn."
                    else:
                        opener += f"You have a monthly gap of {_safe_money(pic['gap'])}."
                st.success("Mock handoff created.")
                st.write("**Agent:** " + opener)
    except Exception as e:
        st.warning(f"Tools section unavailable: {e}")


import json
import csv
from io import StringIO


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

st.set_page_config(page_title="Senior Navigator • Planner + Cost", page_icon="🧭", layout="wide")

# CSS for confirm buttons and gamification animations
st.markdown("""
    <style>
    .stButton > button[kind="primary"] {
        background-color: #4CAF50;
        color: white;
        border-radius: 5px;
        padding: 10px 20px;
        font-weight: bold;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #45a049;
    }
    .stAlert {
        animation: fadeIn 0.5s;
    }
    .badge {
        animation: fadeIn 0.5s;
    }
    @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
    }
    </style>
""", unsafe_allow_html=True)

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
def _merge_conditions_from_cost_planner() -> dict[str, list[str]]:
    """Gather conditions per person from canon and saved keys. Sanitize to valid options."""
    valid = set(CONDITION_OPTIONS)
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
    conditions = st.session_state.get("pfma_conditions", {}).get(pid, _merge_conditions_from_cost_planner().get(pid, []))
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

# ---------------- PFMA render ----------------
def render_pfma():
    st.header("Plan for My Advisor")
    _render_pfma_tools_block()
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
        s.pfma_conditions = _merge_conditions_from_cost_planner()
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
            st.session_state.pfma_confirmed_sections = s.pfma_confirmed_sections  # Force state update
            st.success("You just earned the Care Plan Confirmer badge! Keep going!")
            st.rerun()  # Explicit rerun to ensure UI updates
    with st.expander("Confirm Cost Planner", expanded=s.get("expander_pfma_conditions", False)):
        st.write("Based on your Cost Planner, we’ve pre-filled your health and mobility details. If you haven’t completed it yet, please add these details to ensure we have the right information. Review and confirm or edit to make sure it’s right.")
        for p in people:
            pid, name = p["id"], p["display_name"]
            default_conditions = s.get("pfma_conditions", {}).get(pid, _merge_conditions_from_cost_planner().get(pid, []))
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
            st.session_state.pfma_confirmed_sections = s.pfma_confirmed_sections  # Force state update
            st.success("You just earned the Cost Planner Confirmer badge! Keep going!")
            st.rerun()  # Explicit rerun to ensure UI updates
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
            st.session_state.pfma_confirmed_sections = s.pfma_confirmed_sections  # Force state update
            st.success("You just earned the Care Needs Expert badge! Keep going!")
            st.rerun()  # Explicit rerun to ensure UI updates
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
            st.session_state.pfma_confirmed_sections = s.pfma_confirmed_sections  # Force state update
            st.success("You just earned the Preferences Pro badge! Keep going!")
            st.rerun()  # Explicit rerun to ensure UI updates
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
            st.session_state.pfma_confirmed_sections = s.pfma_confirmed_sections  # Force state update
            st.success("You just earned the Household Hero badge! Keep going!")
            st.rerun()  # Explicit rerun to ensure UI updates
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
            st.session_state.pfma_confirmed_sections = s.pfma_confirmed_sections  # Force state update
            st.success("You just earned the Benefits Boss badge! Keep going!")
            st.rerun()  # Explicit rerun to ensure UI updates
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
                st.session_state.pfma_confirmed_sections = s.pfma_confirmed_sections  # Force state update
                st.success("You just earned the Personal Info Star badge! Keep going!")
                st.rerun()  # Explicit rerun to ensure UI updates
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
3. Add income, benefits, assets, and home decisions.
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
    st.header("Household & Budget")
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
            cond = s.get(f"ih_conditions_saved_{pid}", s.get("ih_conditions"))
            cond_str = ", ".join(cond) if isinstance(cond, list) else (cond or "—")
            detail = f"{hrs} hrs/day × {days} days/mo, Caregiver: {ctype}, Conditions: {cond_str}"
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
