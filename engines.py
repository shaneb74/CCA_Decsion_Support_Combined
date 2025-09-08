# engines.py — Planner & Cost engines (self-contained, JSON-driven, evidence-ranked)
from __future__ import annotations

import json, re, random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple
from pathlib import Path

# ---------------- Planner result ----------------
@dataclass
class PlannerResult:
    """Stable, pickle-safe result object."""
    care_type: str                    # "in_home" | "assisted_living" | "memory_care" | "none"
    flags: List[str]
    scores: Dict[str, int]
    reasons: List[str]
    narrative: str
    raw_rule: Optional[str] = None

# ---------------- Planner engine ----------------
class PlannerEngine:
    """
    Reads Q&A JSON and Recommendation JSON and converts answers {"q1": 1, ...}
    into a PlannerResult **strictly using the JSON rules**, then ranks outcomes
    by evidence (priority order) rather than first-match wins.
    """
    def __init__(self, qa_path: str, rec_path: str):
        with open(qa_path, "r", encoding="utf-8") as f:
            self.qa = json.load(f)
        with open(rec_path, "r", encoding="utf-8") as f:
            self.rec = json.load(f)

        self.rules: Dict[str, Dict[str, Any]] = self.rec.get("final_recommendation", {})
        self.precedence: List[str] = self.rec.get("decision_precedence", list(self.rules.keys()))

        # thresholds (accept ints or strings like ">= 6")
        self.in_home_min = self._num(self.rec.get("final_decision_thresholds", {}).get("in_home_min"), 3)
        self.al_min      = self._num(self.rec.get("final_decision_thresholds", {}).get("assisted_living_min"), 6)
        self.dep_min     = self._num(self.rec.get("final_decision_thresholds", {}).get("dependence_flags_min"), 2)

        # scoring weights
        self.sc_in = self.rec.get("scoring", {}).get("in_home", {})
        self.sc_al = self.rec.get("scoring", {}).get("assisted_living", {})

        # flag → category map (for scoring)
        self.flag2cat: Dict[str, str] = self.rec.get("flag_to_category_mapping", {})

        # rank contributions (higher is more decisive)
        self.rank_weights = {
            "memory_care_override": 100,
            "dependence_flag_logic": 80,
            "assisted_living_score": 70,
            "balanced_al": 60,
            "in_home_possible_with_cognitive_and_safety_risks": 50,
            "in_home_with_mobility_challenges": 40,
            "in_home_with_support_and_financial_needs": 30,
            "independent_with_safety_concern": 20,
            "independent_no_support_risk": 15,
            "no_care_needed": 10,
            "in_home_with_support_fallback": 1,
        }

    @staticmethod
    def _num(v, default):
        if isinstance(v, (int, float)): return int(v)
        if isinstance(v, str):
            m = re.search(r"(\d+)", v)
            if m: return int(m.group(1))
        return default

    def run(self, answers: Dict[str, int], *, name: str = "You") -> PlannerResult:
        flags, scores, debug = self._evaluate(answers)
        rule_name, outcome = self._decide_best(flags, scores)
        narrative = self._render(rule_name, flags, scores, name)
        return PlannerResult(
            care_type=outcome,
            flags=sorted(flags),
            scores=scores,
            reasons=debug,
            narrative=narrative,
            raw_rule=rule_name,
        )

    # ---- evaluate answers to flags + scores ----
    def _evaluate(self, answers: Dict[str, int]) -> Tuple[Set[str], Dict[str, int], List[str]]:
        flags: Set[str] = set()
        debug: List[str] = []

        # questions in JSON are iterated 1..N to match UI "q1..qN" keys
        for idx, q in enumerate(self.qa.get("questions", []), start=1):
            qk = f"q{idx}"
            a = answers.get(qk)
            if a is None:
                continue
            for _cat, tlist in q.get("trigger", {}).items():
                for t in tlist:
                    if "answer" in t and int(t["answer"]) == int(a):
                        fl = t.get("flag")
                        if fl:
                            flags.add(fl)
                            debug.append(f"{qk}={a} → flag {fl}")

        # score categories for any triggered flags
        cats = {self.flag2cat[fl] for fl in flags if fl in self.flag2cat}
        in_score = sum(self.sc_in.get(c, 0) for c in cats)
        al_score = sum(self.sc_al.get(c, 0) for c in cats)
        scores = {"in_home_score": in_score, "assisted_living_score": al_score}
        debug.append(f"scores: in_home={in_score} al={al_score}")
        return flags, scores, debug

    # ---- evidence-ranked decision (not first-match) ----
    def _decide_best(self, flags: Set[str], scores: Dict[str, int]) -> Tuple[str, str]:
        # Evaluate all rules, collect candidates with weights, then pick the best
        candidates: List[Tuple[int, str, str]] = []  # (weight, rule_name, outcome)

        # memory care fast-path
        if "severe_cognitive_risk" in flags and any(fl in flags for fl in ["no_support", "high_safety_concern"]):
            candidates.append((self.rank_weights.get("memory_care_override", 100), "memory_care_override", "memory_care"))

        for rule in self.precedence:
            meta = self.rules.get(rule) or {}
            if self._match(rule, meta, flags, scores):
                outcome = meta.get("outcome")
                if not outcome:
                    r = rule.lower()
                    if "memory" in r: outcome = "memory_care"
                    elif "assisted" in r or "al_" in r: outcome = "assisted_living"
                    elif "no_care" in r or "independent" in r or "none" in r: outcome = "none"
                    else: outcome = "in_home"
                weight = self.rank_weights.get(rule, 5)
                candidates.append((weight, rule, outcome))

        if not candidates:
            # final fallback
            return "no_care_needed", "none"

        # choose highest weight; if tie, prefer higher care level as safety net
        def outcome_rank(o: str) -> int:
            return {"memory_care": 3, "assisted_living": 2, "in_home": 1, "none": 0}.get(o, 0)

        candidates.sort(key=lambda x: (x[0], outcome_rank(x[2])), reverse=True)
        top = candidates[0]
        return top[1], top[2]

    # ---- per-rule matchers aligning with JSON names ----
    def _match(self, rule_name: str, meta: Dict[str, Any], flags: Set[str], scores: Dict[str, int]) -> bool:
        f = flags; s = scores
        in_min = self.in_home_min; al_min = self.al_min; dep_min = self.dep_min

        def any_of(*need: str) -> bool: return any(n in f for n in need)
        def all_of(*need: str) -> bool: return all(n in f for n in need)
        def none_of(*ban: str) -> bool: return all(n not in f for n in ban)

        if rule_name == "dependence_flag_logic":
            to_count = self.rec.get("dependence_flag_logic", {}).get(
                "trigger_if_flags",
                ["high_dependence", "high_mobility_dependence", "no_support",
                 "severe_cognitive_risk", "high_safety_concern"],
            )
            count = sum(1 for fl in to_count if fl in f)
            return count >= dep_min

        if rule_name == "assisted_living_score":
            return s["assisted_living_score"] >= al_min

        if rule_name == "balanced_al":
            return (s["assisted_living_score"] >= al_min and s["in_home_score"] >= in_min and
                    none_of("high_dependence", "high_mobility_dependence", "no_support", "high_safety_concern", "severe_cognitive_risk"))

        if rule_name == "in_home_with_mobility_challenges":
            return (s["assisted_living_score"] >= al_min - 1 and s["in_home_score"] >= in_min and
                    "high_mobility_dependence" in f and
                    none_of("moderate_cognitive_decline", "severe_cognitive_risk"))

        if rule_name == "in_home_possible_with_cognitive_and_safety_risks":
            return (s["in_home_score"] >= in_min and s["assisted_living_score"] >= in_min and
                    any_of("moderate_cognitive_decline", "severe_cognitive_risk", "moderate_safety_concern", "high_safety_concern"))

        if rule_name == "in_home_with_support_and_financial_needs":
            return (s["in_home_score"] >= in_min and s["assisted_living_score"] < al_min and "needs_financial_assistance" in f)

        if rule_name == "independent_with_safety_concern":
            return (none_of("moderate_cognitive_decline", "severe_cognitive_risk", "high_dependence", "high_mobility_dependence") and
                    any_of("moderate_safety_concern", "high_safety_concern"))

        if rule_name == "independent_no_support_risk":
            return (none_of("moderate_cognitive_decline", "severe_cognitive_risk", "high_mobility_dependence") and "no_support" in f)

        if rule_name == "no_care_needed":
            return (s["assisted_living_score"] < in_min and s["in_home_score"] < in_min and
                    none_of("high_dependence", "high_mobility_dependence", "no_support", "severe_cognitive_risk",
                            "high_safety_concern", "moderate_cognitive_decline", "moderate_safety_concern", "high_risk"))

        # If we don't have a custom matcher, allow it so narrative/outcome still render
        return True

    # ---- narrative rendering ----
    def _rand(self, seq: List[str]) -> str:
        return random.choice(seq) if seq else ""

    def _render_message(self, template: str, ctx: Dict[str, Any]) -> str:
        try:
            return template.format(**{k: ("" if v is None else v) for k, v in ctx.items()})
        except Exception:
            return template

    def _render(self, rule_name: str, flags: Set[str], scores: Dict[str, int], name: str) -> str:
        meta = self.rules.get(rule_name, {})
        template = meta.get("message_template", "")

        # key issues
        phrases: List[str] = []
        for flg in flags:
            variants = self.rec.get("issue_phrases", {}).get(flg, [])
            if variants:
                phrases.append(random.choice(variants))
        key_issues = ", ".join(phrases) if phrases else "your current situation"

        # preference clause
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
            home_preference=("prefer to stay home" if ("prefers_home" in flags or "strongly_prefers_home" in flags) else "are open to moving"),
            recommendation=(meta.get("outcome", "in-home care").replace("_", " ").title()),
        )
        return self._render_message(template, ctx)

# ---------------- Calculator engine ----------------
class CalculatorEngine:
    """
    Thin shim; real cost calculation and UI live in cost_controls.py and asset_engine.py.
    This provides a stable method signature for app.py.
    """
    def __init__(self, *args, **kwargs):
        pass

    def monthly_cost(self, inputs: Any) -> int:
        # Fallback only — real per-scenario math comes from cost_controls/asset_engine.
        care_type = getattr(inputs, "care_type", "in_home")
        base = {"in_home": 4000, "assisted_living": 6500, "memory_care": 8500, "none": 0}
        return int(base.get(care_type, 4000))