import streamlit as st
import pandas as pd
import numpy as np
import json
import plotly.express as px
import plotly.graph_objects as go
from processor import TimelineProcessor, process_timeline_json
from chatbot import TimelineChatbot

# ── Page Config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Google Timeline Analytics", page_icon="📍", layout="wide")

# ── Initialise Processor & Chatbot ────────────────────────────────────────────
processor = TimelineProcessor()
try:
    chatbot = TimelineChatbot(api_key=st.secrets["GROQ_API_KEY"])
    CHAT_ENABLED = True
except Exception:
    CHAT_ENABLED = False

# ── Session state ─────────────────────────────────────────────────────────────
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "chat_context" not in st.session_state:
    st.session_state.chat_context = ""

# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Process data FIRST (before any UI renders)
#   This guarantees chat_context is populated before the sidebar draws,
#   so the chatbot input always appears correctly on the very first upload.
# ══════════════════════════════════════════════════════════════════════════════
data, metrics = None, None
df_segments = df_activities = df_visits = pd.DataFrame()

# Sidebar file uploader must be declared here so uploaded_file is available
st.sidebar.title("🛠️ Control Center")
uploaded_file = st.sidebar.file_uploader("Upload Timeline JSON", type=["json"])

if uploaded_file:
    try:
        raw_bytes = uploaded_file.read()
        json_str  = raw_bytes.decode("utf-8")

        with st.spinner("Analysing mobility patterns & geocoding locations in parallel…"):
            data    = process_timeline_json(json_str)   # @st.cache_data — instant after first run
            metrics = processor.calculate_metrics(data)

        if not data['segments'].empty:
            df_segments   = data['segments']
            df_activities = data['activities']
            df_visits     = data['visits']

            # Build chatbot context BEFORE sidebar renders (critical fix)
            if CHAT_ENABLED and not st.session_state.chat_context:
                st.session_state.chat_context = chatbot.build_context(data, metrics)

    except Exception as e:
        st.error(f"Error processing file: {e}")
        st.exception(e)
        st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Render Sidebar (context is now guaranteed to be set if data loaded)
# ══════════════════════════════════════════════════════════════════════════════

# Sidebar data summary (only when data is loaded)
if data is not None and metrics:
    stats = metrics.get('cleaning_stats', {})
    st.sidebar.divider()
    st.sidebar.subheader("🗂 Data Summary")
    st.sidebar.write(f"**Records:** {stats.get('total_records', 0)}")
    st.sidebar.progress(metrics.get('quality_score', 0) / 100)
    st.sidebar.caption(f"Quality: {metrics.get('quality_score', 0):.1f}%")

# Sidebar chatbot
st.sidebar.divider()
st.sidebar.subheader("💬 Timeline AI Assistant")

if not CHAT_ENABLED:
    st.sidebar.warning("Chatbot unavailable — check GROQ_API_KEY in secrets.toml")
elif not st.session_state.chat_context:
    st.sidebar.info("Upload your JSON above to activate the AI assistant.")
else:
    # Process new user message first, then render history above input
    user_input = st.sidebar.chat_input("Ask about your timeline…")

    if user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        reply = chatbot.chat(
            user_input,
            st.session_state.chat_history[:-1],   # history excluding the just-added msg
            st.session_state.chat_context
        )
        st.session_state.chat_history.append({"role": "assistant", "content": reply})

    # Always render full history above the chat input
    for msg in st.session_state.chat_history:
        with st.sidebar.chat_message(msg["role"]):
            st.write(msg["content"])

# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Main Content Area
# ══════════════════════════════════════════════════════════════════════════════

# Custom CSS
st.markdown("""<style>
.stMetric { background:white; padding:15px; border-radius:12px;
            box-shadow:0 4px 12px rgba(0,0,0,0.05); border:1px solid #eee; }
</style>""", unsafe_allow_html=True)

st.title("📍 Google Timeline Analytics")
st.markdown("---")

if data is None:
    st.info("👋 Upload your `Semantic Location History.json` to begin.")
    st.stop()

if df_segments.empty:
    st.warning("⚠️ No valid data segments found in this file.")
    st.stop()

# ── Top KPIs ──────────────────────────────────────────────────────────────────
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total Visits",           metrics.get('total_visits', 0))
k2.metric("Unique Locations",       metrics.get('unique_locations', 0))
k3.metric("Avg Stay",               f"{round(metrics.get('avg_visit_duration', 0))} min")
k4.metric("Total Walking Distance", f"{round(metrics.get('total_walking_km', 0), 1)} km")
k5.metric("Total Walking Time",     f"{round(metrics.get('total_walking_hrs', 0), 1)} hrs")
st.markdown("---")

dashboard_tab, explorer_tab = st.tabs(["📊 Analytics Dashboard", "📋 Raw Data Explorer"])

