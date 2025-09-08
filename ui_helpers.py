# ui_helpers.py — common UI helpers for radios & session

from __future__ import annotations
from typing import Dict, List, Tuple, Optional
import streamlit as st


def _is_intlike(x) -> bool:
    try:
        int(str(x))
        return True
    except Exception:
        return False


def order_answer_map(amap: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """
    Return (ordered_keys, ordered_labels) safely, whether amap keys are '1','2',... or arbitrary.
    Preserves insertion order when keys are not all int-like.
    """
    if not isinstance(amap, dict) or not amap:
        return [], []
    keys = list(amap.keys())
    if all(_is_intlike(k) for k in keys):
        ordered_keys = [str(k) for k in sorted(int(str(k)) for k in keys)]
    else:
        ordered_keys = [str(k) for k in keys]  # keep JSON insertion order
    labels = [amap[k] for k in ordered_keys]
    return ordered_keys, labels


def radio_from_answer_map(
    label: str,
    amap: Dict[str, str],
    *,
    key: str,
    help_text: Optional[str] = None,
    default_key: Optional[str] = None,
) -> Optional[str]:
    """
    Render a radio from a JSON answer map and return the SELECTED KEY (string).
    Falls back to default_key (if provided) or the first ordered option.
    """
    keys, labels = order_answer_map(amap)
    if not labels:
        return default_key
    idx = keys.index(str(default_key)) if (default_key is not None and str(default_key) in keys) else 0
    sel = st.radio(label, labels, index=idx, key=key, help=help_text)
    return keys[labels.index(sel)] if sel in labels else default_key


def use_state(key: str, default):
    """Get or set a default value in session_state."""
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]