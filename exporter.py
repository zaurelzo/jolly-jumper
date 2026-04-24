import datetime
import json
import math
import os
import time

import bs4 as bs
import requests
import dotenv
from dateutil import tz


# =========================
# Environment configuration
# =========================

ENV_PATH = ".env"

CLIENT_ID = "CLIENT_ID"
CLIENT_SECRET = "CLIENT_SECRET"

READ_AUTHORIZATION_CODE = "READ_AUTHORIZATION_CODE"
WRITE_AUTHORIZATION_CODE = "WRITE_AUTHORIZATION_CODE"

READ_TOKEN = "READ_TOKEN"
WRITE_TOKEN = "WRITE_TOKEN"


# =========================
# Authentication
# =========================

def authenticate(mode):
    """
    Authenticate with Strava API.

    - Uses stored token if available
    - Otherwise exchanges authorization code for a token
    - Refreshes token if expired
    - Saves updated token back to .env
    """
    if mode not in ("READ", "WRITE"):
        raise ValueError(f"Unsupported mode: {mode}")

    token_key = READ_TOKEN if mode == "READ" else WRITE_TOKEN
    code_key = READ_AUTHORIZATION_CODE if mode == "READ" else WRITE_AUTHORIZATION_CODE

    token = os.getenv(token_key)
    auth_code = os.getenv(code_key)

    assert auth_code, f"{code_key} must be set in {ENV_PATH}"

    client_id = os.getenv(CLIENT_ID)
    client_secret = os.getenv(CLIENT_SECRET)

    assert client_id, "CLIENT_ID is required"
    assert client_secret, "CLIENT_SECRET is required"

    # Load token if already stored
    token = json.loads(token) if token else None

    # Step 1: Get token if missing
    if not token:
        token = request_token(client_id, client_secret, auth_code)

    # Step 2: Refresh token if expired
    if token["expires_at"] < time.time():
        token = refresh_token(client_id, client_secret, token["refresh_token"])

    # Persist token
    dotenv.set_key(ENV_PATH, token_key, json.dumps(token))

    return token


def request_token(client_id, client_secret, code):
    """Exchange authorization code for access token."""
    res = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": int(client_id),
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
    )

    if not res.ok:
        raise RuntimeError(f"Failed to get token: {res.content}")

    return res.json()


def refresh_token(client_id, client_secret, refresh_token_value):
    """Refresh expired token."""
    res = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": int(client_id),
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token_value,
        },
    )

    if not res.ok:
        raise RuntimeError(f"Failed to refresh token: {res.content}")

    return res.json()


# =========================
# Strava API
# =========================

def get_last_activity(token):
    """
    Retrieve the most recent activity from Strava.

    We only fetch one activity (per_page=1) to get the latest date.
    """
    url = "https://www.strava.com/api/v3/activities"
    res = requests.get(
        url,
        params={"access_token": token["access_token"], "per_page": 1, "page": 1},
    )

    if not res.ok:
        raise RuntimeError(f"Cannot retrieve last activity: {res.content}")

    return res.json()[0]


def push_activity(token, path, start_time, file_format="gpx", trainer=False):
    """
    Upload an activity file to Strava.

    - Converts UTC start time to local time
    - Builds a readable activity name
    """
    with open(path, "rb") as f:
        files = {"file": f}

        # Convert UTC -> local time
        start_dt = datetime.datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%SZ")
        start_dt = start_dt.replace(tzinfo=tz.tzutc()).astimezone(tz.tzlocal())

        name = f"Ride on {start_dt.strftime('%d-%m-%Y at %H:%M:%S')}"
        description = f"Uploaded via script on {datetime.datetime.now()}"

        params = {
            "name": name,
            "description": description,
            "data_type": file_format,
            "trainer": "VirtualRide" if trainer else "Workout",
        }

        res = requests.post(
            "https://www.strava.com/api/v3/uploads",
            params={"access_token": token["access_token"]},
            files=files,
            data=params,
        )

    if not res.ok:
        raise RuntimeError(f"Upload failed for {path}: {res.content}")

    return res.json()


def check_upload(token, activity_id):
    """Check upload status (processed, ready, error, etc.)."""
    res = requests.get(
        f"https://www.strava.com/api/v3/uploads/{activity_id}",
        params={"access_token": token["access_token"]},
    )

    if not res.ok:
        raise RuntimeError(f"Cannot check upload: {res.content}")

    return res.json()


# =========================
# GPX processing
# =========================

