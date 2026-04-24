from fitparse import FitFile
import exporter
import math
import time
import datetime
import os
import dotenv


def load_config():
    """
    Load environment variables and configuration file.

    - Ensures the .env file exists and is valid
    - Loads environment variables (Strava credentials, etc.)
    - Loads user configuration (e.g., activities folder)
    """
    exporter.check_valid_env_file(exporter.ENV_PATH)
    dotenv.load_dotenv(exporter.ENV_PATH)

    return exporter.load_conf_file([
        ("garmin_activities_folder", "Path to folder containing activities")
    ])


def get_last_activity_date():
    """
    Retrieve the date of the last activity uploaded to Strava.

    This is used as a reference point to avoid re-uploading old activities.
    """
    token = exporter.authenticate("READ")
    activity = exporter.get_last_activity(token)
    return activity["start_date"]


def select_activities_to_upload(conf, last_activity_date):
    """
    Select FIT files that are newer than the last uploaded Strava activity.

    Returns:
        List of tuples: (file_path, formatted_start_time)
    """
    folder = conf["garmin_activities_folder"]

    # Convert Strava date string into a datetime object
    last_date = datetime.datetime.strptime(
        last_activity_date, "%Y-%m-%dT%H:%M:%SZ"
    )

    activities = []

    # Iterate over all files in the Garmin folder
    for filename in os.listdir(folder):
        file_path = os.path.join(folder, filename)

        # Parse FIT file
        fitfile = FitFile(file_path)

        # Get the first record (contains start timestamp)
        first_record = next(fitfile.get_messages("record"), None)

        if not first_record:
            print(f"No record found for {file_path}")
            continue

        # Extract timestamp from first record
        for field in first_record:
            if field.name == "timestamp":
                start_time = field.value

                # Keep only activities newer than last uploaded
                if start_time > last_date:
                    activities.append(
                        (file_path, start_time.strftime("%Y-%m-%d %H:%M:%S"))
                    )
                break

    # Sort activities so older ones are uploaded first
    activities.sort(key=lambda x: x[0])
    return activities


def compute_activity_stats(file_path):
    """
    Compute basic statistics for an activity:
    - Total distance (in km)
    - Total duration (in minutes)

    Distance is computed using the haversine formula between GPS points.
    Time is computed from timestamp differences.
    """
    fitfile = FitFile(file_path)
    records = list(fitfile.get_messages("record"))

    # Ensure we have enough data points
    if len(records) < 2:
        raise ValueError(f"{file_path} must contain at least two records")

    total_distance = 0  # meters
    total_time = 0      # seconds

    for r1, r2 in zip(records, records[1:]):
        data1 = {f.name: f.value for f in r1}
        data2 = {f.name: f.value for f in r2}

        # --- Distance computation ---
        # Convert Garmin semicircles to degrees
        if data1.get("position_lat") is not None:
            lat1 = data1["position_lat"] * 180 / (2**31)
            lon1 = data1["position_long"] * 180 / (2**31)
            lat2 = data2["position_lat"] * 180 / (2**31)
            lon2 = data2["position_long"] * 180 / (2**31)

            # Add distance between two GPS points
            total_distance += exporter.haversine((lat1, lon1), (lat2, lon2))

        # --- Time computation ---
        if data1.get("timestamp") and data2.get("timestamp"):
            delta = data2["timestamp"] - data1["timestamp"]
            total_time += delta.total_seconds()

    # Convert to km and minutes
    return total_distance / 1000, total_time / 60


def upload_activities(activities):
    """
    Upload activities to Strava.

    Returns:
        token: authentication token used for upload
        uploaded: dict mapping activity_id -> (file_path, distance, duration)
    """
    token = exporter.authenticate("WRITE")
    uploaded = {}

    for file_path, start_time in activities:
        # Compute stats before upload (used for logging)
        distance, duration = compute_activity_stats(file_path)

        # Detect indoor activity (no GPS distance)
        is_home_trainer = distance == 0.0

        # Upload activity to Strava
        response = exporter.push_activity(
            token,
            file_path,
            start_time,
            start_time_pattern="%Y-%m-%d %H:%M:%S",
            device_name="Garmin",
            file_format="fit",
            on_home_trainer=is_home_trainer,
        )

        # Store metadata for later status tracking
        uploaded[response["id_str"]] = (file_path, distance, duration)

    return token, uploaded


def wait_for_uploads(token, uploaded):
    """
    Poll Strava until all uploads are processed.

    Strava processes uploads asynchronously, so we must:
    - Check status repeatedly
    - Wait between checks (to avoid hitting API limits)
    """
    for activity_id, (file_path, distance, duration) in uploaded.items():
        status = exporter.check_upload(token, activity_id, file_path)

        # Keep checking while processing is ongoing
        while "processed" in status["status"]:
            print(f"Processing {file_path}... status={status['status']}")

            # Strava recommends waiting ~8 seconds between checks
            time.sleep(8)

            status = exporter.check_upload(token, activity_id, file_path)

        # Final result
        if "ready" in status["status"]:
            print(
                f"Uploaded {file_path} | "
                f"distance={distance:.2f} km | time={duration:.2f} min"
            )
        else:
            print(f"Error uploading {file_path}: {status}")


def main():
    """
    Main workflow:

    1. Load configuration
    2. Get last uploaded activity from Strava
    3. Select new activities from Garmin folder
    4. Upload them
    5. Wait for processing to complete
    """
    config = load_config()
    last_date = get_last_activity_date()

    print(
        f"Last activity date: {last_date}\n"
        f"Scanning folder: {config['garmin_activities_folder']}"
    )

    # Step 1: Find new activities
    activities = select_activities_to_upload(config, last_date)

    if not activities:
        print("No activities to upload.")
        return

    print(f"{len(activities)} activities to upload.")

    # Step 2: Upload
    token, uploaded = upload_activities(activities)

    # Step 3: Wait for Strava processing
    wait_for_uploads(token, uploaded)


if __name__ == "__main__":
    main()