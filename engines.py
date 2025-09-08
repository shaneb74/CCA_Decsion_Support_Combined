# engines.py — Planner & Cost engines (self-contained, JSON-driven)
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ----------------------------- Data models -----------------------------

@dataclass
class PlannerResult:
    """Stable, pickle-safe result object returned by PlannerEngine.run()."""
    care_type: str                         # "none" | "in_home" | "assisted_living" | "memory_care"
    flags: List[str]                       # triggered flag ids
    scores: Dict[str, int]                 # {"in_home_score": int, "assisted_living_score": int}
    reasons: List[str]                     # human-readable trace of how we got here
    narrative: str                         # rendered contextual blurb
    raw_rule: Optional[str] = None         # which JSON rule matched (from decision_precedence)


# ----------------------------- Planner Engine -----------------------------

class PlannerEngine:
    """
    Loads your Q&A JSON and Recommendation JSON, evaluates answers -> flags,
    maps flags to scoring categories, then walks JSON decision_precedence to
    produce a care recommendation and narrative.
    """

    # --- construction ---

    def __init__(self, qa_path: str | Path, rec_path: str | Path):
        with open(qa_path, "r", encoding="utf-8") as f:
            self.qa = json.load(f)
        with open(rec_path, "r", encoding="utf-8") as f:
            self.rec = json.load(f)

        # Rules (unordered dict) + precedence (ordered list of rule names)
        self.rules: Dict[str, Dict[str, Any]] = self.rec.get("final_recommendation", {})
        self.precedence: List[str] = self.rec.get(
            "decision_precedence",
            list(self.rules.keys())
        )

        # Thresholds (support ints or strings like ">= 6")
        th = self.rec.get("final_decision_thresholds", {})
        self.in_min = self._num(th.get("in_home_min"), 3)
        self.al_min = self._num(th.get("assisted_living_min"), 6)
        self.dep_min = self._num(th.get("dependence_flags_min"), 2)

        # Dependence flags list if present
        self.dep_flags: List[str] = (
            self.rec.get("dependence_flag_logic", {}).get(
                "trigger_if_flags",
                ["high_dependence", "high_mobility_dependence", "no_support",
                 "severe_cognitive_risk", "high_safety_concern"]
            )
        )

        # Map flags -> scoring categories
        self.flag_to_cat: Dict[str, str] = self.rec.get("flag_to_category_mapping", {})

        # Scoring tables
        self.score_in_home: Dict[str, int] = self.rec.get("scoring", {}).get("in_home", {})
        self.score_al: Dict[str, int] = self.rec.get("scoring", {}).get("assisted_living", {})

    @staticmethod
    def _num(v: Any, default: int) -> int:
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str):
            m = re.search(r"(\d+)", v)
            if m:
                return int(m.group(1))
        return default

    # --- public API ---

    def run(self, answers: Dict[str, int], *, name: str = "You") -> PlannerResult:
        """
        Answers are 1-based keys saved by the UI: {"q1": 2, "q2": 1, ...}.
        """
        flags, scores, trace = self._evaluate(answers)
        rule, outcome = self._decide(flags, scores)
        narrative = self._render(rule, outcome, flags, scores, name)

        return PlannerResult(
            care_type=outcome,
            flags=sorted(flags),
            scores=scores,
            reasons=trace,
            narrative=narrative,
            raw_rule=rule,
        )

    # --- evaluation: answers -> flags -> scores ---

    def _evaluate(self, answers: Dict[str, int]) -> Tuple[Set[str], Dict[str, int], List[str]]:
        flags: Set[str] = set()
        trace: List[str] = []

        # Walk questions in 1-based order to match UI
        for idx, q in enumerate(self.qa.get("questions", []), start=1):
            qk = f"q{idx}"
            a = answers.get(qk)
            if a is None:
                continue

            # Triggers can be grouped by category, but we accept any level
            triggers = q.get("trigger", {})
            for _cat, tlist in triggers.items():
                for t in tlist:
                    try:
                        want = int(t.get("answer"))
                    except Exception:
                        continue
                    if want == int(a):
                        fl = t.get("flag")
                        if fl:
                            flags.add(fl)
                            trace.append(f"{qk}={a} → flag {fl}")

        # Map flags -> scoring categories
        cats: Set[str] = set()
        for fl in flags:
            cat = self.flag_to_cat.get(fl)
            if cat:
                cats.add(cat)
        if cats:
            trace.append(f"categories: {sorted(cats)}")

        # Sum scores per category
        in_score = sum(self.score_in_home.get(c, 0) for c in cats)
        al_score = sum(self.score_al.get(c, 0) for c in cats)
        scores = {"in_home_score": in_score, "assisted_living_score": al_score}
        trace.append(f"scores: in_home={in_score} al={al_score}")

        return flags, scores, trace

    # --- decision: obey JSON precedence strictly ---

    def _decide(self, flags: Set[str], scores: Dict[str, int]) -> Tuple[str, str]:
        """
        Walk decision_precedence and pick the *first* rule whose criteria match.
        IMPORTANT: Unknown rules DO NOT match anymore (no silent True).
        """
        # Quick hard override for severe memory + no support/high safety concern
        if "severe_cognitive_risk" in flags and (
            "no_support" in flags or "high_safety_concern" in flags
        ):
            return "memory_care_override", "memory_care"

        for rule in self.precedence:
            meta = self.rules.get(rule)
            if not meta:
                # Unknown name in precedence; skip
                continue
            if self._match_rule(rule, meta, flags, scores):
                # Outcome may be omitted in JSON; infer from rule name if necessary
                outcome = meta.get("outcome")
                if not outcome:
                    outcome = self._infer_outcome_from_name(rule, default="in_home")
                return rule, outcome

        # If nothing matched, use the JSON fallback if present
        if "in_home_with_support_fallback" in self.rules:
            return "in_home_with_support_fallback", "in_home"
        # absolute fallback
        return "no_care_needed", "none"

    def _match_rule(self, rule: str, meta: Dict[str, Any], flags: Set[str], scores: Dict[str, int]) -> bool:
        """Return True iff this rule's criteria match. Unknown rules -> False."""
        f = flags
        s = scores
        in_min, al_min, dep_min = self.in_min, self.al_min, self.dep_min

        def any_of(*need: str) -> bool: return any(n in f for n in need)
        def all_of(*need: str) -> bool: return all(n in f for n in need)
        def none_of(*ban: str) -> bool: return all(n not in f for n in ban)

        # Handle the rule names we know from your JSON
        if rule == "memory_care_override":
            return ("severe_cognitive_risk" in f) and any_of("no_support", "high_safety_concern")

        if rule == "dependence_flag_logic":
            count = sum(1 for fl in self.dep_flags if fl in f)
            return count >= dep_min

        if rule == "assisted_living_score":
            return s["assisted_living_score"] >= al_min

        if rule == "balanced_al":
            return (s["assisted_living_score"] >= al_min and
                    s["in_home_score"] >= in_min and
                    none_of("high_dependence", "high_mobility_dependence", "no_support",
                            "high_safety_concern", "severe_cognitive_risk"))

        if rule == "in_home_with_mobility_challenges":
            return (s["assisted_living_score"] >= al_min - 1 and
                    s["in_home_score"] >= in_min and
                    ("high_mobility_dependence" in f) and
                    none_of("moderate_cognitive_decline", "severe_cognitive_risk"))

        if rule == "in_home_possible_with_cognitive_and_safety_risks":
            return (s["in_home_score"] >= in_min and
                    s["assisted_living_score"] >= in_min and
                    any_of("moderate_cognitive_decline", "severe_cognitive_risk",
                           "moderate_safety_concern", "high_safety_concern"))

        if rule == "in_home_with_support_and_financial_needs":
            return (s["in_home_score"] >= in_min and
                    s["assisted_living_score"] < al_min and
                    "needs_financial_assistance" in f)

        if rule == "independent_with_safety_concern":
            return (none_of("moderate_cognitive_decline", "severe_cognitive_risk",
                            "high_dependence", "high_mobility_dependence") and
                    any_of("moderate_safety_concern", "high_safety_concern"))

        if rule == "independent_no_support_risk":
            return (none_of("moderate_cognitive_decline", "severe_cognitive_risk",
                            "high_mobility_dependence") and
                    ("no_support" in f))

        if rule == "no_care_needed":
            return (s["assisted_living_score"] < in_min and
                    s["in_home_score"] < in_min and
                    none_of("high_dependence", "high_mobility_dependence", "no_support",
                            "severe_cognitive_risk", "high_safety_concern",
                            "moderate_cognitive_decline", "moderate_safety_concern", "high_risk"))

        # Heuristic support for additional/renamed rules **without** becoming permissive:
        r = rule.lower()
        if "assisted" in r:
            # Any AL-typed rule must at least clear AL threshold.
            return s["assisted_living_score"] >= al_min
        if "in_home" in r and "fallback" not in r:
            # Any in-home typed rule must at least clear in-home threshold.
            return s["in_home_score"] >= in_min
        if "memory" in r:
            # Memory-typed rules require severe risk (keeps us conservative).
            return ("severe_cognitive_risk" in f)

        # Unknown rule → DO NOT MATCH (prevents accidental early capture)
        return False

    @staticmethod
    def _infer_outcome_from_name(rule: str, default: str = "in_home") -> str:
        r = rule.lower()
        if "memory" in r: return "memory_care"
        if "assisted" in r or "al_" in r: return "assisted_living"
        if "no_care" in r or "none" in r: return "none"
        if "in_home" in r: return "in_home"
        return default

    # --- narrative rendering ---

    def _render(self, rule: str, outcome: str, flags: Set[str], scores: Dict[str, int], name: str) -> str:
        meta = self.rules.get(rule, {})
        template = meta.get("message_template", "")

        # Build {key_issues} from issue_phrases
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
            home_preference=("prefer to stay home"
                             if ("prefers_home" in flags or "strongly_prefers_home" in flags)
                             else "are open to moving"),
            recommendation=outcome.replace("_", " ").title(),
        )

        return self._format_template(template, ctx)

    @staticmethod
    def _rand(seq: List[str]) -> str:
        return random.choice(seq) if seq else ""

    @staticmethod
    def _format_template(template: str, ctx: Dict[str, Any]) -> str:
        safe = {k: ("" if v is None else v) for k, v in ctx.items()}
        try:
            return template.format(**safe)
        except Exception:
            # Return raw template if any placeholder mismatch occurs
            return template


# ----------------------------- Calculator Engine -----------------------------

class CalculatorEngine:
    """
    Intentionally simple placeholder. Your real pricing logic can live elsewhere.
    """
    def __init__(self, *args, **kwargs):
        pass

    def monthly_cost(self, inputs: Any) -> int:
        care_type = getattr(inputs, "care_type", "in_home")
        base = {"in_home": 4000, "assisted_living": 6500, "memory_care": 8500, "none": 0}
        return int(base.get(care_type, 4000))