# engines.py
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Set, Union
import json


# ----------------------------- Utilities -----------------------------

def _load_json(p: Union[str, Path]) -> dict:
    p = Path(p)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _get(d: Mapping[str, Any], path: Iterable[str], default=None):
    cur = d
    for key in path:
        if not isinstance(cur, Mapping) or key not in cur:
            return default
        cur = cur[key]
    return cur


# ----------------------------- Planner -------------------------------

@dataclass
class PlannerResult:
    care_type: str
    flags: Set[str] = field(default_factory=set)
    scores: Dict[str, Any] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    advisory: Optional[str] = None

    # Dict-like convenience so legacy UI code using .get(...) or ['key'] still works
    def get(self, key: str, default=None):
        return asdict(self).get(key, default)

    def __getitem__(self, key: str):
        return asdict(self)[key]


class PlannerEngine:
    """
    Reads the Q&A spec and produces flags; then applies conservative,
    deterministic thresholds to recommend in_home / assisted_living / memory_care.

    Requirements this satisfies:
    - Use the triggers in question_answer_logic to set flags (no hard-coded indices)
    - Treat 'severe' situations as facility-first
    - Avoid handing out 'in-home' when severe risk is present
    - Return a result that is compatible with both object-style and dict-style access
    """

    def __init__(self, qa_path: Union[str, Path], rec_path: Optional[Union[str, Path]] = None):
        self.qa: dict = _load_json(qa_path)
        # rec_path may contain cost settings in your repo; planner thresholds are embedded here.
        self.rec: dict = _load_json(rec_path) if rec_path else {}
        # Final thresholds may be configured later; keep sane defaults here.
        self.thresholds = {
            "memory_care": {
                "any": {"severe_cognitive_risk"},
                "combo": [
                    # moderate cognition + one of these elevates to memory care
                    ({"moderate_cognitive_decline"}, {"high_dependence", "high_mobility_dependence", "no_support", "high_safety_concern"}),
                ],
            },
            "assisted_living": {
                "any": {
                    "high_dependence",
                    "high_mobility_dependence",
                    "no_support",
                    "high_safety_concern",
                    "very_low_access",
                },
                "count_moderate": 2,  # >= 2 moderates → assisted living (unless memory care hit above)
            },
            # in_home only if no severe and moderate load is low or mitigated by preference + support
        }

        # Classification buckets derived from your Q&A flags (see JSON):
        #   - severe set pushes away from in-home immediately
        #   - moderate set can aggregate to assisted living
        self.severe_flags: Set[str] = {
            "high_dependence",
            "high_mobility_dependence",
            "severe_cognitive_risk",
            "high_safety_concern",
            "no_support",
            "very_low_access",
        }
        self.moderate_flags: Set[str] = {
            "moderate_dependence",
            "moderate_mobility",
            "moderate_cognitive_decline",
            "moderate_safety_concern",
            "limited_support",
            "low_access",
        }

        # Preference flags come from Q9
        self.prefers_home_flags: Set[str] = {"strongly_prefers_home", "prefers_home"}
        self.open_to_move_flag: str = "open_to_move"

    # ------------------------ public API ------------------------

    def run(self, answers: Mapping[str, int], conditional_answer: Optional[Union[int, str]] = None) -> PlannerResult:
        flags = self._collect_flags(answers)

        care_type, reasons, advisory = self._decide(flags)

        # Scores/debug payload is optional; helpful for QA
        scores = self._scores_snapshot(flags)

        return PlannerResult(
            care_type=care_type,
            flags=flags,
            scores=scores,
            reasons=reasons,
            advisory=advisory,
        )

    # ------------------------ internals -------------------------

    def _collect_flags(self, answers: Mapping[str, int]) -> Set[str]:
        """
        Iterate Q&A spec and set flags based on the 'trigger' section.
        The Q&A JSON looks like:
          questions[*].trigger.<category>[{"answer": <int>, "flag": "<flag>"}]
        """
        out: Set[str] = set()
        questions: List[dict] = self.qa.get("questions", [])
        for i, q in enumerate(questions, start=1):
            key = f"q{i}"
            if key not in answers:
                continue
            chosen = answers[key]
            trigger = q.get("trigger") or {}
            for _category, rules in trigger.items():
                for rule in rules:
                    if int(rule.get("answer", -999)) == int(chosen):
                        flag = str(rule.get("flag", "")).strip()
                        if flag:
                            out.add(flag)
        return out

    def _decide(self, flags: Set[str]) -> (str, List[str], Optional[str]):
        reasons: List[str] = []
        advisory: Optional[str] = None

        # 1) Memory care checks (strict)
        if any(flag in flags for flag in self.thresholds["memory_care"]["any"]):
            reasons.append("Significant cognitive risk reported; 24/7 support is typically required.")
            return "memory_care", reasons, "Memory care is recommended due to safety and supervision needs."

        for need, companions in self.thresholds["memory_care"].get("combo", []):
            if need.issubset(flags) and any(c in flags for c in companions):
                reasons.append("Cognitive concerns combined with high care burden or low support.")
                return "memory_care", reasons, "Memory care is recommended considering cognition plus support/safety."

        # 2) Assisted living checks
        if any(flag in flags for flag in self.thresholds["assisted_living"]["any"]):
            hit = [f for f in self.thresholds["assisted_living"]["any"] if f in flags]
            reasons.append(f"Facility-level support indicated: {', '.join(sorted(hit))}.")
            return "assisted_living", reasons, "Daily assistance and safety monitoring available in assisted living."

        moderate_count = sum(1 for f in self.moderate_flags if f in flags)
        if moderate_count >= int(self.thresholds["assisted_living"]["count_moderate"]):
            reasons.append(f"Multiple moderate risk factors ({moderate_count}) suggest facility support.")
            return "assisted_living", reasons, "Assisted living is recommended for dependable daily support."

        # 3) In-home eligibility
        if any(f in flags for f in self.severe_flags):
            # safety valve: if any severe slipped through, do not return in-home
            reasons.append("Severe factors present; in-home without full-time support is unsafe.")
            return "assisted_living", reasons, "Assisted living better addresses risk profile."

        # Slight preference handling: strong preference + no severe + low moderate → in-home
        if moderate_count <= 1 and (self.prefers_home_flags & flags):
            reasons.append("Strong preference to remain at home with manageable risk.")
            return "in_home", reasons, "In-home care can work with the right support plan."

        # Default: in-home if risk is low and/or user isn’t opposed to moving
        reasons.append("Risks appear manageable with support.")
        return "in_home", reasons, "Start with in-home and reassess if needs increase."

    def _scores_snapshot(self, flags: Set[str]) -> Dict[str, Any]:
        return {
            "severe_hits": sorted(list(self.severe_flags & flags)),
            "moderate_hits": sorted(list(self.moderate_flags & flags)),
            "preference": sorted(list(self.prefers_home_flags & flags)) + (["open_to_move"] if self.open_to_move_flag in flags else []),
            "all_flags": sorted(list(flags)),
        }


