
# tools.py — Standalone "Tools & AI Agent" view for Senior Navigator
from __future__ import annotations
import json, csv
from io import StringIO
import streamlit as st

# ---------------- Shared helpers ----------------
def _to_int(v, default=0):
    try:
        if v is None or v == "":
            return default
        if isinstance(v, (int, float)):
            return int(v)
        s = str(v).replace("$","").replace(",","").strip()
        if s == "":
            return default
        return int(float(s))
    except Exception:
        return default

def _g(s, *names, default=0):
    for n in names:
        if n in s and s.get(n) not in (None, ""):
            return s.get(n)
    return default

def _m(n):
    try:
        return f"${int(n):,}"
    except Exception:
        try:
            return f"${float(n):,.0f}"
        except Exception:
            return str(n)

# ---------------- Internal totals (read session state only) ----------------
def _compute_totals():
    s = st.session_state
    # Income (synonyms)
    inc_A = _to_int(_g(s,"inc_A")) or (_to_int(_g(s,"a_ss","ind_a_ss")) + _to_int(_g(s,"a_pn","ind_a_pn")) + _to_int(_g(s,"a_other","ind_a_other")))
    inc_B = _to_int(_g(s,"inc_B")) or (_to_int(_g(s,"b_ss","ind_b_ss")) + _to_int(_g(s,"b_pn","ind_b_pn")) + _to_int(_g(s,"b_other","ind_b_other")))
    inc_house = _to_int(_g(s,"inc_house")) or (_to_int(_g(s,"hh_rent","rent_income")) + _to_int(_g(s,"hh_annuity")) + _to_int(_g(s,"hh_invest","hh_investments")) + _to_int(_g(s,"hh_trust")) + _to_int(_g(s,"hh_other")))
    va_A = _to_int(_g(s,"va_A","a_va_monthly"))
    va_B = _to_int(_g(s,"va_B","b_va_monthly"))
    rm_monthly = _to_int(_g(s,"rm_monthly","rm_monthly_income"))
    income_total = inc_A + inc_B + inc_house + va_A + va_B + rm_monthly
    # Costs (synonyms)
    care_total = _to_int(_g(s,"care_total","care_monthly_total"))
    home_monthly = _to_int(_g(s,"home_monthly","home_monthly_total"))
    mods_monthly = _to_int(_g(s,"mods_monthly","mods_monthly_total"))
    other_monthly = _to_int(_g(s,"other_monthly","other_monthly_total"))
    monthly_costs_total = care_total + home_monthly + mods_monthly + other_monthly
    # Assets (synonyms)
    assets_common = _to_int(_g(s,"assets_common","assets_common_total"))
    assets_detail = _to_int(_g(s,"assets_detail","assets_detailed_total","assets_less_common_total"))
    apply_sale = bool(_g(s,"apply_sale_to_assets","apply_home_proceeds","apply_net_proceeds","apply_home_sale_to_assets","apply_sale_net_to_assets","apply_home_sale"))
    sale_proceeds = _to_int(_g(s,"sale_proceeds","home_sale_net_proceeds","sale_net")) if apply_sale else 0
    rm_lump = _to_int(_g(s,"rm_lump","rm_lump_applied"))
    rm_fees_oop = _to_int(_g(s,"rm_fees_oop","rm_fees_oop_total"))
    mods_upfront = _to_int(_g(s,"mods_upfront","mods_upfront_total"))
    mods_deduct = bool(_g(s,"mods_deduct","mods_deduct_assets"))
    assets_total_effective = assets_common + assets_detail + sale_proceeds + rm_lump - rm_fees_oop - (mods_upfront if mods_deduct else 0)
    gap = monthly_costs_total - income_total
    months_runway = int(assets_total_effective // gap) if (gap > 0 and assets_total_effective > 0) else 0
    years = months_runway // 12
    rem = months_runway % 12

    return {
        "inc_A": inc_A, "inc_B": inc_B, "inc_house": inc_house, "va_A": va_A, "va_B": va_B,
        "rm_monthly": rm_monthly, "income_total": income_total,
        "care_total": care_total, "home_monthly": home_monthly, "mods_monthly": mods_monthly,
        "other_monthly": other_monthly, "monthly_costs_total": monthly_costs_total,
        "assets_common": assets_common, "assets_detail": assets_detail, "sale_proceeds": sale_proceeds,
        "rm_lump": rm_lump, "rm_fees_oop": rm_fees_oop, "assets_total_effective": assets_total_effective,
        "gap": gap, "years": years, "rem": rem
    }

# ---------------- Public: render the Tools page ----------------
def render_tools():
    """Standalone Tools & AI Agent view.
    Safe to call from any step. Read-only; nothing leaves your browser.
    """
    st.header("Tools & AI Agent")
    st.caption("Exports and a mock handoff to your AI agent. Read-only; nothing leaves your browser.")

    totals = _compute_totals()
    inc_A = totals["inc_A"]; inc_B = totals["inc_B"]; inc_house = totals["inc_house"]
    va_A = totals["va_A"]; va_B = totals["va_B"]; rm_monthly = totals["rm_monthly"]
    income_total = totals["income_total"]
    care_total = totals["care_total"]; home_monthly = totals["home_monthly"]
    mods_monthly = totals["mods_monthly"]; other_monthly = totals["other_monthly"]
    monthly_costs_total = totals["monthly_costs_total"]
    assets_common = totals["assets_common"]; assets_detail = totals["assets_detail"]
    sale_proceeds = totals["sale_proceeds"]; rm_lump = totals["rm_lump"]
    rm_fees_oop = totals["rm_fees_oop"]; assets_total_effective = totals["assets_total_effective"]
    gap = totals["gap"]; years = totals["years"]; rem = totals["rem"]

    colA, colB = st.columns(2)

    # --------- Exports ---------
    with colA:
        st.subheader("Exports")
        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Section","Item","Amount"])
        for k,v in {"individual_A":inc_A,"individual_B":inc_B,"household":inc_house,"va_A":va_A,"va_B":va_B,"reverse_mortgage_monthly":rm_monthly,"total":income_total}.items():
            writer.writerow(["Income",k,v])
        for k,v in {"care":care_total,"home":home_monthly,"mods_monthly":mods_monthly,"other":other_monthly,"total":monthly_costs_total}.items():
            writer.writerow(["Costs",k,v])
        for k,v in {"common":assets_common,"less_common":assets_detail,"home_sale_proceeds_applied":sale_proceeds,"reverse_mortgage_lump_applied":rm_lump,"rm_fees_out_of_pocket":rm_fees_oop,"total_effective":assets_total_effective}.items():
            writer.writerow(["Assets",k,v])
        writer.writerow(["Picture","gap",gap]); writer.writerow(["Picture","runway_months", (years*12 + rem)])
        st.download_button("Export CSV", buf.getvalue().encode("utf-8"), "senior_navigator_export.csv", "text/csv", key="tools_csv")

        # HTML/print export
        def _row(lbl, val): return f"<tr><td>{lbl}</td><td>{_m(val)}</td></tr>"
        html_parts = [
            '<html><head><meta charset="utf-8"><title>Senior Navigator Export</title>',
            '<style>body{font-family:Arial,sans-serif;margin:24px} table{border-collapse:collapse;margin-bottom:18px} th,td{border:1px solid #ddd;padding:8px} th{background:#f7f7f7}</style></head><body>',
            '<h2>Financial Breakdown</h2>',
            '<h3>Monthly Income</h3><table><tr><th>Source</th><th>Monthly</th></tr>',
            _row("Individual A", inc_A), _row("Individual B", inc_B), _row("Household", inc_house),
            _row("VA — A", va_A), _row("VA — B", va_B), _row("Reverse mortgage (monthly)", rm_monthly),
            f"<tr><th>Total</th><th>{_m(income_total)}</th></tr>", "</table>",
            '<h3>Monthly Costs</h3><table><tr><th>Category</th><th>Monthly</th></tr>',
            _row("Care", care_total), _row("Home", home_monthly), _row("Home modifications", mods_monthly),
            _row("Other", other_monthly), f"<tr><th>Total</th><th>{_m(monthly_costs_total)}</th></tr>", "</table>",
            '<h3>Assets</h3><table><tr><th>Assets</th><th>Amount</th></tr>',
            _row("Common", assets_common), _row("Less common", assets_detail), _row("Home sale net proceeds (applied)", sale_proceeds),
            _row("Reverse mortgage lump (applied)", rm_lump),
            f"<tr><td>RM fees out-of-pocket (deducted)</td><td>- {_m(rm_fees_oop)}</td></tr>",
            f"<tr><th>Assets Total (effective)</th><th>{_m(assets_total_effective)}</th></tr>", "</table>"
        ]
        if gap > 0:
            ym = f"{years} years {rem} months" if years else f"{rem} months"
            html_parts.append(f"<p><b>Monthly gap:</b> {_m(gap)}. <b>Estimated runway:</b> {ym}.</p>")
        else:
            html_parts.append(f"<p><b>Monthly surplus:</b> {_m(-gap)}.</p>")
        html_parts.append("</body></html>")
        html_blob = "\n".join(html_parts)
        st.download_button("Export Print View (HTML)", html_blob.encode("utf-8"), "senior_navigator_export.html", "text/html", key="tools_html")

    # --------- AI Agent (mock) ---------
    with colB:
        st.subheader("AI Agent Handoff (Mock)")
        preset = st.selectbox("Prompt preset", ["Close the funding gap","Compare housing options","Maximize benefits","Explain my numbers","Tune in-home care hours"], key="tools_preset")
        preview = {
            "goal": preset,
            "context": {
                "income_total": income_total,
                "costs_total": monthly_costs_total,
                "gap": gap,
                "assets_total_effective": assets_total_effective,
                "home_decision": st.session_state.get("home_decision",""),
                "rm_plan": st.session_state.get("rm_plan",""),
            },
            "request": "Suggest 3 concrete options with pros/cons and a first step."
        }
        st.text_area("Prompt that would be sent", value=json.dumps(preview, indent=2), height=220, key="tools_prompt")
        if st.button("Send to AI Agent (mock)", key="tools_send"):
            opener = f"I see total monthly income {_m(income_total)} and costs {_m(monthly_costs_total)}. "
            if gap <= 0:
                opener += f"You have a monthly surplus of {_m(-gap)}."
            else:
                if years or rem:
                    opener += f"You have a monthly gap of {_m(gap)}. Effective assets {_m(assets_total_effective)} cover about {years}y {rem}m at current spend."
                else:
                    opener += f"You have a monthly gap of {_m(gap)}."
            st.success("Mock handoff created.")
            st.write("**Agent:** " + opener)

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back to app", key="tools_back"):
            st.session_state.step = st.session_state.get("return_step", "intro")
            st.rerun()
    with c2:
        st.caption("Nothing is transmitted; this is a prototype-only view.")
