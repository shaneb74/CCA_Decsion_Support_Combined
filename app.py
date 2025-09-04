# app_diag.py
import sys, traceback, platform, json
from pathlib import Path
import streamlit as st

st.set_page_config(page_title="Senior Navigator • Diagnostics", layout="wide")
st.title("Diagnostics")

# Environment
st.subheader("Environment")
st.write({"python": sys.version, "platform": platform.platform()})

# Files
root = Path(__file__).resolve().parent
data = root / "data"
st.subheader("Repo layout")
st.write({"root": str(root), "has_data_folder": data.exists()})
st.write("Data files:", [p.name for p in data.glob("*")] if data.exists() else "missing")

# Engines import
st.subheader("engines.py import")
try:
    import engines
    st.success("Imported engines")
    st.write("Exports:", [n for n in dir(engines) if not n.startswith("_")][:40])
except Exception:
    st.error("Failed to import engines")
    st.code(traceback.format_exc())
    st.stop()

# Init engines
try:
    planner = engines.PlannerEngine()
    st.success("PlannerEngine initialized")
    qa = getattr(planner, "qa", {})
    st.write("Questions count:", len(qa.get("questions", [])))
except Exception:
    st.error("PlannerEngine init failed")
    st.code(traceback.format_exc())

try:
    calculator = engines.CalculatorEngine()
    st.success("CalculatorEngine initialized")
    settings = getattr(calculator, "settings", {})
    st.write("Settings keys:", list(settings.keys())[:30])
except Exception:
    st.error("CalculatorEngine init failed")
    st.code(traceback.format_exc())

# Try a tiny monthly_cost
st.subheader("monthly_cost smoke test")
try:
    CalcInputs = getattr(engines, "CalcInputs", None)
    if CalcInputs:
        inp = CalcInputs(state="National", care_type="in_home", care_level="Medium", mobility="Independent", chronic="Some")
        setattr(inp, "in_home_hours_per_day", 4)
        setattr(inp, "in_home_days_per_month", 20)
    else:
        from types import SimpleNamespace
        inp = SimpleNamespace(state="National", care_type="in_home", care_level="Medium", mobility="Independent", chronic="Some",
                              in_home_hours_per_day=4, in_home_days_per_month=20)
    est = calculator.monthly_cost(inp)
    st.success(f"monthly_cost returned: ${est:,}")
except Exception:
    st.error("monthly_cost failed")
    st.code(traceback.format_exc())