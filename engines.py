# engines.py — Production build: robust JSON-driven recommendations + narratives
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple


# --------------------------- Data types ---------------------------

@dataclass
class PlannerResult:
    """Normalized output that app.py expects."""
    care_type: str                    # "in_home" | "assisted_living" | "memory_care" | "none"
    flags: List[str]
    scores: Dict[str, int]
    reasons: List[str]                # debug trace of what fired
    narrative: str
    raw_rule: Optional[str] = None    # which rule produced the recommendation


# --------------------------- Helper utils ---------------------------

def _num_from_threshold(v: Any, default: int) -> int:
    """
    Accept numbers or strings like '>= 6', '6', 'at least 6', etc.
    """
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        m = re.search(r"(\d+)", v)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return default


def _first_nonempty(*vals: Optional[str]) -> str:
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v
    return ""


def resolve_narrative(rec_like: Any) -> str:
    """
    Small compatibility helper: given a PlannerResult-like object or dict,
    extract the best-available narrative. Safe to import from app.py.
    """
    if hasattr(rec_like, "narrative"):
        return getattr(rec_like, "narrative") or ""
    if isinstance(rec_like, dict):
        return _first_nonempty(
            rec_like.get("advisory"),
            rec_like.get("message"),
            rec_like.get("message_rendered"),
            rec_like.get("narrative"),
        )
    return ""


# --------------------------- Planner Engine ---------------------------

