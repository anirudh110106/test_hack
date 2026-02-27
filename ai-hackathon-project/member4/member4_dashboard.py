import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

import folium
import requests
import polyline
from folium.plugins import HeatMap


BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parent

MEMBER1_POINTS = REPO_DIR / "member1" / "output_data.json"
MEMBER2_POINTS = REPO_DIR / "member2" / "points_with_clusters.json"
MEMBER2_CLUSTERS = REPO_DIR / "member2" / "clusters.json"
MEMBER3_INTEL = REPO_DIR / "member3" / "intelligence.json"


CONFIDENCE_COLOR = {
    "HIGH": "green",
    "MEDIUM": "orange",
    "LOW": "red",
}


def _load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_points():
    """
    Pipeline-first:
    - Prefer member2/points_with_clusters.json (has cluster_id)
    - Fallback to member1/output_data.json (no clusters) with cluster_id=-1
    """
    if MEMBER2_POINTS.exists():
        points = _load_json(MEMBER2_POINTS)
        for p in points:
            p.setdefault("cluster_id", -1)
    elif MEMBER1_POINTS.exists():
        points = _load_json(MEMBER1_POINTS)
        for p in points:
            p["cluster_id"] = -1
    else:
        raise FileNotFoundError(
            f"Missing data: expected {MEMBER2_POINTS} or {MEMBER1_POINTS}"
        )

    points = sorted(points, key=lambda x: x.get("timestamp") or "9999")
    return points


def load_clusters_meta():
    return _load_json(MEMBER2_CLUSTERS) if MEMBER2_CLUSTERS.exists() else {}


def load_intelligence():
    return _load_json(MEMBER3_INTEL) if MEMBER3_INTEL.exists() else {}


def cluster_label(cluster_id: int, clusters_meta: dict) -> str:
    for c in clusters_meta.get("clusters", []):
        if c.get("cluster_id") == cluster_id:
            lat, lon = c.get("center", [None, None])
            visits = c.get("visits", "?")
            if lat is not None and lon is not None:
                return f"Cluster {cluster_id} ({lat:.4f}, {lon:.4f}) • visits {visits}"
            return f"Cluster {cluster_id} • visits {visits}"
    return f"Cluster {cluster_id}"


def infer_confidence(point: dict, clusters_meta: dict) -> str:
    """
    Practical rule:
    - cluster_id == -1 => LOW (noise / unclustered)
    - clusters with highest visits => HIGH
    - other clustered => MEDIUM
    """
    cid = int(point.get("cluster_id", -1))
    if cid == -1:
        return "LOW"

    clusters = clusters_meta.get("clusters", [])
    if not clusters:
        return "MEDIUM"

    top_visits = max((c.get("visits", 0) for c in clusters), default=0)
    cid_visits = next((c.get("visits", 0) for c in clusters if c.get("cluster_id") == cid), 0)
    return "HIGH" if cid_visits == top_visits and top_visits > 0 else "MEDIUM"


def haversine_km(a_lat, a_lon, b_lat, b_lon) -> float:
    r = 6371.0
    dlat = radians(b_lat - a_lat)
    dlon = radians(b_lon - a_lon)
    lat1 = radians(a_lat)
    lat2 = radians(b_lat)
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * r * asin(sqrt(h))


def compute_total_distance_km(points) -> float:
    if len(points) < 2:
        return 0.0
    dist = 0.0
    for i in range(len(points) - 1):
        a = points[i]
        b = points[i + 1]
        dist += haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
    return dist


@dataclass
class Exposure:
    score_10: int
    label: str
    explanation: str
    bar_pct: int


def compute_exposure(points, summary: dict) -> Exposure:
    """
    Simple heuristic score (0-10) to make the UI practical.
    Higher score when there are identifiable repeated clusters and long history.
    """
    if not points:
        return Exposure(0, "Low", "No data", 0)

    cluster_ids = [p.get("cluster_id", -1) for p in points if p.get("cluster_id", -1) != -1]
    unique_clusters = len(set(cluster_ids))
    total = len(points)
    anomalies = int(summary.get("anomalies_detected", 0))

    score = 3
    if total >= 10:
        score += 2
    if unique_clusters >= 2:
        score += 2
    if unique_clusters >= 3:
        score += 1
    if anomalies == 0:
        score += 1
    # cap
    score = max(0, min(10, score))

    if score >= 7:
        return Exposure(score, "High", "Home/work clusters likely identifiable", min(100, score * 10))
    if score >= 4:
        return Exposure(score, "Medium", "Some routine patterns visible", min(100, score * 10))
    return Exposure(score, "Low", "Limited routine patterns visible", min(100, score * 10))


