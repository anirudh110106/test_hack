from google.cloud import vision
from google.oauth2 import service_account
import os

BASE_DIR = os.path.dirname(__file__)
KEY_PATH = os.path.join(BASE_DIR, "vision-key.json")

def get_vision_client():
    credentials = service_account.Credentials.from_service_account_file(KEY_PATH)
    return vision.ImageAnnotatorClient(credentials=credentials)

def get_location_from_image(image_path):
    print(f"\n[VISION API] Accessing Google Vision for: {image_path}")
    try:
        client = get_vision_client()

        with open(image_path, "rb") as image_file:
            content = image_file.read()

        image = vision.Image(content=content)
        response = client.landmark_detection(image=image)

        if response.landmark_annotations:
            landmark = response.landmark_annotations[0]
            print(f"[VISION API] Success! Found landmark: {landmark.description}")
            if landmark.locations:
                lat = landmark.locations[0].lat_lng.latitude
                lon = landmark.locations[0].lat_lng.longitude
                return lat, lon
        else:
            print("[VISION API] Google Vision searched but did not recognize any famous landmarks in this photo.")

    except Exception as e:
        print(f"\n[VISION API CRITICAL ERROR] Google rejected your API key!")
        print(f"Details: {e}")
        print("Note: Google automatically blocks API keys if they are pasted into AI chats to prevent abuse.")

    return None