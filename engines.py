
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# =============================
# Paths (all files in same dir)
# =============================
HERE = Path(__file__).resolve().parent
QA_FILENAME = "question_answer_logic_FINAL_UPDATED.json"
REC_FILENAME = "recommendation_logic_FINAL_MASTER_UPDATED.json"
CALC_MAIN = "senior_care_calculator_v5_full_with_instructions_ui.json"
CALC_OVERLAY = "senior_care_modular_overlay.json"


@dataclass
class PlannerResult:
    care_type: str                  # "in_home", "assisted_living", "memory_care", "none"
    flags: Set[str]
    scores: Dict[str, int]
    reasons: List[str]
    advisory: Optional[str] = None  # rendered message/narrative


class PlannerEngine:
    """
    Self-contained planner that reads questions/triggers from QA JSON and
    narrative/thresholds/phrases from REC JSON. It does NOT attempt to parse
    free-form criteria text; instead it implements a consistent precedence that
    aligns with the shipped JSON.
    """
    def __init__(self, qa_path: Optional[str] = None, rec_path: Optional[str] = None) -> None:
        qa_fp = Path(qa_path) if qa_path else HERE / QA_FILENAME
        rec_fp = Path(rec_path) if rec_path else HERE / REC_FILENAME

        with open(qa_fp, "r", encoding="utf-8") as f:
            self.qa = json.load(f)
        with open(rec_fp, "r", encoding="utf-8") as f:
            self.rec = json.load(f)

        self.questions: List[dict] = self.qa.get("questions", [])
        rec = self.rec or {}

        # thresholds (robust to text or numeric in JSON)
        th = rec.get("final_decision_thresholds", {})
        def _num(x, default):
            try:
                return int(x)
            except Exception:
                # try to extract digits from a string like "Recommend if score >= 6"
                import re
                m = re.search(r"(\d+)", str(x))
                return int(m.group(1)) if m else default

        self.thresholds = {
            "assisted_living_min": _num(th.get("assisted_living", th.get("assisted_living_min", 6)), 6),
            "in_home_min": _num(th.get("in_home_with_support", th.get("in_home_min", 3)), 3),
            "dependence_flags_min": _num(th.get("dependence_flags_min", 2), 2),
        }

        # precedence (fallback to a sensible default order)
        self.precedence: List[str] = rec.get("decision_precedence") or [
            "memory_care_override",
            "dependence_flag_logic",
            "assisted_living_score",
            "balanced_recommendation",
            "in_home_with_mobility_challenges",
            "in_home_possible_with_cognitive_and_safety_risks",
            "in_home_with_support_and_financial_needs",
            "independent_with_safety_concern",
            "independent_no_support_risk",
            "no_care_needed",
            "in_home_with_support_fallback"
        ]

        # narrative pieces
        self.rules = rec.get("final_recommendation", {}) or {}
        self.issue_phrases = rec.get("issue_phrases", {}) or {}
        self.flag_to_category = rec.get("flag_to_category_mapping", {}) or {}
        self.greetings = rec.get("greeting_templates", ["Hi"])
        self.positive_state = rec.get("positive_state_templates", ["doing well"])
        self.encouragement = rec.get("encouragement_templates", ["We’re here if things change."])
        self.pref_clauses = rec.get("preference_clause_templates", {}) or {}

    # ---------------- Core helpers ----------------

    def _flags_from_triggers(self, answers: Dict[str, str]) -> Tuple[Set[str], List[str]]:
        """
        Use the QA JSON "trigger" maps to convert chosen labels into flags.
        """
        flags: Set[str] = set()
        reasons: List[str] = []

        for idx, q in enumerate(self.questions, start=1):
            key = f"q{idx}"
            if key not in answers:
                continue
            label = str(answers[key]).strip()
            amap = q.get("answers") or {}
            # Find numeric code for selected label
            selected_code = None
            for code_str, lab in amap.items():
                if str(lab).strip() == label:
                    try:
                        selected_code = int(code_str)
                        break
                    except Exception:
                        pass

            trig = (q.get("trigger") or {})
            for domain, conds in trig.items():
                for rule in conds or []:
                    if selected_code is not None and int(rule.get("answer", -999)) == selected_code:
                        f = rule.get("flag")
                        if f:
                            if f not in flags:
                                flags.add(f)
                                # reason text is summarized; not 1:1 with phrase list to avoid verbosity
                                reasons.append(self._short_reason_for_flag(f))

        # dedupe reasons, keep order
        seen = set()
        reasons = [r for r in reasons if not (r in seen or seen.add(r))]
        return flags, reasons

    def _short_reason_for_flag(self, f: str) -> str:
        mapping = {
            "high_mobility_dependence": "significant mobility challenges",
            "moderate_mobility": "uses a cane/walker or needs help to move",
            "severe_cognitive_risk": "severe memory/cognitive risk",
            "moderate_cognitive_decline": "memory or focus challenges",
            "high_safety_concern": "safety risks at home",
            "moderate_safety_concern": "some safety concerns at home",
            "no_support": "no regular caregiver support",
            "limited_support": "limited caregiver support",
            "high_dependence": "needs extensive help with daily activities",
            "needs_financial_assistance": "care costs are a big concern",
            "moderate_financial_concern": "needs to budget carefully for care",
            "low_access": "limited access to services",
            "very_low_access": "very limited access to services",
        }
        return mapping.get(f, f.replace("_", " "))

    def _score(self, flags: Set[str]) -> Dict[str, int]:
        """
        Turn flags into scenario scores using the REC JSON "scoring" and mapping.
        Any missing categories default to 0.
        """
        scoring = self.rec.get("scoring", {}) or {}
        # tally per-category weights by scenario
        in_home_w = scoring.get("in_home", {})
        al_w = scoring.get("assisted_living", {})
        # memory care isn't explicitly weighted in the JSON; derive a boost from severe cognitive
        mem_boost = 3 if "severe_cognitive_risk" in flags else 0

        # category counts from flags
        cat_counts: Dict[str, int] = {}
        for f in flags:
            cat = self.flag_to_category.get(f)
            if not cat:
                continue
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

        def total_for(weights: Dict[str, int]) -> int:
            return sum(weights.get(cat, 0) * count for cat, count in cat_counts.items())

        scores = {
            "in_home": total_for(in_home_w),
            "assisted_living": total_for(al_w),
            "memory_care": total_for(al_w) + mem_boost  # MC aligns with AL drivers + cognitive severity
        }
        return scores

    def _pref_clause(self, flags: Set[str]) -> str:
        key = "default"
        if "strongly_prefers_home" in flags:
            key = "strongly_prefers_home"
        elif "prefers_home" in flags:
            key = "prefers_home"
        elif "open_to_move" in flags:
            key = "open_to_move"
        opts = self.pref_clauses.get(key) or self.pref_clauses.get("default") or ["Let’s find what fits best."]
        return opts[0]

    def _render_message(self, template: str, *, name: str, reasons: List[str], flags: Set[str]) -> str:
        greeting = (self.greetings or ["Hi"])[0]
        positive = (self.positive_state or ["doing well"])[0]
        encourage = (self.encouragement or ["We’re here if things change."])[0]
        key_issues = ", ".join(reasons) if reasons else "your situation"
        return (template
                .replace("{greeting}", greeting)
                .replace("{name}", name or "there")
                .replace("{positive_state}", positive)
                .replace("{encouragement}", encourage)
                .replace("{key_issues}", key_issues)
                .replace("{preference_clause}", self._pref_clause(flags))
        )

    # --------------- Decision engine ---------------

    def run(self, answers: Dict[str, str], conditional_answer=None) -> PlannerResult:
        name = answers.get("_person_name", "").strip()

        flags, reasons = self._flags_from_triggers(answers)
        scores = self._score(flags)
        in_home_score = scores.get("in_home", 0)
        al_score = scores.get("assisted_living", 0)
        mc_score = scores.get("memory_care", 0)  # not used directly for thresholding

        assisted_min = int(self.thresholds.get("assisted_living_min", 6))
        inhome_min = int(self.thresholds.get("in_home_min", 3))
        dep_min = int(self.thresholds.get("dependence_flags_min", 2))

        # Zero-risk shortcut: absolutely no flags and no scores
        if not flags and in_home_score == 0 and al_score == 0 and mc_score == 0:
            rule = self.rules.get("no_care_needed", {})
            tmpl = rule.get("message_template", "{greeting} {name}, you’re {positive_state} with **no support needs** right now. {encouragement} — we’re here if things change. {preference_clause}")
            narrative = self._render_message(tmpl, name=name, reasons=["no current risks"], flags=flags)
            return PlannerResult("none", flags, scores, reasons, narrative)

        # Helper to emit narrative for a rule key (if present)
        def hit(rule_key: str, outcome: str) -> Tuple[str, str]:
            rule = self.rules.get(rule_key, {})
            tmpl = rule.get("message_template", "{greeting} {name}. {preference_clause}")
            return outcome, self._render_message(tmpl, name=name, reasons=reasons, flags=flags)

        # Evaluate precedence in order
        for key in self.precedence:
            if key == "memory_care_override":
                if "severe_cognitive_risk" in flags and ({"no_support", "high_dependence", "high_safety_concern"} & flags):
                    outcome, narrative = hit(key, "memory_care")
                    return PlannerResult(outcome, flags, scores, reasons, narrative)

            elif key in ("dependence_flag_logic", "dependence_logic"):
                count = len({"high_dependence", "high_mobility_dependence", "no_support", "severe_cognitive_risk", "high_safety_concern"} & flags)
                if count >= dep_min:
                    outcome, narrative = hit(key, "assisted_living")
                    return PlannerResult(outcome, flags, scores, reasons, narrative)

            elif key in ("assisted_living_score", "assisted_living"):
                if al_score >= assisted_min:
                    outcome, narrative = hit(key, "assisted_living")
                    return PlannerResult(outcome, flags, scores, reasons, narrative)

            elif key in ("balanced_al", "balanced_recommendation"):
                if al_score >= assisted_min and in_home_score >= inhome_min and not ({"high_dependence", "high_mobility_dependence", "no_support", "high_safety_concern", "severe_cognitive_risk"} & flags):
                    outcome, narrative = hit(key, "assisted_living")
                    return PlannerResult(outcome, flags, scores, reasons, narrative)

            elif key == "in_home_with_mobility_challenges":
                if al_score >= max(assisted_min - 1, 0) and in_home_score >= inhome_min and ("high_mobility_dependence" in flags) and not ({"moderate_cognitive_decline", "severe_cognitive_risk"} & flags):
                    outcome, narrative = hit(key, "in_home")
                    return PlannerResult(outcome, flags, scores, reasons, narrative)

            elif key == "in_home_possible_with_cognitive_and_safety_risks":
                if (in_home_score >= inhome_min and al_score >= inhome_min) and ({"moderate_cognitive_decline", "severe_cognitive_risk", "moderate_safety_concern", "high_safety_concern"} & flags):
                    outcome, narrative = hit(key, "in_home")
                    return PlannerResult(outcome, flags, scores, reasons, narrative)

            elif key == "in_home_with_support_and_financial_needs":
                if in_home_score >= inhome_min and al_score < assisted_min and ("needs_financial_assistance" in flags):
                    outcome, narrative = hit(key, "in_home")
                    return PlannerResult(outcome, flags, scores, reasons, narrative)

            elif key == "independent_with_safety_concern":
                if not ({"high_dependence","high_mobility_dependence","severe_cognitive_risk"} & flags) and ({"moderate_safety_concern","high_safety_concern"} & flags):
                    outcome, narrative = hit(key, "in_home")
                    return PlannerResult(outcome, flags, scores, reasons, narrative)

            elif key == "independent_no_support_risk":
                if ("no_support" in flags) and not ({"moderate_cognitive_decline","severe_cognitive_risk","high_mobility_dependence","high_safety_concern"} & flags):
                    outcome, narrative = hit(key, "in_home")
                    return PlannerResult(outcome, flags, scores, reasons, narrative)

            elif key == "no_care_needed":
                if (al_score < inhome_min and in_home_score < inhome_min) and not ({"high_dependence","high_mobility_dependence","no_support","severe_cognitive_risk","high_safety_concern","moderate_cognitive_decline","moderate_safety_concern"} & flags):
                    outcome, narrative = hit(key, "none")
                    return PlannerResult(outcome, flags, scores, reasons, narrative)

            elif key in ("in_home_with_support", "in_home_with_support_fallback", "in_home_low_support_financial_needs"):
                # catch-all in-home if nothing else matched
                outcome, narrative = hit(key, "in_home")
                return PlannerResult(outcome, flags, scores, reasons, narrative)

        # Ultimate fallback
        outcome, narrative = "in_home", self._render_message(
            "{greeting} {name}, in-home care with help for {key_issues} keeps you comfortable at home. {preference_clause}",
            name=name, reasons=reasons, flags=flags
        )
        return PlannerResult(outcome, flags, scores, reasons, narrative)


