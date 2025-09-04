
# engines.py
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from typing import Dict, List, Literal, Optional, Tuple

CareType = Literal['memory_care','assisted_living','in_home']

@dataclass
class PlannerResult:
    care_type: CareType
    flags: List[str]
    scores: Dict[str, int]
    reasons: List[str]
    advisory: Optional[str] = None

class PlannerEngine:
    def __init__(self, qa_path: str, rec_path: str):
        self.qa = json.load(open(qa_path))
        self.rec = json.load(open(rec_path))
        self.scoring = self.rec.get('scoring', {})
        self.dependence_logic = set(self.rec.get('dependence_flag_logic', {}).get('trigger_if_flags', []))
        self.final_thresholds = self.rec.get('final_decision_thresholds', {})
        self.final_texts = self.rec.get('final_recommendation', {})

    def run(self, answers: Dict[str, int], conditional_answer: Optional[int] = None) -> PlannerResult:
        flags = self._flags_from_answers(answers)
        # conditional Q: if severe_cognitive_decline then check 24/7
        if 'severe_cognitive_decline' in flags:
            # if user answered No (2), set memory_care_required
            if conditional_answer == 2:
                flags.add('memory_care_required')

        # overrides
        if 'memory_care_required' in flags:
            return PlannerResult('memory_care', list(flags), {'in_home':0,'assisted_living':0},
                                 [self.final_texts.get('memory_care_required_override',{}).get('message','Memory Care required')])
        if 'severe_cognitive_decline' in flags and conditional_answer != 1:
            return PlannerResult('memory_care', list(flags), {'in_home':0,'assisted_living':0},
                                 [self.final_texts.get('memory_care_override',{}).get('message','Memory Care recommended')])

        in_home, assisted = self._score(flags)
        scores = {'in_home': in_home, 'assisted_living': assisted}

        # thresholds
        if assisted >= 6:
            msg = self.final_texts.get('assisted_living_recommendation', {}).get('message', 'Assisted Living is recommended.')
            return PlannerResult('assisted_living', list(flags), scores, [msg])
        if in_home >= 6 and assisted < 6:
            msg = self.final_texts.get('in_home_with_support', {}).get('message', 'In-Home Care with support is recommended.')
            return PlannerResult('in_home', list(flags), scores, [msg])

        # fallback advisory
        advisory = self.final_texts.get('balanced_recommendation', {}).get('message', 'Both options could work; consider support at home vs community setting.')
        # pick care_type leaning by score
        care = 'assisted_living' if assisted >= in_home else 'in_home'
        return PlannerResult(care, list(flags), scores, [advisory], advisory=advisory)

    def _flags_from_answers(self, answers: Dict[str,int]) -> set:
        flags = set()
        for idx, q in enumerate(self.qa.get('questions', []), start=1):
            ans = answers.get(f'q{idx}')
            if ans is None:
                continue
            for domain, rules in q.get('trigger', {}).items():
                for rule in rules:
                    if rule.get('answer') == ans:
                        flags.add(rule.get('flag'))
        return flags

    def _score(self, flags: set) -> Tuple[int,int]:
        # map flags to domains (heuristic)
        domain_for_flag = {
          'moderate_dependence':'care_burden','high_dependence':'care_burden',
          'moderate_mobility':'care_burden','high_mobility_dependence':'care_burden',
          'moderate_risk':'social_isolation','high_risk':'social_isolation',
          'limited_support':'caregiver_support','no_support':'caregiver_support',
          'moderate_cognitive_decline':'cognitive_function','severe_cognitive_decline':'cognitive_function',
          'moderate_safety_concern':'home_safety','high_safety_concern':'home_safety',
          'low_access':'geographic_access','very_low_access':'geographic_access',
          'can_afford_assisted_living':'financial_feasibility','can_afford_in_home':'financial_feasibility',
          'needs_financial_assistance':'financial_feasibility'
        }
        seen = set()
        in_home = 0
        assisted = 0
        for f in flags:
            d = domain_for_flag.get(f)
            if not d or d in seen:
                continue
            seen.add(d)
            in_home += int(self.scoring.get('in_home',{}).get(d, 0))
            assisted += int(self.scoring.get('assisted_living',{}).get(d, 0))

        # dependence boost if 2+ heavy flags
        if len(self.dependence_logic.intersection(flags)) >= 2:
            assisted += int(self.scoring.get('assisted_living',{}).get('dependence', 0))
        return in_home, assisted

# Simple calculator engine using provided lookups
from dataclasses import dataclass
@dataclass
class CalcInputs:
    state: str = 'National'
    care_type: CareType = 'assisted_living'
    room_type: Optional[str] = None
    in_home_hours_per_day: int = 4
    care_level: str = 'Medium'  # Low/Medium/High
    mobility: str = 'Independent'  # Independent/Assisted/Non-ambulatory
    chronic: str = 'Some'  # None/Some/Multiple/Complex
    share_unit_with_person_b: bool = False

class CalculatorEngine:
    def __init__(self, calc_path: str, overlay_path: str):
        self.calc = json.load(open(calc_path))
        self.overlay = json.load(open(overlay_path))
        self.settings = self.calc.get('settings', {})
        self.lookups = self.calc.get('lookups', {})

    def monthly_cost(self, inp: CalcInputs) -> int:
        m = self.lookups
        days = int(self.settings.get('days_per_month', 30))
        state_mult = float(m.get('state_multipliers',{}).get(inp.state, 1.0))

        care_add = int(m.get('care_level_adders',{}).get(inp.care_level, 0))

        # mobility adders differ for facility vs in_home
        if inp.care_type == 'in_home':
            mob_add = int(m.get('mobility_adders',{}).get('in_home',{}).get(inp.mobility, 0))
        else:
            mob_add = int(m.get('mobility_adders',{}).get('facility',{}).get(inp.mobility, 0))

        chronic_add = int(m.get('chronic_adders',{}).get(inp.chronic, 0))

        if inp.care_type in ('assisted_living','memory_care'):
            base = int(m.get('room_type',{}).get(inp.room_type or 'Studio', 4200))
            if inp.care_type == 'memory_care':
                mc_mult = float(self.settings.get('memory_care_multiplier', 1.25))
                base = int(round(base * mc_mult))
            subtotal = base + care_add + mob_add + chronic_add
            subtotal = int(round(subtotal * state_mult))
            return subtotal

        # in-home care
        rate = int(m.get('in_home_care_matrix',{}).get(str(inp.in_home_hours_per_day), 42))
        subtotal = int(inp.in_home_hours_per_day) * int(rate) * days
        subtotal += care_add + mob_add + chronic_add
        subtotal = int(round(subtotal * state_mult))
        return subtotal
