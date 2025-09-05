# engines.py — Planner + Self-contained Care Recommendation + Calculator
# Drop-in replacement. Works with app.py that uses:
#   from engines import PlannerEngine, CalculatorEngine
#
# What you get:
# - PlannerEngine: exposes .qa for UI; run(...) returns a dict with care_type, flags, scores, reasons, advisory
# - CareRecommendationEngine: deterministic rule precedence from recommendation JSON; renders narrative message
# - CalculatorEngine: monthly_cost(...) for in_home, assisted_living, memory_care; carries VA/LTC defaults in .settings

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# =========================
# Utilities
# =========================

def _safe_get(obj: Any, key: str, default=None):
    """Supports dict or SimpleNamespace-like objects."""
    return getattr(obj, key, None) if hasattr(obj, key) else obj.get(key, default)

def _to_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default

def _to_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


# =========================
# CareRecommendationEngine (self-contained)
# =========================

@dataclass
class RecResult:
    care_type: str
    rule_key: str
    flags: List[str]
    scores: Dict[str, float]
    reasons: List[str]
    message: Optional[str]
    debug: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "care_type": self.care_type,
            "rule_key": self.rule_key,
            "flags": list(self.flags),
            "scores": self.scores,
            "reasons": self.reasons,
            "message": self.message,
            "debug": self.debug,
        }


