# Google Timeline Analytics — Project Notes

## 📁 Project Location
`d:\health\`

## 🗂 File Structure
| File | Purpose |
|---|---|
| `app.py` | Streamlit main dashboard |
| `processor.py` | Core data ETL, geocoding, metrics |
| `chatbot.py` | Groq AI chatbot integration |
| `.streamlit/secrets.toml` | API keys (Groq) |
| `run_app.ps1` | Launch script |
| `requirements.txt` | Python dependencies |
| `sample_timeline.json` | Sample dataset for first-time users (Committed to Git) |
| `.geocache.pkl` | Persistent on-disk geocode cache (auto-generated) |

## ✅ What Has Been Built

### Data Pipeline (`processor.py`)
- Loads `Timeline.json` using `pd.json_normalize` on `semanticSegments`, `rawSignals`, `userLocationProfile`
- Datetime conversion + feature engineering (`start date`, `end date`, `start_hour`, `day_of_week`)
- Segment classification into **Activities** (moving) and **Visits** (stationary)
- E7 coordinate fallback parsing
- Special character cleaning (`Â`, `°`) in coordinates
- **Parallel geocoding** with `ThreadPoolExecutor(max_workers=10)` — ~10× faster than sequential
- **Persistent on-disk geocode cache** (`.geocache.pkl`) — coordinates never re-fetched across sessions
- **Global in-process geocode cache** — survives Streamlit widget interactions within a session
- **Module-level `@st.cache_data`** keyed on JSON string — ETL runs once, all widget changes are instant
- Transport mode normalisation: `SUBWAY` / `subway` → `Metro`
- Frequent Places extraction with custom name mapping and noise filtering

### Custom Location Mapping (hardcoded in `processor.py`)
| Coordinate | Name |
|---|---|
| `13.087, 80.198` | HOME_CHENNAI |
| `12.964, 80.194` | Work |
| `12.995, 80.199` | St Thomas Mt Metro |
| `13.090, 80.201` | Gym |
| `13.137–13.135, 79.909–79.910` | Hometown |
| `13.134, 79.912` | Hospital |
| `13.152, 79.858` | Friends Hangout spot |
| `13.086, 80.214` | Anna Nagar Tower Park |
| `13.081, 80.197` | Vr mall |
| `13.015, 80.204` | Olympia Towers |
| `13.108, 79.924` | Friends Hangout spot |
| `13.117, 79.914` | Thiruvallur Railway Station |
| `13.085, 80.275` | CHENNAI CENTRAL |
| `13.084, 80.202` | Friends PG |
| `12.991, 80.248` | Ramanujam IT Park |
| `13.085, 80.204` | Rams Tea / Frankie Spot |

### Dashboard (`app.py`)
- **KPI cards**: Total Visits, Unique Locations, Avg Stay, **Total Walking Distance**, **Total Walking Time** (all rounded)
- **Charts**:
  - Location vs Time Spent — **vertical** bar chart, `Turbo` colour scale, hours labelled inside bars
  - Transport Mode pie — hover shows rounded hours
  - Weekly/Monthly mobility trend (unique visits)
  - Dual-axis Walking trend — y-axes rounded to 1 decimal
  - Visit Intensity Heatmap (`density_map`)
- **Aesthetics**: Premium "Glassmorphism" design with **Inter** font, theme-aware CSS (works in dark/light mode), and transparent chart backgrounds
- **Mobile Responsive**: Columns stack vertically on screens < 640px
- **Landing Page**: Friendly instructions and feature highlights shown when no file is uploaded
- **Raw Data Explorer** tab: Segments, Signals, Frequent Places tables
- **Sidebar**: Data quality score, chatbot
- **Render order**: file processing happens before any UI draws so chatbot sidebar is always correct on first upload

### AI Chatbot (`chatbot.py`)
- Model: `llama-3.1-8b-instant` via Groq free API
- Context: auto-built from timeline data (locations, distances, modes, date range)
- UI: Streamlit native `st.chat_message` + `st.chat_input` in sidebar
- Chat history always renders **above** the input box
- Robust error handling if API key is missing or service is down

---

## 🔮 Future Enhancements (Resume Next Session)

### High Priority
- [ ] **Route visualisation** — Plot actual travel paths (start → end) on a map using Plotly `Scattermap`
- [ ] **Day-level drilldown** — Click a date on the trend line to see all visits/activities for that day
- [ ] **Commute analysis** — Time to work each day, average commute duration, most common route

### Medium Priority  
- [ ] **Health score card** — Weekly walking targets (e.g., 10,000 steps equivalent), progress bar
- [ ] **Location clusters** — Detect unknown/unnamed locations with DBSCAN spatial clustering and auto-label them
- [ ] **Chatbot memory** — Give the AI access to the actual segment-level data (not just summary) so it can answer specific date/time questions
- [ ] **Export** — Download processed data as CSV / Excel from the Raw Data tab

### Low Priority / Nice to Have
- [ ] **Dark mode** — CSS toggle for dark dashboard theme
- [ ] **Multi-file upload** — Merge multiple Timeline exports (different years)
- [ ] **Notification frequency score** — How predictable is your daily routine?

---

## ▶️ How to Run
```powershell
cd d:\health
.\run_app.ps1
```
Then open `http://localhost:8501` and upload `Timeline.json`.

