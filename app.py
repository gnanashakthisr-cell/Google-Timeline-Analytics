import streamlit as st
import pandas as pd
import numpy as np
import json
import plotly.express as px
import plotly.graph_objects as go
from processor import TimelineProcessor, process_timeline_json
from chatbot import TimelineChatbot

# ── Page Config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Google Timeline Analytics",
    page_icon="📍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Theme-aware CSS (works in both light & dark mode) ────────────────────────
st.markdown("""
<style>
/* Import modern font */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* Root variables that adapt to Streamlit theme */
:root {
    --card-bg: rgba(255,255,255,0.05);
    --card-border: rgba(255,255,255,0.1);
    --card-shadow: 0 4px 20px rgba(0,0,0,0.3);
}

/* Override body font */
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

/* KPI metric cards — use Streamlit CSS variables so they work in both themes */
[data-testid="metric-container"] {
    background-color: rgba(255, 255, 255, 0.05) !important;
    padding: 16px 20px !important;
    border-radius: 14px !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    box-shadow: 0 4px 15px rgba(0,0,0,0.2) !important;
}

[data-testid="metric-container"] label {
    color: var(--text-color, #FAFAFA) !important;
    font-size: 0.8rem !important;
    font-weight: 500 !important;
    opacity: 0.8 !important;
}

[data-testid="metric-container"] [data-testid="stMetricValue"] {
    color: var(--text-color, #FAFAFA) !important;
    font-size: 1.8rem !important;
    font-weight: 700 !important;
}

/* Section headings */
.section-title {
    font-size: 1rem;
    font-weight: 600;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 6px;
}

/* Tabs styling */
[data-testid="stTab"] {
    font-weight: 500;
}

/* Sidebar */
[data-testid="stSidebar"] {
    border-right: 1px solid rgba(128,128,128,0.15);
}

/* Plotly chart containers */
[data-testid="stPlotlyChart"] {
    border-radius: 12px;
    overflow: hidden;
}

/* Mobile responsive: stack columns vertically on small screens */
@media (max-width: 640px) {
    [data-testid="column"] {
        width: 100% !important;
        flex: none !important;
    }
}
</style>
""", unsafe_allow_html=True)

# ── Plotly dark template globally ─────────────────────────────────────────────
CHART_TEMPLATE = "plotly_dark"   # works great on dark bg, still readable on light

# ── Initialise Processor & Chatbot ────────────────────────────────────────────
processor = TimelineProcessor()
CHAT_ENABLED = False
CHAT_ERROR   = ""

try:
    api_key = st.secrets.get("GROQ_API_KEY", "")
    if not api_key:
        CHAT_ERROR = "GROQ_API_KEY not set in secrets."
    else:
        chatbot = TimelineChatbot(api_key=api_key)
        CHAT_ENABLED = True
except Exception as e:
    CHAT_ERROR = str(e)

# ── Session state ─────────────────────────────────────────────────────────────
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "chat_context" not in st.session_state:
    st.session_state.chat_context = ""

# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Process data FIRST (before any UI renders)
# ══════════════════════════════════════════════════════════════════════════════
data, metrics = None, None
df_segments = df_activities = df_visits = pd.DataFrame()

# Sidebar file uploader
st.sidebar.title("🛠️ Control Center")
uploaded_file = st.sidebar.file_uploader("Upload Timeline JSON", type=["json"])

if uploaded_file:
    try:
        raw_bytes = uploaded_file.read()
        json_str  = raw_bytes.decode("utf-8")

        with st.spinner("⚙️ Analysing mobility patterns… (first run may take a minute for geocoding)"):
            data    = process_timeline_json(json_str)   # @st.cache_data — instant after first run
            metrics = processor.calculate_metrics(data)

        if not data['segments'].empty:
            df_segments   = data['segments']
            df_activities = data['activities']
            df_visits     = data['visits']

            # Build chatbot context BEFORE sidebar renders (critical)
            if CHAT_ENABLED and not st.session_state.chat_context:
                st.session_state.chat_context = chatbot.build_context(data, metrics)

    except Exception as e:
        st.error(f"❌ Error processing file: {e}")
        st.exception(e)
        st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Render Sidebar
