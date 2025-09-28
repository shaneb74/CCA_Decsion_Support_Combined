# asset_engine.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional
import streamlit as st

# Canonical mapping for home decisions
HOME_DECISION_MAP = {
    "Keep": "KEEP",
    "Sell": "SELL",
    "HELOC": "HELOC",
    "Reverse mortgage": "RM",
}

def _fmt(x: int | float) -> str:
    try:
        return f"${int(x):,}"
    except Exception:
        return "$0"

def _money(label, key, default=0, *, step=50, min_value=0, help_text=None) -> int:
    """Safe numeric input that does not mutate session state in code."""
    try:
        v0 = int(st.session_state.get(key, default) or default)
    except Exception:
        v0 = default
    v = st.number_input(label, min_value=min_value, step=step, value=v0, key=key, help=help_text)
    try:
        return int(v)
    except Exception:
        return 0

@dataclass
class HouseholdResult:
    # Income
    indiv_income_A: int
    indiv_income_B: int
    household_income: int
    # Benefits
    va_A: int
    va_B: int
    ltc_add_A: int
    ltc_add_B: int
    benefits_total: int
    # Home costs and proceeds
    home_monthly_total: int
    home_sale_net_proceeds: int
    # Mods
    mods_monthly_total: int
    mods_upfront_total: int
    mods_deduct_assets: bool
    # Other monthly
    other_monthly_total: int
    # Assets
    assets_common_total: int
    assets_detailed_total: int
    # Final assets rollup (applies proceeds and deducts mods upfront if selected)
    assets_total_effective: int

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