with dashboard_tab:
    col1, col2 = st.columns([3, 2])

    with col1:
        st.write("**📊 Visit Location vs Time Spent**")
        if not df_visits.empty:
            loc_summary = (
                df_visits.groupby('display_name')['duration_minutes']
                .sum().reset_index()
                .rename(columns={'duration_minutes': 'total_hours'})
            )
            loc_summary['total_hours'] = (loc_summary['total_hours'] / 60).round(1)
            loc_summary = loc_summary.sort_values('total_hours', ascending=False).head(15)
            fig_bar = px.bar(
                loc_summary, x='display_name', y='total_hours',
                title="Top 15 Locations by Total Time Spent",
                labels={'display_name': 'Location', 'total_hours': 'Hours Spent'},
                color='total_hours', color_continuous_scale='Turbo',
                text='total_hours'
            )
            fig_bar.update_traces(texttemplate='%{text}h', textposition='inside')
            fig_bar.update_layout(
                showlegend=False, coloraxis_showscale=False,
                margin=dict(t=40, b=120),
                xaxis=dict(title='Location', tickangle=-35),
                yaxis=dict(title='Hours Spent', tickformat='.1f')
            )
            st.plotly_chart(fig_bar, use_container_width=True)

    with col2:
        st.write("**🚆 Transport Mode Distribution**")
        mode_dur = metrics.get('mode_duration_mins', {})
        if mode_dur:
            mode_df = pd.DataFrame(list(mode_dur.items()), columns=['Mode', 'Minutes'])
            mode_df['Hours'] = (mode_df['Minutes'] / 60).round(1)
            fig_pie = px.pie(
                mode_df, values='Minutes', names='Mode', hole=0.5,
                title="Time Spent per Mode (incl. Walking)",
                color_discrete_sequence=px.colors.qualitative.Prism,
                custom_data=['Hours']
            )
            fig_pie.update_traces(
                hovertemplate='<b>%{label}</b><br>%{customdata[0]} hrs<extra></extra>'
            )
            st.plotly_chart(fig_pie, use_container_width=True)

    st.markdown("---")
    trend_col, walk_col = st.columns(2)

    with trend_col:
        st.write("**📈 Mobility Trend (Unique Visits)**")
        granularity = st.radio("Group By:", ["Weekly", "Monthly"], horizontal=True)
        if not df_visits.empty:
            df_v = df_visits.copy()
            df_v['dt'] = pd.to_datetime(df_v['start_time'])
            if granularity == "Weekly":
                df_v['period'] = df_v['dt'].dt.to_period('W').apply(lambda r: r.start_time)
            else:
                df_v['period'] = df_v['dt'].dt.to_period('M').apply(lambda r: r.start_time)
            trend_df = df_v.groupby('period')['display_name'].nunique().reset_index(name='unique_visits')
            fig_trend = px.line(trend_df, x='period', y='unique_visits', markers=True,
                                title=f"{granularity} Unique Locations Visited",
                                color_discrete_sequence=['#FF4B4B'])
            st.plotly_chart(fig_trend, use_container_width=True)

    with walk_col:
        st.write("**🚶 Walking Performance Trend**")
        if not df_activities.empty:
            df_w = df_activities[df_activities['mode_type'].str.upper() == 'WALKING'].copy()
            if not df_w.empty:
                df_w['dt']   = pd.to_datetime(df_w['start_time'])
                df_w['week'] = df_w['dt'].dt.to_period('W').apply(lambda r: r.start_time)
                walk_trend = df_w.groupby('week').agg(
                    distance=('distance_km', 'sum'),
                    duration=('duration_minutes', lambda x: x.sum() / 60)
                ).reset_index()
                fig_walk = go.Figure()
                fig_walk.add_trace(go.Scatter(
                    x=walk_trend['week'], y=walk_trend['distance'].round(1),
                    name='Dist (km)', line=dict(color='#2ECC71', width=3)
                ))
                fig_walk.add_trace(go.Scatter(
                    x=walk_trend['week'], y=walk_trend['duration'].round(1),
                    name='Time (hrs)', line=dict(color='#3498DB', width=3), yaxis='y2'
                ))
                fig_walk.update_layout(
                    title="Weekly Walking Distance & Duration",
                    yaxis=dict(title="Distance (km)",  tickformat='.1f'),
                    yaxis2=dict(title="Duration (hrs)", tickformat='.1f', overlaying='y', side='right'),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                st.plotly_chart(fig_walk, use_container_width=True)
            else:
                st.info("No walking activities detected.")

    st.markdown("---")
    st.write("**🗺️ Visit Hotspot Map**")
    if not df_visits.empty:
        fig_map = px.density_map(
            df_visits.dropna(subset=['location_lat', 'location_lng']),
            lat='location_lat', lon='location_lng', z='duration_minutes',
            radius=20, zoom=10, map_style="open-street-map",
            title="Visit Intensity Map"
        )
        fig_map.update_layout(height=500, margin=dict(t=30, b=0, l=0, r=0))
        st.plotly_chart(fig_map, use_container_width=True)

with explorer_tab:
    exp1, exp2, exp3 = st.tabs(["🎞️ Segments", "📡 Signals", "📍 Frequent Places"])
    with exp1: st.dataframe(df_segments,                                 use_container_width=True)
    with exp2: st.dataframe(data.get('signal',          pd.DataFrame()), use_container_width=True)
    with exp3: st.dataframe(data.get('frequent_places', pd.DataFrame()), use_container_width=True)