class CareRecommendationEngine:
    """
    Loads recommendation JSON, applies deterministic precedence,
    renders message_template with {greeting}, {name}, {key_issues}, {preference_clause}.
    """

    def __init__(self, rec_json_path: str):
        with open(rec_json_path, "r", encoding="utf-8") as f:
            self.rec = json.load(f)

        self._thresholds = self.rec.get("final_decision_thresholds", {}) or {}
        self._precedence = self.rec.get("decision_precedence", []) or []
        self._rules = (self.rec.get("final_recommendation") or {})
        if not self._rules:
            raise ValueError("recommendation JSON missing final_recommendation rules")

        # Narrative pools
        self._greetings = self.rec.get("greeting_templates", []) or ["Hi"]
        self._positives = self.rec.get("positive_state_templates", []) or ["doing well"]
        self._encouragements = self.rec.get("encouragement_templates", []) or ["We’re here for you"]
        self._pref_clauses = self.rec.get("preference_clause_templates", {}) or {}
        self._issue_phrases = self.rec.get("issue_phrases", {}) or {}

        # Thresholds
        self._assisted_min = int(self._thresholds.get("assisted_living_min", 6))
        self._inhome_min   = int(self._thresholds.get("in_home_min", 3))
        self._dep_min      = int(self._thresholds.get("dependence_flags_min", 2))

    # ---------- Public API ----------
    def decide(
        self,
        name: str,
        flags: Set[str],
        scores: Dict[str, float],
        home_pref: str = "default",
        reasons: Optional[List[str]] = None,
    ) -> RecResult:
        flags = set(flags or set())
        scores = dict(scores or {})
        reasons = list(reasons or [])

        al_score = self._get_score(scores, "assisted_living")
        ih_score = self._get_score(scores, "in_home")

        rule_key, outcome = self._evaluate_rules(flags, al_score, ih_score)

        ctx = self._build_context(name=name, flags=flags, home_pref=home_pref)
        message = self._render_message(rule_key, ctx)

        debug = {
            "assisted_living_score": al_score,
            "in_home_score": ih_score,
            "thresholds": {
                "assisted_living_min": self._assisted_min,
                "in_home_min": self._inhome_min,
                "dependence_flags_min": self._dep_min,
            },
            "matched_rule": rule_key,
            "active_flags": sorted(flags),
        }

        return RecResult(
            care_type=outcome,
            rule_key=rule_key,
            flags=sorted(flags),
            scores={"assisted_living": al_score, "in_home": ih_score},
            reasons=reasons,
            message=message,
            debug=debug,
        )

    # ---------- Rule evaluation ----------
    def _evaluate_rules(self, flags: Set[str], al: float, ih: float) -> Tuple[str, str]:
        f = flags
        dep_count = sum(1 for k in (
            "high_dependence",
            "high_mobility_dependence",
            "no_support",
            "severe_cognitive_risk",
            "high_safety_concern",
        ) if k in f)

        order = self._precedence or [
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
            "in_home_with_support_fallback",
        ]

        for key in order:
            if key == "memory_care_override":
                if ("severe_cognitive_risk" in f) and (
                    ("no_support" in f) or ("high_dependence" in f) or ("high_safety_concern" in f)
                ):
                    return key, "memory_care"

            elif key == "dependence_flag_logic":
                if dep_count >= self._dep_min:
                    return key, "assisted_living"

            elif key == "assisted_living_score":
                if al >= self._assisted_min:
                    return key, "assisted_living"

            elif key == "balanced_al":
                none_of = all(k not in f for k in (
                    "high_dependence", "high_mobility_dependence", "no_support",
                    "high_safety_concern", "severe_cognitive_risk"
                ))
                if al >= self._assisted_min and ih >= self._inhome_min and none_of:
                    return key, "assisted_living"

            elif key == "in_home_with_mobility_challenges":
                if (al >= (self._assisted_min - 1) and ih >= self._inhome_min
                    and ("high_mobility_dependence" in f)
                    and ("moderate_cognitive_decline" not in f)
                    and ("severe_cognitive_risk" not in f)):
                    return key, "in_home"

            elif key == "in_home_possible_with_cognitive_and_safety_risks":
                any_risk = any(k in f for k in (
                    "moderate_cognitive_decline", "severe_cognitive_risk",
                    "moderate_safety_concern", "high_safety_concern"
                ))
                if ih >= self._inhome_min and al >= self._inhome_min and any_risk:
                    return key, "in_home"

            elif key == "in_home_with_support_and_financial_needs":
                if ih >= self._inhome_min and al < self._assisted_min and ("needs_financial_assistance" in f):
                    return key, "in_home"

            elif key == "independent_with_safety_concern":
                independent = (
                    "high_dependence" not in f and
                    "high_mobility_dependence" not in f and
                    "severe_cognitive_risk" not in f and
                    "moderate_cognitive_decline" not in f
                )
                safety = ("moderate_safety_concern" in f) or ("high_safety_concern" in f)
                if independent and safety:
                    return key, "in_home"

            elif key == "independent_no_support_risk":
                independent = (
                    "high_dependence" not in f and
                    "high_mobility_dependence" not in f and
                    "severe_cognitive_risk" not in f and
                    "moderate_cognitive_decline" not in f
                )
                if independent and ("no_support" in f):
                    return key, "in_home"

            elif key == "no_care_needed":
                risky = any(k in f for k in (
                    "high_dependence", "high_mobility_dependence", "no_support",
                    "severe_cognitive_risk", "high_safety_concern",
                    "moderate_cognitive_decline", "moderate_safety_concern", "high_risk"
                ))
                if (al < self._inhome_min) and (ih < self._inhome_min) and not risky:
                    return key, "none"

            elif key == "in_home_with_support_fallback":
                return key, "in_home"

        return "in_home_with_support_fallback", "in_home"

    # ---------- Narrative building ----------
    def _pick(self, items: List[str], default: str = "") -> str:
        try:
            return random.choice(items) if items else default
        except Exception:
            return default

    def _build_context(self, name: str, flags: Set[str], home_pref: str) -> Dict[str, str]:
        pref_list = self._pref_clauses.get(home_pref, self._pref_clauses.get("default", []))
        preference_clause = self._pick(pref_list, "")

        priority = [
            "high_dependence", "high_mobility_dependence", "severe_cognitive_risk",
            "high_safety_concern", "moderate_cognitive_decline", "moderate_safety_concern",
            "no_support", "limited_support", "high_risk", "moderate_risk",
            "needs_financial_assistance"
        ]
        ordered = [k for k in priority if k in flags] or list(flags)
        key_issues = []
        for k in ordered[:4]:
            pool = self._issue_phrases.get(k, [])
            key_issues.append(self._pick(pool, k.replace("_", " ")))
        key_issues_str = ", ".join(key_issues) if key_issues else "your current needs"

        ctx = {
            "greeting": self._pick(self._greetings, "Hi"),
            "name": name,
            "positive_state": self._pick(self._positives, "doing well"),
            "encouragement": self._pick(self._encouragements, "We’re here for you"),
            "preference_clause": preference_clause,
            "key_issues": key_issues_str,
            "home_preference": (
                "prefer to stay home"
                if home_pref in ("prefers_home", "strongly_prefers_home")
                else "are open to options"
            ),
            "recommendation": "this plan",
        }
        return ctx

    def _render_message(self, rule_key: str, ctx: Dict[str, str]) -> Optional[str]:
        try:
            tmpl = (self._rules.get(rule_key) or {}).get("message_template")
            return tmpl.format(**ctx) if tmpl else None
        except Exception:
            return None

    def _get_score(self, scores: Dict[str, float], which: str) -> float:
        val = scores.get(which)
        if val is None:
            val = scores.get(f"{which}_score")
        try:
            return float(val or 0)
        except Exception:
            return 0.0


