from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from datetime import datetime


def dms_to_decimal(dms, ref):
    try:
        # Works if values are floats like (17.0, 32.0, 44.82)
        degrees = float(dms[0])
        minutes = float(dms[1])
        seconds = float(dms[2])
    except:
        # Works if values are rationals like ((17,1),(32,1),(44,100))
        degrees = dms[0][0] / dms[0][1]
        minutes = dms[1][0] / dms[1][1]
        seconds = dms[2][0] / dms[2][1]

    decimal = degrees + minutes / 60 + seconds / 3600

    if ref in ["S", "W"]:
        decimal = -decimal

    return decimal

def extract_metadata(path):
    try:
        image = Image.open(path)
        exif_data = image._getexif()

        if not exif_data:
            return None

        gps_info = {}
        timestamp = None

        for tag_id, value in exif_data.items():
            tag = TAGS.get(tag_id, tag_id)

            # Extract GPS
            if tag == "GPSInfo":
                for key in value:
                    sub_tag = GPSTAGS.get(key, key)
                    gps_info[sub_tag] = value[key]

            # Accept multiple timestamp types
            if tag in ["DateTimeOriginal", "DateTime", "DateTimeDigitized"]:
                timestamp = value

        # Only require GPS, timestamp optional
        if "GPSLatitude" not in gps_info or "GPSLongitude" not in gps_info:
            return None

        lat = dms_to_decimal(gps_info["GPSLatitude"], gps_info["GPSLatitudeRef"])
        lon = dms_to_decimal(gps_info["GPSLongitude"], gps_info["GPSLongitudeRef"])

        # If timestamp missing, assign None instead of rejecting
        if timestamp:
            timestamp = datetime.strptime(timestamp, "%Y:%m:%d %H:%M:%S").isoformat()
        else:
            timestamp = None

        return {
            "lat": lat,
            "lon": lon,
            "timestamp": timestamp
        }

    except Exception as e:
        print("Error:", e)
        return None