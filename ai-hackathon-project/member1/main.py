import os
import json
from exif_utils import extract_metadata
from database import insert_image, fetch_all, init_db

def process_folder(folder_path="images"):
    if not os.path.exists(folder_path):
        print("Folder not found.")
        return
    else:
        print("found")

    files = os.listdir(folder_path)

    valid = 0
    invalid = 0

    for file in files:
        file_path = os.path.join(folder_path, file)

        if not file.lower().endswith((".jpg", ".jpeg", ".png")):
            continue

        print(f"\nProcessing: {file}")

        # 1️⃣ Try EXIF first
        metadata = extract_metadata(file_path)

        # 2️⃣ If EXIF missing → Use Vision
        if not metadata:
            from vision_utils import get_location_from_image
            location = get_location_from_image(file_path)

            if location:
                metadata = {
                    "lat": location[0],
                    "lon": location[1],
                    "timestamp": None
                }

        # 3️⃣ If still no metadata → skip
        if not metadata:
            print("No GPS found (EXIF + Vision failed)")
            invalid += 1
            continue

        print("Metadata returned:", metadata)

        result = {
            "image_id": file,
            "lat": metadata["lat"],
            "lon": metadata["lon"],
            "timestamp": metadata["timestamp"]
        }

        insert_image(result)
        valid += 1

    print(f"\nProcessed: {valid + invalid}")
    print(f"Valid: {valid}")
    print(f"Invalid: {invalid}")

    export_json()


def export_json():
    rows = fetch_all()

    data = []
    for row in rows:
        data.append({
            "image_id": row[0],
            "lat": row[1],
            "lon": row[2],
            "timestamp": row[3]
        })

    with open("output_data.json", "w") as f:
        json.dump(data, f, indent=4)

    print("output_data.json generated successfully")

if __name__ == "__main__":
    init_db()
    process_folder()