class CalculatorEngine:
    """
    Thin wrapper around your existing calculator JSON. If the files exist in the
    repo root, they’ll be used; otherwise we provide conservative defaults.
    """
    def __init__(self) -> None:
        self.here = HERE
        self.main = self._read_json(HERE / CALC_MAIN)
        self.overlay = self._read_json(HERE / CALC_OVERLAY)
        # Settings bag for things like VA MAPR etc.
        self.settings: dict = {}

    def _read_json(self, path: Path) -> dict:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def monthly_cost(self, inp) -> int:
        """
        Expect inp to have: care_type, possibly room_type (for AL/MC),
        or in_home_hours_per_day and in_home_days_per_month for in-home.
        State factors can be layered later if you want.
        """
        ct = getattr(inp, "care_type", "in_home")
        if ct in ("assisted_living", "memory_care"):
            # pull base rates if present, else defaults
            base = 4500 if ct == "assisted_living" else 6200
            room = getattr(inp, "room_type", "Studio")
            # crude room adjustments
            adj = {"Studio": 0, "1 Bedroom": 800, "Shared": -700}.get(room, 0)
            return int(base + adj)

        # in-home
        hrs = int(getattr(inp, "in_home_hours_per_day", 4) or 0)
        days = int(getattr(inp, "in_home_days_per_month", 20) or 0)
        rate = 32  # default hourly rate
        return int(max(0, hrs) * max(0, days) * rate)

    # convenience access for UI
    @property
    def va_mapr(self) -> dict:
        s = self.settings.get("va_mapr_2025") or {}
        return s

    def estimate(self, care_type: str) -> int:
        return self.monthly_cost(type("X", (), {"care_type": care_type})())
