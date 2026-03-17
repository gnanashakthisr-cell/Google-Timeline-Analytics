import streamlit as st
import pandas as pd
import numpy as np
import json
import re
import time
import os
import pickle
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from geopy.geocoders import Nominatim

# ── Persistent on-disk geocode cache ─────────────────────────────────────────
_CACHE_FILE = Path(__file__).parent / ".geocache.pkl"

def _load_disk_cache() -> Dict[str, str]:
    try:
        if _CACHE_FILE.exists():
            with open(_CACHE_FILE, "rb") as f:
                return pickle.load(f)
    except Exception:
        pass
    return {}

def _save_disk_cache(cache: Dict[str, str]):
    try:
        with open(_CACHE_FILE, "wb") as f:
            pickle.dump(cache, f)
    except Exception:
        pass

# Shared in-process geocode cache (survives Streamlit re-runs in same process)
_GLOBAL_GEO_CACHE: Dict[str, str] = _load_disk_cache()

LOCATION_MAPPING: Dict[str, str] = {
    "13.087, 80.198": "HOME_CHENNAI",
    "12.964, 80.194": "Work",
    "12.995, 80.199": "St Thomas Mt Metro",
    "13.090, 80.201": "Gym",
    "13.137, 79.910": "Hometown",
    "13.136, 79.910": "Hometown",
    "13.135, 79.909": "Hometown",
    "13.134, 79.912": "Hospital",
    "13.152, 79.858": "Friends Hangout spot",
    "13.086, 80.214": "Anna Nagar Tower Park",
    "13.081, 80.197": "Vr mall",
    "13.015, 80.204": "Olympia Towers",
    "13.088, 80.200": "Gym",
    "13.108, 79.924": "Friends Hangout spot",
    "13.117, 79.914": "Thiruvallur Railway Station",
    "13.085, 80.275": "CHENNAI CENTRAL",
    "13.084, 80.202": "Friends PG",
    "12.991, 80.248": "Ramanujam IT Park",
    "13.085, 80.204": "Rams Tea / Frankie Spot",
}
TO_REMOVE = {"13.085, 80.202", "13.137, 79.909", "13.085, 80.201"}