def build_summary(points, intel: dict, clusters_meta: dict) -> dict:
    if not points:
        return {
            "total_locations": 0,
            "total_distance_km": 0.0,
            "avg_daily_distance_km": 0.0,
            "most_visited_place": "N/A",
            "inferred_home": "N/A",
            "inferred_work": "N/A",
            "most_active_hour": "N/A",
            "most_active_day": "N/A",
            "night_movement_pct": 0.0,
            "anomalies_detected": 0,
            "date_range": "N/A",
        }

    # Total distance from member3 if present; else compute
    intel_summary = intel.get("summary", {})
    total_distance_km = float(intel_summary.get("total_distance_km", compute_total_distance_km(points)))

    # Date range and avg daily distance (filter out None timestamps)
    timestamps = []
    for p in points:
        ts = p.get("timestamp")
        if ts:
            try:
                timestamps.append(datetime.fromisoformat(ts))
            except (ValueError, TypeError):
                pass

    if not timestamps:
        return {
            "total_locations": len(points),
            "total_distance_km": round(total_distance_km, 2),
            "avg_daily_distance_km": 0.0,
            "most_visited_place": "N/A",
            "inferred_home": "N/A",
            "inferred_work": "N/A",
            "most_active_hour": "N/A",
            "most_active_day": "N/A",
            "night_movement_pct": 0.0,
            "anomalies_detected": 0,
            "date_range": "N/A",
        }

    timestamps_sorted = sorted(timestamps)
    first_ts = timestamps_sorted[0]
    last_ts = timestamps_sorted[-1]
    unique_days = {ts.date() for ts in timestamps_sorted}
    days_count = max(1, len(unique_days))
    avg_daily_distance_km = total_distance_km / days_count

    # Home/work from member3 dwell_times (top 2)
    inferred_home = "Unknown"
    inferred_work = "Unknown"
    most_visited_place = "Unknown"

    dwell = intel.get("dwell_times", {})
    if dwell:
        dwell_list = sorted(
            dwell.values(),
            key=lambda d: d.get("total_dwell_seconds", 0),
            reverse=True,
        )
        if dwell_list:
            home_cluster_id = int(dwell_list[0]["cluster_id"])
            inferred_home = cluster_label(home_cluster_id, clusters_meta)
            most_visited_place = inferred_home
            if len(dwell_list) > 1:
                work_cluster_id = int(dwell_list[1]["cluster_id"])
                inferred_work = cluster_label(work_cluster_id, clusters_meta)

    # Active hour/day
    hour_counts = Counter(ts.hour for ts in timestamps_sorted)
    top_hour = max(hour_counts, key=hour_counts.get)
    most_active_hour = f"{top_hour:02d}:00 - {top_hour:02d}:59"

    weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day_counts = Counter(weekday_names[ts.weekday()] for ts in timestamps_sorted)
    most_active_day = max(day_counts, key=day_counts.get)

    # Night movement from member3 time_of_day_profile if present
    tod = intel.get("time_of_day_profile", {})
    night_pct = float(tod.get("night", {}).get("percentage", 0.0))

    anomalies = sum(1 for p in points if int(p.get("cluster_id", -1)) == -1)
    date_range = f"{first_ts.date().isoformat()} - {last_ts.date().isoformat()}"

    return {
        "total_locations": len(points),
        "total_distance_km": round(total_distance_km, 2),
        "avg_daily_distance_km": round(avg_daily_distance_km, 2),
        "most_visited_place": most_visited_place,
        "inferred_home": inferred_home,
        "inferred_work": inferred_work,
        "most_active_hour": most_active_hour,
        "most_active_day": most_active_day,
        "night_movement_pct": round(night_pct, 1),
        "anomalies_detected": anomalies,
        "date_range": date_range,
    }


