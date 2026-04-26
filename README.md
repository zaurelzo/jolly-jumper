# Strava Activity Exporter

I am the happy owner of both a Kalenji watch and a Garmin Edge 520+ that I use to record my cycling activities.  
I wrote this script to automatically export my latest rides to my Strava account.

To export activities from the Kalenji watch to GPX files, I used the open-source project [kalenji-gps-watch-reader](https://github.com/ColinPitrat/kalenji-gps-watch-reader).  
[This article](https://medium.com/swlh/using-python-to-connect-to-stravas-api-and-analyse-your-activities-dummies-guide-5f49727aac86) and the [Strava documentation](https://developers.strava.com/docs/reference/) helped me understand how to use the API.

---

# Supported Devices

| Device | Format | Argument |
|---|---|---|
| Kalenji (OnMove 200/220) | GPX | `kalenji` |
| Garmin Edge 520+ (and most Garmin devices) | FIT | `garmin` |

---

# How to Run

Plug in your device and run:

```bash
./exporter.sh <device>
```

Examples:

```bash
./exporter.sh kalenji
./exporter.sh garmin
```

---

# How It Works

### Kalenji

`exporter.sh` first runs `kalenji_reader` to extract GPX files from the watch using the `watch-conf` configuration:

```
source=Path
path=/media/zaurelzo/ONMOVE-220/DATA
device=OnMove200
filters=FixElevation,ComputeInstantSpeed
gpx_extensions=none
directory=/home/zaurelzo/kalenji_activities
```

It then calls `exporter.py --device kalenji`, which selects GPX files newer than the last Strava activity and uploads them.

### Garmin

`exporter.sh` calls `exporter.py --device garmin` directly.  
The script reads FIT files from the configured Garmin folder, selects those newer than the last Strava activity, and uploads them. Activities with no GPS data (e.g. indoor trainer sessions) are automatically detected and tagged as virtual rides.

---

# Dependencies

```bash
pip install -r requirements.txt
```

---

# Configuration

Create a `configuration` file in the project folder using `key:value` format.  
Only the keys relevant to the device you use are required:

```
# Kalenji (required for --device kalenji)
activities_folder:/home/zaurelzo/kalenji_activities
max_dist:100

# Garmin (required for --device garmin)
garmin_activities_folder:/media/zaurelzo/GARMIN/ACTIVITY
```

`max_dist` is a Kalenji-only setting: if an activity exceeds this distance (in km), the script attempts to fix it by removing the last GPS point (a known hardware quirk on some Kalenji models).

---

# Environment Configuration

Create a `.env` file in the project folder:

```bash
CLIENT_ID=client_id_of_your_app_created_in_strava
CLIENT_SECRET=client_secret_of_your_strava_app
```

> **Warning:** The `.env` file must end with an empty line (`\n`).

`CLIENT_ID` and `CLIENT_SECRET` are the only values you need to set manually.  
All other variables (`AUTHORIZATION_CODE`, `READ_TOKEN`, `WRITE_TOKEN`) are populated automatically on first run.

---

# Authorization

On the first run, the script will automatically:

1. Open the Strava authorization page in your browser
2. Ask you to log in and click **Authorize**
3. Capture the authorization code via a temporary local server on `http://localhost:5000`
4. Save the code and tokens to your `.env` file

On subsequent runs, the stored tokens are reused silently.  
If a token expires, it is refreshed automatically.  
If the refresh token itself becomes invalid (e.g. you revoked access in Strava settings), the script detects this and re-opens the browser to re-authorize — no manual steps needed.
