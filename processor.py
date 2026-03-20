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

_COORD_RE = re.compile(r"[-+]?\d*\.\d+|\d+")
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

@st.cache_data(show_spinner=False)
def process_timeline_json(json_data_str: str) -> Dict[str, Any]:
    """
    Highly optimized ETL. Iterates raw dicts directly to avoid 
    the massive overhead of pd.json_normalize on large nested arrays.
    """
    json_data = json.loads(json_data_str)
    
    segments_list = json_data.get('semanticSegments') or json_data.get('timelineObjects', [])
    
    activities_data = []
    visits_data = []
    
    for idx, item in enumerate(segments_list):
        act = item.get('activitySegment') or item.get('activity')
        vis = item.get('placeVisit') or item.get('visit')
        
        s_time = item.get('startTime')
        e_time = item.get('endTime')

        if act:
            start_loc = act.get('startLocation') or act.get('start') or {}
            end_loc   = act.get('endLocation')   or act.get('end')   or {}
            
            s_lat, s_lng = _clean_coords(start_loc.get('latLng'))
            e_lat, e_lng = _clean_coords(end_loc.get('latLng'))
            
            if np.isnan(s_lat) and 'latitudeE7' in start_loc:
                s_lat, s_lng = start_loc['latitudeE7']/1e7, start_loc['longitudeE7']/1e7
            if np.isnan(e_lat) and 'latitudeE7' in end_loc:
                e_lat, e_lng = end_loc['latitudeE7']/1e7, end_loc['longitudeE7']/1e7
                
            mode = act.get('topCandidate', {}).get('type') or act.get('activityType', 'UNKNOWN')
            dist = (act.get('distanceMeters') or act.get('distance', 0)) / 1000.0
            
            activities_data.append({
                'segment_id': idx + 1, 'start_time': s_time, 'end_time': e_time,
                'start_lat': s_lat, 'start_lng': s_lng, 'end_lat': e_lat, 'end_lng': e_lng,
                'distance_km': dist, 'mode_type': mode,
                'probability': act.get('topCandidate', {}).get('probability', 0.0)
            })

        elif vis:
            loc_root = (vis.get('topCandidate', {}).get('placeLocation') or 
                       vis.get('location') or {})
            
            lat, lng = _clean_coords(loc_root.get('latLng'))
            if np.isnan(lat) and 'latitudeE7' in loc_root:
                lat, lng = loc_root['latitudeE7']/1e7, loc_root['longitudeE7']/1e7
            
            coord_key = f"{lat:.3f}, {lng:.3f}" if not np.isnan(lat) else ""
            if coord_key in TO_REMOVE: continue
            
            visits_data.append({
                'segment_id': idx + 1, 'start_time': s_time, 'end_time': e_time,
                'location_lat': lat, 'location_lng': lng,
                'json_name': loc_root.get('name') or loc_root.get('address'),
                'semantic_type': vis.get('topCandidate', {}).get('semanticType') or vis.get('placeConfidence', 'UNKNOWN'),
                'coord_key': coord_key
            })

    df_act = pd.DataFrame(activities_data)
    df_vis = pd.DataFrame(visits_data)

    for df in [df_act, df_vis]:
        if not df.empty:
            df['start_time'] = pd.to_datetime(df['start_time'], utc=True)
            df['end_time']   = pd.to_datetime(df['end_time'],   utc=True)
            df['duration_minutes'] = (df['end_time'] - df['start_time']).dt.total_seconds() / 60
            df['date'] = df['start_time'].dt.date
            if 'mode_type' in df.columns:
                df['mode_type'] = df['mode_type'].replace(['SUBWAY', 'subway'], 'Metro', regex=True)

    if not df_vis.empty:
        needs_geo = (
            df_vis[(~df_vis['coord_key'].isin(LOCATION_MAPPING)) & 
                   (df_vis['json_name'].isna() | (df_vis['json_name'] == ""))]
            .groupby('coord_key')
            .size()
            .sort_values(ascending=False)
            .head(25)
            .reset_index()
        )

        unique_coords = []
        for _, row in needs_geo.iterrows():
            match = df_vis[df_vis['coord_key'] == row['coord_key']].iloc[0]
            unique_coords.append((row['coord_key'], match['location_lat'], match['location_lng']))

        geo_map = _reverse_geocode_batch(unique_coords) if unique_coords else {}

        def _get_name(row):
            k = row['coord_key']
            if k in LOCATION_MAPPING: return LOCATION_MAPPING[k]
            if row['semantic_type'] == 'INFERRED_WORK': return 'Work'
            if row['semantic_type'] == 'INFERRED_HOME': return 'Home'
            name = row['json_name']
            if pd.notna(name) and name not in ["", "Unknown Location"]:
                return str(name).split(',')[0]
            return geo_map.get(k, f"Loc ({row['location_lat']:.3f}, {row['location_lng']:.3f})")

        df_vis['display_name'] = df_vis.apply(_get_name, axis=1)
        df_vis = df_vis.rename(columns={'json_name': 'location_name'})

    df_seg = pd.concat([
        df_act.assign(segment_type='Activity'),
        df_vis.assign(segment_type='Visit')
    ]).sort_values('start_time').reset_index(drop=True) if (not df_act.empty or not df_vis.empty) else pd.DataFrame()

    signal = pd.DataFrame(json_data.get('rawSignals', []))
    if not signal.empty: signal = signal.head(1000) # Only keep a preview to save time

    frequent_places = pd.DataFrame()
    profile = json_data.get('userLocationProfile', {})
    if 'frequentPlaces' in profile:
        frequent_places = pd.DataFrame(profile['frequentPlaces'])
        if not frequent_places.empty and 'placeLocation' in frequent_places.columns:
            frequent_places["placeLocation"] = frequent_places["placeLocation"].str.replace("[Â°]", "", regex=True).str.strip()
            frequent_places["Location Name"] = frequent_places["placeLocation"].map(LOCATION_MAPPING)

    return {
        'segments': df_seg, 'activities': df_act, 'visits': df_vis,
        'signal': signal, 'frequent_places': frequent_places,
        'data_count': len(segments_list)
    }