# ══════════════════════════════════════════════════════════════════════════════

if data is not None and metrics:
    stats = metrics.get('cleaning_stats', {})
    st.sidebar.divider()
    st.sidebar.subheader("🗂 Data Summary")
    st.sidebar.write(f"**Records:** {stats.get('total_records', 0)}")
    q = metrics.get('quality_score', 0)
    st.sidebar.progress(int(q) / 100)
    st.sidebar.caption(f"Quality: {q:.1f}%")

st.sidebar.divider()
st.sidebar.subheader("💬 Timeline AI Assistant")

if not CHAT_ENABLED:
    st.sidebar.warning(f"⚠️ Chatbot unavailable — {CHAT_ERROR}")
elif not st.session_state.chat_context:
    st.sidebar.info("📤 Upload your JSON above to activate the AI assistant.")
else:
    user_input = st.sidebar.chat_input("Ask about your timeline…")

    if user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        reply = chatbot.chat(
            user_input,
            st.session_state.chat_history[:-1],
            st.session_state.chat_context
        )
        st.session_state.chat_history.append({"role": "assistant", "content": reply})

    for msg in st.session_state.chat_history:
        with st.sidebar.chat_message(msg["role"]):
            st.write(msg["content"])

# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Main Content Area
# ══════════════════════════════════════════════════════════════════════════════

st.title("📍 Google Timeline Analytics")
st.markdown("---")

if data is None:
    # Landing page with instructions
    col_a, col_b = st.columns([1, 1])
    with col_a:
        st.info("👋 **Upload your** `Semantic Location History.json` **to begin.**")
        st.markdown("""
        **How to export your Google Timeline:**
        1. Go to [Google Takeout](https://takeout.google.com)
        2. Select **Location History (Timeline)**
        3. Download and extract the ZIP
        4. Upload `Semantic Location History.json` using the sidebar
        """)
    with col_b:
        st.markdown("""
        ### 📊 What you'll see:
        - 🗺️ **Visit Hotspot Map** — where you spend time  
        - 📈 **Mobility Trends** — weekly/monthly patterns  
        - 🚶 **Walking Performance** — distance & duration  
        - 🚆 **Transport Modes** — breakdown by travel type  
        - 💬 **AI Chatbot** — ask questions about your data  
        """)
    st.stop()

if df_segments.empty:
    st.warning("⚠️ No valid data segments found in this file.")
    st.stop()

# ── Top KPIs ──────────────────────────────────────────────────────────────────
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("🏁 Total Visits",           metrics.get('total_visits', 0))
k2.metric("📍 Unique Locations",       metrics.get('unique_locations', 0))
k3.metric("⏱️ Avg Stay",               f"{round(metrics.get('avg_visit_duration', 0))} min")
k4.metric("🚶 Walking Distance",       f"{round(metrics.get('total_walking_km', 0), 1)} km")
k5.metric("⏰ Walking Time",           f"{round(metrics.get('total_walking_hrs', 0), 1)} hrs")
st.markdown("---")

dashboard_tab, explorer_tab = st.tabs(["📊 Analytics Dashboard", "📋 Raw Data Explorer"])