def build_road_following_path(points):
    """
    Road-following route using OSRM (OpenStreetMap routing), with fallback.
    Returns list of [lat, lon].
    """
    if len(points) < 2:
        return [[p["lat"], p["lon"]] for p in points]

    osrm_url = (
        "http://router.project-osrm.org/route/v1/driving/"
        "{lon1},{lat1};{lon2},{lat2}?overview=full"
    )

    # Small cache to avoid repeating calls for identical segments
    cache = {}
    road_coords = []

    def key_for(a, b):
        return (
            round(a["lat"], 5),
            round(a["lon"], 5),
            round(b["lat"], 5),
            round(b["lon"], 5),
        )

    for i in range(len(points) - 1):
        start = points[i]
        end = points[i + 1]
        k = key_for(start, end)
        if k in cache:
            segment = cache[k]
        else:
            url = osrm_url.format(
                lon1=start["lon"],
                lat1=start["lat"],
                lon2=end["lon"],
                lat2=end["lat"],
            )
            try:
                resp = requests.get(url, timeout=8)
                resp.raise_for_status()
                data = resp.json()
                geometry = data["routes"][0]["geometry"]
                segment = polyline.decode(geometry) # Returns list of (lat, lon)
                segment = [[lat, lon] for lat, lon in segment]
            except Exception as e:
                print(f"[OSRM WARNING]: Routing failed. Falling back to straight line. {e}")
                segment = [[start["lat"], start["lon"]], [end["lat"], end["lon"]]]
            cache[k] = segment

        if road_coords and segment:
            segment = segment[1:]  # avoid duplicate join point
        road_coords.extend(segment)

    return road_coords or [[p["lat"], p["lon"]] for p in points]


