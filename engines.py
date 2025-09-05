from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple, Set
import random

# ============================== Planner Engine ==============================

@dataclass
class PlannerResult:
    care_type: str                     # "in_home" | "assisted_living" | "memory_care" | "none"
    flags: Set[str] = field(default_factory=set)
    scores: Dict[str, int] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    narrative: Optional[str] = None    # fully rendered message for UI


class PlannerEngine:
    """
    Loads Q&A + recommendation JSON and produces:
      - flags (from explicit flag_map and conservative heuristics)
      - scores (in_home_score, assisted_living_score)
      - final care_type chosen by decision_precedence
      - rendered narrative message (no formatting burden on UI)
    """

    def __init__(self, qa_path: str, rec_path: str):
        with open(qa_path, "r") as f:
            self.qa = json.load(f)
        with open(rec_path, "r") as f:
            self.rec = json.load(f)

        # Core sections (exist in your latest JSONs)
        self.scoring = self.rec.get("scoring", {})
        self.thresholds = self.rec.get("final_decision_thresholds", {})
        self.precedence = self.rec.get("decision_precedence", [])
        self.rules = self.rec.get("final_recommendation", {})

        # Narrative parts
        self.greetings = self.rec.get("greeting_templates", ["Hello"])
        self.positives = self.rec.get("positive_state_templates", ["doing well"])
        self.encouragements = self.rec.get("encouragement_templates", ["We’re here if things change."])
        self.pref_clauses = self.rec.get("preference_clause_templates", {"default": ["Let’s find the best fit."]})
        self.issue_phrases = self.rec.get("issue_phrases", {})

        # Sanity defaults
        self.assisted_min = int(self.thresholds.get("assisted_living_min", 6))
        self.inhome_min   = int(self.thresholds.get("in_home_min", 3))

    # ----------------------------- Public API -----------------------------

    def run(self, answers: Dict[str, Any], conditional_answer: Optional[str] = None) -> PlannerResult:
        flags = self._collect_flags(answers, conditional_answer)
        scores, reasons = self._score(flags)
        care_type, matched_rule_key = self._decide(flags, scores)
        narrative = self._render_narrative(matched_rule_key, flags, scores)
        return PlannerResult(
            care_type=care_type,
            flags=flags,
            scores=scores,
            reasons=reasons,
            narrative=narrative
        )

    # ----------------------------- Flag logic -----------------------------

    def _collect_flags(self, answers: Dict[str, Any], conditional_answer: Optional[str]) -> Set[str]:
        flags: Set[str] = set()

        # 1) Explicit mapping from QA JSON (stable and preferred)
        flag_map = self.qa.get("flag_map", {})
        for qkey, mapping in flag_map.items():
            val = answers.get(qkey)
            if val is None:
                continue
            sval = str(val)
            mapped = mapping.get(sval)
            if isinstance(mapped, list):
                flags.update(mapped)
            elif isinstance(mapped, str):
                flags.add(mapped)

        # 2) Conservative heuristics in case JSON lacks a specific map
        # Note: only add non-trivial risk flags here; avoid overflagging
        for qkey, val in answers.items():
            try:
                iv = int(val)
            except Exception:
                continue

            qtext = qkey.lower()

            # Mobility: treat highest category as heavy dependence
            if "mobility" in qtext and iv >= 4:
                flags.add("high_mobility_dependence")
            elif "mobility" in qtext and iv == 3:
                flags.add("moderate_mobility")

            # Cognitive: rely on flag_map when possible; heuristics as backup
            if "cogn" in qtext or "memory" in qtext:
                if iv >= 4:
                    flags.add("severe_cognitive_risk")
                elif iv == 3:
                    flags.add("moderate_cognitive_decline")

            # Support: optional backup
            if "support" in qtext or "caregiver" in qtext:
                if iv >= 4:
                    flags.add("no_support")
                elif iv == 3:
                    flags.add("limited_support")

            # Safety
            if "safety" in qtext or "fall" in qtext:
                if iv >= 4:
                    flags.add("high_safety_concern")
                elif iv == 3:
                    flags.add("moderate_safety_concern")

            # Mood/social isolation (mild signal; don’t force AL)
            if "isolation" in qtext or "mood" in qtext or "depress" in qtext:
                if iv >= 4:
                    flags.add("high_risk")
                elif iv == 3:
                    flags.add("moderate_risk")

        # Conditional question (your 9th) often tracks wandering/safety; treat “Yes” as moderate safety concern minimum
        if conditional_answer is not None and str(conditional_answer) == "1":
            flags.add("moderate_safety_concern")

        return flags

    # ----------------------------- Scoring -----------------------------

    def _score(self, flags: Set[str]) -> Tuple[Dict[str, int], List[str]]:
        in_home = 0
        al = 0
        reasons: List[str] = []

        def add_reason(f: str):
            ph = self.issue_phrases.get(f)
            if ph and isinstance(ph, list) and ph[0]:
                txt = ph[0]
                if txt not in reasons:
                    reasons.append(txt)

        # Strong AL signals
        for f in flags:
            if f in {"high_dependence", "high_mobility_dependence", "no_support", "severe_cognitive_risk", "high_safety_concern"}:
                al += 2
                add_reason(f)

        # Mixed signals
        for f in flags:
            if f in {"moderate_cognitive_decline", "moderate_safety_concern"}:
                in_home += 1
                al += 1
                add_reason(f)

        # Mild in-home assistance signals
        for f in flags:
            if f in {"limited_support", "mental_health_concern", "high_risk", "moderate_risk", "moderate_mobility"}:
                in_home += 1
                add_reason(f)

        return {"in_home_score": in_home, "assisted_living_score": al}, reasons

    # ----------------------------- Decision -----------------------------

    def _decide(self, flags: Set[str], scores: Dict[str, int]) -> Tuple[str, str]:
        # Absolute “no care needed” if there are truly no concerning flags and trivial scores
        hard_flags = {
            "high_dependence", "high_mobility_dependence", "no_support",
            "severe_cognitive_risk", "high_safety_concern", "moderate_cognitive_decline",
            "moderate_safety_concern", "high_risk", "limited_support", "moderate_mobility"
        }
        if not (flags & hard_flags) and scores.get("assisted_living_score", 0) < 1 and scores.get("in_home_score", 0) < 1:
            return "none", "no_care_needed"

        # Strict precedence (first match wins)
        for key in self.precedence:
            rule = self.rules.get(key) or {}
            outcome = rule.get("outcome")
            if not outcome:
                continue
            if self._rule_matches(rule, flags, scores):
                return outcome, key

        # Fallback
        return "in_home", "in_home_with_support_fallback"

    def _rule_matches(self, rule: Dict[str, Any], flags: Set[str], scores: Dict[str, int]) -> bool:
        crit = (rule.get("criteria") or "").strip().lower()

        al = scores.get("assisted_living_score", 0)
        ih = scores.get("in_home_score", 0)

        def any_of(*names): return any(n in flags for n in names)
        def none_of(*names): return not any(n in flags for n in names)

        # Hard-coded interpretations for your ruleset names/phrases
        if "memory_care_override" in rule.get("id", "") or "severe_cognitive_risk" in crit:
            return any_of("severe_cognitive_risk") and any_of("no_support", "high_dependence", "high_safety_concern", "high_mobility_dependence")

        if "dependence_flag_logic" in crit or "at least 2 of" in crit:
            strong = {"high_dependence", "high_mobility_dependence", "no_support", "severe_cognitive_risk", "high_safety_concern"}
            hit = len(flags & strong) >= int(self.thresholds.get("dependence_flags_min", 2))
            return hit

        if "assisted_living_score" in crit:
            return al >= self.assisted_min

        if "balanced_al" in crit:
            return al >= self.assisted_min and ih >= self.inhome_min and \
                   none_of("high_dependence", "high_mobility_dependence", "no_support", "high_safety_concern", "severe_cognitive_risk")

        if "in_home_with_mobility_challenges" in crit:
            return (al >= self.assisted_min - 1) and (ih >= self.inhome_min) and \
                   any_of("high_mobility_dependence") and not any_of("moderate_cognitive_decline", "severe_cognitive_risk")

        if "in_home_possible_with_cognitive_and_safety_risks" in crit:
            return ih >= self.inhome_min and al >= self.inhome_min and \
                   any_of("moderate_cognitive_decline", "severe_cognitive_risk", "moderate_safety_concern", "high_safety_concern")

        if "in_home_with_support_and_financial_needs" in crit:
            return ih >= self.inhome_min and al < self.assisted_min and any_of("needs_financial_assistance")

        if "independent_with_safety_concern" in crit:
            return any_of("moderate_safety_concern", "high_safety_concern") and \
                   none_of("severe_cognitive_risk", "high_dependence", "high_mobility_dependence")

        if "independent_no_support_risk" in crit:
            return any_of("no_support") and none_of("severe_cognitive_risk", "high_dependence", "high_mobility_dependence")

        if "no_care_needed" in crit or rule.get("outcome") == "none":
            # If it survived here, verify no serious indicators
            return not any_of(
                "high_dependence","high_mobility_dependence","no_support","severe_cognitive_risk","high_safety_concern",
                "moderate_cognitive_decline","moderate_safety_concern","high_risk","limited_support","moderate_mobility"
            ) and scores.get("assisted_living_score",0) < self.inhome_min and scores.get("in_home_score",0) < self.inhome_min

        if "default" in crit or "fallback" in crit:
            return True

        return False

    # ----------------------------- Narrative -----------------------------

    def _render_narrative(self, rule_key: str, flags: Set[str], scores: Dict[str, int]) -> str:
        rule = self.rules.get(rule_key) or {}
        tpl = rule.get("message_template") or "{greeting} {name}, let’s choose a safe plan. {preference_clause}"

        greeting = random.choice(self.greetings) if self.greetings else "Hello"
        positive = random.choice(self.positives) if self.positives else "doing well"
        encouragement = random.choice(self.encouragements) if self.encouragements else "We’re here if things change."
        pref_group = "default"
        pref_clause = random.choice(self.pref_clauses.get(pref_group, ["Let’s find the best fit."]))

        key_issues = []
        for f in flags:
            arr = self.issue_phrases.get(f)
            if arr:
                key_issues.append(arr[0])
        joined = ", ".join(key_issues[:4]) if key_issues else "your situation"

        return tpl.format(
            greeting=greeting,
            name="{name}",                    # UI replaces this placeholder with the person’s name
            positive_state=positive,
            encouragement=encouragement,
            preference_clause=pref_clause,
            key_issues=joined,
            home_preference="prefer staying home"
        )