class IncomeAssetsEngine:
    """Renders the full Household & Budget UI and returns a HouseholdResult."""
    def __init__(self, calculator=None):
        self.calculator = calculator

    # ---------- sections ----------
    def _section_income_individual(self, nameA: str, nameB: str | None):
        with st.expander("Monthly Income — Individual", expanded=True):
            if nameB:
                a_ss, a_pn, a_oth = st.columns(3)
                with a_ss: a1 = _money(f"Social Security — {nameA}", "a_ss", 0)
                with a_pn: a2 = _money(f"Pension — {nameA}", "a_pn", 0)
                with a_oth: a3 = _money(f"Other — {nameA}", "a_other", 0)
                b_ss, b_pn, b_oth = st.columns(3)
                with b_ss: b1 = _money(f"Social Security — {nameB}", "b_ss", 0)
                with b_pn: b2 = _money(f"Pension — {nameB}", "b_pn", 0)
                with b_oth: b3 = _money(f"Other — {nameB}", "b_other", 0)
            else:
                a1 = _money(f"Social Security — {nameA}", "a_ss", 0)
                a2 = _money(f"Pension — {nameA}", "a_pn", 0)
                a3 = _money(f"Other — {nameA}", "a_other", 0)
                b1 = b2 = b3 = 0
            indiv_A = a1 + a2 + a3
            indiv_B = b1 + b2 + b3
            st.metric("Subtotal — Individual income", _fmt(indiv_A + indiv_B))
        return indiv_A, indiv_B

    def _section_income_household(self):
        with st.expander("Monthly Income — Household (shared)", expanded=False):
            r   = _money("Rental income", "hh_rent", 0)
            an  = _money("Annuity income", "hh_annuity", 0)
            inv = _money("Dividends/interest (joint)", "hh_invest", 0)
            tr  = _money("Trust distributions", "hh_trust", 0)
            oth = _money("Other household income", "hh_other", 0)
            subtotal = r + an + inv + tr + oth
            st.metric("Subtotal — Household income", _fmt(subtotal))
        return subtotal

    def _section_benefits(self, names: List[str]):
        """
        Restored rich VA/A&A & LTC block:
        - VA wizard or direct entry; stores a_va_monthly / b_va_monthly
        - LTC Yes/No per person; stores has_ltc_insurance (True if either Yes)
        - Uses calculator.settings['ltc_monthly_add'] as the LTC monthly add (default 1800)
        """
        with st.expander("Benefits (VA, Long-Term Care insurance)", expanded=True):
            nA = names[0] if names else "Person A"
            nB = names[1] if len(names) > 1 else None

            # Settings seed
            settings = getattr(self.calculator, "settings", {}) if self.calculator else {}
            settings = settings or {}
            if "va_mapr_2025" not in settings:
                settings["va_mapr_2025"] = {
                    "Veteran (no dependents) — A&A": 2358,
                    "Veteran + 1 dependent — A&A": 2795,
                    "Two veterans married, one A&A": 2795,
                    "Surviving spouse — A&A": 1515,
                    "Surviving spouse + 1 child — A&A": 1808,
                }
            if "ltc_monthly_add" not in settings:
                settings["ltc_monthly_add"] = 1800
            if self.calculator:
                self.calculator.settings = settings

            va_mapr = settings["va_mapr_2025"]
            ltc_add_val = int(settings["ltc_monthly_add"])

            def va_block(prefix: str, person_name: str) -> Dict[str, Any]:
                st.write(f"**{person_name}**")
                choice = st.radio(
                    f"Choose an option for {person_name}:",
                    [
                        "Not a veteran / No VA pension",
                        "I already receive or qualify for VA pension/Aid & Attendance",
                        "I served, but I’m not sure if I qualify",
                    ],
                    index=0,
                    key=f"{prefix}_va_path",
                )
                result = {"monthly": 0, "detail": "No VA pension"}

                if choice.startswith("I already receive"):
                    tier = st.selectbox(
                        "Select status",
                        list(va_mapr.keys()),
                        key=f"{prefix}_va_tier",
                        help="Monthly caps from VA MAPR. Enter your actual payment if you know it.",
                    )
                    cap = int(va_mapr[tier])
                    st.caption(f"Estimated monthly cap for this tier: {_fmt(cap)}.")
                    amt = st.number_input(
                        "Monthly VA payment (enter actual if known; otherwise use cap)",
                        min_value=0, step=25,
                        value=int(st.session_state.get(f"{prefix}_va_actual", cap) or cap),
                        key=f"{prefix}_va_actual",
                    )
                    result = {"monthly": int(amt), "detail": tier}

                elif choice.startswith("I served"):
                    st.info("Quick check (not exhaustive):")
                    wartime   = st.checkbox("Served during a wartime period", key=f"{prefix}_wartime")
                    age_dis   = st.checkbox("65+ or permanently and totally disabled", key=f"{prefix}_age_dis")
                    discharge = st.checkbox("Discharge not dishonorable", key=f"{prefix}_discharge")
                    need_aa   = st.checkbox("Needs help with daily activities or housebound", key=f"{prefix}_need_aa")
                    networth  = st.checkbox("Net worth under VA limit", key=f"{prefix}_networth")

                    likely = wartime and age_dis and discharge and networth
                    if likely:
                        st.success("You may qualify for VA pension; Aid & Attendance may apply if daily help/housebound.")
                        result["detail"] = "Wizard: likely eligible"
                    else:
                        st.warning("Based on these answers, VA pension may not apply. You can still check with a local VSO.")
                        result["detail"] = "Wizard: uncertain"

                return result

            # VA blocks
            col1, col2 = st.columns(2)
            with col1:
                a_res = va_block("a", nA)
            if nB:
                with col2:
                    b_res = va_block("b", nB)
            else:
                b_res = {"monthly": 0, "detail": "No VA pension"}

            # LTC flags per person
            lc1, lc2 = st.columns(2)
            with lc1:
                a_ltc_choice = st.selectbox(
                    f"Long-term care insurance — {nA}",
                    ["No", "Yes"],
                    key="a_ltc_choice",
                )
            if nB:
                with lc2:
                    b_ltc_choice = st.selectbox(
                        f"Long-term care insurance — {nB}",
                        ["No", "Yes"],
                        key="b_ltc_choice",
                    )
            else:
                b_ltc_choice = "No"
                st.selectbox("Long-term care insurance — (n/a)", ["No"], key="b_ltc_choice_disabled", disabled=True)

            # Persist VA monthly for PFMA & Breakdown consumers
            a_va = int(a_res.get("monthly", 0))
            b_va = int(b_res.get("monthly", 0)) if nB else 0
            st.session_state["a_va_monthly"] = a_va
            st.session_state["b_va_monthly"] = b_va

            # Persist LTC flags for PFMA
            has_ltc = (a_ltc_choice == "Yes") or (b_ltc_choice == "Yes")
            st.session_state["has_ltc_insurance"] = bool(has_ltc)

            # If you use an LTC add-on in affordability math, compute it (kept for compatibility)
            a_ltc_add = ltc_add_val if a_ltc_choice == "Yes" else 0
            b_ltc_add = ltc_add_val if (nB and b_ltc_choice == "Yes") else 0

            benefits_total = a_va + b_va + a_ltc_add + b_ltc_add
            st.caption("These flags feed the PFMA Benefits & coverage checkboxes.")
            st.metric("Subtotal — Benefits (VA + LTC add-ons)", _fmt(benefits_total))

        return a_va, b_va, a_ltc_add, b_ltc_add, benefits_total

    def _section_home_decision(self):
        with st.expander("Home decision (keep, sell, HELOC, reverse mortgage)", expanded=True):
            decision = st.selectbox("What do you plan to do with the home?",
                                    ["Keep", "Sell", "HELOC", "Reverse mortgage"],
                                    key="home_decision")
            apply_proceeds = st.checkbox("Apply net proceeds to assets summary", value=True, key="apply_proceeds_assets")

            home_monthly = 0
            sale_proceeds = 0

            if decision_code == "KEEP":
                c1, c2, c3 = st.columns(3)
                with c1: mort = _money("Monthly mortgage/HELOC payment", "home_mort", 0)
                with c2: tax  = _money("Monthly property taxes", "home_tax", 0)
                with c3: ins  = _money("Monthly homeowners insurance", "home_ins", 0)
                c4, c5 = st.columns(2)
                with c4: hoa  = _money("Monthly HOA/maintenance", "home_hoa", 0)
                with c5: util = _money("Monthly utilities (avg.)", "home_util", 0)
                home_monthly = mort + tax + ins + hoa + util
                st.metric("Subtotal — Home monthly costs", _fmt(home_monthly))

            elif decision_code == "SELL":
                c1, c2, c3 = st.columns(3)
                with c1: sale = _money("Estimated sale price", "home_sale_price", 0, step=1000)
                with c2: pay  = _money("Principal payoff at sale", "home_payoff", 0, step=1000)
                with c3:
                    fee = st.slider("Typical fees (realtor/closing) — percent", 4.0, 8.0, 6.0, 0.25, key="home_fee_pct")
                    st.caption(f"You chose {fee:.2f}%")
                fees_amt = int(round(sale * (fee / 100.0)))
                sale_proceeds = max(0, sale - pay - fees_amt)
                st.metric("Estimated net proceeds", _fmt(sale_proceeds))
                st.metric("Subtotal — Home monthly costs", _fmt(0))

            elif decision_code == "HELOC":
                c1, c2, c3 = st.columns(3)
                with c1: heloc = _money("Monthly HELOC payment", "home_heloc", 0)
                with c2: tax   = _money("Monthly property taxes", "home_tax", 0)
                with c3: ins   = _money("Monthly homeowners insurance", "home_ins", 0)
                c4, c5 = st.columns(2)
                with c4: hoa   = _money("Monthly HOA/maintenance", "home_hoa", 0)
                with c5: util  = _money("Monthly utilities (avg.)", "home_util", 0)
                home_monthly = heloc + tax + ins + hoa + util
                st.metric("Subtotal — Home monthly costs", _fmt(home_monthly))

            else:  # Reverse mortgage
                c1, c2 = st.columns(2)
                with c1: tax = _money("Monthly property taxes", "home_tax", 0)
                with c2: ins = _money("Monthly homeowners insurance", "home_ins", 0)
                c3, c4 = st.columns(2)
                with c3: hoa  = _money("Monthly HOA/maintenance", "home_hoa", 0)
                with c4: util = _money("Monthly utilities (avg.)", "home_util", 0)
                home_monthly = tax + ins + hoa + util
                st.metric("Subtotal — Home monthly costs", _fmt(home_monthly))

        # Persist for Breakdown consumers
        st.session_state["home_monthly_total"] = int(home_monthly)
        st.session_state["home_sale_net_proceeds"] = int(sale_proceeds if st.session_state.get("apply_proceeds_assets") else 0)
        return int(home_monthly), int(sale_proceeds)

    def _section_mods(self):
        with st.expander("Home modifications (grab bars, ramps, bath, etc.)", expanded=False):
            pay_method = st.radio("Payment method", ["Amortize monthly", "Pay upfront (one-time)"],
                                  index=0, key="mods_pay_method",
                                  help="Choose whether to spread the cost over months or pay upfront.")
            finish = st.selectbox("Finish level", ["Budget", "Standard", "Custom"], index=1,
                                  help="Budget ≈ 0.8×, Standard = 1.0×, Custom ≈ 1.35×")
            mult = {"Budget": 0.8, "Standard": 1.0, "Custom": 1.35}[finish]

            items = [
                ("mods_grab",        "Grab bars & railings (avg $800)",                800),
                ("mods_door",        "Widen doorways (avg $2,500)",                    2500),
                ("mods_shower",      "Bathroom walk-in shower conversion (avg $12,000)", 12000),
                ("mods_ramp",        "Ramp installation (avg $3,500)",                 3500),
                ("mods_stair",       "Stair lift (avg $4,500)",                        4500),
                ("mods_sensors",     "Smart home monitoring/sensors (avg $1,200)",     1200),
                ("mods_lighting",    "Lighting & fall-risk improvements (avg $1,500)", 1500),
            ]

            total_cost = 0
            colL, colR = st.columns(2)
            for idx, (key, label, base) in enumerate(items):
                target = colL if idx % 2 == 0 else colR
                with target:
                    checked = st.checkbox(label, key=f"{key}_chk", value=False)
                    if checked:
                        qty = st.number_input("Qty", min_value=1, step=1, value=1, key=f"{key}_qty")
                        total_cost += int(base * mult * int(qty))

            if pay_method == "Amortize monthly":
                months = st.slider("Amortize over (months)", 6, 60, 12, 1, key="mods_months")
                monthly = int(round(total_cost / max(1, months)))
                st.session_state["mods_monthly_total"] = monthly
                st.session_state["mods_upfront_total"] = 0
                st.session_state["mods_deduct_assets"] = False
                st.metric("Subtotal — Home mods (amortized monthly)", _fmt(monthly))
            else:
                st.session_state["mods_monthly_total"] = 0
                st.session_state["mods_upfront_total"] = total_cost
                deduct = st.checkbox("Deduct upfront cost from assets summary", value=True, key="mods_deduct_assets")
                st.metric("Upfront cost — Home mods", _fmt(total_cost))

        return int(st.session_state.get("mods_monthly_total", 0)), int(st.session_state.get("mods_upfront_total", 0)), bool(st.session_state.get("mods_deduct_assets", False))

    def _section_other_monthlies(self):
        with st.expander("Other monthly costs (meds, insurance, misc.)", expanded=False):
            c1, c2, c3, c4 = st.columns(4)
            with c1: meds   = _money("Medications", "oth_meds", 0)
            with c2: med    = _money("Medicare/health insurance", "oth_med", 0)
            with c3: dental = _money("Dental insurance", "oth_dent", 0)
            with c4: other  = _money("Other recurring", "oth_other", 0)
            subtotal = meds + med + dental + other
            st.session_state["other_monthly_total"] = subtotal
            st.metric("Subtotal — Other monthly costs", _fmt(subtotal))
        return subtotal

    def _section_assets_common(self):
        with st.expander("Assets — Common", expanded=False):
            cols = st.columns(3)
            with cols[0]: checking = _money("Checking", "as_checking", 0, step=500)
            with cols[1]: savings  = _money("Savings", "as_savings", 0, step=500)
            with cols[2]: brokerage= _money("Brokerage (taxable)", "as_brokerage", 0, step=500)
            cols = st.columns(3)
            with cols[0]: cds      = _money("CDs / Money Market", "as_cds", 0, step=500)
            with cols[1]: retire   = _money("Retirement (IRA/401k)", "as_retire", 0, step=500)
            with cols[2]: hsa      = _money("HSA", "as_hsa", 0, step=500)
            subtotal = checking + savings + brokerage + cds + retire + hsa
            st.session_state["assets_common_total"] = subtotal
            st.metric("Subtotal — Common assets", _fmt(subtotal))
        return subtotal

    def _section_assets_detailed(self):
        with st.expander("Assets — Detailed", expanded=False):
            cols = st.columns(3)
            with cols[0]: annuities = _money("Annuities (current value)", "as_ann", 0, step=500)
            with cols[1]: vehicles  = _money("Vehicles (equity)", "as_veh", 0, step=500)
            with cols[2]: other     = _money("Other assets", "as_other_assets", 0, step=500)
            subtotal = annuities + vehicles + other
            st.session_state["assets_detailed_total"] = subtotal
            st.metric("Subtotal — Detailed assets", _fmt(subtotal))
        return subtotal

    # ---------- main render ----------
    def render(self, people: list[dict]) -> HouseholdResult:
        names = [p["display_name"] for p in people]
        nameA = names[0] if names else "Person A"
        nameB = names[1] if len(names) > 1 else None

        st.header("Household & Budget (optional)")
        st.markdown("Add income, benefits, home decisions, assets, and other costs to see affordability.")

        a_indiv, b_indiv = self._section_income_individual(nameA, nameB)
        hh_income = self._section_income_household()
        va_A, va_B, ltc_A, ltc_B, benefits_total = self._section_benefits(names)
        home_monthly, sale_net = self._section_home_decision()
        mods_monthly, mods_upfront, mods_deduct = self._section_mods()
        other_monthly = self._section_other_monthlies()
        assets_common = self._section_assets_common()
        assets_detail = self._section_assets_detailed()

        # Effective assets rollup (apply proceeds, deduct upfront mods optionally)
        effective_assets = assets_common + assets_detail + int(st.session_state.get("home_sale_net_proceeds", 0))
        if mods_deduct:
            effective_assets -= mods_upfront
        if effective_assets < 0:
            effective_assets = 0

        # Return consolidated result
        return HouseholdResult(
            indiv_income_A=a_indiv,
            indiv_income_B=b_indiv,
            household_income=hh_income,
            va_A=va_A,
            va_B=va_B,
            ltc_add_A=ltc_A,
            ltc_add_B=ltc_B,
            benefits_total=benefits_total,
            home_monthly_total=home_monthly,
            home_sale_net_proceeds=int(st.session_state.get("home_sale_net_proceeds", 0)),
            mods_monthly_total=mods_monthly,
            mods_upfront_total=mods_upfront,
            mods_deduct_assets=mods_deduct,
            other_monthly_total=other_monthly,
            assets_common_total=assets_common,
            assets_detailed_total=assets_detail,
            assets_total_effective=effective_assets,
        )
