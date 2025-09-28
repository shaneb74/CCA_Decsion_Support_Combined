# asset_engine.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional
import streamlit as st

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
    # Liabilities
    liabilities_total: int
    # Final assets rollup (applies proceeds, deducts mods and liabilities if selected)
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
                with a_ss: a1 = _money(f"Social Security — {nameA}", "a_ss", default=0)
                with a_pn: a2 = _money(f"Pension — {nameA}", "a_pn", default=0)
                with a_oth: a3 = _money(f"Other income — {nameA}", "a_other", default=0)
                b_ss, b_pn, b_oth = st.columns(3)
                with b_ss: b1 = _money(f"Social Security — {nameB}", "b_ss", default=0)
                with b_pn: b2 = _money(f"Pension — {nameB}", "b_pn", default=0)
                with b_oth: b3 = _money(f"Other income — {nameB}", "b_other", default=0)
                return a1 + a2 + a3, b1 + b2 + b3
            else:
                a_ss, a_pn, a_oth = st.columns(3)
                with a_ss: a1 = _money(f"Social Security — {nameA}", "a_ss", default=0)
                with a_pn: a2 = _money(f"Pension — {nameA}", "a_pn", default=0)
                with a_oth: a3 = _money(f"Other income — {nameA}", "a_other", default=0)
                return a1 + a2 + a3, 0

    def _section_income_household(self):
        with st.expander("Monthly Income — Household", expanded=True):
            fields = [
                ("Rental income", "hh_rent"),
                ("Annuity income", "hh_annuity"),
                ("Investment income", "hh_invest"),
                ("Trust income", "hh_trust"),
                ("Other household income", "hh_other"),
            ]
            total = 0
            for label, key in fields:
                total += _money(label, key, default=0)
            return total

    def _section_benefits(self, names: List[str]):
        with st.expander("Benefits", expanded=True):
            va_options = [
                "None",
                "Veteran only (A&A)",
                "Veteran with spouse (A&A)",
                "Two veterans married, both A&A (household ceiling)",
                "Surviving spouse (A&A)",
            ]
            va_values = {
                "None": 0.0,
                "Veteran only (A&A)": 2358.33,
                "Veteran with spouse (A&A)": 2795.67,
                "Two veterans married, both A&A (household ceiling)": 3740.50,
                "Surviving spouse (A&A)": 1515.58,
            }
            ltc_add = 1800  # From settings
            va_A = 0; va_B = 0; ltc_A = 0; ltc_B = 0
            if len(names) > 1:
                c1, c2 = st.columns(2)
                with c1:
                    va_A = va_values.get(st.selectbox(f"VA benefit — {names[0]}", va_options, key="a_va"), 0)
                    ltc_A = ltc_add if st.checkbox(f"Long-term care insurance — {names[0]}", key="a_ltc") else 0
                with c2:
                    va_B = va_values.get(st.selectbox(f"VA benefit — {names[1]}", va_options, key="b_va"), 0)
                    ltc_B = ltc_add if st.checkbox(f"Long-term care insurance — {names[1]}", key="b_ltc") else 0
            else:
                va_A = va_values.get(st.selectbox(f"VA benefit — {names[0]}", va_options, key="a_va"), 0)
                ltc_A = ltc_add if st.checkbox(f"Long-term care insurance — {names[0]}", key="a_ltc") else 0
            # Validate VA eligibility
            if va_A > 0 and "Veteran" not in st.session_state.get("pfma_marital", {}).get("A", "None"):
                st.warning(f"VA benefit selected for {names[0]}, but marital status does not indicate veteran eligibility.")
            if va_B > 0 and "Veteran" not in st.session_state.get("pfma_marital", {}).get("B", "None"):
                st.warning(f"VA benefit selected for {names[1] if len(names) > 1 else names[0]}, but marital status does not indicate veteran eligibility.")
            return int(va_A), int(va_B), int(ltc_A), int(ltc_B), int(va_A + va_B + ltc_A + ltc_B)

    def _section_home_decision(self):
        with st.expander("Home Decisions", expanded=True):
            home_decision = st.radio(
                "Home decision",
                ["Stay in home", "Sell home", "Rent out home"],
                key="home_decision",
                help="This impacts monthly costs and available assets."
            )
            home_monthly = 0
            proceeds = 0
            if home_decision == "Stay in home":
                home_monthly += _money("Monthly mortgage or rent", "home_mortgage_rent", default=0)
                home_monthly += _money("Property taxes (monthly)", "home_taxes", default=0)
                home_monthly += _money("Home maintenance (monthly)", "home_maintenance", default=0)
            elif home_decision == "Sell home":
                home_value = _money("Home value (estimated)", "home_value", default=0)
                mortgage_balance = _money("Remaining mortgage balance", "home_mortgage_balance", default=0)
                closing_costs = _money("Closing costs (e.g., 6% of value)", "home_closing_costs", default=0)
                proceeds = max(0, home_value - mortgage_balance - closing_costs)
                st.session_state.home_sale_net_proceeds = proceeds
            elif home_decision == "Rent out home":
                home_monthly += _money("Monthly mortgage or management fees", "home_mortgage_management", default=0)
                home_monthly += _money("Property taxes (monthly)", "home_taxes_rent", default=0)
                home_monthly += _money("Home maintenance (monthly)", "home_maintenance_rent", default=0)
                rental_income = _money("Rental income (monthly)", "home_rental_income", default=0)
                st.session_state.hh_rent = rental_income
            return home_monthly, proceeds

    def _section_mods(self):
        with st.expander("Home Modifications", expanded=True):
            mods = [
                ("Grab bars and rails", "mod_grab_bars", 250),
                ("Ramps", "mod_ramps", 1000),
                ("Stair lifts", "mod_stair_lifts", 3000),
                ("Bathroom modifications", "mod_bathroom", 2000),
            ]
            monthly = 0
            upfront = 0
            for label, key, default in mods:
                if st.checkbox(label, key=f"check_{key}"):
                    cost = _money(f"{label} cost", key, default=default)
                    if st.checkbox(f"Finance {label} monthly", key=f"finance_{key}"):
                        monthly += cost // 12  # Simple annual-to-monthly conversion
                    else:
                        upfront += cost
            mods_deduct = st.checkbox("Deduct upfront modifications from assets", key="mods_deduct_assets")
            return monthly, upfront, mods_deduct

    def _section_other_monthlies(self):
        with st.expander("Other Monthly Costs", expanded=True):
            fields = [
                ("Medical expenses", "optional_medical"),
                ("Prescriptions", "optional_prescriptions"),
                ("Phone & internet", "optional_phone_internet"),
                ("Life insurance premiums", "optional_life_insurance"),
                ("Transportation", "optional_transportation"),
                ("Family travel", "optional_family_travel"),
                ("Auto payment", "optional_auto"),
                ("Auto insurance", "optional_auto_insurance"),
                ("Other", "optional_other"),
                ("HELOC payment (if any)", "heloc_payment_monthly"),
            ]
            total = 0
            for label, key in fields:
                total += _money(label, key, default=0)
            return total

    def _section_assets_common(self):
        with st.expander("Assets — Common", expanded=True):
            fields = [
                ("Cash and savings (checking, savings, MMAs)", "cash_savings"),
                ("Brokerage (taxable) total", "brokerage_taxable"),
                ("Traditional IRA balance", "ira_traditional"),
                ("Roth IRA balance", "ira_roth"),
                ("IRA total (if not using granular)", "ira_total"),
                ("401(k) balance", "employer_401k"),
                ("Home equity (net)", "home_equity"),
                ("Annuities (surrender value)", "annuity_surrender"),
            ]
            total = 0
            for label, key in fields:
                total += _money(label, key, default=0)
            return total

    def _section_assets_detailed(self):
        with st.expander("Assets — Detailed", expanded=True):
            fields = [
                ("Certificates of deposit (CDs)", "cds_balance"),
                ("403(b) balance", "employer_403b"),
                ("457(b) balance", "employer_457b"),
                ("SEP IRA balance", "ira_sep"),
                ("SIMPLE IRA balance", "ira_simple"),
                ("Life insurance cash value", "life_cash_value"),
                ("HSA balance", "hsa_balance"),
                ("Other assets", "other_assets"),
            ]
            total = 0
            for label, key in fields:
                total += _money(label, key, default=0)
            return total

    def _section_liabilities(self):
        with st.expander("Liabilities", expanded=True):
            fields = [
                ("Mortgage balance (if not selling home)", "mortgage_balance"),
                ("Credit card debt", "credit_card_debt"),
                ("Personal loans", "personal_loans"),
                ("Auto loans", "auto_loans"),
                ("Other liabilities", "other_liabilities"),
            ]
            total = 0
            for label, key in fields:
                total += _money(label, key, default=0)
            return total

    def render(self, people: List[Dict[str, Any]]) -> Optional[HouseholdResult]:
        names = [p["display_name"] for p in people]
        nameA = names[0] if names else "Person A"
        nameB = names[1] if len(names) > 1 else None

        st.header("Household & Budget (optional)")
        st.markdown("Add income, benefits, assets, home decisions, liabilities, and other costs to see affordability.")

        a_indiv, b_indiv = self._section_income_individual(nameA, nameB)
        hh_income = self._section_income_household()
        va_A, va_B, ltc_A, ltc_B, benefits_total = self._section_benefits(names)
        home_monthly, sale_net = self._section_home_decision()
        mods_monthly, mods_upfront, mods_deduct = self._section_mods()
        other_monthly = self._section_other_monthlies()
        assets_common = self._section_assets_common()
        assets_detail = self._section_assets_detailed()
        liabilities_total = self._section_liabilities()

        # Effective assets rollup (apply proceeds, deduct mods and liabilities)
        effective_assets = assets_common + assets_detail + sale_net - liabilities_total
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
            home_sale_net_proceeds=sale_net,
            mods_monthly_total=mods_monthly,
            mods_upfront_total=mods_upfront,
            mods_deduct_assets=mods_deduct,
            other_monthly_total=other_monthly,
            assets_common_total=assets_common,
            assets_detailed_total=assets_detail,
            liabilities_total=liabilities_total,
            assets_total_effective=effective_assets,
        )
