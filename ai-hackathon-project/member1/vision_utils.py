import requests
import base64

API_KEY = "AIzaSyCvZmoPW6wb1x0O-ZrhLOOMLMLsLJswUCU"

VISION_URL = f"https://vision.googleapis.com/v1/images:annotate?key={API_KEY}"


def get_location_from_image(image_path):
    try:
        print(f"\n[VISION API] Accessing Google Vision for: {image_path}")

        with open(image_path, "rb") as f:
            image_content = base64.b64encode(f.read()).decode()

        body = {
            "requests": [
                {
                    "image": {"content": image_content},
                    "features": [{"type": "LANDMARK_DETECTION"}],
                }
            ]
        }

        response = requests.post(VISION_URL, json=body, timeout=15)

        if response.status_code != 200:
            print("[VISION API] Error:", response.status_code, response.text)
            return None

        result = response.json()
        landmark_annotations = result["responses"][0].get("landmarkAnnotations")

        if not landmark_annotations:
            print("[VISION API] No landmark detected.")
            return None

        landmark = landmark_annotations[0]
        location = landmark["locations"][0]["latLng"]

        lat = location["latitude"]
        lon = location["longitude"]

        print("[VISION API] Landmark detected:", landmark["description"])
        print("[VISION API] Coordinates:", lat, lon)

        return lat, lon

    except Exception as e:
        print("[VISION API] Critical Error:", str(e))
        return None