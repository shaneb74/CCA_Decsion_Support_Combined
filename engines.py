from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import json


# ----------------------------- Data models ----------------------------- #

@dataclass
class PlannerResult:
    care_type: str                     # "in_home" | "assisted_living" | "memory_care" | "no_care"
    flags: Set[str]                    # normalized flags accumulated from answers
    scores: Dict[str, int]             # e.g. {"in_home": 3, "assisted_living": 6}
    reasons: List[str]                 # human-readable reasons
    advisory: Optional[str] = None     # extra helper language
    # Carryover signals for app.py (UI defaults and nudges)
    mobility_prefill: Optional[str] = None     # "Independent" | "Assisted" | "Non-ambulatory"
    home_pref: Optional[str] = None            # "prefers_home"|"open_to_move"|"strongly_prefers_home"|None
    home_pref_note: Optional[str] = None       # A short nudge for Home Mods drawer
    carryover: Optional[Dict[str, Any]] = None # extensible bag for future signals


# ----------------------------- Planner Engine ----------------------------- #

class PlannerEngine:
    """
    Loads question/answer logic and recommendation logic from JSON files, then
    evaluates answers to produce a recommendation and structured carryover data.

    JSON expectations (summarized from your updated files):
      - Q&A JSON:
          {
            "questions": [
               {"question": "...", "answers": {"1":"...", "2":"..."}, "flag_map": {"1":["foo_flag"], "2":["bar_flag"]}, "help": "..."},
               ...
            ],
            "conditional_questions": [...optional...]
          }

      - Recommendation JSON:
          {
            "flag_to_category_mapping": {"flag_name": "category_name", ...},
            "scoring": {
                "categories": {"catA": 1, "catB": 2, ...},
                "tracks": {"in_home": ["catA","catB"], "assisted_living": ["catB","catC"] }
            },
            "final_decision_thresholds": {"assisted_living": 6, "in_home": 3},
            "overrides": {
                "memory_care": {"requires_all_flags": ["severe_cognitive_risk","no_support"] }
            },
            "templates": {
                "assisted_living": {"headline": "...", "body": "..."},
                "in_home": {"headline": "...", "body": "..."},
                "memory_care": {"headline": "...", "body": "..."},
                "no_care": {"headline": "...", "body": "..."},
                "borderline": {"headline":"...", "body":"..."}
            }
          }
    """

    def __init__(self, qa_path: str, rec_path: str):
        self.qa_path = Path(qa_path)
        self.rec_path = Path(rec_path)
        with self.qa_path.open("r", encoding="utf-8") as f:
            self.qa = json.load(f)
        with self.rec_path.open("r", encoding="utf-8") as f:
            self.rec = json.load(f)

        # Extract pieces with safe defaults
        self.flag_cat = self.rec.get("flag_to_category_mapping", {}) or {}
        self.scoring = self.rec.get("scoring", {}) or {}
        self.categories_weights = (self.scoring.get("categories") or {})
        self.tracks = (self.scoring.get("tracks") or {"in_home": [], "assisted_living": []})
        self.final_thresholds = self.rec.get("final_decision_thresholds", {}) or {"assisted_living": 6, "in_home": 3}
        self.overrides = self.rec.get("overrides", {}) or {}
        self.templates = self.rec.get("templates", {}) or {}

    # ----------------- public API ----------------- #
    def run(self, answers: Dict[str, int], conditional_answer: Optional[str] = None) -> PlannerResult:
        """
        Evaluate answers into flags, compute scores, apply overrides & thresholds,
        and return a PlannerResult with carryover signals.
        """
        flags = self._collect_flags(answers)
        scores, cat_tallies = self._score(flags)
        care_type, reasons, advisory = self._decide(flags, scores, cat_tallies)

        mobility_prefill = self._carryover_mobility(answers)
        home_pref, home_pref_note = self._carryover_home_pref(flags)

        return PlannerResult(
            care_type=care_type,
            flags=set(flags),
            scores=scores,
            reasons=reasons,
            advisory=advisory,
            mobility_prefill=mobility_prefill,
            home_pref=home_pref,
            home_pref_note=home_pref_note,
            carryover={"categories": cat_tallies}
        )

    # ----------------- internals ----------------- #
    def _collect_flags(self, answers: Dict[str, int]) -> List[str]:
        """Map each selected answer to its configured flags."""
        collected: List[str] = []
        for idx, q in enumerate(self.qa.get("questions", []), start=1):
            ans_key = str(answers.get(f"q{idx}", ""))
            if not ans_key:
                continue
            # optional direct mapping inside Q structure
            # Prefer "flag_map" if available; otherwise infer nothing here.
            flag_map = q.get("flag_map") or {}
            mapped = flag_map.get(ans_key, [])
            if isinstance(mapped, str):
                mapped = [mapped]
            collected.extend(mapped)
        # Optional conditional block — if your JSON still emits flags via a conditional, handle similarly here.
        # But your latest schema moves cognition gating into flag rules and templates, so we stop here.
        return [f for f in collected if f]

    def _score(self, flags: List[str]) -> Tuple[Dict[str, int], Dict[str, int]]:
        """
        Convert flags into category tallies then into track scores.

        Category score = sum of weights for categories touched by the flags.
        Track score    = sum of the category scores for categories included in the track.
        """
        # Tallies per category
        cat_counts: Dict[str, int] = {}
        for fl in flags:
            cat = self.flag_cat.get(fl)
            if not cat:
                continue
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

        # Weighted category scores
        cat_scores: Dict[str, int] = {}
        for cat, count in cat_counts.items():
            w = int(self.categories_weights.get(cat, 1))
            cat_scores[cat] = w * count

        # Track scores
        scores: Dict[str, int] = {}
        for track, cats in self.tracks.items():
            scores[track] = sum(cat_scores.get(c, 0) for c in (cats or []))

        return scores, cat_scores

    def _decide(self, flags: List[str], scores: Dict[str, int], cat_scores: Dict[str, int]) -> Tuple[str, List[str], Optional[str]]:
        """
        Apply override then thresholds to choose final care_type.
        Also builds a concise 'reasons' list and optional advisory text from templates.
        """
        flset = set(flags)
        reasons: List[str] = []
        advisory: Optional[str] = None

        # 1) Memory care override: requires ALL specified flags
        mc_rule = (self.overrides.get("memory_care") or {}).get("requires_all_flags", [])
        if mc_rule and all(r in flset for r in mc_rule):
            care_type = "memory_care"
            reasons.append("Severe cognitive risk with no daily support present.")
            tmpl = self.templates.get("memory_care") or {}
            if tmpl.get("body"):
                advisory = tmpl.get("body")
            return care_type, reasons, advisory

        # 2) Thresholds
        assisted_cut = int(self.final_thresholds.get("assisted_living", 6))
        inhome_cut = int(self.final_thresholds.get("in_home", 3))

        assisted = int(scores.get("assisted_living", 0))
        inhome = int(scores.get("in_home", 0))

        # assisted first if it clears threshold
        if assisted >= assisted_cut:
            care_type = "assisted_living"
            reasons.append(f"Assisted living score {assisted} ≥ threshold {assisted_cut}.")
            tmpl = self.templates.get("assisted_living") or {}
            if tmpl.get("body"):
                advisory = tmpl.get("body")
            return care_type, reasons, advisory

        # in-home next if it clears and assisted does not
        if inhome >= inhome_cut and assisted < assisted_cut:
            care_type = "in_home"
            reasons.append(f"In-home score {inhome} ≥ threshold {inhome_cut} and assisted score {assisted} below {assisted_cut}.")
            tmpl = self.templates.get("in_home") or {}
            if tmpl.get("body"):
                advisory = tmpl.get("body")
            return care_type, reasons, advisory

        # possible "no care" if both undercuts and no dependence flags
        dependence_flags = {"high_dependence", "high_mobility_dependence", "no_support", "high_safety_concern", "severe_cognitive_risk"}
        if inhome < inhome_cut and assisted < assisted_cut and flset.isdisjoint(dependence_flags):
            care_type = "no_care"
            reasons.append("No dependence flags and scores below thresholds.")
            tmpl = self.templates.get("no_care") or {}
            if tmpl.get("body"):
                advisory = tmpl.get("body")
            return care_type, reasons, advisory

        # borderline fallback
        care_type = "in_home"
        reasons.append("Borderline case: in-home trial with support may work; reassess regularly.")
        tmpl = self.templates.get("borderline") or {}
        if tmpl.get("body"):
            advisory = tmpl.get("body")
        return care_type, reasons, advisory

    # ----------------- carryover helpers ----------------- #

    def _carryover_mobility(self, answers: Dict[str, int]) -> Optional[str]:
        """
        Infer mobility default for the calculator from the mobility question.
        We look for the first QA item containing 'mobility' in its label.
        Mapping:
            1 -> Independent
            2/3 -> Assisted
            4+ -> Non-ambulatory
        """
        for idx, q in enumerate(self.qa.get("questions", []), start=1):
            text = (q.get("question") or "").lower()
            if "mobility" not in text:
                continue
            choice = int(answers.get(f"q{idx}", 0) or 0)
            if choice <= 1:
                return "Independent"
            if choice in (2, 3):
                return "Assisted"
            return "Non-ambulatory"
        return None

    def _carryover_home_pref(self, flags: List[str]) -> Tuple[Optional[str], Optional[str]]:
        """
        Use flags to detect home preference and create a short note for the Home Mods drawer.
        Flags we look for (names should match your JSON): 'prefers_home', 'strongly_prefers_home', 'open_to_move'
        """
        fl = set(flags)
        if "strongly_prefers_home" in fl:
            return "strongly_prefers_home", "Because the plan indicates a strong preference to remain at home, consider safety and accessibility updates."
        if "prefers_home" in fl:
            return "prefers_home", "Since the plan prefers remaining at home, review common safety and accessibility updates."
        if "open_to_move" in fl:
            return "open_to_move", None
        return None, None


