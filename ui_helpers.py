# ui_helpers.py — safe helpers for JSON answer maps
from __future__ import annotations
import streamlit as st

def _is_intlike(x) -> bool:
    try:
        int(str(x))
        return True
    except Exception:
        return False

def order_answer_map(amap: dict[str, str]) -> tuple[list[str], list[str]]:
    if not isinstance(amap, dict) or not amap:
        return [], []
    keys = list(amap.keys())
    if all(_is_intlike(k) for k in keys):
        ordered_keys = [str(k) for k in sorted(int(str(k)) for k in keys)]
    else:
        ordered_keys = [str(k) for k in keys]
    labels = [amap[k] for k in ordered_keys]
    return ordered_keys, labels

def radio_from_answer_map(label, amap, *, key, help_text=None, default_key=None) -> str | None:
    keys, labels = order_answer_map(amap)
    if not labels:
        return default_key
    if default_key is not None and str(default_key) in keys:
        idx = keys.index(str(default_key))
    else:
        idx = 0
    sel_label = st.radio(label, labels, index=idx, key=key, help=help_text)
    return keys[labels.index(sel_label)]