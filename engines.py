# engines.py — Planner + Calculator engines (memory-care strictly gated)
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple


# ----------------------------- Planner types -----------------------------
@dataclass
class PlannerResult:
    care_type: str                    # "none" | "in_home" | "assisted_living" | "memory_care"
    flags: List[str]
    scores: Dict[str, int]
    reasons: List[str]
    narrative: str
    raw_rule: Optional[str] = None


# ----------------------------- PlannerEngine -----------------------------
class PlannerEngine:
    """
    Uses:
      - question_answer_logic_FINAL_UPDATED.json  (Q&A, triggers)
      - recommendation_logic_FINAL_MASTER_UPDATED.json (scoring, rules, narrative)
    Produces a PlannerResult from {"q1": int, ...}.
    """

    def __init__(self, qa_path: str, rec_path: str):
        with open(qa_path, "r", encoding="utf-8") as f:
            self.qa = json.load(f)
        with open(rec_path, "r", encoding="utf-8") as f:
            self.rec = json.load(f)

        self.rules: Dict[str, Dict[str, Any]] = self.rec.get("final_recommendation", {})
        self.precedence: List[str] = self.rec.get("decision_precedence", list(self.rules.keys()))
        self.thresholds = self.rec.get("final_decision_thresholds", {})

        def _num(v, d):
            if isinstance(v, (int, float)):
                return int(v)
            if isinstance(v, str):
                m = re.search(r"(\d+)", v)
                if m:
                    return int(m.group(1))
            return d

        self.in_min = _num(self.thresholds.get("in_home_min"), 3)
        self.al_min = _num(self.thresholds.get("assisted_living_min"), 6)

        dep_cfg = self.rec.get("dependence_flag_logic", {}).get("criteria", "")
        m = re.search(r"(\d+)\s*or more", dep_cfg)
        self.dep_min = int(m.group(1)) if m else _num(self.thresholds.get("dependence_flags_min"), 2)

        # Evidence weights (can be overridden in JSON "rule_weights")
        self.rule_weights = {
            "memory_care_override": 100,
            "assisted_living": 70,
            "moderate_needs_assisted_living_recommendation": 70,
            "close_to_assisted_living_with_moderate_needs": 70,
            "balanced_recommendation": 30,
            "in_home_with_support": 30,
            "in_home_with_uncertain_support": 30,
            "in_home_possible_with_cognitive_and_safety_risks": 30,
            "in_home_with_mobility_challenges": 30,
            "in_home_score": 30,
            "independent_with_safety_concern": 20,
            "independent_no_support_risk": 18,
            "in_home_low_support_financial_needs": 18,
            "no_care_needed": 10,
        }
        self.rule_weights.update(self.rec.get("rule_weights", {}))

    # ---- public API
    def run(self, answers: Dict[str, int], *, name: str = "You") -> PlannerResult:
        flags, scores, debug = self._evaluate(answers)

        # STRICT memory-care override (requires SEVERE + (no support OR high safety))
        if ("severe_cognitive_risk" in flags) and (("no_support" in flags) or ("high_safety_concern" in flags)):
            rule = "memory_care_override"
            narrative = self._render(rule, flags, scores, name)
            return PlannerResult("memory_care", sorted(flags), scores, debug, narrative, raw_rule=rule)

        # Evaluate all rules → candidates
        candidates: List[Tuple[str, str, int]] = []  # (rule, outcome, weight)
        for rule in self.precedence:
            meta = self.rules.get(rule)
            if not meta:
                continue
            if self._match(rule, meta, flags, scores):
                outcome = meta.get("outcome")
                if not outcome:
                    r = rule.lower()
                    if "memory" in r: outcome = "memory_care"
                    elif "assisted" in r or "al_" in r: outcome = "assisted_living"
                    elif "no_care" in r or "none" in r: outcome = "none"
                    else: outcome = "in_home"
                weight = int(self.rule_weights.get(rule, 0))
                candidates.append((rule, outcome, weight))

        # HARD FILTER: no Memory Care unless severe cognitive risk is present.
        if "severe_cognitive_risk" not in flags:
            candidates = [(r, o, w) for (r, o, w) in candidates if o != "memory_care"]

        # Fallbacks if nothing left
        if not candidates:
            if "in_home_with_support_fallback" in self.rules:
                rule = "in_home_with_support_fallback"
                narrative = self._render(rule, flags, scores, name)
                return PlannerResult("in_home", sorted(flags), scores, debug, narrative, raw_rule=rule)
            rule = "no_care_needed"
            narrative = self._render(rule, flags, scores, name)
            return PlannerResult("none", sorted(flags), scores, debug, narrative, raw_rule=rule)

        # Pick highest weight; on ties: Memory > Assisted > In-home (since MC is now gated)
        candidates.sort(key=lambda t: (t[2], 2 if t[1] == "assisted_living" else 1 if t[1] == "in_home" else 0),
                        reverse=True)
        best_rule, best_outcome, _ = candidates[0]
        debug.append("CANDIDATES: " + " | ".join(f"{r}->{o} (w={w})" for r, o, w in candidates))
        debug.append(f"CHOICE: {best_rule} -> {best_outcome}")

        narrative = self._render(best_rule, flags, scores, name)
        return PlannerResult(best_outcome, sorted(flags), scores, debug, narrative, raw_rule=best_rule)

    # ---- internals
    def _evaluate(self, answers: Dict[str, int]) -> Tuple[Set[str], Dict[str, int], List[str]]:
        flags: Set[str] = set()
        debug: List[str] = []

        for idx, q in enumerate(self.qa.get("questions", []), start=1):
            qk = f"q{idx}"
            a = answers.get(qk)
            if a is None:
                continue
            trig = q.get("trigger", {})
            for _cat, tlist in trig.items():
                for t in tlist:
                    if "answer" in t and int(t["answer"]) == int(a):
                        fl = t.get("flag")
                        if fl:
                            flags.add(fl)
                            debug.append(f"{qk}={a} -> flag {fl}")

        # category scoring
        cat_map: Dict[str, str] = self.rec.get("flag_to_category_mapping", {})
        categories = sorted({cat_map[f] for f in flags if f in cat_map})
        if categories:
            debug.append(f"categories: {categories}")

        s_in = sum(self.rec["scoring"]["in_home"].get(c, 0) for c in categories)
        s_al = sum(self.rec["scoring"]["assisted_living"].get(c, 0) for c in categories)
        scores = {"in_home": s_in, "assisted_living": s_al}
        debug.append(f"scores: in_home={s_in} al={s_al}")
        return flags, scores, debug

    def _match(self, rule: str, meta: Dict[str, Any], flags: Set[str], scores: Dict[str, int]) -> bool:
        f, s = flags, scores
        def any_of(*need: str) -> bool: return any(n in f for n in need)
        def all_of(*need: str) -> bool: return all(n in f for n in need)
        def none_of(*ban: str) -> bool: return all(n not in f for n in ban)

        if rule == "dependence_flag_logic":
            to_count = self.rec.get("dependence_flag_logic", {}).get(
                "trigger_if_flags",
                ["high_dependence", "high_mobility_dependence", "no_support", "severe_cognitive_risk", "high_safety_concern"]
            )
            return sum(1 for x in to_count if x in f) >= self.dep_min

        if rule == "assisted_living":
            return s["assisted_living"] >= self.al_min

        if rule == "moderate_needs_assisted_living_recommendation":
            return (s["assisted_living"] >= self.al_min
                    and s["in_home"] >= self.in_min
                    and all_of("moderate_dependence", "moderate_mobility", "moderate_cognitive_decline"))

        if rule == "close_to_assisted_living_with_moderate_needs":
            return (s["assisted_living"] >= max(self.al_min - 1, 0)
                    and s["in_home"] >= self.in_min
                    and all_of("moderate_dependence", "moderate_cognitive_decline"))

        if rule == "balanced_recommendation":
            return (s["assisted_living"] >= self.al_min
                    and s["in_home"] >= self.in_min
                    and none_of("high_dependence", "high_mobility_dependence", "no_support",
                                "high_safety_concern", "severe_cognitive_risk"))

        if rule == "in_home_with_mobility_challenges":
            return (s["assisted_living"] >= max(self.al_min - 1, 0)
                    and s["in_home"] >= self.in_min
                    and "high_mobility_dependence" in f
                    and none_of("moderate_cognitive_decline", "severe_cognitive_risk"))

        if rule == "in_home_possible_with_cognitive_and_safety_risks":
            return (s["in_home"] >= self.in_min
                    and s["assisted_living"] >= self.in_min
                    and any_of("moderate_cognitive_decline", "severe_cognitive_risk",
                               "moderate_safety_concern", "high_safety_concern"))

        if rule == "in_home_with_support_and_financial_needs":
            return (s["in_home"] >= self.in_min
                    and s["assisted_living"] < self.al_min
                    and "needs_financial_assistance" in f)

        if rule == "in_home_low_support_financial_needs":
            return ("needs_financial_assistance" in f
                    and "limited_support" in f
                    and none_of("moderate_safety_concern", "high_safety_concern",
                                "moderate_cognitive_decline", "severe_cognitive_risk",
                                "high_mobility_dependence"))

        if rule == "independent_with_safety_concern":
            return (none_of("moderate_cognitive_decline", "severe_cognitive_risk",
                            "high_dependence", "high_mobility_dependence")
                    and any_of("moderate_safety_concern", "high_safety_concern"))

        if rule == "independent_no_support_risk":
            return (none_of("moderate_cognitive_decline", "severe_cognitive_risk", "high_mobility_dependence")
                    and "no_support" in f)

        if rule == "no_care_needed":
            return (s["assisted_living"] < self.in_min
                    and s["in_home"] < self.in_min
                    and none_of("high_dependence", "high_mobility_dependence", "no_support",
                                "severe_cognitive_risk", "high_safety_concern",
                                "moderate_cognitive_decline", "moderate_safety_concern", "high_risk"))

        # Unrecognized: allow
        return True

    # ---- narrative
    def _rand(self, seq: List[str]) -> str:
        return random.choice(seq) if seq else ""

    def _render_message(self, template: str, ctx: Dict[str, Any]) -> str:
        safe = {k: ("" if v is None else v) for k, v in ctx.items()}
        try:
            return template.format(**safe)
        except Exception:
            return template

    def _render(self, rule: str, flags: Set[str], scores: Dict[str, int], name: str) -> str:
        meta = self.rules.get(rule, {})
        template = meta.get("message_template", "")

        phrases: List[str] = []
        catalog: Dict[str, List[str]] = self.rec.get("issue_phrases", {})
        for flg in flags:
            if flg in catalog and catalog[flg]:
                phrases.append(random.choice(catalog[flg]))
        key_issues = ", ".join(phrases) if phrases else "your current situation"

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
            recommendation=meta.get("outcome", "in-home care").replace("_", " ").title(),
        )
        return self._render_message(template, ctx)