def haversine(coord1, coord2):
    """Compute distance (meters) between two GPS points."""
    R = 6372800
    lat1, lon1 = coord1
    lat2, lon2 = coord2

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def compute_activity_stats(path):
    """
    Compute distance (km) and duration (minutes).

    NOTE:
    - Time is approximated (5 seconds per point)
    - Could be improved by parsing timestamps
    """
    with open(path, "rb") as f:
        soup = bs.BeautifulSoup(f, "html.parser")

    points = soup.find_all("trkpt")
    assert len(points) >= 2, f"{path} must contain at least 2 points"

    distance = 0
    duration = 0

    for p1, p2 in zip(points, points[1:]):
        lat1, lon1 = float(p1["lat"]), float(p1["lon"])
        lat2, lon2 = float(p2["lat"]), float(p2["lon"])

        distance += haversine((lat1, lon1), (lat2, lon2))
        duration += 5  # rough estimation

    return distance / 1000, duration / 60


def delete_last_point(path):
    """
    Remove last GPS point.

    Used to fix corrupted activities where the last point is incorrect.
    """
    with open(path, "rb") as f:
        soup = bs.BeautifulSoup(f, "html.parser")

    points = soup.find_all("trkpt")
    if points:
        points[-1].extract()

    with open(path, "w") as f:
        f.write(str(soup))


# =========================
# Activity selection
# =========================

def select_activities(conf, last_date_str):
    """
    Select GPX files newer than last uploaded activity.
    """
    folder = conf["activities_folder"]
    last_date = datetime.datetime.strptime(last_date_str, "%Y-%m-%dT%H:%M:%SZ")

    activities = []

    for file in os.listdir(folder):
        if not file.endswith("gpx"):
            continue

        path = os.path.join(folder, file)

        with open(path, "rb") as f:
            soup = bs.BeautifulSoup(f, "html.parser")

        start_time = soup.find("metadata").find("time").string
        start_dt = datetime.datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%SZ")

        if start_dt > last_date:
            activities.append((path, start_time))

    activities.sort(key=lambda x: x[0])
    return activities


# =========================
# Config helpers
# =========================

def load_conf(required):
    """Load configuration file (key:value format)."""
    conf = {}

    with open("configuration") as f:
        for line in f:
            if ":" in line:
                k, v = line.strip().split(":", 1)
                conf[k] = v

    for key, desc in required:
        if key not in conf:
            raise ValueError(f"{key} is required ({desc})")

    return conf


def check_env_file(path):
    """Ensure .env ends with newline (required by dotenv)."""
    with open(path) as f:
        if not f.read().endswith("\n"):
            raise ValueError(f"{path} must end with a newline")


# =========================
# Upload workflow
# =========================

def upload_pipeline(conf):
    """
    Full upload pipeline:
    1. Get last activity
    2. Select new files
    3. Fix bad activities if needed
    4. Upload
    5. Wait for processing
    """
    read_token = authenticate("READ")
    last_activity = get_last_activity(read_token)

    print(f"Last activity: {last_activity['start_date']}")

    activities = select_activities(conf, last_activity["start_date"])

    if not activities:
        print("No activities to upload.")
        return

    write_token = authenticate("WRITE")
    uploaded = {}

    for path, start_time in activities:
        dist, duration = compute_activity_stats(path)

        # Fix abnormal distance
        if dist > float(conf["max_dist"]):
            print(f"Fixing {path} (distance too large: {dist} km)")
            delete_last_point(path)
            dist, duration = compute_activity_stats(path)

        if dist > float(conf["max_dist"]):
            raise RuntimeError(f"Cannot fix {path}")

        res = push_activity(write_token, path, start_time)
        uploaded[res["id_str"]] = (path, dist, duration)

    wait_for_uploads(write_token, uploaded)


def wait_for_uploads(token, uploaded):
    """Poll Strava until uploads are ready."""
    for activity_id, (path, dist, duration) in uploaded.items():
        status = check_upload(token, activity_id)

        while "processed" in status["status"]:
            print(f"Processing {path}...")
            time.sleep(8)
            status = check_upload(token, activity_id)

        if "ready" in status["status"]:
            print(f"Uploaded {path} | {dist:.2f} km | {duration:.2f} min")
        else:
            print(f"Error for {path}: {status}")


# =========================
# Main
# =========================

def main():
    """
    Entry point:
    - Load env
    - Load config
    - Run upload pipeline
    """
    check_env_file(ENV_PATH)
    dotenv.load_dotenv(ENV_PATH)

    conf = load_conf([
        ("activities_folder", "Folder containing GPX files"),
        ("max_dist", "Max allowed distance before fixing activity"),
    ])

    upload_pipeline(conf)


if __name__ == "__main__":
    main()