# -------------------------- Calculator ------------------------------

class CalculatorEngine:
    """
    Cost model using your JSON lookups/settings.
    - Facility: base room + adders + state multiplier (+ memory multiplier if memory care)
    - In-home: hourly rate from hours/day matrix * hours/day * days/month + adders

    Inputs object may be a simple object or dict with fields:
        state, care_type, room_type, care_level, mobility, chronic,
        in_home_hours_per_day, in_home_days_per_month
    """

    def __init__(self, primary_calc_json: Optional[Union[str, Path]] = None, overlay_json: Optional[Union[str, Path]] = None):
        # Load both known files if available; otherwise allow app to pass explicit paths
        self.settings: dict = {}
        self.lookups: dict = {}
        self._load_calc_files(primary_calc_json, overlay_json)

    # Compatibility with legacy UI:
    def estimate(self, care_type: str) -> int:
        # Minimal fallback if someone calls old API by mistake
        base = {"assisted_living": 5200, "memory_care": int(5200 * 1.25), "in_home": 0}.get(care_type, 0)
        return int(base)

    def monthly_cost(self, inputs: Any) -> int:
        # accept object or dict
        g = (lambda k, default=None: (getattr(inputs, k, None) if not isinstance(inputs, dict) else inputs.get(k, None)) or default)

        state = g("state", "National")
        care_type = g("care_type", "in_home")
        room_type = g("room_type", "1 Bedroom")
        care_level = g("care_level", "Medium")
        mobility = g("mobility", "Independent")
        chronic = g("chronic", "Some")

        days_per_month = int(self.settings.get("days_per_month", 30))
        state_mult = float(_get(self.lookups, ["state_multipliers", state], 1.0))

        # Mobility severity → Low/Medium/High for adders
        mob_sev = {
            "Independent": "Low",
            "Independent (no device)": "Low",
            "Assisted": "Medium",
            "Assisted (cane/walker or needs help)": "Medium",
            "Non-ambulatory": "High",
            "Non-ambulatory (wheelchair/bedbound)": "High",
        }.get(str(mobility), "Low")

        chronic_add = int(_get(self.lookups, ["chronic_adders", str(chronic)], 0))

        if care_type in ("assisted_living", "memory_care"):
            base_room = int(_get(self.lookups, ["room_type", room_type], 5200))
            care_add = int(_get(self.lookups, ["care_level_adders", care_level], 0))
            mob_add = int(_get(self.lookups, ["mobility_adders", "facility", mob_sev], 0))

            total = (base_room + care_add + mob_add + chronic_add)
            total = int(total * state_mult)

            if care_type == "memory_care":
                mem_mult = float(self.settings.get("memory_care_multiplier", 1.25))
                total = int(total * mem_mult)
            return max(total, 0)

        # In-home
        hours_per_day = int(g("in_home_hours_per_day", 4))
        days = int(g("in_home_days_per_month", 20))
        if days <= 0:
            days = int(self.settings.get("days_per_month", 30))

        # pick hourly rate from the matrix; choose best matching tier <= chosen hours
        matrix: Dict[str, int] = _get(self.lookups, ["in_home_care_matrix"], {})
        applicable = sorted((int(h) for h in matrix.keys()))
        hourly = 42  # sane default
        for h in applicable:
            if hours_per_day >= h:
                hourly = int(matrix[str(h)])
        mob_add = int(_get(self.lookups, ["mobility_adders", "in_home", mob_sev], 0))
        care_add = int(_get(self.lookups, ["care_level_adders", care_level], 0))

        subtotal = (hourly * hours_per_day * days) + mob_add + care_add + chronic_add
        subtotal = int(subtotal * state_mult)
        return max(subtotal, 0)

    # ------------------------ internals -------------------------

    def _load_calc_files(self, primary: Optional[Union[str, Path]], overlay: Optional[Union[str, Path]]):
        # If the app supplies explicit paths, use them; otherwise try the known filenames beside the app
        merged = {}

        def merge_into(dst: dict, src: dict):
            for k, v in src.items():
                if isinstance(v, dict) and isinstance(dst.get(k), dict):
                    merge_into(dst[k], v)
                else:
                    dst[k] = v

        # Try to load overlay first (so the primary can fill gaps) or vice versa — either direction is fine,
        # we just want a merged dict with "settings" and "lookups" keys present.
        try:
            if overlay:
                merge_into(merged, _load_json(overlay))
        except Exception:
            pass
        try:
            if primary:
                merge_into(merged, _load_json(primary))
        except Exception:
            pass

        # The two files you provided contain "settings" and "lookups"; normalize them
        self.settings = merged.get("settings", {})
        # include some top-level keys that act like settings in your second file
        for k in ("ltc_monthly_add", "display_cap_years_funded", "memory_care_multiplier", "days_per_month"):
            if k in merged and k not in self.settings:
                self.settings[k] = merged[k]

        self.lookups = merged.get("lookups", {})
        # also hoist lookups that sit at top-level in one of your JSONs
        if "va_mapr_2025" in merged:
            self.lookups.setdefault("va_mapr_2025", merged["va_mapr_2025"])
        for key in ("state_multipliers", "care_level_adders", "mobility_adders", "chronic_adders", "room_type", "in_home_care_matrix"):
            self.lookups.setdefault(key, merged.get(key, {}))


# --------------------- Simple inputs shim (UI) -----------------------

class CalcInputs:
    """
    Convenience struct so the UI can pass object-like inputs (also accepts dict in monthly_cost).
    """
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)