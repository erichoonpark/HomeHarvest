from __future__ import annotations

from difflib import SequenceMatcher
import json
from pathlib import Path
import re
from typing import Iterable

import pandas as pd

from str_neighborhood_summary import (
    NEIGHBORHOOD_CAP_DEFAULT,
    canonicalize_neighborhood_name,
    load_neighborhood_summary,
)


DEFAULT_PALM_SPRINGS_ZIPS = {"92258", "92262", "92263", "92264"}


def _is_missing_text(value: object) -> bool:
    if value is None or pd.isna(value):
        return True
    return str(value).strip() == ""


def _split_neighborhood_tokens(neighborhoods_value: str | None) -> list[str]:
    if neighborhoods_value is None or pd.isna(neighborhoods_value):
        return []
    parts = [p.strip() for p in re.split(r"[,;/|]+", str(neighborhoods_value)) if p.strip()]
    return parts


def _tokenize_text(value: str | None) -> set[str]:
    normalized = canonicalize_neighborhood_name(value or "")
    return {token for token in normalized.split() if len(token) >= 3}


def load_neighborhood_aliases(aliases_path: str | Path) -> dict[str, str]:
    path = Path(aliases_path)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return {
        canonicalize_neighborhood_name(alias): canonicalize_neighborhood_name(target) for alias, target in raw.items()
    }


def load_zip_crosswalk(crosswalk_path: str | Path) -> dict[str, set[str]]:
    path = Path(crosswalk_path)
    if not path.exists():
        return {}
    crosswalk_df = pd.read_csv(path)
    out: dict[str, set[str]] = {}
    for row in crosswalk_df.to_dict(orient="records"):
        key = canonicalize_neighborhood_name(row["organized_neighborhood"])
        zip_codes = {z.strip() for z in str(row.get("zip_codes", "")).split("|") if z and str(z).strip()}
        if zip_codes:
            out[key] = zip_codes
    return out


def _choose_best_match(
    candidates: Iterable[str],
    summary_keys: set[str],
    aliases: dict[str, str],
    zip_code: str,
    crosswalk: dict[str, set[str]],
) -> tuple[str | None, float]:
    best_key: str | None = None
    best_score = 0.0
    normalized_candidates = [canonicalize_neighborhood_name(c) for c in candidates if c]
    if not normalized_candidates:
        return None, 0.0

    for candidate in normalized_candidates:
        candidate = aliases.get(candidate, candidate)
        for summary_key in summary_keys:
            if summary_key not in crosswalk:
                continue
            if zip_code and zip_code not in crosswalk[summary_key]:
                continue
            score = SequenceMatcher(None, candidate, summary_key).ratio()
            if score > best_score:
                best_score = score
                best_key = summary_key

    if best_key is None:
        # Fallback when no crosswalk row exists for a workbook neighborhood.
        for candidate in normalized_candidates:
            candidate = aliases.get(candidate, candidate)
            for summary_key in summary_keys:
                score = SequenceMatcher(None, candidate, summary_key).ratio()
                if score > best_score:
                    best_score = score
                    best_key = summary_key
    return best_key, best_score


def _build_zip_candidates(crosswalk: dict[str, set[str]], summary_keys: set[str]) -> dict[str, list[str]]:
    zip_candidates: dict[str, list[str]] = {}
    for key, zip_codes in crosswalk.items():
        if key not in summary_keys:
            continue
        for zip_code in zip_codes:
            zip_candidates.setdefault(zip_code, []).append(key)
    return zip_candidates


def _build_zip_dominant_neighborhood(
    summary_by_key: dict[str, dict],
    zip_candidates: dict[str, list[str]],
) -> dict[str, str]:
    dominant: dict[str, str] = {}
    for zip_code, keys in zip_candidates.items():
        if not keys:
            continue
        dominant[zip_code] = max(
            keys,
            key=lambda key: (
                int(summary_by_key.get(key, {}).get("total_residential_units", 0) or 0),
                key,
            ),
        )
    return dominant