with dashboard_tab:
    col1, col2 = st.columns([3, 2])

    with col1:
        st.markdown('<div class="section-title">📊 Visit Location vs Time Spent</div>', unsafe_allow_html=True)
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
                color='total_hours',
                color_continuous_scale='Turbo',
                text='total_hours',
                template=CHART_TEMPLATE,
            )
            fig_bar.update_traces(texttemplate='%{text}h', textposition='inside')
            fig_bar.update_layout(
                showlegend=False, coloraxis_showscale=False,
                margin=dict(t=50, b=120),
                xaxis=dict(title='Location', tickangle=-35),
                yaxis=dict(title='Hours Spent', tickformat='.1f'),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
            )
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.info("No visit data available.")

    with col2:
        st.markdown('<div class="section-title">🚆 Transport Mode Distribution</div>', unsafe_allow_html=True)
        mode_dur = metrics.get('mode_duration_mins', {})
        if mode_dur:
            mode_df = pd.DataFrame(list(mode_dur.items()), columns=['Mode', 'Minutes'])
            mode_df['Hours'] = (mode_df['Minutes'] / 60).round(1)
            fig_pie = px.pie(
                mode_df, values='Minutes', names='Mode', hole=0.5,
                title="Time Spent per Mode",
                color_discrete_sequence=px.colors.qualitative.Prism,
                custom_data=['Hours'],
                template=CHART_TEMPLATE,
            )
            fig_pie.update_traces(
                hovertemplate='<b>%{label}</b><br>%{customdata[0]} hrs<extra></extra>'
            )
            fig_pie.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
            )
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("No transport mode data available.")

    st.markdown("---")
    trend_col, walk_col = st.columns(2)

    with trend_col:
        st.markdown('<div class="section-title">📈 Mobility Trend (Unique Visits)</div>', unsafe_allow_html=True)
        granularity = st.radio("Group By:", ["Weekly", "Monthly"], horizontal=True)
        if not df_visits.empty:
            df_v = df_visits.copy()
            df_v['dt'] = pd.to_datetime(df_v['start_time'])
            if granularity == "Weekly":
                df_v['period'] = df_v['dt'].dt.to_period('W').apply(lambda r: r.start_time)
            else:
                df_v['period'] = df_v['dt'].dt.to_period('M').apply(lambda r: r.start_time)
            trend_df = df_v.groupby('period')['display_name'].nunique().reset_index(name='unique_visits')
            fig_trend = px.line(
                trend_df, x='period', y='unique_visits', markers=True,
                title=f"{granularity} Unique Locations Visited",
                color_discrete_sequence=['#FF4B4B'],
                template=CHART_TEMPLATE,
            )
            fig_trend.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                xaxis_title="Period",
                yaxis_title="Unique Locations",
            )
            st.plotly_chart(fig_trend, use_container_width=True)
        else:
            st.info("No visit trend data available.")

    with walk_col:
        st.markdown('<div class="section-title">🚶 Walking Performance Trend</div>', unsafe_allow_html=True)
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
                    template=CHART_TEMPLATE,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    yaxis=dict(title="Distance (km)", tickformat='.1f'),
                    yaxis2=dict(title="Duration (hrs)", tickformat='.1f', overlaying='y', side='right'),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                st.plotly_chart(fig_walk, use_container_width=True)
            else:
                st.info("No walking activities detected.")
        else:
            st.info("No activity data available.")

    st.markdown("---")
    st.markdown('<div class="section-title">🗺️ Visit Hotspot Map</div>', unsafe_allow_html=True)
    if not df_visits.empty:
        map_df = df_visits.dropna(subset=['location_lat', 'location_lng'])
        if not map_df.empty:
            fig_map = px.density_map(
                map_df,
                lat='location_lat', lon='location_lng', z='duration_minutes',
                radius=20, zoom=10, map_style="carto-darkmatter",
                title="Visit Intensity Map",
                template=CHART_TEMPLATE,
            )
            fig_map.update_layout(
                height=500,
                margin=dict(t=40, b=0, l=0, r=0),
                paper_bgcolor='rgba(0,0,0,0)',
            )
            st.plotly_chart(fig_map, use_container_width=True)
        else:
            st.info("No location coordinates available for map.")
    else:
        st.info("No visit data for map.")

with explorer_tab:
    exp1, exp2, exp3 = st.tabs(["🎞️ Segments", "📡 Signals", "📍 Frequent Places"])
    with exp1:
        st.dataframe(df_segments, use_container_width=True)
    with exp2:
        st.dataframe(data.get('signal', pd.DataFrame()), use_container_width=True)
    with exp3:
        st.dataframe(data.get('frequent_places', pd.DataFrame()), use_container_width=True)