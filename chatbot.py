import streamlit as st
import pandas as pd
from typing import List, Dict, Any

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False


class TimelineChatbot:
    """Groq-powered chatbot that answers questions about the user's Google Timeline."""

    MODEL = "llama-3.1-8b-instant"   # Free, fast, 128k context

    def __init__(self, api_key: str):
        if not GROQ_AVAILABLE:
            raise ImportError("groq package not installed. Run: pip install groq")
        self._client = Groq(api_key=api_key)

    # ------------------------------------------------------------------
    # Context builder – turns DataFrames + metrics into a system prompt
    # ------------------------------------------------------------------
    def build_context(self, data: Dict[str, Any], metrics: Dict[str, Any]) -> str:
        df_vis = data.get('visits', pd.DataFrame())
        df_act = data.get('activities', pd.DataFrame())

        # Date range
        date_range = "unknown"
        if not df_vis.empty and 'start_time' in df_vis:
            dates = pd.to_datetime(df_vis['start_time'])
            date_range = f"{dates.min().date()} to {dates.max().date()}"

        # Top locations
        top_locs = ""
        if not df_vis.empty and 'display_name' in df_vis.columns:
            loc_counts = df_vis.groupby('display_name').agg(
                visits=('display_name', 'count'),
                hours=('duration_minutes', lambda x: round(x.sum() / 60, 1))
            ).sort_values('hours', ascending=False).head(8)
            rows = [f"  • {r.Index}: {r.visits} visits, {r.hours} hrs" for r in loc_counts.itertuples()]
            top_locs = "\n".join(rows)

        # Transport mode breakdown
        mode_dur = metrics.get('mode_duration_mins', {})
        modes_str = ", ".join([f"{m}: {round(h/60,1)} hrs" for m, h in sorted(mode_dur.items(), key=lambda x: -x[1])]) if mode_dur else "N/A"

        context = f"""You are a personal mobility data assistant for the user.
You have access to the user's full Google Timeline analytics. Answer questions conversationally and concisely.

=== TIMELINE SUMMARY ===
Period: {date_range}

--- Key KPIs ---
Total Visits: {metrics.get('total_visits', 'N/A')}
Unique Locations Visited: {metrics.get('unique_locations', 'N/A')}
Average Visit Duration: {round(metrics.get('avg_visit_duration', 0), 1)} minutes
Total Distance Travelled: {round(metrics.get('total_dist_km', 0), 1)} km
Active Time Ratio: {round(metrics.get('activity_ratio', 0), 1)}%
Data Quality Score: {round(metrics.get('quality_score', 0), 1)}%

--- Walking Health ---
Walking Distance: {round(metrics.get('total_walking_km', 0), 2)} km
Walking Time: {round(metrics.get('total_walking_hrs', 0), 2)} hrs

--- Transport Modes (time spent) ---
{modes_str}

--- Top Locations ---
{top_locs if top_locs else 'No visit data available.'}

=== INSTRUCTIONS ===
- Be concise and friendly. Use bullet points when listing multiple items.
- If the user asks something not in the data above, say you don't have that detail.
- Refer to locations by their familiar names (e.g., HOME_CHENNAI, Work, Gym).
- Use Indian English naturally (e.g., distances in km).
"""
        return context

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------
    def chat(self, user_message: str, history: List[Dict[str, str]], context: str) -> str:
        messages = [{"role": "system", "content": context}]
        # include recent history (last 8 turns to stay under token limits)
        messages += history[-8:]
        messages.append({"role": "user", "content": user_message})
        try:
            response = self._client.chat.completions.create(
                model=self.MODEL,
                messages=messages,
                max_tokens=512,
                temperature=0.6,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"⚠️ Chatbot error: {e}"
