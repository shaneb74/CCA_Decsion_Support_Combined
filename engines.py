# engines.py — minimal, stable engines with in-home fix
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Set, Union

# ---------------- Planner ----------------
class PlannerEngine:
    """
    Loads Q/A and recommendation logic JSONs and returns a simple recommendation.
    This stays intentionally conservative: it won't surprise your UI.
    """
    def __init__(self, qa_path: str, rec_path: str):
        self.qa_path = Path(qa_path)
        self.rec_path = Path(rec_path)

        with self.qa_path.open("r", encoding="utf-8") as f:
            self.qa = json.load(f)

        with Path(rec_path).open("r", encoding="utf-8") as f:
            self.rec = json.load(f)

        # Optional thresholds in your rec JSON
        self.final_thresholds: Dict[str, int] = (
            self.rec.get("final_thresholds") or
            self.rec.get("thresholds") or
            {"in_home": 0, "assisted_living": 6, "memory_care": 10}
        )

    def _score(self, answers: Dict[str, int]) -> int:
        # Extremely boring scoring: sum numeric answers. Your JSON can override this later.
        try:
            return int(sum(int(v) for v in answers.values()))
        except Exception:
            return 0

    def run(self, answers: Dict[str, int], conditional_answer: Optional[Union[str, int]] = None):
        score = self._score(answers)

        # Map to care_type using thresholds
        al_cut = int(self.final_thresholds.get("assisted_living", 6))
        mc_cut = int(self.final_thresholds.get("memory_care", 10))

        if score >= mc_cut:
            care_type = "memory_care"
        elif score >= al_cut:
            care_type = "assisted_living"
        else:
            care_type = "in_home"

        # Lightweight flags/reasons
        flags: Set[str] = set()
        reasons = []
        advisory = None

        # Try to detect mobility question if present in your Q text
        for key, val in answers.items():
            q_idx = int(key.replace("q", "")) if key.startswith("q") and key[1:].isdigit() else None
            if q_idx:
                try:
                    q_text = self.qa["questions"][q_idx - 1]["question"].lower()
                except Exception:
                    q_text = ""
                if "memory" in q_text and int(val) >= 3:
                    flags.add("severe_cognitive_decline")
                    reasons.append("Memory-related responses suggest higher supervision needs.")
                if "mobility" in q_text and int(val) >= 3:
                    flags.add("limited_mobility")
                    reasons.append("Mobility responses suggest assistance or wheelchair use.")

        if care_type == "assisted_living":
            advisory = "Assisted living is recommended. With strong in-home support, staying home may still be possible."
        elif care_type == "memory_care":
            advisory = "Memory care is recommended for safety and specialized support."

        return {
            "care_type": care_type,
            "flags": flags,
            "scores": {"total": score},
            "reasons": reasons,
            "advisory": advisory,
        }

# ---------------- Calculator ----------------
@dataclass
class CalcInputs:
    state: str = "National"
    care_type: str = "in_home"  # in_home | assisted_living | memory_care
    care_level: str = "Medium"  # Low | Medium | High
    mobility: str = "Independent"  # Independent | Assisted | Non-ambulatory
    chronic: str = "Some"  # None | Some | Multiple/Complex

    # in-home only
    in_home_hours_per_day: int = 4
    in_home_days_per_month: int = 20

    # residence only
    room_type: str = "Studio"  # Studio | 1 Bedroom | Shared

class CalculatorEngine:
    """
    Stable calculator with explicit in-home hours/day × days/month math and simple
    multipliers for care level, mobility, chronic conditions, and state.
    """
    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        self.settings: Dict[str, Any] = settings or {}

        # Base monthly for facility; hourly for in-home
        self.base: Dict[str, float] = self.settings.get("base_rates", {
            "assisted_living": 5200.0,     # monthly
            "memory_care": 6500.0,         # monthly
            "in_home": 35.0,               # hourly
        })

        # Room type multipliers for facility
        self.room_mult: Dict[str, float] = self.settings.get("room_mult", {
            "Studio": 1.00,
            "1 Bedroom": 1.15,
            "Shared": 0.85,
        })

        # State adjustment multipliers
        self.state_adj: Dict[str, float] = self.settings.get("state_adj", {
            "National": 1.00,
            "Washington": 1.18,
            "California": 1.22,
            "Texas": 0.95,
            "Florida": 1.02,
        })

    # Public convenience if your old app called .estimate("in_home")
    def estimate(self, care_type: str) -> int:
        return self.monthly_cost(CalcInputs(care_type=care_type))

    def monthly_cost(self, inputs: Union[CalcInputs, Any]) -> int:
        care = getattr(inputs, "care_type", "in_home")
        state = getattr(inputs, "state", "National")
        care_level = getattr(inputs, "care_level", "Medium")
        mobility = getattr(inputs, "mobility", "Independent")
        chronic = getattr(inputs, "chronic", "Some")

        # Common multipliers
        level_mult = {"Low": 0.90, "Medium": 1.00, "High": 1.20}.get(care_level, 1.00)
        mob_mult = {"Independent": 1.00, "Assisted": 1.08, "Non-ambulatory": 1.15}.get(mobility, 1.00)
        chrn_mult = {"None": 0.95, "Some": 1.00, "Multiple/Complex": 1.15}.get(chronic, 1.00)
        state_mult = float(self.state_adj.get(state, 1.0))

        if care == "in_home":
            # --- THIS IS THE FIX: hours/day × days/month × hourly ---
            hpd = int(getattr(inputs, "in_home_hours_per_day", 4) or 4)
            dpm = int(getattr(inputs, "in_home_days_per_month", 20) or 20)
            hourly = float(self.base.get("in_home", 35.0))
            hours_month = max(hpd, 0) * max(dpm, 0)
            est = hours_month * hourly
            total = est * level_mult * mob_mult * chrn_mult * state_mult
            return int(round(max(total, 0)))

        # Assisted living / memory care
        if care in ("assisted_living", "memory_care"):
            base = float(self.base.get(care, 5000.0))
            room = getattr(inputs, "room_type", "Studio")
            room_k = room if room in self.room_mult else "Studio"
            total = base * self.room_mult[room_k] * level_mult * mob_mult * chrn_mult * state_mult
            return int(round(max(total, 0)))

        # Fallback
        return int(round(max(float(self.base.get("assisted_living", 5200.0)) * state_mult, 0)))