# =========================
# PlannerEngine
# =========================

class PlannerEngine:
    """
    Exposes:
      - self.qa : the question JSON (for UI)
      - run(answers: dict, conditional_answer: Optional[str], person_name: str, home_pref: str)
        -> dict with care_type, flags, scores, reasons, advisory
    Notes:
      - We build flags by keyword matching on the answer text (stable across your current JSON).
      - We compute rough scores from the "scoring" weights in the recommendation JSON when available.
    """

    def __init__(self, qa_path: str, rec_path: str):
        with open(qa_path, "r", encoding="utf-8") as f:
            self.qa = json.load(f)

        with open(rec_path, "r", encoding="utf-8") as f:
            self.rec = json.load(f)

        # Prepare scoring weights if present
        self._weights = (self.rec.get("scoring") or {})
        self._al_weights = self._weights.get("assisted_living", {}) or {}
        self._ih_weights = self._weights.get("in_home", {}) or {}

        # Self-contained care rec engine
        self._care_rec_engine = CareRecommendationEngine(rec_path)

    # ---------- public ----------
    def run(
        self,
        answers: Dict[str, int],
        *,
        conditional_answer: Optional[str] = None,
        person_name: str = "Person",
        home_pref: str = "default",
    ) -> Dict[str, Any]:
        """
        answers: mapping "q1" -> numeric key per question_answer_logic file
        conditional_answer: optional '1'/'2' etc when your JSON asks a 9th question
        """

        # Map numeric selections to answer text
        q_list = self.qa.get("questions", [])
        answer_texts: Dict[str, str] = {}
        for idx, q in enumerate(q_list, start=1):
            ans_map = q.get("answers", {}) or {}
            key = f"q{idx}"
            sel = answers.get(key)
            if sel is not None:
                sel_str = str(sel)
                if sel_str in ans_map:
                    answer_texts[key] = str(ans_map[sel_str])

        # Build flags from answer texts using conservative keyword detection
        flags: Set[str] = set()
        reasons: List[str] = []

        def mark(flag: str, reason: str):
            flags.add(flag)
            reasons.append(reason)

        # Mobility
        for k, txt in answer_texts.items():
            t = txt.lower()
            if "wheelchair" in t or "bedbound" in t or "mostly immobile" in t:
                mark("high_mobility_dependence", "Requires wheelchair or is non-ambulatory")
            elif "cane" in t or "walker" in t or "needs assistance" in t:
                mark("moderate_mobility", "Uses cane/walker or needs some assistance")

        # Cognitive
        for txt in answer_texts.values():
            t = txt.lower()
            if "severe" in t and ("memory" in t or "cognition" in t or "cognitive" in t):
                mark("severe_cognitive_risk", "Severe cognitive symptoms reported")
            elif "memory" in t or "cognitive" in t:
                if "moderate" in t or "some" in t:
                    mark("moderate_cognitive_decline", "Moderate cognitive concerns")

        # Support network
        for txt in answer_texts.values():
            t = txt.lower()
            if "no one" in t or "alone" in t or "no support" in t:
                mark("no_support", "No regular caregiver support")
            elif "limited" in t or "occasional" in t:
                mark("limited_support", "Limited or occasional support")

        # Safety
        for txt in answer_texts.values():
            t = txt.lower()
            if "falls" in t or "unsafe" in t or "wander" in t or "emergency" in t:
                if "serious" in t or "often" in t or "high" in t:
                    mark("high_safety_concern", "Significant home safety concerns")
                else:
                    mark("moderate_safety_concern", "Some home safety concerns")

        # Mood / social isolation
        for txt in answer_texts.values():
            t = txt.lower()
            if "lonely" in t or "down" in t or "isolated" in t:
                if "often" in t or "frequent" in t or "most of the time" in t:
                    mark("high_risk", "High social isolation or low mood")
                else:
                    mark("moderate_risk", "Some isolation or mood concerns")

        # Finances
        for txt in answer_texts.values():
            t = txt.lower()
            if "worry about money" in t or "concern" in t or "limited funds" in t:
                mark("needs_financial_assistance", "Cost sensitivity noted")

        # Preference to stay home (if your Q&A exposes it as text)
        pref = home_pref
        for txt in answer_texts.values():
            t = txt.lower()
            if "prefer to stay home" in t or "stay at home" in t:
                pref = "prefers_home"
            if "must stay home" in t or "strongly prefer home" in t:
                pref = "strongly_prefers_home"

        # Score using available weights, degrade gracefully if absent
        scores = {"assisted_living": 0.0, "in_home": 0.0}
        # Assisted
        for fkey, w in self._al_weights.items():
            if fkey in flags:
                scores["assisted_living"] += _to_float(w, 1.0)
        # In-home
        for fkey, w in self._ih_weights.items():
            if fkey in flags:
                scores["in_home"] += _to_float(w, 1.0)

        # Reasonable baselines when no configured weights
        if self._al_weights == {} and self._ih_weights == {}:
            # crude but safe: dependence and severe cognitive push AL
            if "high_dependence" in flags or "high_mobility_dependence" in flags:
                scores["assisted_living"] += 3
            if "severe_cognitive_risk" in flags:
                scores["assisted_living"] += 3
            if "no_support" in flags or "high_safety_concern" in flags:
                scores["assisted_living"] += 2
            # in-home supported by moderate risk items
            if "moderate_mobility" in flags or "limited_support" in flags:
                scores["in_home"] += 2
            if "moderate_safety_concern" in flags or "moderate_cognitive_decline" in flags:
                scores["in_home"] += 1

        # Build base result before final decision
        base_res = {
            "flags": sorted(list(flags)),
            "scores": scores,
            "reasons": reasons,
            "home_pref": pref,
        }

        # Final decision + rendered message
        final = self._finalize_recommendation(base_res, name=person_name)
        return final

    # ---------- private ----------
    def _finalize_recommendation(self, base_res: Any, name: str) -> dict:
        flags     = set(_safe_get(base_res, "flags", []))
        scores    = _safe_get(base_res, "scores", {}) or {}
        reasons   = list(_safe_get(base_res, "reasons", []))
        home_pref = _safe_get(base_res, "home_pref", "default")

        rec_out = self._care_rec_engine.decide(
            name=name,
            flags=flags,
            scores=scores,
            home_pref=home_pref,
            reasons=reasons
        ).as_dict()

        payload = {
            "care_type": rec_out["care_type"],
            "flags": rec_out["flags"],
            "scores": rec_out["scores"],
            "reasons": rec_out["reasons"],
            "message": rec_out["message"],
            "rule_key": rec_out["rule_key"],
            "debug": rec_out["debug"],
        }
        # Back-compat for app.py which reads 'advisory'
        payload["advisory"] = payload.get("message")
        return payload


