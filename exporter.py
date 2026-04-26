import argparse
import datetime
import json
import math
import os
import time
import threading
import webbrowser

import bs4 as bs
import requests
import dotenv
from dateutil import tz
from fitparse import FitFile
from flask import Flask, request as flask_request


# =========================
# Environment configuration
# =========================

ENV_PATH = ".env"

CLIENT_ID = "CLIENT_ID"
CLIENT_SECRET = "CLIENT_SECRET"

AUTHORIZATION_CODE = "AUTHORIZATION_CODE"

TOKEN = "TOKEN"  # Single token covers both read and write scopes

OAUTH_REDIRECT_URI = "http://localhost:5000/authorization"
OAUTH_SCOPES = "profile:read_all,activity:read_all,profile:write,activity:write"


# =========================
# OAuth – automatic authorization
# =========================

def get_authorization_code(client_id):
    """
    Automatically retrieve the Strava OAuth authorization code by:
    1. Opening the Strava authorization URL in the user's browser
    2. Starting a temporary Flask server to catch the redirect
    3. Extracting and returning the code from the redirect URL

    The user only needs to click "Authorize" in their browser once.

    Flask runs in a background daemon thread. Once the code is captured,
    the main thread returns — the daemon thread dies automatically with it.
    We never kill the process, so the rest of the script continues normally.
    """
    auth_url = (
        f"http://www.strava.com/oauth/authorize"
        f"?client_id={client_id}"
        f"&response_type=code"
        f"&redirect_uri={OAUTH_REDIRECT_URI}"
        f"&approval_prompt=force"
        f"&scope={OAUTH_SCOPES}"
    )

    app = Flask(__name__)
    app.logger.disabled = True
    import logging
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)

    captured = {}

    @app.route("/authorization")
    def authorization():
        code = flask_request.args.get("code")
        if code:
            captured["code"] = code
            return "<h2>Authorization successful! You can close this tab and return to the terminal.</h2>", 200
        return "<h2>Authorization failed: no code received.</h2>", 400

    print("Opening Strava authorization in your browser...")
    webbrowser.open(auth_url)

    # Flask runs as a daemon thread — it dies automatically once the main
    # thread returns, so no explicit shutdown is needed.
    flask_thread = threading.Thread(
        target=lambda: app.run(port=5000, debug=False, use_reloader=False)
    )
    flask_thread.daemon = True
    flask_thread.start()

    timeout, waited = 120, 0
    while "code" not in captured and waited < timeout:
        time.sleep(1)
        waited += 1

    if "code" not in captured:
        raise RuntimeError("Timed out waiting for Strava authorization. Please try again.")

    return captured["code"]


# =========================
# Authentication
# =========================

def authenticate():
    """
    Authenticate with Strava API.

    - If no authorization code is stored, launches browser-based OAuth flow automatically
    - Uses stored token if available and not expired
    - Otherwise exchanges authorization code for a token
    - Refreshes token if expired; re-runs full OAuth if refresh token is invalid
    - Saves updated token back to .env
    - A single token covers both read and write (scope set at OAuth time)
    """
    token_key = TOKEN

    client_id = os.getenv(CLIENT_ID)
    client_secret = os.getenv(CLIENT_SECRET)
    assert client_id, "CLIENT_ID is required in .env"
    assert client_secret, "CLIENT_SECRET is required in .env"

    auth_code = os.getenv(AUTHORIZATION_CODE)
    if not auth_code:
        print("No authorization code found. Starting automatic OAuth flow...")
        auth_code = get_authorization_code(client_id)
        dotenv.set_key(ENV_PATH, AUTHORIZATION_CODE, auth_code)
        dotenv.load_dotenv(ENV_PATH, override=True)

    raw_token = os.getenv(token_key)
    token = json.loads(raw_token) if raw_token else None

    if not token:
        token = request_token(client_id, client_secret, auth_code)

    if token["expires_at"] < time.time():
        refreshed = refresh_token(client_id, client_secret, token["refresh_token"])
        if refreshed is None:
            print("Clearing stale credentials and restarting authorization...")
            dotenv.set_key(ENV_PATH, token_key, "")
            dotenv.set_key(ENV_PATH, AUTHORIZATION_CODE, "")
            dotenv.load_dotenv(ENV_PATH, override=True)
            return authenticate()
        token = refreshed

    dotenv.set_key(ENV_PATH, token_key, json.dumps(token))
    dotenv.set_key(ENV_PATH, AUTHORIZATION_CODE, auth_code)

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
    """
    Refresh expired token.

    Returns the new token dict, or None if the refresh token is invalid/revoked
    (so the caller can re-trigger the full OAuth flow).
    """
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
        print(f"Refresh token rejected by Strava (status {res.status_code}). Re-authorization required.")
        return None
    return res.json()


# =========================
# Strava API
# =========================

def get_last_activity(token):
    """Retrieve the most recent activity from Strava."""
    res = requests.get(
        "https://www.strava.com/api/v3/activities",
        params={"access_token": token["access_token"], "per_page": 1, "page": 1},
    )
    if not res.ok:
        raise RuntimeError(f"Cannot retrieve last activity: {res.content}")
    return res.json()[0]


