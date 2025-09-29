# totals.py — single source of truth for income, costs, assets, picture
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

def get_income_totals(s):
    inc_A = _to_int(_g(s,"inc_A")) or (_to_int(_g(s,"a_ss","ind_a_ss")) + _to_int(_g(s,"a_pn","ind_a_pn")) + _to_int(_g(s,"a_other","ind_a_other")))
    inc_B = _to_int(_g(s,"inc_B")) or (_to_int(_g(s,"b_ss","ind_b_ss")) + _to_int(_g(s,"b_pn","ind_b_pn")) + _to_int(_g(s,"b_other","ind_b_other")))
    inc_house = _to_int(_g(s,"inc_house")) or (_to_int(_g(s,"hh_rent","rent_income")) + _to_int(_g(s,"hh_annuity")) + _to_int(_g(s,"hh_invest","hh_investments")) + _to_int(_g(s,"hh_trust")) + _to_int(_g(s,"hh_other")))
    va_A = _to_int(_g(s,"va_A","a_va_monthly"))
    va_B = _to_int(_g(s,"va_B","b_va_monthly"))
    rm_monthly = _to_int(_g(s,"rm_monthly","rm_monthly_income"))
    income_total = inc_A + inc_B + inc_house + va_A + va_B + rm_monthly
    return dict(inc_A=inc_A, inc_B=inc_B, inc_house=inc_house, va_A=va_A, va_B=va_B, rm_monthly=rm_monthly, total=income_total)

def get_cost_totals(s):
    care_total = _to_int(_g(s,"care_total","care_monthly_total"))
    home_monthly = _to_int(_g(s,"home_monthly","home_monthly_total"))
    mods_monthly = _to_int(_g(s,"mods_monthly","mods_monthly_total"))
    other_monthly = _to_int(_g(s,"other_monthly","other_monthly_total"))
    total = care_total + home_monthly + mods_monthly + other_monthly
    return dict(care_total=care_total, home_monthly=home_monthly, mods_monthly=mods_monthly, other_monthly=other_monthly, total=total)

def get_asset_totals(s):
    assets_common = _to_int(_g(s,"assets_common","assets_common_total"))
    assets_detail = _to_int(_g(s,"assets_detail","assets_detailed_total","assets_less_common_total"))
    apply_sale = bool(_g(s,"apply_sale_to_assets","apply_home_proceeds","apply_net_proceeds","apply_home_sale_to_assets","apply_sale_net_to_assets","apply_home_sale"))
    sale_proceeds = _to_int(_g(s,"sale_proceeds","home_sale_net_proceeds","sale_net")) if apply_sale else 0
    rm_lump = _to_int(_g(s,"rm_lump","rm_lump_applied"))
    rm_fees_oop = _to_int(_g(s,"rm_fees_oop","rm_fees_oop_total"))
    mods_upfront = _to_int(_g(s,"mods_upfront","mods_upfront_total"))
    mods_deduct = bool(_g(s,"mods_deduct","mods_deduct_assets"))
    assets_total_effective = assets_common + assets_detail + sale_proceeds + rm_lump - rm_fees_oop - (mods_upfront if mods_deduct else 0)
    return dict(common=assets_common, detail=assets_detail, sale_proceeds=sale_proceeds, rm_lump=rm_lump, rm_fees_oop=rm_fees_oop, total_effective=assets_total_effective)

def compute_picture(s):
    income = get_income_totals(s)
    costs = get_cost_totals(s)
    assets = get_asset_totals(s)
    gap = costs["total"] - income["total"]
    months_runway = int(assets["total_effective"] // gap) if (gap > 0 and assets["total_effective"] > 0) else 0
    years = months_runway // 12
    rem = months_runway % 12
    return dict(gap=gap, months_runway=months_runway, years=years, rem=rem)