# ── Module-level cached ETL (avoids re-runs on every widget interaction) ─────
@st.cache_data(show_spinner=False)
def process_timeline_json(json_data_str: str) -> Dict[str, Any]:
    """
    Full ETL pipeline. Accepts the raw JSON as a *string* so st.cache_data
    can hash it cheaply. Returns DataFrames as dicts of records (serialisable).
    """
    json_data = json.loads(json_data_str)

    if 'semanticSegments' in json_data:
        data_copy = pd.json_normalize(json_data['semanticSegments'])
    else:
        data_copy = pd.json_normalize(json_data.get('timelineObjects', []))

    signal = pd.json_normalize(json_data.get('rawSignals', []))
    user_location_profile = json_data.get('userLocationProfile', {})
    user_location = pd.json_normalize(user_location_profile)

    # --- Frequent Places ---
    frequent_places = pd.DataFrame()
    if 'frequentPlaces' in user_location_profile:
        frequent_places = pd.json_normalize(user_location_profile['frequentPlaces'])
        if not frequent_places.empty and 'placeLocation' in frequent_places.columns:
            frequent_places["placeLocation"] = (
                frequent_places["placeLocation"]
                .str.replace("Â", "").str.replace("°", "").str.strip()
            )
            frequent_places = frequent_places[~frequent_places["placeLocation"].isin(TO_REMOVE)]
            frequent_places["Location Name"] = frequent_places["placeLocation"].map(LOCATION_MAPPING)
            frequent_places = frequent_places.rename(columns={"placeId": "Google Place ID"})
            cols = ["Location Name", "placeLocation", "semanticType", "Google Place ID"]
            cols = [c for c in cols if c in frequent_places.columns]
            cols += [c for c in frequent_places.columns if c not in cols]
            frequent_places = frequent_places[cols]

    empty_result = {
        'segments': pd.DataFrame(), 'activities': pd.DataFrame(),
        'visits': pd.DataFrame(), 'data_copy': data_copy,
        'signal': signal, 'user_location': user_location,
        'frequent_places': frequent_places
    }

    if data_copy.empty:
        return empty_result

    if 'startTime' in data_copy.columns:
        data_copy['startTime'] = pd.to_datetime(data_copy['startTime'], utc=True)
    if 'endTime' in data_copy.columns:
        data_copy['endTime'] = pd.to_datetime(data_copy['endTime'], utc=True)

    # ── Vectorised column detection ───────────────────────────────────────────
    activity_cols = [c for c in data_copy.columns if c.startswith(('activity', 'activitySegment'))]
    visit_cols    = [c for c in data_copy.columns if c.startswith(('visit', 'placeVisit'))]

    pfx_act = 'activitySegment.' if 'activitySegment.distance' in data_copy.columns else 'activity.'
    pfx_vis = 'placeVisit.' if 'placeVisit.hierarchyLevel' in data_copy.columns else 'visit.'
    loc_p   = (f'{pfx_vis}topCandidate.placeLocation.'
               if f'{pfx_vis}topCandidate.placeLocation.latLng' in data_copy.columns
               else f'{pfx_vis}location.')

    # ── Build activity rows vectorised ───────────────────────────────────────
    activities_data = []
    visits_data     = []

    if activity_cols:
        act_mask = data_copy[activity_cols].notna().any(axis=1)
        act_rows = data_copy[act_mask]
        for idx, row in act_rows.iterrows():
            s_lat, s_lng = _clean_coords(row.get(f'{pfx_act}start.latLng') or row.get(f'{pfx_act}startLocation.latLng'))
            e_lat, e_lng = _clean_coords(row.get(f'{pfx_act}end.latLng')   or row.get(f'{pfx_act}endLocation.latLng'))
            if np.isnan(s_lat) and f'{pfx_act}startLocation.latitudeE7' in row.index:
                s_lat = row[f'{pfx_act}startLocation.latitudeE7'] / 1e7
                s_lng = row[f'{pfx_act}startLocation.longitudeE7'] / 1e7
            if np.isnan(e_lat) and f'{pfx_act}endLocation.latitudeE7' in row.index:
                e_lat = row[f'{pfx_act}endLocation.latitudeE7'] / 1e7
                e_lng = row[f'{pfx_act}endLocation.longitudeE7'] / 1e7
            mode = row.get(f'{pfx_act}topCandidate.type') or row.get(f'{pfx_act}activityType', 'UNKNOWN')
            activities_data.append({
                'segment_id': idx + 1,
                'start_time': row.get('startTime'), 'end_time': row.get('endTime'),
                'start_lat': s_lat, 'start_lng': s_lng, 'end_lat': e_lat, 'end_lng': e_lng,
                'distance_km': (row.get(f'{pfx_act}distanceMeters') or row.get(f'{pfx_act}distance', 0)) / 1000.0,
                'mode_type': mode,
                'probability': row.get(f'{pfx_act}topCandidate.probability', 0.0),
            })

    if visit_cols:
        vis_mask = data_copy[visit_cols].notna().any(axis=1)
        vis_rows = data_copy[vis_mask]
        for idx, row in vis_rows.iterrows():
            lat, lng = _clean_coords(row.get(f'{loc_p}latLng'))
            if np.isnan(lat) and f'{loc_p}latitudeE7' in row.index:
                lat  = row[f'{loc_p}latitudeE7'] / 1e7
                lng  = row[f'{loc_p}longitudeE7'] / 1e7
            coord_key = f"{lat:.3f}, {lng:.3f}" if not np.isnan(lat) else ""
            if coord_key in TO_REMOVE:
                continue
            visits_data.append({
                'segment_id': idx + 1,
                'start_time': row.get('startTime'), 'end_time': row.get('endTime'),
                'location_lat': lat, 'location_lng': lng,
                'json_name': row.get(f'{loc_p}name') or row.get(f'{loc_p}address'),
                'semantic_type': row.get(f'{pfx_vis}topCandidate.semanticType') or row.get(f'{pfx_vis}placeConfidence', 'UNKNOWN'),
                'coord_key': coord_key,
            })

    df_act = pd.DataFrame(activities_data)
    df_vis = pd.DataFrame(visits_data)

    for df in [df_act, df_vis]:
        if not df.empty:
            df['duration_minutes'] = (df['end_time'] - df['start_time']).dt.total_seconds() / 60
            df['date'] = df['start_time'].dt.date

    # ── Normalise transport mode ──────────────────────────────────────────────
    if not df_act.empty:
        df_act['mode_type'] = df_act['mode_type'].replace(
            ['SUBWAY', 'subway'], 'Metro', regex=True
        )

    # ── Auto parallel geocoding for visits ───────────────────────────────────
    if not df_vis.empty:
        needs_geo = df_vis[
            (~df_vis['coord_key'].isin(LOCATION_MAPPING)) &
            (df_vis['json_name'].isna() | (df_vis['json_name'] == ""))
        ].drop_duplicates(subset=['coord_key'])

        unique_coords = [
            (row['coord_key'], row['location_lat'], row['location_lng'])
            for _, row in needs_geo.iterrows()
            if not np.isnan(row['location_lat'])
        ]

        geo_map: Dict[str, str] = {}
        if unique_coords:
            geo_map = _reverse_geocode_batch(unique_coords)

        def _display(row):
            if row['coord_key'] in LOCATION_MAPPING:
                return LOCATION_MAPPING[row['coord_key']]
            if row['semantic_type'] == 'INFERRED_WORK': return 'Work'
            if row['semantic_type'] == 'INFERRED_HOME': return 'Home'
            if pd.notna(row['json_name']) and row['json_name'] not in ["", "Unknown Location"]:
                return str(row['json_name']).split(',')[0]
            geo_name = geo_map.get(row['coord_key'], '')
            if geo_name and geo_name != 'Unknown Location':
                return geo_name
            return f"Loc ({row['location_lat']:.3f}, {row['location_lng']:.3f})"

        df_vis['display_name'] = df_vis.apply(_display, axis=1)
        df_vis = df_vis.rename(columns={'json_name': 'location_name'})

    df_seg = pd.concat([
        df_act.assign(segment_type='Activity'),
        df_vis.assign(segment_type='Visit')
    ]).sort_values('start_time').reset_index(drop=True)

    return {
        'segments': df_seg, 'activities': df_act, 'visits': df_vis,
        'data_copy': data_copy, 'signal': signal,
        'user_location': user_location, 'frequent_places': frequent_places,
    }


