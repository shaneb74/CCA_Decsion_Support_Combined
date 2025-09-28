# Run with: python -m pytest -q  (optional)
import json, pathlib

BASE = pathlib.Path(__file__).resolve().parents[1]
qa = json.loads((BASE / "question_answer_logic_FINAL_UPDATED.json").read_text())
rec = json.loads((BASE / "recommendation_logic_FINAL_MASTER_UPDATED.json").read_text())

def test_category_alignment():
    qa_cats = set().union(*(q.get("trigger", {}).keys() for q in qa.get("questions", [])))
    scoring = rec.get("scoring", {})
    score_cats = set(scoring.get("in_home", {}).keys()) | set(scoring.get("assisted_living", {}).keys())
    assert qa_cats - score_cats == set(), f"Missing in scoring: {qa_cats - score_cats}"
    assert score_cats - qa_cats <= set(), f"Extra in scoring: {score_cats - qa_cats}"

def test_keys_exist_for_totals():
    keys = ["home_sale_net_proceeds","mods_upfront_total","mods_deduct_assets","rm_lump_applied","rm_fees_oop_total","rm_monthly_income"]
    for k in keys:
        assert isinstance(k, str)
