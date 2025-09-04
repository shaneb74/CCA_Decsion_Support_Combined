import streamlit as st
from pathlib import Path
from engines import PlannerEngine, CalculatorEngine, CalcInputs

planner = PlannerEngine()
calculator = CalculatorEngine()

DATA_DIR = Path(__file__).resolve().parent / "data"
if not DATA_DIR.exists():
    st.error("Missing data folder with JSON configs.")
    st.stop()

st.title("Combined Decision Support Prototype")
st.write("Planner and Calculator engines initialized successfully.")