# ── Geocoding helpers (module-level, no class overhead) ──────────────────────

def _make_geolocator():
    return Nominatim(user_agent=f"timeline_analyzer_{time.time()}", timeout=5)


def _geocode_one(args: Tuple[str, float, float]) -> Tuple[str, str]:
    """Geocode a single lat/lng pair. Returns (key, name)."""
    key, lat, lng = args
    try:
        geo = _make_geolocator()
        result = geo.reverse((lat, lng), exactly_one=True, language='en')
        if result:
            addr = result.raw.get('address', {})
            name = ", ".join(filter(None, [
                addr.get('road'),
                addr.get('suburb', addr.get('village', addr.get('neighbourhood'))),
                addr.get('city', addr.get('town'))
            ]))
            return key, (name if name else result.address.split(',')[0])
    except Exception:
        pass
    return key, "Unknown Location"


def _reverse_geocode_batch(
    unique_coords: List[Tuple[str, float, float]],
    max_workers: int = 10,
) -> Dict[str, str]:
    """
    Parallel geocoding. Uses global in-process + on-disk cache so repeated
    uploads of the same file skip all network calls instantly.
    """
    global _GLOBAL_GEO_CACHE

    to_fetch = [(k, la, ln) for k, la, ln in unique_coords if k not in _GLOBAL_GEO_CACHE]

    if not to_fetch:
        return _GLOBAL_GEO_CACHE.copy()

    progress = st.progress(0, text=f"Geocoding {len(to_fetch)} new locations…")
    new_results: Dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_geocode_one, args): args[0] for args in to_fetch}
        done = 0
        for future in as_completed(future_map):
            key, name = future.result()
            new_results[key] = name
            _GLOBAL_GEO_CACHE[key] = name
            done += 1
            progress.progress(done / len(to_fetch), text=f"Geocoding: {done}/{len(to_fetch)}")

    progress.empty()
    _save_disk_cache(_GLOBAL_GEO_CACHE)   # persist to disk for next session
    return _GLOBAL_GEO_CACHE.copy()


