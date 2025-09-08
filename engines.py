# engines.py — Best-fit, JSON-driven recommendation engine
from __future__ import annotations

import json
import re
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# --------------------------- Results ---------------------------

@dataclass
class PlannerResult:
    care_type: str                    # "in_home" | "assisted_living" | "memory_care" | "none"
    flags: List[str]
    scores: Dict[str, int]            # {"in_home_score": int, "assisted_living_score": int}
    reasons: List[str]                # human-readable debug trail
    narrative: str
    raw_rule: Optional[str] = None    # the rule name that won


# --------------------------- Engine ----------------------------

class PlannerEngine:
    """
    Reads Q&A JSON and Recommendation JSON and converts a dict of answers
    { "q1": int, "q2": int, ... } into a PlannerResult using a BEST-FIT selection.
    """
    def __init__(self, qa_path: str | Path, rec_path: str | Path):
        with open(qa_path, "r", encoding="utf-8") as f:
            self.qa: Dict[str, Any] = json.load(f)
        with open(rec_path, "r", encoding="utf-8") as f:
            self.rec: Dict[str, Any] = json.load(f)

        # Core sections we rely on (fall back safely)
        self.rules: Dict[str, Dict[str, Any]] = self.rec.get("final_recommendation", {})
        self.precedence: List[str] = self.rec.get("decision_precedence", list(self.rules.keys()))
        self.thresholds: Dict[str, Any] = self.rec.get("final_decision_thresholds", {})
        self.flag_to_category: Dict[str, str] = self.rec.get("flag_to_category_mapping", {})
        self.scoring: Dict[str, Dict[str, int]] = self.rec.get("scoring", {"in_home": {}, "assisted_living": {}})

        # Numeric thresholds (accept int or strings like ">= 6")
        def _num(v, default):
            if isinstance(v, (int, float)):
                return int(v)
            if isinstance(v, str):
                m = re.search(r"(\d+)", v)
                if m:
                    return int(m.group(1))
            return default

        self.in_home_min = _num(self.thresholds.get("in_home_min"), 3)
        self.al_min      = _num(self.thresholds.get("assisted_living_min"), 6)
        self.dep_min     = _num(self.thresholds.get("dependence_flags_min"), 2)

        # Per-rule weights (higher = stronger recommendation). We also infer weights by name.
        self.rank_weights: Dict[str, int] = {
            # hard overrides
            "memory_care_override": 100,

            # strong AL
            "assisted_living": 70,
            "moderate_needs_assisted_living_recommendation": 70,
            "close_to_assisted_living_with_moderate_needs": 60,
            "assisted_living_score": 60,

            # balanced / nuanced in-home
            "in_home_possible_with_cognitive_and_safety_risks": 50,
            "balanced_recommendation": 40,
            "in_home_with_support": 35,
            "in_home_with_uncertain_support": 32,
            "in_home_score": 30,
            "in_home_with_mobility_challenges": 30,

            # independents
            "independent_with_safety_concern": 20,
            "independent_no_support_risk": 18,

            # explicit none
            "no_care_needed": 10,
        }

        # Severity rank for tie-breakers (outcome → severity)
        self.severity_rank = {"none": 0, "in_home": 1, "assisted_living": 2, "memory_care": 3}

        # Used by "dependence_flag_logic"
        self.dep_logic_cfg = self.rec.get("dependence_flag_logic", {})
        if not isinstance(self.dep_logic_cfg, dict):
            self.dep_logic_cfg = {}

    # --------------------------- Public API ---------------------------

    def run(self, answers: Dict[str, int], *, name: str = "You") -> PlannerResult:
        flags, scores, reasons = self._evaluate(answers)

        # Build a candidate list by checking every rule (best-fit selection)
        candidates: List[Tuple[int, str, str]] = self._collect_candidates(flags, scores, reasons)

        # Choose the best candidate deterministically
        chosen_rule, outcome = self._choose_best(candidates, scores, reasons)

        # Render narrative using the chosen rule
        narrative = self._render_narrative(chosen_rule, flags, scores, name)

        return PlannerResult(
            care_type=outcome,
            flags=sorted(flags),
            scores=scores,
            reasons=reasons,
            narrative=narrative,
            raw_rule=chosen_rule,
        )

    # --------------------------- Internals ---------------------------

    def _evaluate(self, answers: Dict[str, int]) -> Tuple[Set[str], Dict[str, int], List[str]]:
        """
        Turn raw answers into flags via QA triggers; map to categories; compute scores.
        """
        reasons: List[str] = []
        flags: Set[str] = set()

        # Questions in UI are 1-based (q1..qN)
        for idx, q in enumerate(self.qa.get("questions", []), start=1):
            qk = f"q{idx}"
            a = answers.get(qk)
            if a is None:
                continue

            triggers = q.get("trigger", {})
            for _cat, tlist in triggers.items():
                for t in tlist:
                    if "answer" in t and int(t["answer"]) == int(a):
                        fl = t.get("flag")
                        if fl:
                            flags.add(fl)
                            reasons.append(f"• {qk}={a} → flag {fl}")

        # Map flags → categories for scoring
        categories: Set[str] = set()
        for fl in flags:
            if fl in self.flag_to_category:
                categories.add(self.flag_to_category[fl])
        if categories:
            reasons.append(f"• categories: {sorted(categories)}")

        in_home_score = sum(self.scoring.get("in_home", {}).get(c, 0) for c in categories)
        al_score      = sum(self.scoring.get("assisted_living", {}).get(c, 0) for c in categories)
        scores = {"in_home_score": in_home_score, "assisted_living_score": al_score}
        reasons.append(f"• scores: in_home={in_home_score} al={al_score}")

        return flags, scores, reasons

    # -------- Candidate collection & best-fit choice --------

    def _collect_candidates(
        self, flags: Set[str], scores: Dict[str, int], reasons: List[str]
    ) -> List[Tuple[int, str, str]]:
        """Evaluate every rule and collect (weight, rule_name, outcome)."""
        f = flags
        s = scores
        in_min, al_min, dep_min = self.in_home_min, self.al_min, self.dep_min

        candidates: List[Tuple[int, str, str]] = []

        # Memory-care override (explicit & safe)
        if "severe_cognitive_risk" in f and ("no_support" in f or "high_safety_concern" in f):
            w = self.rank_weights.get("memory_care_override", 100)
            candidates.append((w, "memory_care_override", "memory_care"))

        # Dynamic pass: walk every rule name in precedence and add if it matches
        for rule in self.precedence:
            meta = self.rules.get(rule, {})
            if not meta:
                continue
            if self._rule_matches(rule, meta, f, s, in_min, al_min, dep_min):
                outcome = self._infer_outcome(rule, meta)
                w = self._weight_for(rule, outcome)
                candidates.append((w, rule, outcome))

        # If nothing matched, add safe fallbacks
        if not candidates:
            # Prefer "in_home_with_support" if available, else "no_care_needed"
            if "in_home_with_support" in self.rules:
                candidates.append((self._weight_for("in_home_with_support", "in_home"), "in_home_with_support", "in_home"))
            else:
                candidates.append((self._weight_for("no_care_needed", "none"), "no_care_needed", "none"))

        # Debug dump
        if candidates:
            pretty = " | ".join(f"{r}->{o} (w={w})" for (w, r, o) in candidates)
            reasons.append(f"• CANDIDATES: {pretty}")

        return candidates

    def _choose_best(
        self, candidates: List[Tuple[int, str, str]], scores: Dict[str, int], reasons: List[str]
    ) -> Tuple[str, str]:
        """
        Choose the best candidate deterministically:
        1) Highest weight
        2) Highest severity (memory > AL > IH > none)
        3) Tie-break within same outcome using relevant numeric score
        4) Finally, lexicographic by rule name for stability
        """
        if not candidates:
            return "no_care_needed", "none"

        def tiebreak_key(item: Tuple[int, str, str]):
            w, rule, outcome = item
            sev = self.severity_rank.get(outcome, 0)
            # within outcome type, prefer higher relevant score
            if outcome == "assisted_living":
                score = scores.get("assisted_living_score", 0)
            elif outcome == "in_home":
                score = scores.get("in_home_score", 0)
            else:
                score = 0
            return (w, sev, score, rule)

        best = max(candidates, key=tiebreak_key)
        _, rule_name, outcome = best
        reasons.append(f"• CHOICE: {rule_name} → {outcome}")
        return rule_name, outcome

    # -------- Rule matching helpers --------

    def _rule_matches(
        self,
        rule_name: str,
        meta: Dict[str, Any],
        f: Set[str],
        s: Dict[str, int],
        in_min: int,
        al_min: int,
        dep_min: int,
    ) -> bool:
        """Known rule handlers. Unknown rules pass to allow JSON-supplied outcomes/messages."""
        def any_of(*need: str) -> bool: return any(n in f for n in need)
        def all_of(*need: str) -> bool: return all(n in f for n in need)
        def none_of(*ban: str) -> bool: return all(n not in f for n in ban)

        if rule_name == "dependence_flag_logic":
            to_count = self.dep_logic_cfg.get(
                "trigger_if_flags",
                ["high_dependence", "high_mobility_dependence", "no_support",
                 "severe_cognitive_risk", "high_safety_concern"],
            )
            count = sum(1 for fl in to_count if fl in f)
            return count >= dep_min

        if rule_name == "assisted_living":
            return s.get("assisted_living_score", 0) >= al_min

        if rule_name == "moderate_needs_assisted_living_recommendation":
            return (
                s.get("assisted_living_score", 0) >= al_min
                and s.get("in_home_score", 0) >= in_min
                and all_of("moderate_dependence", "moderate_mobility", "moderate_cognitive_decline")
            )

        if rule_name == "close_to_assisted_living_with_moderate_needs":
            return (
                s.get("assisted_living_score", 0) >= max(al_min - 1, 0)
                and s.get("in_home_score", 0) >= in_min
                and all_of("moderate_dependence", "moderate_cognitive_decline")
            )

        if rule_name == "balanced_recommendation":
            return (
                s.get("assisted_living_score", 0) >= al_min
                and s.get("in_home_score", 0) >= in_min
                and none_of("high_dependence", "high_mobility_dependence", "no_support",
                            "high_safety_concern", "severe_cognitive_risk")
            )

        if rule_name == "in_home_with_mobility_challenges":
            return (
                s.get("assisted_living_score", 0) >= max(al_min - 1, 0)
                and s.get("in_home_score", 0) >= in_min
                and "high_mobility_dependence" in f
                and none_of("moderate_cognitive_decline", "severe_cognitive_risk")
            )

        if rule_name == "in_home_possible_with_cognitive_and_safety_risks":
            return (
                s.get("in_home_score", 0) >= in_min
                and s.get("assisted_living_score", 0) >= in_min
                and any_of("moderate_cognitive_decline", "severe_cognitive_risk",
                           "moderate_safety_concern", "high_safety_concern")
            )

        if rule_name == "in_home_with_support_and_financial_needs":
            return (
                s.get("in_home_score", 0) >= in_min
                and s.get("assisted_living_score", 0) < al_min
                and "needs_financial_assistance" in f
            )

        if rule_name == "in_home_with_uncertain_support":
            return any_of(
                "limited_support", "moderate_risk", "high_risk", "mental_health_concern",
                "moderate_dependence", "moderate_mobility", "moderate_safety_concern",
                "low_access", "very_low_access"
            )

        if rule_name == "independent_with_safety_concern":
            return (
                none_of("moderate_cognitive_decline", "severe_cognitive_risk",
                        "high_dependence", "high_mobility_dependence")
                and any_of("moderate_safety_concern", "high_safety_concern")
            )

        if rule_name == "independent_no_support_risk":
            return (
                none_of("moderate_cognitive_decline", "severe_cognitive_risk", "high_mobility_dependence")
                and "no_support" in f
            )

        if rule_name == "no_care_needed":
            return (
                s.get("assisted_living_score", 0) < in_min
                and s.get("in_home_score", 0) < in_min
                and none_of(
                    "high_dependence", "high_mobility_dependence", "no_support",
                    "severe_cognitive_risk", "high_safety_concern",
                    "moderate_cognitive_decline", "moderate_safety_concern", "high_risk"
                )
            )

        # If we don't have a named handler, allow it so the JSON can still supply outcome/message
        return True

    def _infer_outcome(self, rule_name: str, meta: Dict[str, Any]) -> str:
        outcome = meta.get("outcome")
        if isinstance(outcome, str) and outcome:
            return outcome
        r = rule_name.lower()
        if "memory" in r:
            return "memory_care"
        if "assisted" in r or r.startswith("al_"):
            return "assisted_living"
        if "no_care" in r or "none" in r or "independent" in r:
            return "none"
        return "in_home"

    def _weight_for(self, rule_name: str, outcome: str) -> int:
        if rule_name in self.rank_weights:
            return self.rank_weights[rule_name]
        # Infer sensible default by outcome
        if outcome == "memory_care":
            return 100
        if outcome == "assisted_living":
            return 70
        if outcome == "in_home":
            return 30
        return 10

    # --------------------------- Narrative ---------------------------

    def _render_narrative(self, rule_name: str, flags: Set[str], scores: Dict[str, int], name: str) -> str:
        meta = self.rules.get(rule_name, {})
        template = meta.get("message_template", "")

        # Build {key_issues} from issue phrases
        phrases: List[str] = []
        issue_catalog: Dict[str, List[str]] = self.rec.get("issue_phrases", {})
        for flg in flags:
            opts = issue_catalog.get(flg)
            if opts:
                phrases.append(random.choice(opts))
        key_issues = ", ".join(phrases) if phrases else "your current situation"

        # Build {preference_clause}
        if "strongly_prefers_home" in flags:
            pref_key = "strongly_prefers_home"
        elif "prefers_home" in flags:
            pref_key = "prefers_home"
        elif "open_to_move" in flags:
            pref_key = "open_to_move"
        else:
            pref_key = "default"
        preference_clause = self._rand(self.rec.get("preference_clause_templates", {}).get(pref_key, [""]))

        greeting       = self._rand(self.rec.get("greeting_templates", ["Hello"]))
        positive_state = self._rand(self.rec.get("positive_state_templates", ["doing well"]))
        encouragement  = self._rand(self.rec.get("encouragement_templates", ["We’re here for you."]))

        ctx = dict(
            name=name,
            key_issues=key_issues,
            preference_clause=preference_clause,
            greeting=greeting,
            positive_state=positive_state,
            encouragement=encouragement,
            home_preference=(
                "prefer to stay home"
                if ("prefers_home" in flags or "strongly_prefers_home" in flags)
                else "are open to moving"
            ),
            recommendation=self._infer_outcome(rule_name, meta).replace("_", " ").title(),
        )
        return self._format(template, ctx)

    def _rand(self, seq: List[str]) -> str:
        if not seq:
            return ""
        return random.choice(seq)

    def _format(self, template: str, ctx: Dict[str, Any]) -> str:
        try:
            return template.format(**{k: ("" if v is None else v) for k, v in ctx.items()})
        except Exception:
            return template


# --------------------------- Cost Engine (unchanged) ---------------------------

class CalculatorEngine:
    """Very light placeholder — your pricing model can live elsewhere."""
    def __init__(self, *args, **kwargs):
        pass

    def monthly_cost(self, inputs: Any) -> int:
        care_type = getattr(inputs, "care_type", "in_home")
        base = {"in_home": 4000, "assisted_living": 6500, "memory_care": 8500, "none": 0}
        return int(base.get(care_type, 4000))