def _make_geolocator():
    return Nominatim(user_agent=f"timeline_analyzer_{time.time()}", timeout=3)

def _geocode_one(args: Tuple[str, float, float]) -> Tuple[str, str]:
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
    except Exception: pass
    finally: time.sleep(0.12) # Respect Nominatim 1req/sec
    return key, "Unknown Location"

def _reverse_geocode_batch(unique_coords: List[Tuple[str, float, float]], max_workers: int = 8) -> Dict[str, str]:
    global _GLOBAL_GEO_CACHE
    to_fetch = [c for c in unique_coords if c[0] not in _GLOBAL_GEO_CACHE]
    if not to_fetch: return _GLOBAL_GEO_CACHE.copy()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_geocode_one, args): args[0] for args in to_fetch}
        for f in as_completed(future_map):
            k, n = f.result()
            _GLOBAL_GEO_CACHE[k] = n

    _save_disk_cache(_GLOBAL_GEO_CACHE)
    return _GLOBAL_GEO_CACHE.copy()

def _clean_coords(val: Any) -> Tuple[float, float]:
    if not isinstance(val, str): return np.nan, np.nan
    try:
        nums = _COORD_RE.findall(val.replace("Â", ""))
        if len(nums) >= 2: return float(nums[0]), float(nums[1])
    except: pass
    return np.nan, np.nan

class TimelineProcessor:
    def process_timeline_json(self, json_data: Dict[str, Any]) -> Dict[str, Any]:
        return process_timeline_json(json.dumps(json_data, default=str))

    def calculate_metrics(self, data: Dict[str, Any]) -> Dict[str, Any]:
        df_act = data.get('activities', pd.DataFrame())
        df_vis = data.get('visits',     pd.DataFrame())
        count  = data.get('data_count', 0)
        
        if df_act.empty and df_vis.empty: return {}

        total_v   = len(df_vis)
        unique_l  = df_vis['display_name'].nunique() if not df_vis.empty else 0
        avg_v_dur = df_vis['duration_minutes'].mean() if not df_vis.empty else 0
        total_d   = df_act['distance_km'].sum() if not df_act.empty else 0
        m_dist    = df_act.groupby('mode_type')['distance_km'].sum().to_dict() if not df_act.empty else {}
        m_dur     = df_act.groupby('mode_type')['duration_minutes'].sum().to_dict() if not df_act.empty else {}

        total_a_m = df_act['duration_minutes'].sum() if not df_act.empty else 0
        total_v_m = df_vis['duration_minutes'].sum() if not df_vis.empty else 0
        
        walk_km  = m_dist.get('WALKING', 0)
        walk_hrs = m_dur.get('WALKING', 0) / 60.0
        
        populated = (df_act['start_lat'].notna().sum() + df_vis['location_lat'].notna().sum())
        q_score = (populated / count * 100) if count > 0 else 0

        return {
            'total_visits': total_v, 'unique_locations': unique_l,
            'avg_visit_duration': avg_v_dur, 'total_dist_km': total_d,
            'mode_dist': m_dist, 'mode_duration_mins': m_dur,
            'quality_score': q_score, 'total_walking_km': walk_km, 'total_walking_hrs': walk_hrs,
            'activity_ratio': (total_a_m / (total_a_m + total_v_m) * 100) if (total_a_m + total_v_m) > 0 else 0,
            'cleaning_stats': { 'total_records': count }
        }
