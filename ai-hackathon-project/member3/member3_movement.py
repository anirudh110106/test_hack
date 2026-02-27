"""
member3_movement.py - Movement Analysis & Intelligence Module (Member 3)
=========================================================================

GeoTrace Hackathon Project

INPUTS:
  - clusters.json          (from Member 2: cluster centroids + metadata)
  - points_with_clusters.json (from Member 2: individual geotagged points with cluster IDs)

OUTPUT:
  - intelligence.json      (to Member 4: full movement intelligence report)

Features:
  1. Haversine distance between consecutive points
  2. Speed estimation (km/h) from timestamps
  3. Movement corridors between clusters
  4. Dwell-time analysis at each cluster
  5. Time-of-day activity profiling
  6. Behavioral pattern classification (stationary / walking / driving)
  7. Summary statistics for the dashboard
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from itertools import combinations

# ─────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)

INPUT_CLUSTERS = os.path.join(ROOT_DIR, "member2", "clusters.json")
INPUT_POINTS = os.path.join(ROOT_DIR, "member2", "points_with_clusters.json")
OUTPUT_INTELLIGENCE = os.path.join(BASE_DIR, "intelligence.json")

# Speed thresholds (km/h) for behaviour classification
SPEED_STATIONARY = 1.0     # < 1 km/h  -> stationary
SPEED_WALKING    = 6.0     # 1-6 km/h  -> walking
SPEED_DRIVING    = 120.0   # 6-120 km/h -> driving  (above -> anomaly / flight)

EARTH_RADIUS_KM = 6371.0


# ─────────────────────────────────────────────
#  UTILITY FUNCTIONS
# ─────────────────────────────────────────────

def haversine(lat1, lon1, lat2, lon2):
    """
    Calculate the great-circle distance between two points
    on Earth using the Haversine formula.
    Returns distance in kilometres.
    """
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_KM * c


def parse_timestamp(ts_str):
    """
    Parse a timestamp string into a datetime object.
    Supports multiple common EXIF and ISO formats.
    """
    formats = [
        "%Y:%m:%d %H:%M:%S",      # EXIF standard
        "%Y-%m-%dT%H:%M:%S",      # ISO 8601
        "%Y-%m-%d %H:%M:%S",      # Common DB format
        "%Y-%m-%dT%H:%M:%S.%f",   # ISO with microseconds
        "%Y-%m-%d %H:%M:%S.%f",   # DB with microseconds
        "%Y:%m:%d %H:%M:%S%z",    # EXIF with timezone
        "%Y-%m-%dT%H:%M:%S%z",    # ISO with timezone
    ]
    for fmt in formats:
        try:
            return datetime.strptime(ts_str, fmt)
        except (ValueError, TypeError):
            continue
    return None


def classify_speed(speed_kmh):
    """Classify a speed value into a behaviour category."""
    if speed_kmh is None:
        return "unknown"
    if speed_kmh < SPEED_STATIONARY:
        return "stationary"
    elif speed_kmh < SPEED_WALKING:
        return "walking"
    elif speed_kmh < SPEED_DRIVING:
        return "driving"
    else:
        return "anomaly/flight"


def time_of_day_bucket(dt):
    """Classify a datetime into a time-of-day bucket."""
    hour = dt.hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"


def format_duration(seconds):
    """Convert seconds into a human-readable duration string."""
    if seconds is None or seconds < 0:
        return "N/A"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


# ─────────────────────────────────────────────
#  CORE ANALYSIS FUNCTIONS
# ─────────────────────────────────────────────

def load_inputs():
    """Load the input JSON files from Member 2."""
    if not os.path.exists(INPUT_CLUSTERS):
        print(f"[ERROR] Missing input file: {INPUT_CLUSTERS}")
        print("        Waiting for Member 2 to generate clusters.json")
        sys.exit(1)

    if not os.path.exists(INPUT_POINTS):
        print(f"[ERROR] Missing input file: {INPUT_POINTS}")
        print("        Waiting for Member 2 to generate points_with_clusters.json")
        sys.exit(1)

    with open(INPUT_CLUSTERS, "r", encoding="utf-8") as f:
        clusters_raw = json.load(f)

    with open(INPUT_POINTS, "r", encoding="utf-8") as f:
        points = json.load(f)

    # Handle M2's format: {"clusters": [...], "noise_points": ..., ...}
    # Normalize to a flat list of cluster dicts with centroid_lat/centroid_lon
    if isinstance(clusters_raw, dict) and "clusters" in clusters_raw:
        clusters = []
        for c in clusters_raw["clusters"]:
            center = c.get("center", [0, 0])
            clusters.append({
                "cluster_id": c.get("cluster_id", 0),
                "centroid_lat": center[0],
                "centroid_lon": center[1],
                "label": c.get("label", f"Cluster {c.get('cluster_id', 0)}"),
                "point_count": c.get("visits", 0),
            })
    elif isinstance(clusters_raw, list):
        clusters = clusters_raw
    else:
        clusters = []

    # Normalize point fields: image_id -> filename
    for p in points:
        if "filename" not in p and "image_id" in p:
            p["filename"] = p["image_id"]

    print(f"[OK] Loaded {len(clusters)} clusters and {len(points)} points")
    return clusters, points


def compute_point_to_point_movements(points):
    """
    Compute distance, time-delta, and speed between consecutive points
    sorted by timestamp. Returns a list of movement segments.
    """
    # Parse timestamps and sort
    parsed_points = []
    for p in points:
        ts = parse_timestamp(p.get("timestamp") or p.get("datetime") or p.get("date"))
        parsed_points.append({
            "lat": p["lat"],
            "lon": p["lon"],
            "timestamp": ts,
            "timestamp_str": p.get("timestamp") or p.get("datetime") or p.get("date") or "unknown",
            "cluster_id": p.get("cluster_id", p.get("cluster", -1)),
            "filename": p.get("filename", p.get("file", "unknown")),
        })

    # Sort by timestamp (put None timestamps at the end)
    parsed_points.sort(key=lambda x: x["timestamp"] or datetime.max)

    segments = []
    for i in range(1, len(parsed_points)):
        prev = parsed_points[i - 1]
        curr = parsed_points[i]

        dist_km = haversine(prev["lat"], prev["lon"], curr["lat"], curr["lon"])

        time_delta_seconds = None
        speed_kmh = None
        if prev["timestamp"] and curr["timestamp"]:
            time_delta_seconds = (curr["timestamp"] - prev["timestamp"]).total_seconds()
            if time_delta_seconds > 0:
                speed_kmh = (dist_km / time_delta_seconds) * 3600  # km/h

        segments.append({
            "from_point": {
                "lat": prev["lat"],
                "lon": prev["lon"],
                "timestamp": prev["timestamp_str"],
                "filename": prev["filename"],
                "cluster_id": prev["cluster_id"],
            },
            "to_point": {
                "lat": curr["lat"],
                "lon": curr["lon"],
                "timestamp": curr["timestamp_str"],
                "filename": curr["filename"],
                "cluster_id": curr["cluster_id"],
            },
            "distance_km": round(dist_km, 4),
            "time_delta_seconds": round(time_delta_seconds, 1) if time_delta_seconds is not None else None,
            "time_delta_human": format_duration(time_delta_seconds),
            "speed_kmh": round(speed_kmh, 2) if speed_kmh is not None else None,
            "behaviour": classify_speed(speed_kmh),
        })

    return segments, parsed_points


def compute_cluster_distances(clusters):
    """
    Compute pairwise distances between all cluster centroids.
    Returns a list of cluster-pair distance records.
    """
    cluster_distances = []
    cluster_list = list(clusters)

    for i, c1 in enumerate(cluster_list):
        for j, c2 in enumerate(cluster_list):
            if i >= j:
                continue
            c1_lat = c1.get("centroid_lat", c1.get("lat", 0))
            c1_lon = c1.get("centroid_lon", c1.get("lon", 0))
            c2_lat = c2.get("centroid_lat", c2.get("lat", 0))
            c2_lon = c2.get("centroid_lon", c2.get("lon", 0))

            dist = haversine(c1_lat, c1_lon, c2_lat, c2_lon)
            cluster_distances.append({
                "cluster_a": c1.get("cluster_id", c1.get("id", i)),
                "cluster_b": c2.get("cluster_id", c2.get("id", j)),
                "cluster_a_label": c1.get("label", c1.get("name", f"Cluster {i}")),
                "cluster_b_label": c2.get("label", c2.get("name", f"Cluster {j}")),
                "distance_km": round(dist, 4),
            })

    cluster_distances.sort(key=lambda x: x["distance_km"])
    return cluster_distances


def analyse_dwell_times(parsed_points):
    """
    Estimate dwell time at each cluster by summing time gaps
    between consecutive points that belong to the same cluster.
    """
    cluster_times = defaultdict(list)  # cluster_id -> list of timestamps

    for p in parsed_points:
        cid = p["cluster_id"]
        if cid is not None and cid != -1 and p["timestamp"]:
            cluster_times[cid].append(p["timestamp"])

    dwell_results = {}
    for cid, timestamps in cluster_times.items():
        timestamps.sort()
        total_dwell = 0.0
        visit_count = 1
        current_visit_start = timestamps[0]
        last_ts = timestamps[0]

        for ts in timestamps[1:]:
            gap = (ts - last_ts).total_seconds()
            if gap > 3600:  # > 1 hour gap = new visit
                total_dwell += (last_ts - current_visit_start).total_seconds()
                visit_count += 1
                current_visit_start = ts
            last_ts = ts

        # Close the last visit
        total_dwell += (last_ts - current_visit_start).total_seconds()

        dwell_results[str(cid)] = {
            "cluster_id": cid,
            "total_dwell_seconds": round(total_dwell, 1),
            "total_dwell_human": format_duration(total_dwell),
            "visit_count": visit_count,
            "point_count": len(timestamps),
            "first_seen": timestamps[0].isoformat(),
            "last_seen": timestamps[-1].isoformat(),
        }

    return dwell_results


def analyse_time_of_day(parsed_points):
    """
    Profile activity across time-of-day buckets.
    Returns counts and percentages for morning / afternoon / evening / night.
    """
    buckets = Counter()
    total = 0

    for p in parsed_points:
        if p["timestamp"]:
            bucket = time_of_day_bucket(p["timestamp"])
            buckets[bucket] += 1
            total += 1

    profile = {}
    for bucket_name in ["morning", "afternoon", "evening", "night"]:
        count = buckets.get(bucket_name, 0)
        profile[bucket_name] = {
            "count": count,
            "percentage": round((count / total) * 100, 1) if total > 0 else 0,
        }

    return profile


def analyse_movement_corridors(segments):
    """
    Identify frequently traveled corridors between clusters.
    A corridor is a pair (origin_cluster, destination_cluster) that appears
    in the movement segments.
    """
    corridor_counts = Counter()
    corridor_distances = defaultdict(list)

    for seg in segments:
        c_from = seg["from_point"]["cluster_id"]
        c_to = seg["to_point"]["cluster_id"]

        # Only count transitions between different, valid clusters
        if (c_from is not None and c_to is not None
                and c_from != -1 and c_to != -1
                and c_from != c_to):
            key = f"{c_from} -> {c_to}"
            corridor_counts[key] += 1
            corridor_distances[key].append(seg["distance_km"])

    corridors = []
    for key, count in corridor_counts.most_common():
        distances = corridor_distances[key]
        corridors.append({
            "corridor": key,
            "trip_count": count,
            "avg_distance_km": round(sum(distances) / len(distances), 4),
            "min_distance_km": round(min(distances), 4),
            "max_distance_km": round(max(distances), 4),
        })

    return corridors


def compute_summary_statistics(segments, parsed_points, clusters):
    """Compute high-level summary statistics for the intelligence report."""
    total_distance = sum(s["distance_km"] for s in segments)
    speeds = [s["speed_kmh"] for s in segments if s["speed_kmh"] is not None and s["speed_kmh"] > 0]
    behaviours = Counter(s["behaviour"] for s in segments)

    # Time span
    valid_times = [p["timestamp"] for p in parsed_points if p["timestamp"]]
    time_span_seconds = None
    time_span_human = "N/A"
    if len(valid_times) >= 2:
        time_span_seconds = (max(valid_times) - min(valid_times)).total_seconds()
        time_span_human = format_duration(time_span_seconds)

    return {
        "total_points": len(parsed_points),
        "total_segments": len(segments),
        "total_clusters": len(clusters),
        "total_distance_km": round(total_distance, 4),
        "total_distance_display": f"{total_distance:.2f} km",
        "avg_speed_kmh": round(sum(speeds) / len(speeds), 2) if speeds else None,
        "max_speed_kmh": round(max(speeds), 2) if speeds else None,
        "min_speed_kmh": round(min(speeds), 2) if speeds else None,
        "time_span_seconds": time_span_seconds,
        "time_span_human": time_span_human,
        "first_timestamp": min(valid_times).isoformat() if valid_times else None,
        "last_timestamp": max(valid_times).isoformat() if valid_times else None,
        "behaviour_breakdown": dict(behaviours),
    }


# ─────────────────────────────────────────────
#  MAIN PIPELINE
# ─────────────────────────────────────────────

def run_pipeline():
    """
    Main entry point - runs the full Member 3 analysis pipeline.
    """
    print("=" * 60)
    print("  GEOTRACE - Member 3: Movement & Pattern Analysis")
    print("=" * 60)
    print()

    # ── Step 1: Load inputs ──
    clusters, points = load_inputs()

    # ── Step 2: Point-to-point movement analysis ──
    print("\n[STEP 2] Computing point-to-point movements...")
    segments, parsed_points = compute_point_to_point_movements(points)
    print(f"         -> {len(segments)} movement segments computed")

    # ── Step 3: Cluster-to-cluster distances ──
    print("[STEP 3] Computing inter-cluster distances...")
    cluster_distances = compute_cluster_distances(clusters)
    print(f"         -> {len(cluster_distances)} cluster pairs analysed")

    # ── Step 4: Dwell-time analysis ──
    print("[STEP 4] Analysing dwell times at clusters...")
    dwell_times = analyse_dwell_times(parsed_points)
    print(f"         -> {len(dwell_times)} clusters with dwell data")

    # ── Step 5: Time-of-day profiling ──
    print("[STEP 5] Profiling time-of-day activity...")
    time_profile = analyse_time_of_day(parsed_points)
    for bucket, data in time_profile.items():
        print(f"         -> {bucket}: {data['count']} points ({data['percentage']}%)")

    # ── Step 6: Movement corridors ──
    print("[STEP 6] Identifying movement corridors...")
    corridors = analyse_movement_corridors(segments)
    print(f"         -> {len(corridors)} corridors identified")

    # ── Step 7: Summary statistics ──
    print("[STEP 7] Computing summary statistics...")
    summary = compute_summary_statistics(segments, parsed_points, clusters)

    # ── Step 8: Build the intelligence report ──
    print("\n[STEP 8] Building intelligence report...")
    intelligence = {
        "meta": {
            "generated_by": "member3_movement.py",
            "generated_at": datetime.now().isoformat(),
            "description": "GeoTrace movement intelligence report",
            "version": "1.0",
        },
        "summary": summary,
        "movement_segments": segments,
        "cluster_distances": cluster_distances,
        "dwell_times": dwell_times,
        "time_of_day_profile": time_profile,
        "movement_corridors": corridors,
    }

    # ── Step 9: Save output ──
    with open(OUTPUT_INTELLIGENCE, "w", encoding="utf-8") as f:
        json.dump(intelligence, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n[DONE] Intelligence report saved to: {OUTPUT_INTELLIGENCE}")
    print(f"       Total distance: {summary['total_distance_display']}")
    print(f"       Time span: {summary['time_span_human']}")
    print(f"       Avg speed: {summary['avg_speed_kmh']} km/h")
    print(f"       Behaviours: {summary['behaviour_breakdown']}")
    print()

    return intelligence


# Also expose as call_member3() for backwards compatibility
def call_member3():
    run_pipeline()


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    run_pipeline()