def build_map(points, summary: dict):
    center = [points[0]["lat"], points[0]["lon"]] if points else [17.3850, 78.4867]
    m = folium.Map(location=center, zoom_start=12, tiles="CartoDB dark_matter")

    # --- Movement Path Layer ---
    path_group = folium.FeatureGroup(name="📍 Movement Path", show=True)

    road_coords = build_road_following_path(points)
    folium.PolyLine(locations=road_coords, color="transparent", weight=0).add_to(path_group)

    for i, point in enumerate(points):
        color = CONFIDENCE_COLOR.get(point.get("confidence", "LOW"), "gray")
        folium.Marker(
            location=[point["lat"], point["lon"]],
            icon=folium.DivIcon(
                html=f"""
                <div style="
                    font-size: 20px;
                    line-height: 20px;
                    transform: translate(-50%, -100%);
                    text-shadow: 0 0 10px {color}, 0 0 18px {color};
                    filter: drop-shadow(0 0 2px rgba(0,0,0,0.6));
                ">📍</div>
                """
            ),
            popup=folium.Popup(
                f"""
                <div style="font-family:Arial; padding:6px;">
                    <b style="font-size:14px;">Stop {i+1}</b><br><br>
                    <b>Image ID:</b> {point.get('image_id', '')}<br>
                    <b>Time:</b> {point.get('timestamp', '')}<br>
                    <b>Cluster:</b> {point.get('cluster_id', 'N/A')}<br>
                    <b>Confidence:</b> {point.get('confidence', 'N/A')}
                </div>
                """,
                max_width=260,
            ),
            tooltip=f"Stop {i+1} — click for details",
        ).add_to(path_group)

    path_group.add_to(m)

    # --- Blinking dot on latest location ---
    if points:
        latest = points[-1]
        folium.Marker(
            location=[latest["lat"], latest["lon"]],
            icon=folium.DivIcon(
                html="""
                <div style="
                    width: 16px;
                    height: 16px;
                    background: #ff4444;
                    border-radius: 50%;
                    border: 2px solid white;
                    animation: pulse 1s infinite;
                "></div>
                <style>
                    @keyframes pulse {
                        0%   { transform: scale(1);   opacity: 1; }
                        50%  { transform: scale(1.6); opacity: 0.5; }
                        100% { transform: scale(1);   opacity: 1; }
                    }
                </style>
                """
            ),
            tooltip="Last Known Location",
        ).add_to(m)

    # --- Heatmap Layer ---
    heat_group = folium.FeatureGroup(name="🔥 Heatmap", show=False)
    HeatMap(
        [[p["lat"], p["lon"]] for p in points],
        radius=40,
        blur=25,
        gradient={"0.4": "blue", "0.65": "lime", "1": "red"},
    ).add_to(heat_group)
    heat_group.add_to(m)

    # --- Custom Floating Layer Control (Modern UI) ---
    map_name = m.get_name()
    path_js_name = path_group.get_name()
    heat_js_name = heat_group.get_name()

    custom_ui_html = f"""
    <style>
    /* Custom Map Panel UI */
    #custom-map-btn {{
        position: absolute; bottom: 20px; right: 20px; z-index: 9999;
        background: #111; color: #00ffcc; border: 1px solid #333;
        width: 44px; height: 44px; border-radius: 12px;
        display: flex; align-items: center; justify-content: center;
        cursor: pointer; cursor: pointer; transition: 0.2s;
        box-shadow: 0 4px 15px rgba(0,0,0,0.5); font-size: 20px;
    }}
    #custom-map-btn:hover {{ border-color: #00ffcc; transform: scale(1.05); }}
    
    #custom-map-panel {{
        position: absolute; bottom: 80px; right: 20px; z-index: 9999;
        background: #111; border: 1px solid #333; border-radius: 16px;
        padding: 24px; width: 280px; color: #fff; opacity: 0; pointer-events: none;
        transform: translateY(20px); transition: all 0.3s ease; box-shadow: 0 10px 30px rgba(0,0,0,0.5);
    }}
    
    .map-style-opt {{
        display: flex; align-items: center; font-size: 13px; color: #ccc; 
        margin-bottom: 8px; cursor: pointer; border: 1px solid transparent; 
        padding: 10px; border-radius: 8px; transition: all 0.2s; background: #1a1a1a;
    }}
    .map-style-opt input {{ display: none; }}
    .map-style-opt.selected {{ border-color: #00ffcc; background: #0d1a16; color: #fff; }}
    .c-radio {{
        width: 14px; height: 14px; border: 2px solid #555; border-radius: 50%; 
        margin-right: 12px; display: inline-block; position: relative;
        transition: all 0.2s;
    }}
    .map-style-opt.selected .c-radio {{ border-color: #00ffcc; }}
    .map-style-opt.selected .c-radio:after {{
        content: ""; position: absolute; width: 8px; height: 8px; background: #00ffcc;
        border-radius: 50%; top: 50%; left: 50%; transform: translate(-50%, -50%);
    }}
    
    .switch {{ position: relative; display: inline-block; width: 34px; height: 20px; }}
    .switch input {{ opacity: 0; width: 0; height: 0; }}
    .slider {{ position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #333; transition: .4s; border-radius: 34px; }}
    .slider:before {{ position: absolute; content: ""; height: 14px; width: 14px; left: 3px; bottom: 3px; background-color: #888; transition: .4s; border-radius: 50%; }}
    input:checked + .slider {{ background-color: #00ffcc; }}
    input:checked + .slider:before {{ transform: translateX(14px); background-color: #111; }}
    
    /* Native controls overrides */
    .leaflet-control-layers {{ display: none !important; }}
    .leaflet-control-zoom {{ border: none !important; box-shadow: 0 4px 15px rgba(0,0,0,0.5) !important; margin-top: 20px !important; margin-left: 20px !important; }}
    .leaflet-control-zoom-in, .leaflet-control-zoom-out {{ background: #111 !important; color: #fff !important; border-bottom: 1px solid #333 !important; text-decoration: none !important; }}
    .leaflet-control-zoom-in:hover, .leaflet-control-zoom-out:hover {{ background: #222 !important; color: #00ffcc !important; }}
    </style>
    
    <div id="custom-map-btn" onclick="toggleMapPanel()">🗺️</div>
    
    <div id="custom-map-panel">
       <div style="font-size:10px; color:#555; letter-spacing:1px; margin-bottom:12px; text-transform:uppercase;">Map Style</div>
       
       <label class="map-style-opt selected" onclick="setMapStyle(event, 'Dark')">
          <input type="radio" value="Dark" checked>
          <span class="c-radio"></span> 🌍 Dark
       </label>
       <label class="map-style-opt" onclick="setMapStyle(event, 'Satellite')">
          <input type="radio" value="Satellite">
          <span class="c-radio"></span> 🛰️ Satellite
       </label>
       <label class="map-style-opt" onclick="setMapStyle(event, 'Street')">
          <input type="radio" value="Street">
          <span class="c-radio"></span> 🛣️ Street
       </label>

       <div style="font-size:10px; color:#555; letter-spacing:1px; margin-top:24px; margin-bottom:12px; text-transform:uppercase;">Overlays</div>
       
       <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; font-size:13px; color:#ccc;">
           <span>📍 Movement Path</span>
           <label class="switch">
              <input type="checkbox" id="toggle-path" checked onchange="toggleOverlay('path', this.checked)">
              <span class="slider"></span>
           </label>
       </div>
       <div style="display:flex; justify-content:space-between; align-items:center; font-size:13px; color:#ccc;">
           <span>🔥 Heatmap</span>
           <label class="switch">
              <input type="checkbox" id="toggle-heat" onchange="toggleOverlay('heat', this.checked)">
              <span class="slider"></span>
           </label>
       </div>
    </div>
    
    <script>
    var panelOpen = false;
    function toggleMapPanel() {{
        var p = document.getElementById('custom-map-panel');
        var b = document.getElementById('custom-map-btn');
        panelOpen = !panelOpen;
        if(panelOpen) {{
            p.style.opacity = '1'; p.style.pointerEvents = 'auto'; p.style.transform = 'translateY(0)';
            b.style.borderColor = '#00ffcc'; b.style.boxShadow = '0 0 15px rgba(0,255,204,0.3)';
        }} else {{
            p.style.opacity = '0'; p.style.pointerEvents = 'none'; p.style.transform = 'translateY(20px)';
            b.style.borderColor = '#333'; b.style.boxShadow = '0 4px 15px rgba(0,0,0,0.5)';
        }}
    }}
    
    var mapTiles = {{
        'Dark': L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{ attribution: '&copy; CartoDB', maxZoom: 19 }}),
        'Satellite': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{ attribution: '&copy; Esri', maxZoom: 19 }}),
        'Street': L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ attribution: '&copy; OpenStreetMap', maxZoom: 19 }})
    }};
    
    document.addEventListener('DOMContentLoaded', function() {{
        setTimeout(function() {{
            var foliumMap = window["{map_name}"];
            window.myMap = foliumMap;
            var pathG = window["{path_js_name}"];
            var heatG = window["{heat_js_name}"];
            window.overlays = {{ 'path': pathG, 'heat': heatG }};
            
            // Folium adds dark_matter by default. 
            window.currentTile = null;
            foliumMap.eachLayer(function(l) {{
                if (l instanceof L.TileLayer) {{
                    window.currentTile = l;
                }}
            }});
            
            window.setMapStyle = function(event, name) {{
                document.querySelectorAll('.map-style-opt').forEach(el => {{
                    el.classList.remove('selected');
                    el.querySelector('input').checked = false;
                }});
                var t = event.currentTarget || event.target.closest('.map-style-opt');
                t.classList.add('selected');
                t.querySelector('input').checked = true;
                
                if (window.currentTile) foliumMap.removeLayer(window.currentTile);
                window.currentTile = mapTiles[name];
                window.currentTile.addTo(foliumMap);
                
                // Keep overlays above the new tile layer
                if (document.getElementById('toggle-path').checked) {{ foliumMap.removeLayer(pathG); foliumMap.addLayer(pathG); }}
                if (document.getElementById('toggle-heat').checked) {{ foliumMap.removeLayer(heatG); foliumMap.addLayer(heatG); }}
            }};
            
            window.toggleOverlay = function(name, show) {{
                var l = window.overlays[name];
                if (show) window.myMap.addLayer(l);
                else window.myMap.removeLayer(l);
            }};
            
            // --- Animated Snake Route ---
            var rawCoords = {road_coords};
            function downsample(coords, maxPoints) {{
                if (!coords || coords.length <= maxPoints) return coords;
                var step = Math.ceil(coords.length / maxPoints);
                var out = [];
                for (var i = 0; i < coords.length; i += step) out.push(coords[i]);
                var last = coords[coords.length - 1];
                var tail = out[out.length - 1];
                if (!tail || tail[0] !== last[0] || tail[1] !== last[1]) out.push(last);
                return out;
            }}
            var arr = downsample(rawCoords, 700);
            if(arr && arr.length >= 2) {{
                var M_idx = 0;
                var drawn = [arr[0]];
                var animLine = L.polyline(drawn, {{color:'#00ffcc', weight:3, opacity:0.9}}).addTo(foliumMap);
                var mDot = L.circleMarker(arr[0], {{radius:6, color:'#00ffcc', fillColor:'#fff', fillOpacity:1}}).addTo(foliumMap);
                function loop() {{
                    if(M_idx < arr.length - 1) {{
                        M_idx++;
                        drawn.push(arr[M_idx]);
                        animLine.setLatLngs(drawn);
                        mDot.setLatLng(arr[M_idx]);
                        setTimeout(loop, 8);
                    }} else {{ foliumMap.removeLayer(mDot); }}
                }}
                loop();
            }}
            
        }}, 800);
    }});
    </script>
    """
    m.get_root().html.add_child(folium.Element(custom_ui_html))
    return m