# =========================
# CalculatorEngine
# =========================

class CalculatorEngine:
    """
    Simple calculator that supports:
      - in_home: uses in_home_hours_per_day * in_home_days_per_month * base hourly rate (state-adjusted)
      - assisted_living / memory_care: base market rate by state + care_level adjustments + room_type factor
    Also exposes .settings for VA/LTC amounts so the app’s VA wizard can use sane defaults.
    """

    def __init__(self, data_dir: Optional[str] = None):
        self.settings: Dict[str, Any] = {}

        # Default VA / LTC so UI never shows "not configured"
        self.settings["va_mapr_2025"] = {
            "Veteran (no dependents) — A&A": 2358,
            "Veteran + 1 dependent — A&A": 2795,
            "Two veterans married, one A&A": 2795,
            "Surviving spouse — A&A": 1515,
            "Surviving spouse + 1 child — A&A": 1808,
        }
        self.settings["ltc_monthly_add"] = 1800

        # Baseline market rates; if you have richer JSON, you can load it here.
        # These are intentionally conservative placeholders; your overlay file can override via app if needed.
        self._state_base = {
            "National": {"in_home_hourly": 32, "al_base": 4800, "mc_base": 6500},
            "California": {"in_home_hourly": 35, "al_base": 5600, "mc_base": 7500},
            "Washington": {"in_home_hourly": 36, "al_base": 5800, "mc_base": 7700},
            "Texas": {"in_home_hourly": 28, "al_base": 4200, "mc_base": 6000},
            "Florida": {"in_home_hourly": 29, "al_base": 4300, "mc_base": 6100},
        }

        # Care level multipliers for AL/MC
        self._care_level_factor = {
            "Low": 1.00,
            "Medium": 1.10,
            "High": 1.20,
        }

        # Room type multipliers (studio baseline)
        self._room_factor = {
            "Studio": 1.00,
            "1 Bedroom": 1.15,
            "Shared": 0.85,
        }

    # Public API
    def monthly_cost(self, inputs: Any) -> float:
        """
        inputs expected attributes:
          - state: str
          - care_type: "in_home" | "assisted_living" | "memory_care"
          - care_level: "Low" | "Medium" | "High"
          - mobility: e.g. "Independent"/"Assisted"/"Non-ambulatory" (not used here directly)
          - chronic:   e.g. "None"/"Some"/"Multiple/Complex" (not used here directly)
          - in_home_hours_per_day: int (if in_home)
          - in_home_days_per_month: int (if in_home)
          - room_type: "Studio" | "1 Bedroom" | "Shared" (if AL/MC)
        """
        state = getattr(inputs, "state", "National") or "National"
        care_type = getattr(inputs, "care_type", "in_home")
        care_level = getattr(inputs, "care_level", "Medium")
        base = self._state_base.get(state, self._state_base["National"])

        if care_type == "in_home":
            hours = _to_int(getattr(inputs, "in_home_hours_per_day", 4), 4)
            days  = _to_int(getattr(inputs, "in_home_days_per_month", 20), 20)
            hourly = _to_float(base.get("in_home_hourly", 32), 32.0)
            return float(hours * days * hourly)

        elif care_type in ("assisted_living", "memory_care"):
            room = getattr(inputs, "room_type", "Studio") or "Studio"
            if care_type == "assisted_living":
                base_rent = _to_float(base.get("al_base", 4800), 4800.0)
            else:
                base_rent = _to_float(base.get("mc_base", 6500), 6500.0)

            level_factor = self._care_level_factor.get(str(care_level), 1.10)
            room_factor  = self._room_factor.get(str(room), 1.00)
            return float(base_rent * level_factor * room_factor)

        # Fallback
        return 0.0