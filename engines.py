from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional, Tuple
from pathlib import Path

# Resolve paths relative to this file so it works locally and on Streamlit Cloud
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = (BASE_DIR / "data") if (BASE_DIR / "data").exists() else (BASE_DIR.parent / "data")

def _load_json(rel_name: str):
    p = DATA_DIR / rel_name
    if not p.exists():
        raise FileNotFoundError(f"Required data file not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)

def _to_int_threshold(val, default_value: int) -> int:
    """Accept int/float/str; if str, extract first integer; else default."""
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        m = re.search(r"(\d+)", val)
        if m:
            return int(m.group(1))
    return default_value

CareType = Literal['memory_care','assisted_living','in_home']

@dataclass
class PlannerResult:
    care_type: CareType
    flags: List[str]
    scores: Dict[str, int]
    reasons: List[str]
    advisory: Optional[str] = None

class PlannerEngine:
    """Deterministic planner that reads Q/A and recommendation configs from data/."""
    def __init__(self,
                 qa_path: str = "question_answer_logic_FINAL_UPDATED.json",
                 rec_path: str = "recommendation_logic_FINAL_MASTER_UPDATED.json"):
        self.qa = _load_json(qa_path)
        self.rec = _load_json(rec_path)
        self.scoring = self.rec.get('scoring', {})
        self.dependence_logic = set(self.rec.get('dependence_flag_logic', {}).get('trigger_if_flags', []))
        self.final_thresholds = self.rec.get('final_decision_thresholds', {})
        self.final_texts = self.rec.get('final_recommendation', {})

    def run(self, answers: Dict[str, int], conditional_answer: Optional[int] = None) -> PlannerResult:
        flags = self._flags_from_answers(answers)

        # Conditional: severe cognitive decline + cannot arrange 24/7
        if 'severe_cognitive_decline' in flags and conditional_answer == 2:
            flags.add('memory_care_required')

        # Overrides
        if 'memory_care_required' in flags:
            msg = self.final_texts.get('memory_care_required_override', {}).get('message', 'Memory Care required.')
            return PlannerResult('memory_care', list(flags), {'in_home':0,'assisted_living':0}, [msg])

        if 'severe_cognitive_decline' in flags and conditional_answer != 1:
            msg = self.final_texts.get('memory_care_override', {}).get('message', 'Memory Care recommended.')
            return PlannerResult('memory_care', list(flags), {'in_home':0,'assisted_living':0}, [msg])

        # Scores
        in_home, assisted = self._score(flags)
        scores = {'in_home': in_home, 'assisted_living': assisted}

        # Thresholds (robust to descriptive strings)
        assisted_cut = _to_int_threshold(self.final_thresholds.get('assisted_living'), 6)
        in_home_cut  = _to_int_threshold(self.final_thresholds.get('in_home'), 6)

        if assisted >= assisted_cut:
            msg = self.final_texts.get('assisted_living_recommendation', {}).get('message', 'Assisted Living is recommended.')
            return PlannerResult('assisted_living', list(flags), scores, [msg])

        if in_home >= in_home_cut and assisted < assisted_cut:
            msg = self.final_texts.get('in_home_with_support', {}).get('message', 'In-Home Care with support is recommended.')
            return PlannerResult('in_home', list(flags), scores, [msg])

        # Fallback
        advisory = self.final_texts.get('balanced_recommendation', {}).get('message',
                    'Both options could work; consider support at home vs a community setting.')
        care = 'assisted_living' if assisted >= in_home else 'in_home'
        return PlannerResult(care, list(flags), scores, [advisory], advisory=advisory)

    def _flags_from_answers(self, answers: Dict[str, int]) -> set:
        flags = set()
        for idx, q in enumerate(self.qa.get('questions', []), start=1):
            ans = answers.get(f'q{idx}')
            if ans is None:
                continue
            for _, rules in q.get('trigger', {}).items():
                for rule in rules:
                    if rule.get('answer') == ans:
                        flags.add(rule.get('flag'))
        return flags

    def _score(self, flags: set) -> Tuple[int,int]:
        # Map flags to scoring domains
        domain_for_flag = {
            'moderate_dependence':'care_burden','high_dependence':'care_burden',
            'moderate_mobility':'care_burden','high_mobility_dependence':'care_burden',
            'moderate_risk':'social_isolation','high_risk':'social_isolation',
            'limited_support':'caregiver_support','no_support':'caregiver_support',
            'moderate_cognitive_decline':'cognitive_function','severe_cognitive_decline':'cognitive_function',
            'moderate_safety_concern':'home_safety','high_safety_concern':'home_safety',
            'low_access':'geographic_access','very_low_access':'geographic_access',
            'can_afford_assisted_living':'financial_feasibility','can_afford_in_home':'financial_feasibility',
            'needs_financial_assistance':'financial_feasibility',
        }
        seen = set()
        in_home = 0
        assisted = 0
        for f in flags:
            d = domain_for_flag.get(f)
            if not d or d in seen:
                continue
            seen.add(d)
            in_home += int(self.scoring.get('in_home', {}).get(d, 0))
            assisted += int(self.scoring.get('assisted_living', {}).get(d, 0))

        # Dependence boost
        if len(self.dependence_logic.intersection(flags)) >= 2:
            assisted += int(self.scoring.get('assisted_living', {}).get('dependence', 0))
        return in_home, assisted

# ---------------- Calculator ----------------

@dataclass
class CalcInputs:
    state: str = 'National'
    care_type: CareType = 'assisted_living'
    room_type: Optional[str] = None
    in_home_hours_per_day: int = 4
    care_level: str = 'Medium'           # Low | Medium | High
    mobility: str = 'Independent'        # Independent | Assisted | Non-ambulatory
    chronic: str = 'Some'                # None | Some | Multiple/Complex
    share_unit_with_person_b: bool = False

class CalculatorEngine:
    """Thin calculator using lookups/settings from calculator JSON."""
    def __init__(self,
                 calc_path: str = "senior_care_calculator_v5_full_with_instructions_ui.json",
                 overlay_path: str = "senior_care_modular_overlay.json"):
        self.calc = _load_json(calc_path)
        self.overlay = _load_json(overlay_path)
        self.settings = self.calc.get('settings', {})
        self.lookups = self.calc.get('lookups', {})

    def monthly_cost(self, inp: CalcInputs) -> int:
        m = self.lookups
        days = int(self.settings.get('days_per_month', 30))
        state_mult = float(m.get('state_multipliers', {}).get(inp.state, 1.0))

        care_add = int(m.get('care_level_adders', {}).get(inp.care_level, 0))

        if inp.care_type == 'in_home':
            mob_add = int(m.get('mobility_adders', {}).get('in_home', {}).get(inp.mobility, 0))
        else:
            mob_add = int(m.get('mobility_adders', {}).get('facility', {}).get(inp.mobility, 0))

        chronic_add = int(m.get('chronic_adders', {}).get(inp.chronic, 0))

        if inp.care_type in ('assisted_living','memory_care'):
            base = int(m.get('room_type', {}).get(inp.room_type or 'Studio', 4200))
            if inp.care_type == 'memory_care':
                mc_mult = float(self.settings.get('memory_care_multiplier', 1.25))
                base = int(round(base * mc_mult))
            subtotal = base + care_add + mob_add + chronic_add
            return int(round(subtotal * state_mult))

        # in-home
        rate = int(m.get('in_home_care_matrix', {}).get(str(inp.in_home_hours_per_day), 42))
        subtotal = int(inp.in_home_hours_per_day) * int(rate) * days
        subtotal += care_add + mob_add + chronic_add
        return int(round(subtotal * state_mult))