def build_dashboard_html(points, summary: dict, exposure: Exposure) -> str:
    # Keep the same UI features as your root version (clock, stat cards, sidebar, export CSV).
    risk_color = "#ff4444" if exposure.label == "High" else "#ff8800" if exposure.label == "Medium" else "#00ffcc"

    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>GeoTrace - Movement Intelligence</title>
    <meta charset="utf-8">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: #0d0d0d;
            color: #e0e0e0;
            font-family: 'Segoe UI', sans-serif;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }}
        .header {{
            background: #111;
            padding: 14px 24px;
            border-bottom: 1px solid #222;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .header h1 {{ font-size: 20px; color: #00ffcc; }}
        .header span {{ font-size: 12px; color: #666; }}
        .stats-bar {{
            display: flex;
            gap: 10px;
            padding: 12px 24px;
            background: #111;
            border-bottom: 1px solid #222;
            flex-wrap: wrap;
        }}
        .stat-card {{
            background: #1a1a1a;
            border: 1px solid #2a2a2a;
            border-radius: 10px;
            padding: 10px 18px;
            min-width: 140px;
        }}
        .stat-label {{
            font-size: 10px;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .stat-value {{
            font-size: 20px;
            font-weight: bold;
            color: #00ffcc;
            margin-top: 2px;
        }}
        .stat-value.danger {{ color: #ff4444; }}
        .main {{
            display: flex;
            flex: 1;
            overflow: hidden;
        }}
        .sidebar {{
            width: 260px;
            background: #111;
            border-right: 1px solid #222;
            padding: 16px;
            overflow-y: auto;
            flex-shrink: 0;
        }}
        .sidebar h3 {{
            font-size: 11px;
            color: #555;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 12px;
            margin-top: 16px;
        }}
        .sidebar h3:first-child {{ margin-top: 0; }}
        .info-row {{
            display: flex;
            justify-content: space-between;
            padding: 7px 0;
            border-bottom: 1px solid #1a1a1a;
            font-size: 13px;
        }}
        .info-row span {{ color: #888; }}
        .info-row b {{
            color: #fff;
            text-align: right;
            max-width: 140px;
            font-weight: 500;
        }}
        .risk-box {{
            background: #1a1a1a;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 12px;
            margin-top: 8px;
        }}
        .risk-title {{
            font-size: 11px;
            color: {risk_color};
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 8px;
        }}
        .risk-bar-bg {{
            background: #333;
            border-radius: 4px;
            height: 8px;
            overflow: hidden;
        }}
        .risk-bar-fill {{
            height: 100%;
            width: {exposure.bar_pct}%;
            background: linear-gradient(90deg, #ff8800, #ff4444);
            border-radius: 4px;
        }}
        .risk-score {{
            font-size: 24px;
            font-weight: bold;
            color: {risk_color};
            margin-top: 6px;
        }}
        .risk-sub {{
            font-size: 11px;
            color: #555;
            margin-top: 2px;
        }}
        .map-container {{ flex: 1; }}
        .map-container iframe {{
            width: 100%;
            height: 100%;
            border: none;
        }}
        .footer {{
            background: #111;
            border-top: 1px solid #222;
            padding: 8px 24px;
            display: flex;
            gap: 32px;
            font-size: 12px;
            color: #555;
        }}
    </style>
</head>
<body>

    <div class="header">
        <h1>GeoTrace</h1>
        <span>Movement Intelligence Dashboard &nbsp;|&nbsp;
              {summary['date_range']}</span>
        <span id="live-clock" style="
            margin-left: auto;
            font-size: 13px;
            color: #00ffcc;
            font-family: monospace;
            letter-spacing: 1px;
        "></span>
        <script>
            function updateClock() {{
                const now = new Date();
                const timeStr = now.toLocaleTimeString('en-IN', {{
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                    hour12: true
                }});
                const dateStr = now.toLocaleDateString('en-IN', {{
                    day: '2-digit',
                    month: 'short',
                    year: 'numeric'
                }});
                document.getElementById('live-clock').textContent
                    = dateStr + '  ' + timeStr;
            }}
            updateClock();
            setInterval(updateClock, 1000);
        </script>
    </div>

    <div class="stats-bar">
        <div class="stat-card">
            <div class="stat-label">Locations</div>
            <div class="stat-value">{summary['total_locations']}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Total Distance</div>
            <div class="stat-value">{summary['total_distance_km']} km</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Avg Daily</div>
            <div class="stat-value">{summary['avg_daily_distance_km']} km</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Most Visited</div>
            <div class="stat-value" style="font-size:13px; margin-top:4px;">
                {summary['most_visited_place']}
            </div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Anomalies</div>
            <div class="stat-value danger">{summary['anomalies_detected']}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Images Analyzed</div>
            <div class="stat-value">{len(points)}</div>
        </div>
    </div>

    <div class="main">

        <div class="sidebar">
            <h3>Behavioral Intel</h3>
            <div class="info-row">
                <span>Home</span>
                <b>{summary['inferred_home']}</b>
            </div>
            <div class="info-row">
                <span>Work</span>
                <b>{summary['inferred_work']}</b>
            </div>
            <div class="info-row">
                <span>Peak Hour</span>
                <b>{summary['most_active_hour']}</b>
            </div>
            <div class="info-row">
                <span>Most Active</span>
                <b>{summary['most_active_day']}</b>
            </div>
            <div class="info-row">
                <span>Night Moves</span>
                <b>{summary['night_movement_pct']}%</b>
            </div>

            <h3>Privacy Risk</h3>
            <div class="risk-box">
                <div class="risk-title">Exposure Score</div>
                <div class="risk-bar-bg">
                    <div class="risk-bar-fill"></div>
                </div>
                <div class="risk-score">{exposure.score_10} / 10</div>
                <div class="risk-sub">
                    {exposure.label} — {exposure.explanation}
                </div>
            </div>
        </div>

        <div class="map-container">
            <iframe src="map.html"></iframe>
        </div>

    </div>

    <div class="footer">
        <span>
            GREEN = High Confidence &nbsp;|&nbsp;
            ORANGE = Medium Confidence &nbsp;|&nbsp;
            RED = Low / Unclustered
        </span>
        <span style="margin-left:auto; display:flex; align-items:center; gap:12px;">
            <button onclick="exportCSV()" style="
                background: #00ffcc;
                color: #000;
                border: none;
                padding: 6px 16px;
                border-radius: 6px;
                font-size: 12px;
                font-weight: bold;
                cursor: pointer;
            ">Export CSV</button>
            Built with GeoTrace — Member 4
        </span>
        <script>
        function exportCSV() {{
            const data = {json.dumps(points)};
            const headers = ['image_id','lat','lon','timestamp','cluster_id','confidence'];
            const rows = data.map(p =>
                headers.map(h => (p[h] !== undefined ? p[h] : '')).join(',')
            );
            const csv = [headers.join(','), ...rows].join('\\n');
            const blob = new Blob([csv], {{ type: 'text/csv' }});
            const url  = URL.createObjectURL(blob);
            const a    = document.createElement('a');
            a.href     = url;
            a.download = 'geotrace_export.csv';
            a.click();
            URL.revokeObjectURL(url);
        }}
        </script>
    </div>

</body>
</html>
"""


def main():
    points = load_points()
    clusters_meta = load_clusters_meta()
    intel = load_intelligence()

    # Fill confidence for UI + legend (root feature)
    for p in points:
        p["confidence"] = infer_confidence(p, clusters_meta)

    summary = build_summary(points, intel, clusters_meta)
    exposure = compute_exposure(points, summary)

    m = build_map(points, summary)
    map_path = BASE_DIR / "map.html"
    m.save(str(map_path))

    dashboard_html = build_dashboard_html(points, summary, exposure)
    dashboard_path = BASE_DIR / "dashboard.html"
    dashboard_path.write_text(dashboard_html, encoding="utf-8")

    print(f"map.html saved at {map_path}")
    print(f"dashboard.html saved at {dashboard_path}")
    print("Open dashboard.html in your browser.")


if __name__ == "__main__":
    main()