# ----------------------------- CalculatorEngine -----------------------------
class CalculatorEngine:
    """
    Cost model reads attributes on `inputs`:
      state, care_type
      AL: al_care_level, al_room_type, al_mobility, al_conditions
      IH: ih_hours_per_day, ih_days_per_month, ih_caregiver_type
      MC: mc_care_level, mc_mobility, mc_conditions
    """

    BASE = {
        "none": 0,
        "in_home_hourly": 32,
        "in_home_hourly_private": 26,
        "assisted_living": 6500,
        "memory_care": 8500,
    }

    LOCATION = {
        "National": 1.00,
        "Washington": 1.15,
        "California": 1.25,
        "Texas": 0.95,
        "Florida": 1.05,
    }

    AL_CARE_LEVEL = {"Low": 1.00, "Medium": 1.10, "High": 1.25}
    AL_ROOM_TYPE  = {"Studio": 0.95, "1 Bedroom": 1.00, "2 Bedroom": 1.15}
    AL_MOBILITY   = {"Independent": 1.00, "Some assistance": 1.08, "Extensive assistance": 1.18}
    AL_CONDITIONS = {"None": 1.00, "Some": 1.06, "Complex": 1.14}

    MC_CARE_LEVEL = {"Low": 1.00, "Medium": 1.10, "High": 1.25}
    MC_MOBILITY   = {"Independent": 1.00, "Some assistance": 1.05, "Extensive assistance": 1.12}
    MC_CONDITIONS = {"None": 1.00, "Some": 1.08, "Complex": 1.18}

    def __init__(self, *args, **kwargs):
        pass

    def _get(self, o: Any, k: str, d: Any): return getattr(o, k, d)
    def _loc(self, i: Any) -> float: return float(self.LOCATION.get(str(self._get(i, "state", "National")), 1.0))

    def _cost_assisted_living(self, i: Any) -> int:
        base = self.BASE["assisted_living"]
        mult = (
            self.AL_CARE_LEVEL.get(self._get(i, "al_care_level", "Medium"), 1.10) *
            self.AL_ROOM_TYPE.get(self._get(i, "al_room_type", "1 Bedroom"), 1.00) *
            self.AL_MOBILITY.get(self._get(i, "al_mobility", "Independent"), 1.00) *
            self.AL_CONDITIONS.get(self._get(i, "al_conditions", "None"), 1.00)
        )
        return int(round(base * self._loc(i) * mult))

    def _cost_in_home(self, i: Any) -> int:
        hours = int(self._get(i, "ih_hours_per_day", 4))
        days  = int(self._get(i, "ih_days_per_month", 20))
        care  = str(self._get(i, "ih_caregiver_type", "agency")).lower()
        hourly = self.BASE["in_home_hourly_private"] if care == "private" else self.BASE["in_home_hourly"]
        return int(round(hours * days * hourly * self._loc(i)))

    def _cost_memory_care(self, i: Any) -> int:
        base = self.BASE["memory_care"]
        mult = (
            self.MC_CARE_LEVEL.get(self._get(i, "mc_care_level", "Medium"), 1.10) *
            self.MC_MOBILITY.get(self._get(i, "mc_mobility", "Some assistance"), 1.05) *
            self.MC_CONDITIONS.get(self._get(i, "mc_conditions", "Some"), 1.08)
        )
        return int(round(base * self._loc(i) * mult))

    def monthly_cost(self, inputs: Any) -> int:
        ct = str(self._get(inputs, "care_type", "in_home")).lower()
        if ct == "none":
            return 0
        if ct in ("assisted_living", "assisted living"):
            return self._cost_assisted_living(inputs)
        if ct in ("memory_care", "memory care"):
            return self._cost_memory_care(inputs)
        return self._cost_in_home(inputs)