def _clean_coords(coord_str: Optional[str]) -> Tuple[float, float]:
    if not isinstance(coord_str, str):
        return np.nan, np.nan
    try:
        nums = re.findall(r"[-+]?\d*\.\d+|\d+", coord_str.replace("Â", "").replace('°', ''))
        if len(nums) >= 2:
            return float(nums[0]), float(nums[1])
    except Exception:
        pass
    return np.nan, np.nan


# ── TimelineProcessor (thin wrapper retained for app.py compatibility) ────────
class TimelineProcessor:
    """Thin wrapper so app.py import continues to work unchanged."""

    def process_timeline_json(self, json_data: Dict[str, Any]) -> Dict[str, Any]:
        return process_timeline_json(json.dumps(json_data, default=str))

    def calculate_metrics(self, data: Dict[str, Any]) -> Dict[str, Any]:
        df_act = data.get('activities', pd.DataFrame())
        df_vis = data.get('visits',     pd.DataFrame())
        d_copy = data.get('data_copy',  pd.DataFrame())
        if df_act.empty and df_vis.empty:
            return {}

        total_v   = len(df_vis)
        unique_l  = df_vis['display_name'].nunique() if not df_vis.empty else 0
        avg_v_dur = df_vis['duration_minutes'].mean() if not df_vis.empty else 0
        total_d   = df_act['distance_km'].sum()       if not df_act.empty else 0
        m_dist    = df_act.groupby('mode_type')['distance_km'].sum().to_dict()       if not df_act.empty else {}
        total_a_m = df_act['duration_minutes'].sum()  if not df_act.empty else 0
        total_v_m = df_vis['duration_minutes'].sum()  if not df_vis.empty else 0
        m_dur     = df_act.groupby('mode_type')['duration_minutes'].sum().to_dict()  if not df_act.empty else {}

        walk_km  = m_dist.get('WALKING', 0)
        walk_hrs = m_dur.get('WALKING', 0) / 60.0
        q_score  = (
            (df_act[['start_lat', 'end_lat']].notna().all(axis=1).sum()
             + df_vis['location_lat'].notna().sum()) / len(d_copy) * 100
        ) if len(d_copy) > 0 else 0

        return {
            'total_visits': total_v, 'unique_locations': unique_l,
            'avg_visit_duration': avg_v_dur, 'total_dist_km': total_d,
            'mode_dist': m_dist, 'total_activity_hrs': total_a_m / 60,
            'total_visit_hrs': total_v_m / 60,
            'activity_ratio': (total_a_m / (total_a_m + total_v_m) * 100)
                              if (total_a_m + total_v_m) > 0 else 0,
            'mode_duration_mins': m_dur, 'quality_score': q_score,
            'total_walking_km': walk_km, 'total_walking_hrs': walk_hrs,
            'cleaning_stats': {
                'total_records': len(d_copy),
                'cleaned_coords': int(q_score * len(d_copy) / 100),
            },
        }