# ============================== Calculator Engine ==============================

class CalculatorEngine:
    """
    Light cost engine. Settings may be overridden by UI.
    """

    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        # Sensible defaults; UI can add/override via .settings
        self.settings = settings or {
            "state_multipliers": {
                "National": 1.0, "Washington": 1.18, "California": 1.22,
                "Texas": 0.96, "Florida": 1.02
            },
            "in_home_hourly_rate": 35,
            "assisted_living_base": 4500,
            "memory_care_base": 6500,
        }

    def _state_multiplier(self, state: str) -> float:
        return float(self.settings.get("state_multipliers", {}).get(state, 1.0))

    def monthly_cost(self, inp) -> int:
        """
        inp attributes:
          - state, care_type
          - in_home_hours_per_day, in_home_days_per_month (for in_home)
          - care_level, mobility, chronic, room_type (for AL/MC)
        """
        state = getattr(inp, "state", "National")
        mult = self._state_multiplier(state)
        care_type = getattr(inp, "care_type", "in_home")

        if care_type == "in_home":
            hours = int(getattr(inp, "in_home_hours_per_day", 0))
            days  = int(getattr(inp, "in_home_days_per_month", 0))
            rate  = int(self.settings.get("in_home_hourly_rate", 35))
            return int(round(hours * days * rate * mult))

        # Facility care
        base = int(self.settings.get("assisted_living_base", 4500))
        if care_type == "memory_care":
            base = int(self.settings.get("memory_care_base", 6500))

        care_level = getattr(inp, "care_level", "Medium")
        mobility   = getattr(inp, "mobility", "Independent")
        chronic    = getattr(inp, "chronic", "Some")
        room_type  = getattr(inp, "room_type", "Studio")

        level_mult = {"Low": 0.95, "Medium": 1.00, "High": 1.20}.get(care_level, 1.00)
        mob_add    = {"Independent": 0, "Assisted": 250, "Non-ambulatory": 500}.get(mobility, 0)
        chronic_add= {"None": 0, "Some": 150, "Multiple/Complex": 400}.get(chronic, 0)
        room_add   = {"Studio": 0, "1 Bedroom": 650, "Shared": -350}.get(room_type, 0)

        total = (base * level_mult + mob_add + chronic_add + room_add) * mult
        return int(round(total))