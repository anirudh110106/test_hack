import json
import numpy as np
from sklearn.cluster import DBSCAN
from math import radians, sin, cos, sqrt, atan2
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)

POINTS_OUTPUT = os.path.join(BASE_DIR, "points_with_clusters.json")
CLUSTERS_OUTPUT = os.path.join(BASE_DIR, "clusters.json")
INPUT_FILE = os.path.join(ROOT_DIR, "member1", "output_data.json")

# -----------------------------
# SETTINGS
# -----------------------------
EPS_KM = 0.5        # 500 meters clustering radius
MIN_SAMPLES = 3     # Minimum points to form a cluster
EARTH_RADIUS = 6371


def call_member2():
    # -----------------------------
    # HAVERSINE DISTANCE FUNCTION
    # -----------------------------
    def haversine(coord1, coord2):
        lat1, lon1 = radians(coord1[0]), radians(coord1[1])
        lat2, lon2 = radians(coord2[0]), radians(coord2[1])

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))

        return EARTH_RADIUS * c

    # -----------------------------
    # LOAD INPUT DATA
    # -----------------------------
    with open(INPUT_FILE, "r") as f:
        data = json.load(f)

    if not data:
        print("Input file is empty.")
        exit()

    # Extract valid coordinates
    coords = []
    valid_points = []

    for point in data:
        if point.get("lat") is not None and point.get("lon") is not None:
            coords.append((point["lat"], point["lon"]))
            valid_points.append(point)

    coords = np.array(coords)

    if len(coords) == 0:
        print("No valid GPS coordinates found.")
        exit()

    # -----------------------------
    # RUN DBSCAN (HAVERSINE)
    # -----------------------------
    coords_rad = np.radians(coords)

    eps = EPS_KM / EARTH_RADIUS

    db = DBSCAN(
        eps=eps,
        min_samples=MIN_SAMPLES,
        algorithm="ball_tree",
        metric="haversine"
    )

    labels = db.fit_predict(coords_rad)

    # Attach cluster IDs
    for i, label in enumerate(labels):
        valid_points[i]["cluster_id"] = int(label)

    # -----------------------------
    # SAVE points_with_clusters.json
    # -----------------------------
    with open(POINTS_OUTPUT, "w") as f:
        json.dump(valid_points, f, indent=4)

    # -----------------------------
    # BUILD CLUSTER SUMMARY
    # -----------------------------
    clusters = {}

    for point in valid_points:
        cid = point["cluster_id"]
        if cid == -1:
            continue

        if cid not in clusters:
            clusters[cid] = []

        clusters[cid].append((point["lat"], point["lon"]))

    cluster_summary = []

    for cid, points in clusters.items():
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]

        center_lat = sum(lats) / len(lats)
        center_lon = sum(lons) / len(lons)

        cluster_summary.append({
            "cluster_id": cid,
            "center": [round(center_lat, 6), round(center_lon, 6)],
            "visits": len(points)
        })

    # -----------------------------
    # CALCULATE MOVEMENT RADIUS
    # -----------------------------
    max_distance = 0

    for i in range(len(cluster_summary)):
        for j in range(i+1, len(cluster_summary)):
            d = haversine(
                cluster_summary[i]["center"],
                cluster_summary[j]["center"]
            )
            if d > max_distance:
                max_distance = d

    # -----------------------------
    # SAVE clusters.json
    # -----------------------------
    final_clusters = {
        "clusters": cluster_summary,
        "noise_points": list(labels).count(-1),
        "movement_radius_km": round(max_distance, 2)
    }

    with open(CLUSTERS_OUTPUT, "w") as f:
        json.dump(final_clusters, f, indent=4)

    print("Clustering complete.")
    print("Files generated:")
    print("-", POINTS_OUTPUT)
    print("-", CLUSTERS_OUTPUT)


if __name__ == "__main__":
    call_member2()