def time_of_day(dt):
    """
    Return a time-of-day label based on the hour of the activity.

        05:00 - 11:59  ->  Morning
        12:00 - 17:59  ->  Afternoon
        18:00 - 04:59  ->  Evening
    """
    hour = dt.hour
    if 5 <= hour < 12:
        return "Morning"
    elif 12 <= hour < 18:
        return "Afternoon"
    else:
        return "Evening"


def push_activity(token, path, start_time, start_time_pattern="%Y-%m-%dT%H:%M:%SZ",
                  file_format="gpx", trainer=False):
    """
    Upload an activity file to Strava.

    - Converts UTC start time to local time
    - Names the activity: e.g. "Morning ride (via Strava exporter)"
    - Supports both GPX (Kalenji) and FIT (Garmin) formats
    """
    start_dt = datetime.datetime.strptime(start_time, start_time_pattern)
    start_dt = start_dt.replace(tzinfo=tz.tzutc()).astimezone(tz.tzlocal())

    name = f"{time_of_day(start_dt)} ride (via Strava exporter)"

    params = {
        "name": name,
        "description": "",
        "data_type": file_format,
        "trainer": "VirtualRide" if trainer else "Workout",
    }

    with open(path, "rb") as f:
        res = requests.post(
            "https://www.strava.com/api/v3/uploads",
            params={"access_token": token["access_token"]},
            files={"file": f},
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


def wait_for_uploads(token, uploaded):
    """Poll Strava until all uploads are ready or errored."""
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
# Shared geo utility
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


# =========================
# GPX (Kalenji) processing
# =========================

def select_gpx_activities(folder, last_date):
    """Select GPX files newer than the last uploaded activity."""
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


def compute_gpx_stats(path):
    """
    Compute distance (km) and duration (minutes) for a GPX file.

    NOTE: Duration is approximated at 5 seconds per GPS point.
    """
    with open(path, "rb") as f:
        soup = bs.BeautifulSoup(f, "html.parser")

    points = soup.find_all("trkpt")
    assert len(points) >= 2, f"{path} must contain at least 2 GPS points"

    distance, duration = 0, 0
    for p1, p2 in zip(points, points[1:]):
        distance += haversine(
            (float(p1["lat"]), float(p1["lon"])),
            (float(p2["lat"]), float(p2["lon"])),
        )
        duration += 5

    return distance / 1000, duration / 60


def delete_last_gpx_point(path):
    """Remove last GPS point to fix corrupted Kalenji activities."""
    with open(path, "rb") as f:
        soup = bs.BeautifulSoup(f, "html.parser")

    points = soup.find_all("trkpt")
    if points:
        points[-1].extract()

    with open(path, "w") as f:
        f.write(str(soup))


# =========================
# FIT (Garmin) processing
# =========================

def select_fit_activities(folder, last_date):
    """Select FIT files newer than the last uploaded activity."""
    activities = []

    for file in os.listdir(folder):
        path = os.path.join(folder, file)
        fitfile = FitFile(path)

        first_record = next(fitfile.get_messages("record"), None)
        if not first_record:
            print(f"No record found for {path}, skipping.")
            continue

        for field in first_record:
            if field.name == "timestamp":
                start_time = field.value
                if start_time > last_date:
                    activities.append((path, start_time.strftime("%Y-%m-%d %H:%M:%S")))
                break

    activities.sort(key=lambda x: x[0])
    return activities


def compute_fit_stats(path):
    """
    Compute distance (km) and duration (minutes) for a FIT file.

    - Distance: haversine between consecutive GPS points (semicircles -> degrees)
    - Duration: sum of timestamp deltas between records
    """
    fitfile = FitFile(path)
    records = list(fitfile.get_messages("record"))

    if len(records) < 2:
        raise ValueError(f"{path} must contain at least 2 records")

    distance, duration = 0, 0

    for r1, r2 in zip(records, records[1:]):
        data1 = {f.name: f.value for f in r1}
        data2 = {f.name: f.value for f in r2}

        if data1.get("position_lat") is not None:
            lat1 = data1["position_lat"] * 180 / (2 ** 31)
            lon1 = data1["position_long"] * 180 / (2 ** 31)
            lat2 = data2["position_lat"] * 180 / (2 ** 31)
            lon2 = data2["position_long"] * 180 / (2 ** 31)
            distance += haversine((lat1, lon1), (lat2, lon2))

        if data1.get("timestamp") and data2.get("timestamp"):
            duration += (data2["timestamp"] - data1["timestamp"]).total_seconds()

    return distance / 1000, duration / 60


# =========================
# Upload pipelines
# =========================

def run_gpx_pipeline(conf, last_date_str, token):
    """Upload pipeline for Kalenji GPX files."""
    folder = conf.get("activities_folder")
    if not folder:
        raise ValueError("activities_folder is required in configuration for Kalenji device")

    max_dist = float(conf.get("max_dist", 0))
    last_date = datetime.datetime.strptime(last_date_str, "%Y-%m-%dT%H:%M:%SZ")

    activities = select_gpx_activities(folder, last_date)
    if not activities:
        print("No new GPX activities to upload.")
        return {}

    uploaded = {}

    for path, start_time in activities:
        dist, duration = compute_gpx_stats(path)

        if dist > max_dist:
            print(f"Fixing {path} (distance too large: {dist:.2f} km)")
            delete_last_gpx_point(path)
            dist, duration = compute_gpx_stats(path)

        if dist > max_dist:
            raise RuntimeError(
                f"Cannot fix {path}: distance {dist:.2f} km still exceeds max {max_dist} km"
            )

        res = push_activity(token, path, start_time, file_format="gpx")
        uploaded[res["id_str"]] = (path, dist, duration)

    wait_for_uploads(token, uploaded)


def run_fit_pipeline(conf, last_date_str, token):
    """Upload pipeline for Garmin FIT files."""
    folder = conf.get("garmin_activities_folder")
    if not folder:
        raise ValueError("garmin_activities_folder is required in configuration for Garmin device")

    if not os.path.isdir(folder):
        raise FileNotFoundError(
            f"Garmin activities folder not found: '{folder}'\n"
            f"Make sure your Garmin device is plugged in and mounted, "
            f"then check the garmin_activities_folder path in your configuration file."
        )

    last_date = datetime.datetime.strptime(last_date_str, "%Y-%m-%dT%H:%M:%SZ")

    activities = select_fit_activities(folder, last_date)
    if not activities:
        print("No new FIT activities to upload.")
        return

    uploaded = {}

    for path, start_time in activities:
        dist, duration = compute_fit_stats(path)
        trainer = dist == 0.0  # No GPS distance means indoor/home trainer

        res = push_activity(
            token, path, start_time,
            start_time_pattern="%Y-%m-%d %H:%M:%S",
            file_format="fit",
            trainer=trainer,
        )
        uploaded[res["id_str"]] = (path, dist, duration)

    wait_for_uploads(token, uploaded)


# =========================
# Config helpers
# =========================

def load_conf(required=None):
    """
    Load configuration file (key:value format).

    Only raises if a key in `required` is missing.
    Extra keys are always loaded silently.
    """
    conf = {}
    with open("configuration") as f:
        for line in f:
            if ":" in line:
                k, v = line.strip().split(":", 1)
                conf[k] = v

    for key, desc in (required or []):
        if key not in conf:
            raise ValueError(f"{key} is required in configuration file ({desc})")

    return conf


def check_env_file(path):
    """
    Ensure the .env file exists and ends with a newline (required by dotenv).

    On first run, the file may not exist yet. We create a template and ask
    the user to fill in CLIENT_ID and CLIENT_SECRET before re-running.

    Also cleans up legacy keys (READ_TOKEN, WRITE_TOKEN) from older versions
    of this script that used separate read/write tokens. These are replaced
    by a single TOKEN key and would cause invalid code exchange errors if left.
    """
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write("CLIENT_ID=\n")
            f.write("CLIENT_SECRET=\n")
        print(f"No .env file found. A template has been created at '{path}'.")
        print("Please fill in CLIENT_ID and CLIENT_SECRET, then re-run the script.")
        raise SystemExit(0)

    # Migrate legacy keys from old READ/WRITE split — clear them so the
    # fresh single-token flow takes over cleanly on next run
    legacy_keys = ("READ_TOKEN", "WRITE_TOKEN", "READ_AUTHORIZATION_CODE", "WRITE_AUTHORIZATION_CODE")
    dotenv.load_dotenv(path)
    needs_migration = any(os.getenv(k) for k in legacy_keys)
    if needs_migration:
        print("Detected legacy credentials from an older version. Clearing them for re-authorization...")
        for k in legacy_keys:
            dotenv.set_key(path, k, "")
        dotenv.set_key(path, "AUTHORIZATION_CODE", "")
        dotenv.set_key(path, "TOKEN", "")
        # Reload so authenticate() sees the cleared values, not the stale ones
        dotenv.load_dotenv(path, override=True)

    with open(path) as f:
        if not f.read().endswith("\n"):
            raise ValueError(f"{path} must end with a newline")


# =========================
# Main
# =========================

def main():
    parser = argparse.ArgumentParser(description="Strava activity uploader")
    parser.add_argument(
        "--device",
        required=True,
        choices=["kalenji", "garmin"],
        help="Device type to export from",
    )
    args = parser.parse_args()

    check_env_file(ENV_PATH)
    dotenv.load_dotenv(ENV_PATH)

    # Load all config — no required keys enforced here,
    # each pipeline validates its own keys
    conf = load_conf()

    # Authenticate once — the token covers both read and write scopes
    token = authenticate()
    last_activity = get_last_activity(token)
    last_date_str = last_activity["start_date"]
    print(f"Last Strava activity: {last_date_str}")

    if args.device == "kalenji":
        run_gpx_pipeline(conf, last_date_str, token)
    elif args.device == "garmin":
        run_fit_pipeline(conf, last_date_str, token)


if __name__ == "__main__":
    main()