def infer_neighborhood_key_from_address_or_zip(
    street: str | None,
    zip_code: str,
    zip_candidates: dict[str, list[str]],
    zip_dominant: dict[str, str],
) -> tuple[str | None, str | None, float | None]:
    candidates = zip_candidates.get(zip_code, [])
    if not candidates:
        return None, None, None

    street_tokens = _tokenize_text(street)
    street_normalized = canonicalize_neighborhood_name(street or "")

    best_key: str | None = None
    best_score = 0.0
    for key in candidates:
        key_tokens = set(key.split())
        overlap = len(street_tokens & key_tokens)
        token_score = overlap / max(len(key_tokens), 1)
        phrase_bonus = 1.0 if key in street_normalized and key else 0.0
        score = max(token_score, phrase_bonus)
        if score > best_score:
            best_score = score
            best_key = key

    if best_key and best_score >= 0.5:
        return best_key, "address_tokens", best_score

    dominant_key = zip_dominant.get(zip_code)
    if dominant_key:
        return dominant_key, "zip_dominant", None

    return None, None, None


def enrich_with_palm_springs_str_neighborhoods(
    properties_df: pd.DataFrame,
    *,
    summary_path: str | Path,
    crosswalk_path: str | Path,
    aliases_path: str | Path,
    cap_threshold: float = NEIGHBORHOOD_CAP_DEFAULT,
    palm_springs_zips: Iterable[str] = DEFAULT_PALM_SPRINGS_ZIPS,
    min_match_score: float = 0.70,
) -> pd.DataFrame:
    if properties_df.empty:
        return properties_df.copy()

    summary_df = load_neighborhood_summary(summary_path)
    summary_by_key = summary_df.set_index("neighborhood_key").to_dict(orient="index")
    summary_keys = set(summary_by_key.keys())
    aliases = load_neighborhood_aliases(aliases_path)
    crosswalk = load_zip_crosswalk(crosswalk_path)
    ps_zips = {str(z) for z in palm_springs_zips}
    zip_candidates = _build_zip_candidates(crosswalk, summary_keys)
    zip_dominant = _build_zip_dominant_neighborhood(summary_by_key, zip_candidates)
    zip_aggregate_stats: dict[str, dict] = {}

    for zip_code in ps_zips:
        zip_keys = [k for k, zips in crosswalk.items() if zip_code in zips and k in summary_by_key]
        if not zip_keys:
            continue
        scoped = [summary_by_key[k] for k in zip_keys]
        total_units = sum(int(r.get("total_residential_units", 0) or 0) for r in scoped)
        weight_total = total_units if total_units > 0 else len(scoped)

        def weighted(metric: str) -> float:
            if total_units > 0:
                return (
                    sum(float(r[metric]) * int(r.get("total_residential_units", 0) or 0) for r in scoped) / total_units
                )
            return sum(float(r[metric]) for r in scoped) / max(len(scoped), 1)

        zip_aggregate_stats[zip_code] = {
            "organized_neighborhood": f"ZIP {zip_code} aggregate",
            "current_neighborhood_percentage": weighted("current_neighborhood_percentage"),
            "projected_neighborhood_percentage": weighted("projected_neighborhood_percentage"),
            "current_number_on_wait_list": int(sum(int(r["current_number_on_wait_list"]) for r in scoped)),
            "applications_processing": int(sum(int(r["applications_processing"]) for r in scoped)),
        }

    enriched = properties_df.copy()
    if "neighborhoods" in enriched.columns:
        enriched["neighborhoods"] = enriched["neighborhoods"].astype("object")
    enriched["str_organized_neighborhood"] = pd.NA
    enriched["str_neighborhood_match_score"] = pd.NA
    enriched["str_nbhd_current_pct"] = pd.NA
    enriched["str_nbhd_projected_pct"] = pd.NA
    enriched["str_nbhd_waitlist"] = pd.NA
    enriched["str_nbhd_apps_processing"] = pd.NA
    enriched["str_nbhd_under_cap_current"] = pd.NA
    enriched["str_nbhd_under_cap_projected"] = pd.NA
    enriched["str_nbhd_headroom_notes"] = pd.NA

    for idx, row in enriched.iterrows():
        city = str(row.get("city", "")).strip().lower()
        zip_code = str(row.get("zip_code", "")).strip()
        neighborhoods_value = row.get("neighborhoods")
        is_ps_row = city == "palm springs" or zip_code in ps_zips
        if not is_ps_row:
            if _is_missing_text(neighborhoods_value) and zip_code:
                enriched.at[idx, "neighborhoods"] = f"ZIP {zip_code}"
            enriched.at[idx, "str_nbhd_headroom_notes"] = (
                "Palm Springs neighborhood-cap enrichment not applicable for this city."
            )
            continue

        candidates = _split_neighborhood_tokens(neighborhoods_value)
        best_key, best_score = _choose_best_match(
            candidates=candidates,
            summary_keys=summary_keys,
            aliases=aliases,
            zip_code=zip_code,
            crosswalk=crosswalk,
        )
        inferred_key, infer_method, infer_score = infer_neighborhood_key_from_address_or_zip(
            street=row.get("street"),
            zip_code=zip_code,
            zip_candidates=zip_candidates,
            zip_dominant=zip_dominant,
        )

        resolved_key = None
        match_score = None
        if best_key and best_score >= min_match_score:
            resolved_key = best_key
            match_score = best_score
        elif inferred_key:
            resolved_key = inferred_key
            match_score = infer_score

        if not resolved_key:
            zip_stats = zip_aggregate_stats.get(zip_code)
            if zip_stats:
                current_pct = float(zip_stats["current_neighborhood_percentage"])
                projected_pct = float(zip_stats["projected_neighborhood_percentage"])
                enriched.at[idx, "str_organized_neighborhood"] = zip_stats["organized_neighborhood"]
                enriched.at[idx, "str_nbhd_current_pct"] = current_pct
                enriched.at[idx, "str_nbhd_projected_pct"] = projected_pct
                enriched.at[idx, "str_nbhd_waitlist"] = int(zip_stats["current_number_on_wait_list"])
                enriched.at[idx, "str_nbhd_apps_processing"] = int(zip_stats["applications_processing"])
                enriched.at[idx, "str_nbhd_under_cap_current"] = current_pct < cap_threshold
                enriched.at[idx, "str_nbhd_under_cap_projected"] = projected_pct < cap_threshold
                enriched.at[idx, "str_nbhd_headroom_notes"] = (
                    "Estimated from ZIP-level neighborhood aggregate (listing neighborhood text missing/ambiguous)."
                )
            else:
                enriched.at[idx, "str_nbhd_headroom_notes"] = (
                    "No confident Organized Neighborhood match from listing neighborhood text."
                )
            if best_key and best_score:
                enriched.at[idx, "str_neighborhood_match_score"] = round(best_score, 4)
            continue

        stats = summary_by_key[resolved_key]
        current_pct = float(stats["current_neighborhood_percentage"])
        projected_pct = float(stats["projected_neighborhood_percentage"])

        enriched.at[idx, "str_organized_neighborhood"] = stats["organized_neighborhood"]
        if match_score is not None:
            enriched.at[idx, "str_neighborhood_match_score"] = round(match_score, 4)
        enriched.at[idx, "str_nbhd_current_pct"] = current_pct
        enriched.at[idx, "str_nbhd_projected_pct"] = projected_pct
        enriched.at[idx, "str_nbhd_waitlist"] = int(stats["current_number_on_wait_list"])
        enriched.at[idx, "str_nbhd_apps_processing"] = int(stats["applications_processing"])
        enriched.at[idx, "str_nbhd_under_cap_current"] = current_pct < cap_threshold
        enriched.at[idx, "str_nbhd_under_cap_projected"] = projected_pct < cap_threshold
        if _is_missing_text(neighborhoods_value):
            enriched.at[idx, "neighborhoods"] = stats["organized_neighborhood"]

        if infer_method == "address_tokens":
            enriched.at[idx, "str_nbhd_headroom_notes"] = (
                "Neighborhood inferred from street/address tokens constrained by ZIP crosswalk."
            )
        elif infer_method == "zip_dominant":
            enriched.at[idx, "str_nbhd_headroom_notes"] = (
                "Neighborhood inferred from ZIP-dominant organized neighborhood."
            )
        else:
            enriched.at[idx, "str_nbhd_headroom_notes"] = (
                "Neighborhood cap benchmark is 20%; junior permits may not count toward cap."
            )

    return enriched