# ----------------------------- Calculator Engine ----------------------------- #

class CalcInputs(SimpleNamespace):
    """Just a namespaced bag for calculator inputs; app constructs this dynamically."""
    pass


class CalculatorEngine:
    """
    Cost model kept intentionally simple and predictable; numbers are placeholders that your
    Streamlit JSON file or settings can override.

    Exposed methods:
      - settings: dict of tweakables (state multipliers, room rates, in-home hourly base, etc.)
      - monthly_cost(inputs): computes per-person monthly cost using inputs.care_type, etc.
    """

    def __init__(self):
        # Defaults; app can set/override self.settings; VA/LTC wizard also writes here.
        self.settings: Dict[str, Any] = {
            # Cost multipliers by state (illustrative)
            "state_multiplier": {
                "National": 1.00,
                "Washington": 1.17,
                "California": 1.20,
                "Texas": 0.95,
                "Florida": 1.05,
            },
            # In-home baseline hourly (adjusted by care_level, mobility, chronic)
            "in_home_hourly_base": 32,  # dollars per hour
            "in_home_care_level_add": {"Low": 0, "Medium": 3, "High": 6},
            "in_home_mobility_add": {"Independent": 0, "Assisted": 2, "Non-ambulatory": 5},
            "in_home_chronic_add": {"None": 0, "Some": 2, "Multiple/Complex": 5},

            # Assisted/memory base monthly by room type
            "al_room_rates": {"Studio": 4200, "1 Bedroom": 4900, "Shared": 3600},
            "mc_room_rates": {"Studio": 6200, "1 Bedroom": 6900, "Shared": 5400},
            "al_care_level_add": {"Low": 0, "Medium": 400, "High": 900},
            "mc_care_level_add": {"Low": 0, "Medium": 600, "High": 1200},
        }

    # public API
    def monthly_cost(self, inp: CalcInputs) -> int:
        """
        Compute monthly cost.

        For in-home:
            hourly = base + care_level_add + mobility_add + chronic_add
            monthly = hourly * in_home_hours_per_day * in_home_days_per_month
        For assisted living / memory care:
            monthly = base_room_rate + care_level_add
        Then apply state multiplier.
        """
        st_mult = float(self._get("state_multiplier", {}).get(getattr(inp, "state", "National"), 1.0))

        care_type = getattr(inp, "care_type", "in_home")
        care_level = getattr(inp, "care_level", "Medium")

        if care_type == "in_home":
            base = int(self._get("in_home_hourly_base", 32))
            lvl_add = int(self._get("in_home_care_level_add", {}).get(care_level, 0))
            mobility = getattr(inp, "mobility", "Independent")
            mob_add = int(self._get("in_home_mobility_add", {}).get(mobility, 0))
            chronic = getattr(inp, "chronic", "Some")
            chr_add = int(self._get("in_home_chronic_add", {}).get(chronic, 0))

            hourly = base + lvl_add + mob_add + chr_add

            hours_per_day = int(getattr(inp, "in_home_hours_per_day", 4) or 0)
            days_per_month = int(getattr(inp, "in_home_days_per_month", 20) or 0)

            monthly = int(round(hourly * hours_per_day * days_per_month))
            return int(round(monthly * st_mult))

        if care_type == "assisted_living":
            room = getattr(inp, "room_type", "Studio")
            base = int(self._get("al_room_rates", {}).get(room, 4200))
            lvl_add = int(self._get("al_care_level_add", {}).get(care_level, 0))
            monthly = base + lvl_add
            return int(round(monthly * st_mult))

        if care_type == "memory_care":
            room = getattr(inp, "room_type", "Studio")
            base = int(self._get("mc_room_rates", {}).get(room, 6200))
            lvl_add = int(self._get("mc_care_level_add", {}).get(care_level, 0))
            monthly = base + lvl_add
            return int(round(monthly * st_mult))

        # Fallback
        return 0

    # internal
    def _get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)