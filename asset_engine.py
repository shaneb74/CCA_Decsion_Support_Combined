# asset_engine.py — minimal, compatible "Household & Budget" drawers
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, Any, List
import streamlit as st

def _fmt(n: int | float) -> str:
    try:
        return f"${int(n):,}"
    except Exception:
        return "$0"

def _money(label: str, key: str, default: int = 0, *, step: int = 50, min_value: int = 0) -> int:
    try:
        v0 = int(st.session_state.get(key, default) or default)
    except Exception:
        v0 = default
    v = st.number_input(label, min_value=min_value, step=step, value=v0, key=key)
    try:
        return int(v)
    except Exception:
        return 0

@dataclass
class HouseholdResult:
    indiv_income_A: int
    indiv_income_B: int
    household_income: int
    # Benefits
    va_A: int
    va_B: int
    ltc_A: bool
    ltc_B: bool
    benefits_total: int
    # Home & other
    home_monthly_total: int
    other_monthly_total: int
    assets_common_total: int
    assets_detailed_total: int

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

class IncomeAssetsEngine:
    """
    Drop‑in compatible stub.
    Provides a basic Household & Budget UI and persists keys the rest of the app expects:
      - a_va_monthly, b_va_monthly
      - a_ltc_flag, b_ltc_flag
      - other_monthly_total, assets_common_total, assets_detailed_total, home_monthly_total
    """

    def __init__(self, calculator=None):
        self.calculator = calculator

    def _income_individual(self, names: List[str]) -> tuple[int, int]:
        nameA = names[0] if names else "Person A"
        nameB = names[1] if len(names) > 1 else None
        with st.expander("Monthly Income — Individual", expanded=True):
            a_ss = _money(f"Social Security — {nameA}", "a_ss", 0)
            a_pn = _money(f"Pension — {nameA}", "a_pn", 0)
            a_oth = _money(f"Other — {nameA}", "a_other", 0)
            if nameB:
                b_ss = _money(f"Social Security — {nameB}", "b_ss", 0)
                b_pn = _money(f"Pension — {nameB}", "b_pn", 0)
                b_oth = _money(f"Other — {nameB}", "b_other", 0)
            else:
                b_ss = b_pn = b_oth = 0
            st.metric("Subtotal — Individual income", _fmt(a_ss+a_pn+a_oth+b_ss+b_pn+b_oth))
        return a_ss+a_pn+a_oth, b_ss+b_pn+b_oth

    def _income_household(self) -> int:
        with st.expander("Monthly Income — Household (shared)", expanded=False):
            r   = _money("Rental income", "hh_rent", 0)
            an  = _money("Annuity income", "hh_annuity", 0)
            inv = _money("Dividends/interest (joint)", "hh_invest", 0)
            tr  = _money("Trust distributions", "hh_trust", 0)
            oth = _money("Other household income", "hh_other", 0)
            subtotal = r + an + inv + tr + oth
            st.metric("Subtotal — Household income", _fmt(subtotal))
        return subtotal

    def _benefits(self, names: List[str]) -> tuple[int, int, bool, bool]:
        nameA = names[0] if names else "Person A"
        nameB = names[1] if len(names) > 1 else None
        with st.expander("Benefits (VA, Long‑Term Care insurance)", expanded=True):
            # VA
            a_va = _money(f"VA monthly — {nameA}", "a_va_monthly", st.session_state.get("a_va_monthly", 0), step=25)
            b_va = _money(f"VA monthly — {nameB or 'Person B'}", "b_va_monthly", st.session_state.get("b_va_monthly", 0), step=25) if nameB else 0
            # LTC flags
            a_ltc = st.checkbox(f"Long‑term care insurance — {nameA}", key="a_ltc_flag", value=bool(st.session_state.get("a_ltc_flag", False)))
            b_ltc = st.checkbox(f"Long‑term care insurance — {nameB or 'Person B'}", key="b_ltc_flag", value=bool(st.session_state.get("b_ltc_flag", False))) if nameB else False
            st.caption("These flags feed the PFMA Benefits & coverage checkboxes.")
            st.metric("Subtotal — Benefits (VA only shown here)", _fmt(int(a_va)+int(b_va)))
        return int(a_va), int(b_va), bool(a_ltc), bool(b_ltc)

    def _home_monthlies(self) -> int:
        with st.expander("Home monthly costs (mortgage, taxes, etc.)", expanded=False):
            mort = _money("Mortgage/HELOC", "home_mort", 0)
            tax  = _money("Property taxes", "home_tax", 0)
            ins  = _money("Homeowners insurance", "home_ins", 0)
            hoa  = _money("HOA/Maintenance", "home_hoa", 0)
            util = _money("Utilities (avg.)", "home_util", 0)
            total = mort + tax + ins + hoa + util
            st.metric("Subtotal — Home monthly costs", _fmt(total))
        st.session_state["home_monthly_total"] = int(total)
        return int(total)

    def _other_monthlies(self) -> int:
        with st.expander("Other monthly costs (meds, insurance, misc.)", expanded=False):
            meds   = _money("Medications", "oth_meds", 0)
            med    = _money("Medicare/health insurance", "oth_med", 0)
            dental = _money("Dental insurance", "oth_dent", 0)
            other  = _money("Other recurring", "oth_other", 0)
            subtotal = meds + med + dental + other
            st.metric("Subtotal — Other monthly costs", _fmt(subtotal))
        st.session_state["other_monthly_total"] = int(subtotal)
        return int(subtotal)

    def _assets(self) -> tuple[int,int]:
        with st.expander("Assets (quick)", expanded=False):
            checking = _money("Checking", "as_checking", 0, step=500)
            savings  = _money("Savings", "as_savings", 0, step=500)
            brokerage= _money("Brokerage", "as_brokerage", 0, step=500)
            cds      = _money("CDs / Money Market", "as_cds", 0, step=500)
            retire   = _money("Retirement (IRA/401k)", "as_retire", 0, step=500)
            hsa      = _money("HSA", "as_hsa", 0, step=500)
            common = checking+savings+brokerage+cds+retire+hsa
            st.metric("Subtotal — Common assets", _fmt(common))
            ann     = _money("Annuities", "as_ann", 0, step=500)
            veh     = _money("Vehicles (equity)", "as_veh", 0, step=500)
            other   = _money("Other assets", "as_other_assets", 0, step=500)
            detailed = ann+veh+other
            st.metric("Subtotal — Detailed assets", _fmt(detailed))
        st.session_state["assets_common_total"] = int(common)
        st.session_state["assets_detailed_total"] = int(detailed)
        return int(common), int(detailed)

    def render(self, people: List[Dict[str, Any]]):
        names = [p.get("display_name","Person A") for p in people] or ["Person A"]
        st.header("Household & Budget (optional)")
        st.markdown("Add income, benefits, assets, home decisions, and other costs to see affordability.")

        a_indiv, b_indiv = self._income_individual(names)
        hh_income = self._income_household()
        a_va, b_va, a_ltc, b_ltc = self._benefits(names)
        home_monthly = self._home_monthlies()
        other_monthly = self._other_monthlies()
        assets_common, assets_detailed = self._assets()

        # Result object (kept minimal)
        return HouseholdResult(
            indiv_income_A=a_indiv,
            indiv_income_B=b_indiv,
            household_income=hh_income,
            va_A=a_va, va_B=b_va,
            ltc_A=a_ltc, ltc_B=b_ltc,
            benefits_total=a_va+b_va,
            home_monthly_total=home_monthly,
            other_monthly_total=other_monthly,
            assets_common_total=assets_common,
            assets_detailed_total=assets_detailed,
        )