class PlannerEngine:
    """
    Reads Q&A JSON and Recommendation JSON (file paths provided to __init__)
    and converts answers {'q1': int, 'q2': int, ...} into a PlannerResult.
    """
    def __init__(self, qa_path: str, rec_path: str):
        with open(qa_path, "r", encoding="utf-8") as f:
            self.qa = json.load(f)
        with open(rec_path, "r", encoding="utf-8") as f:
            self.rec = json.load(f)

        # Rules & precedence
        self.rules: Dict[str, Dict[str, Any]] = self.rec.get("final_recommendation", {})
        self.precedence: List[str] = self.rec.get("decision_precedence", [])
        if not self.precedence:
            # Safe default order (first match wins). These names align with your JSON.
            self.precedence = [
                "memory_care_override",
                "dependence_flag_logic",
                "assisted_living_score",
                "balanced_al",
                "in_home_with_mobility_challenges",
                "in_home_possible_with_cognitive_and_safety_risks",
                "in_home_with_support_and_financial_needs",
                "independent_with_safety_concern",
                "independent_no_support_risk",
                "no_care_needed",
                "in_home_with_support_fallback",  # last resort
            ]

        # Thresholds (support numeric or textual)
        th = self.rec.get("final_decision_thresholds", {})
        self.in_home_min = _num_from_threshold(th.get("in_home_min"), 3)
        self.al_min      = _num_from_threshold(th.get("assisted_living_min"), 6)
        self.dep_min     = _num_from_threshold(th.get("dependence_flags_min"), 2)

        # Dependence flags list can live under the rule body
        dep_rule = self.rules.get("dependence_flag_logic", {})
        self.dep_count_flags: List[str] = dep_rule.get("trigger_if_flags", [
            "high_dependence",
            "high_mobility_dependence",
            "no_support",
            "severe_cognitive_risk",
            "high_safety_concern",
        ])

        # Mapping & scoring
        self.flag_to_cat: Dict[str, str] = self.rec.get("flag_to_category_mapping", {})
        self.scoring = self.rec.get("scoring", {
            "in_home": {},
            "assisted_living": {},
        })

        # Narrative pieces
        self.issue_phrases: Dict[str, List[str]] = self.rec.get("issue_phrases", {})
        self.pref_templates: Dict[str, List[str]] = self.rec.get("preference_clause_templates", {})
        self.greeting_templates: List[str] = self.rec.get("greeting_templates", ["Hello"])
        self.positive_templates: List[str] = self.rec.get("positive_state_templates", ["doing well"])
        self.encourage_templates: List[str] = self.rec.get("encouragement_templates", ["We’re here for you."])

    # -------- public API --------
    def run(self, answers: Dict[str, int], *, name: str = "You") -> PlannerResult:
        """
        Answers are 1-based keys: {'q1': 2, 'q2': 1, ...}
        """
        flags, scores, debug = self._evaluate(answers)
        rule_name, outcome = self._decide(flags, scores)
        narrative = self._render(rule_name, flags, scores, name)
        return PlannerResult(
            care_type=outcome,
            flags=sorted(flags),
            scores=scores,
            reasons=debug,
            narrative=narrative,
            raw_rule=rule_name,
        )

    # -------- internals --------
    def _evaluate(self, answers: Dict[str, int]) -> Tuple[Set[str], Dict[str, int], List[str]]:
        """
        Turn raw answers into flags + scores using JSON triggers + flag_to_category_mapping.
        """
        flags: Set[str] = set()
        debug: List[str] = []

        # IMPORTANT: questions in your UI are saved q1..qN (1-based)
        for idx, q in enumerate(self.qa.get("questions", []), start=1):
            qk = f"q{idx}"
            a = answers.get(qk)
            if a is None:
                continue

            triggers = q.get("trigger", {})
            # triggers is a dict of categories -> list of {'answer': int, 'flag': 'name'}
            for _cat, tlist in triggers.items():
                if not isinstance(tlist, list):
                    continue
                for t in tlist:
                    try:
                        if "answer" in t and int(t["answer"]) == int(a):
                            fl = t.get("flag")
                            if fl:
                                flags.add(fl)
                                debug.append(f"{qk}={a} → flag {fl}")
                    except Exception:
                        # ignore malformed trigger rows quietly but keep going
                        continue

        # Map flags to categories (set semantics, avoid double count)
        triggered_categories: Set[str] = set()
        for fl in flags:
            cat = self.flag_to_cat.get(fl)
            if cat:
                triggered_categories.add(cat)

        if triggered_categories:
            debug.append(f"categories: {sorted(triggered_categories)}")

        # Sum category weights
        in_home_score = sum(int(self.scoring.get("in_home", {}).get(c, 0)) for c in triggered_categories)
        al_score      = sum(int(self.scoring.get("assisted_living", {}).get(c, 0)) for c in triggered_categories)

        scores = {
            "in_home_score": in_home_score,
            "assisted_living_score": al_score,
        }
        debug.append(f"scores: in_home={in_home_score} al={al_score}")
        return flags, scores, debug

    def _decide(self, flags: Set[str], scores: Dict[str, int]) -> Tuple[str, str]:
        """
        Walk precedence and pick the first matching rule; infer outcome when omitted.
        """
        f = flags
        s = scores

        # Strict memory-care override: require severe cognitive + (no support OR high safety OR high dependence)
        if ("severe_cognitive_risk" in f) and (
            "no_support" in f or "high_safety_concern" in f or "high_dependence" in f
        ):
            return "memory_care_override", "memory_care"

        # Walk precedence
        for rule in self.precedence:
            meta = self.rules.get(rule)
            if not meta:
                continue
            if self._match(rule, meta, f, s):
                outcome = meta.get("outcome")
                if not outcome:
                    r = rule.lower()
                    if "memory" in r:
                        outcome = "memory_care"
                    elif "assisted" in r or "al_" in r:
                        outcome = "assisted_living"
                    elif "no_care" in r or "independent" in r or "none" in r:
                        outcome = "none"
                    else:
                        outcome = "in_home"
                return rule, outcome

        # Final fallback: gentle in-home
        if "in_home_with_support_fallback" in self.rules:
            return "in_home_with_support_fallback", "in_home"
        return "no_care_needed", "none"

    def _match(self, rule_name: str, meta: Dict[str, Any],
               flags: Set[str], scores: Dict[str, int]) -> bool:
        """
        Custom handlers for known rule names. Unknown rules return False
        (so they don't accidentally match just because they exist).
        """
        f = flags
        s = scores
        in_min = self.in_home_min
        al_min = self.al_min
        dep_min = self.dep_min

        def any_of(*need: str) -> bool: return any(n in f for n in need)
        def all_of(*need: str) -> bool: return all(n in f for n in need)
        def none_of(*ban: str) -> bool: return all(n not in f for n in ban)

        # ---- explicit handlers (names from your JSON) ----
        if rule_name == "memory_care_override":
            # already handled early; keep here for completeness
            return ("severe_cognitive_risk" in f) and (
                "no_support" in f or "high_safety_concern" in f or "high_dependence" in f
            )

        if rule_name in ("assisted_living_score", "assisted_living"):
            return s.get("assisted_living_score", 0) >= al_min

        if rule_name == "dependence_flag_logic":
            count = sum(1 for fl in self.dep_count_flags if fl in f)
            return count >= dep_min

        if rule_name == "balanced_al":
            return (s.get("assisted_living_score", 0) >= al_min and
                    s.get("in_home_score", 0) >= in_min and
                    none_of("high_dependence", "high_mobility_dependence", "no_support",
                            "high_safety_concern", "severe_cognitive_risk"))

        if rule_name == "in_home_with_mobility_challenges":
            return (s.get("assisted_living_score", 0) >= (al_min - 1) and
                    s.get("in_home_score", 0) >= in_min and
                    "high_mobility_dependence" in f and
                    none_of("moderate_cognitive_decline", "severe_cognitive_risk"))

        if rule_name == "in_home_possible_with_cognitive_and_safety_risks":
            return (s.get("in_home_score", 0) >= in_min and
                    s.get("assisted_living_score", 0) >= in_min and
                    any_of("moderate_cognitive_decline", "severe_cognitive_risk",
                           "moderate_safety_concern", "high_safety_concern"))

        if rule_name == "in_home_with_support_and_financial_needs":
            return (s.get("in_home_score", 0) >= in_min and
                    s.get("assisted_living_score", 0) < al_min and
                    "needs_financial_assistance" in f)

        if rule_name == "independent_with_safety_concern":
            return (none_of("moderate_cognitive_decline", "severe_cognitive_risk",
                            "high_dependence", "high_mobility_dependence") and
                    any_of("moderate_safety_concern", "high_safety_concern"))

        if rule_name == "independent_no_support_risk":
            return (none_of("moderate_cognitive_decline", "severe_cognitive_risk", "high_mobility_dependence") and
                    "no_support" in f)

        if rule_name == "no_care_needed":
            return (s.get("assisted_living_score", 0) < in_min and
                    s.get("in_home_score", 0) < in_min and
                    none_of("high_dependence", "high_mobility_dependence", "no_support",
                            "severe_cognitive_risk", "high_safety_concern",
                            "moderate_cognitive_decline", "moderate_safety_concern", "high_risk"))

        # Unknown rule names MUST NOT match implicitly
        return False

    # ---------------- Narrative rendering ----------------

    def _rand(self, seq: List[str]) -> str:
        if not seq:
            return ""
        return random.choice(seq)

    def _render_message(self, template: str, ctx: Dict[str, Any]) -> str:
        safe = {k: ("" if v is None else v) for k, v in ctx.items()}
        try:
            return template.format(**safe)
        except Exception:
            return template

    def _render(self, rule_name: str, flags: Set[str], scores: Dict[str, int], name: str) -> str:
        meta = self.rules.get(rule_name, {})
        template = meta.get("message_template", "")

        # Build {key_issues}
        phrases: List[str] = []
        issue_catalog: Dict[str, List[str]] = self.issue_phrases
        for flg in flags:
            plist = issue_catalog.get(flg)
            if plist:
                phrases.append(self._rand(plist))
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
        preference_clause = self._rand(self.pref_templates.get(pref_key, [""]))

        greeting       = self._rand(self.greeting_templates)
        positive_state = self._rand(self.positive_templates)
        encouragement  = self._rand(self.encourage_templates)

        ctx = dict(
            name=name,
            key_issues=key_issues,
            preference_clause=preference_clause,
            greeting=greeting,
            positive_state=positive_state,
            encouragement=encouragement,
            home_preference=(
                "prefer to stay home" if ("prefers_home" in flags or "strongly_prefers_home" in flags)
                else "are open to moving"
            ),
            recommendation=(meta.get("outcome") or "").replace("_", " ").title(),
        )
        return self._render_message(template, ctx)


# --------------------------- Calculator Engine (unchanged stub) ---------------------------

class CalculatorEngine:
    """
    Very light placeholder. Your real pricing model can live elsewhere.
    """
    def __init__(self, *args, **kwargs):
        pass

    def monthly_cost(self, inputs: Any) -> int:
        care_type = getattr(inputs, "care_type", "in_home")
        base = {"in_home": 4000, "assisted_living": 6500, "memory_care": 8500, "none": 0}
        return int(base.get(care_type, 4000))