---

## 📋 Changelog

### Session — 2026-03-18 (UX, Deployment & Robustness)

#### 🧪 Sample Data & Clean Repo
- **Sample Dataset**: Integrated `sample_timeline.json` into the repository. 
- **Auto-Load Features**: Added "Use Sample Data" buttons to the sidebar and landing page so new users can explore the app instantly without their own export.
- **Git Hygiene**: Cleaned up the project structure by removing `test_fix.py`, `preflight.py`, and old implementation logs. Updated `.gitignore` to specifically allow only the sample JSON file.

#### 🎨 Premium UI/UX (`app.py`)
- **Glassmorphism Design**: Metric cards and sidebar styled with semi-transparent backgrounds and subtle borders for a modern, sleek look.
- **Theme-Awareness**: CSS variables ensure visibility and aesthetics in both **Streamlit Light and Dark modes**. No more "white on white" or "black on black" issues.
- **Mobile First**: Added responsive breakpoints to stack layout columns on small devices, preventing horizontal scrolling.
- **Instructions**: New landing page with a clear "How to use" guide.

#### 🚀 Render Deployment Fixes
- **Startup Script**: Created `render_start.sh` with specific headless flags to bypass Chromium overhead and prevent initial health-check timeouts (Fixes 5-minute loading issue).
- **Upload Limit**: Increased maximum allowed file size to **200MB** to support large location history exports.

#### 🔧 ETL Stability (`processor.py`)
- **Iterative Parsing**: Replaced `pd.json_normalize` with a direct dictionary iteration pass. This fixed "out-of-memory" and "incorrect data shape" crashes (resolved issue where `timelinePath` lists broke the DataFrame).
- **Geocode Throttling**: Limited automatic geocoding to the **top 25 unknown locations**. This ensures the data processing always completes within the 30-40 second window required for browser-based apps.

### Session — 2026-03-17 (Performance & UI Polish)

#### ⚡ Performance (`processor.py`)
- **Fixed broken `@st.cache_data`** — was on an instance method (`_self`), Streamlit couldn't hash the object so cache was always skipped. Moved ETL to a module-level cached function keyed on the JSON string. Widget interactions (tabs, radio buttons) now re-render **instantly**.
- **Removed `st.rerun()`** after chatbot context build — previously caused a full second processing pass on every upload.
- **On-disk geocode cache** added (`.geocache.pkl`). Coordinates geocoded once are saved to disk and never re-fetched, even after app restarts.
- **In-process global geocode cache** (`_GLOBAL_GEO_CACHE`) survives Streamlit re-runs within the same session.
- **`max_workers` bumped** from 8 → 10 for the parallel geocoding thread pool.

| Scenario | Before | After |
|---|---|---|
| First upload (cold) | ~2 min | ~20–40 s |
| Same file re-uploaded | ~2 min | < 1 s |
| Clicking tabs/widgets | ~2 min | < 1 s |
| App restart, same file | ~2 min | < 5 s |

#### 🎨 UI Changes (`app.py`)
- KPI labels renamed: `Walking Dist` → **Total Walking Distance**, `Walking Time` → **Total Walking Time**; Avg Stay now shows whole number.
- **Bar chart flipped vertical** — x = location, y = hours; sorted descending (most time on left); labels angled −35°; hours printed inside bars.
- **Bar chart colour** changed from `Blues` (invisible on white background) → `Turbo` (vibrant, clear).
- **Pie chart hover** shows rounded hours instead of raw minutes.
- **Walking trend** y-axis values rounded to 1 decimal place.
- Fixed Plotly deprecation: `density_mapbox` → `density_map`, `mapbox_style` → `map_style`.

#### 🤖 Chatbot Fix (`app.py`)
- **Race condition fixed**: sidebar chatbot previously rendered before file processing, so on first upload it always showed "Upload your JSON" — even though the file was already loaded. Fixed by restructuring render order: process data first → set `chat_context` → then render sidebar.
- Chat history now always appears **above** the input box (not below it).

#### 🗺️ Location Mapping (`processor.py`)
- `13.134, 79.912`: renamed `Dental clinic` → **Hospital**
