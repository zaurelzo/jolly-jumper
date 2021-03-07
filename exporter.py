import datetime
import json
import math
import os
import time

import bs4 as bs
import requests
import dotenv
from dateutil import tz

# env variables
ENV_PATH = ".env"
CLIENT_ID = "CLIENT_ID"
CLIENT_SECRET = "CLIENT_SECRET"
# TODO :  when get_authorization_code will be implemented, you will not need this var anymore
READ_AUTHORIZATION_CODE = "READ_AUTHORIZATION_CODE"
WRITE_AUTHORIZATION_CODE = "WRITE_AUTHORIZATION_CODE"
READ_TOKEN = "READ_TOKEN"
WRITE_TOKEN = "WRITE_TOKEN"


# authenticate the user and return a read or write token api
def authenticate(op_type):
    token = None
    authorization_code = None
    rw_token = None
    rw_code = None
    if op_type == "READ":
        rw_token = READ_TOKEN
        rw_code = READ_AUTHORIZATION_CODE
        token = os.getenv(READ_TOKEN)
        authorization_code = os.getenv(READ_AUTHORIZATION_CODE)
    elif op_type == "WRITE":
        rw_token = WRITE_TOKEN
        rw_code = WRITE_AUTHORIZATION_CODE
        token = os.getenv(WRITE_TOKEN)
        authorization_code = os.getenv(WRITE_AUTHORIZATION_CODE)
    else:
        print(op_type + " is a non supported operation")
        exit(1)

    assert authorization_code is not None, "For " + op_type + " operation, you need to retrieve a " + op_type \
                                           + " authorization code and set " + rw_code \
                                           + " variable in the " + ENV_PATH + " file. See README instructions."
    client_id = os.getenv(CLIENT_ID)
    client_secret = os.getenv(CLIENT_SECRET)
    assert client_id is not None, "Env var " + CLIENT_ID + " is required. Copy its value from your strava account"
    assert client_secret is not None, "Env var " + CLIENT_SECRET + " is required. Copy its value from your strava account"

    if token is not None:
        token = json.loads(token)
    else:
        # First call, we do not yet have the read or write token, let's retrieve a authorization code and
        # then retrieve the token
        res = requests.post(
            url='https://www.strava.com/oauth/token',
            data={
                'client_id': int(client_id),
                'client_secret': client_secret,
                'code': authorization_code,
                'grant_type': 'authorization_code',
            }
        )
        if res.status_code < 200 or res.status_code > 300:
            print("Cannot retrieve " + op_type + " token ", res.content)
            exit(1)
        token = res.json()
    if token['expires_at'] < time.time():
        # Incoherent state, if the read/write token is set, that mean that we have already retrieve a read_token/write_token and an
        # read/write authorization code. So, we should have store the authorization code
        assert authorization_code is not None, "Incoherent state. " + rw_token + " env variable has been set in" + ENV_PATH \
                                               + " file but not the " \
                                               + rw_code + " env variable. See README instruction to how to retrieve " \
                                               + op_type + " authorization code and set " + rw_code + " variable in " \
                                               + ENV_PATH + " file"

        res = requests.post(
            url='https://www.strava.com/oauth/token',
            data={
                'client_id': int(client_id),
                'client_secret': client_secret,
                'code': authorization_code,
                'grant_type': 'refresh_token',
                'refresh_token': token['refresh_token']
            }
        )

        if res.status_code < 200 or res.status_code > 300:
            print("Cannot retrieve " + op_type + " token ", res.content)
            exit(1)
        token = res.json()  # Save new tokens to file
    if op_type == "READ":
        dotenv.set_key(ENV_PATH, READ_TOKEN, json.dumps(token))
        dotenv.set_key(ENV_PATH, READ_AUTHORIZATION_CODE, authorization_code)
    elif op_type == "WRITE":
        dotenv.set_key(ENV_PATH, WRITE_TOKEN, json.dumps(token))
        dotenv.set_key(ENV_PATH, WRITE_AUTHORIZATION_CODE, authorization_code)
    return token


# retrieve last uploaded activity infos from strava in json format
def get_last_activity(read_token):
    url = "https://www.strava.com/api/v3/activities"
    access_token = read_token['access_token']
    # change per_page (up to 200) and page (1,2,3 etc.) to retrieve more activities
    r = requests.get(url + '?access_token=' + access_token + '&per_page=1' + '&page=1')
    if r.status_code < 200 or r.status_code > 300:
        print("Cannot retrieve last activity ", r.content)
        exit(1)
    info = r.content[1:len(r.content) - 1]
    return json.loads(info)


# upload an activity to strava
def push_activity(write_token, activity_path, start_time, start_time_pattern='%Y-%m-%dT%H:%M:%SZ',
                  device_name="kalenji", file_format="gpx", on_home_trainer=False):
    files = {'file': open(activity_path, 'rb')}
    # now date is local time aware
    now_as_string = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    now_as_string = now_as_string.split(" ")

    # convert start_time using local timezone
    start_time_object = datetime.datetime.strptime(start_time, start_time_pattern)
    to_zone = tz.tzlocal()
    from_zone = tz.tzutc()
    start_time_object = start_time_object.replace(tzinfo=from_zone)
    start_time_object = start_time_object.astimezone(to_zone)
    start_time_as_string = start_time_object.strftime("%d-%m-%Y %H:%M:%S")
    start_time_as_string = start_time_as_string.split(" ")

    params = {"name": device_name + " ride on " + start_time_as_string[0] + " at " + start_time_as_string[1],
              "description": "upload activity using exporter script on " + now_as_string[0] + " at " + now_as_string[1],
              "data_type": file_format, "trainer": "Workout"}
    if on_home_trainer:
        params["trainer"] = " VirtualRide"

    r = requests.post('https://www.strava.com/api/v3/uploads?access_token=' + write_token['access_token'],
                      files=files, data=params)
    if r.status_code < 200 or r.status_code > 300:
        print("Cannot push activity " + activity_path, r.content)
        exit(1)
    return r.json()


# verifiy the status of an uploaded acitvity (processed, ready , duplicate etc.)
def check_upload(write_token, activity_id, activity_path):
    r = requests.get(
        'https://www.strava.com/api/v3/uploads/' + activity_id + '?access_token=' + write_token['access_token'])
    if r.status_code < 200 or r.status_code > 300:
        print("Cannot check upload status for activity " + activity_path, r.content)
        exit(1)
    return r.json()


# return the following infos for an activity : (distance in km, time in minutes)
def compute_activity_stats(path_to_file):
    file_content = open(path_to_file, 'rb')
    soup = bs.BeautifulSoup(file_content, 'html.parser')
    activities_coords = soup.find_all("trkpt")
    assert len(activities_coords) >= 2, path_to_file + "activity must contain at least two geo points"
    id1, id2 = 0, 1
    dist_in_meters = 0
    total_activity_time_in_seconds = 0
    while id2 < len(activities_coords):
        lat1, long1 = float(activities_coords[id1].get("lat")), float(activities_coords[id1].get("lon"))
        lat2, long2 = float(activities_coords[id2].get("lat")), float(activities_coords[id2].get("lon"))
        dist_in_meters += haversine((lat1, long1), (lat2, long2))
        # date2 = datetime.datetime.strptime(activities_coords[id2].find_all("time")[0].string, '%Y-%m-%dT%H:%M:%S.%fZ')
        # date1 = datetime.datetime.strptime(activities_coords[id1].find_all("time")[0].string, '%Y-%m-%dT%H:%M:%S.%fZ')
        # elapsed_time = date2 - date1
        # minutes, seconds = divmod(elapsed_time.total_seconds(), 60)
        # total_activity_time_in_seconds = total_activity_time_in_seconds + seconds + minutes * 60
        total_activity_time_in_seconds = total_activity_time_in_seconds + 5
        id1 += 1
        id2 += 1
    return (dist_in_meters / 1000), (total_activity_time_in_seconds / 60)


# compute the distance in meter between two geo points
# taken from https://janakiev.com/blog/gps-points-distance-python/
def haversine(coord1, coord2):
    R = 6372800  # Earth radius in meters
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# select activities to upload base on the date of the last uploaded activity
# return an array of the following tuple : (activity_path, starting_time_of_the_activity)
def select_activities_to_upload(conf, date_last_activity):
    folder = os.listdir(conf["activities_folder"])
    last_date = datetime.datetime.strptime(date_last_activity, '%Y-%m-%dT%H:%M:%SZ')
    activities_to_upload = []
    for file in folder:
        if file.endswith('gpx'):
            file_path = os.path.join(conf["activities_folder"], file)
            file_content = open(file_path, 'rb')
            soup = bs.BeautifulSoup(file_content, 'html.parser')
            starting_time = soup.find_all("metadata")[0].find_all("time")[0].string
            starting_time_as_object = datetime.datetime.strptime(starting_time, '%Y-%m-%dT%H:%M:%SZ')
            if starting_time_as_object > last_date:
                activities_to_upload.append((file_path, starting_time))
    # sort on activity name, older activity will be uploaded first
    activities_to_upload.sort(key=lambda elt: elt[0])
    return activities_to_upload


def load_conf_file(required_params):
    # load conf file
    content = open("configuration", 'r').read().split("\n")
    # print(type(content))
    conf_as_json = {}
    for line in content:
        key_and_val = line.split(":")
        if len(key_and_val) == 2:
            conf_as_json[key_and_val[0]] = key_and_val[1]
        else:
            print("Ignore line : ", line, " , should follow pattern 'key:value'")
    for key in required_params:
        if key[0] not in conf_as_json:
            print("Key " + key[0] + " is required in configuration file. it definition is : " + key[1])
            exit(1)
    return conf_as_json


# I dont'know why, but sometimes, the kalenji watch record one last geo bad point which will increase
# the distance of an acitvity. This function just remove the last geo point of the activity
def delete_last_activity_geo_point(path_to_file):
    with  open(path_to_file, 'rb') as file_content:
        soup = bs.BeautifulSoup(file_content, 'html.parser')
        activities_coords = soup.find_all("trkpt")
        if len(activities_coords) > 0:
            (activities_coords[len(activities_coords) - 1]).extract()
            with open(path_to_file, "w") as file:
                file.write(str(soup))


def check_valid_env_file(path_to_file):
    with  open(path_to_file, 'r') as file_content:
        contents = file_content.read()
        if not contents.endswith("\n"):
            print(path_to_file + " file must end with an empty line.")
            exit(1)


if __name__ == "__main__":
    check_valid_env_file(ENV_PATH)
    # load env variable
    dotenv.load_dotenv(ENV_PATH)
    configuration = load_conf_file([("activities_folder", "Path to folder which contains activities"),
                                    ("max_dist",
                                     "up to this distance in km, consider that the acitivity may contain a bad geopoint")])
    read_token = authenticate("READ")
    last_activity_info = get_last_activity(read_token)
    print("Computing from " + configuration["activities_folder"] + " activities to upload. Last activity date is " +
          last_activity_info['start_date'])
    activities = select_activities_to_upload(configuration, last_activity_info['start_date'])
    if len(activities) == 0:
        print("No activity to upload")
        exit(1)
    print("Trying to upload these activities ", activities)
    write_token = authenticate("WRITE")
    pushed_infos = {}
    for activity_path, start_time in activities:
        dist, enjoy_time = compute_activity_stats(activity_path)
        # for the moment, let's just delete the last geo point and see if it's fix the activity
        # if it's not sufficient, we will find another way to deal with this case
        if dist > float(configuration["max_dist"]):
            # WARNING
            print(
                "For activity " + activity_path + " , dist=" + str(
                    dist) + " km and time=" + str(enjoy_time) + " minutes. Max activity distance is"
                + configuration["max_dist"] + " km. Fixing this activity by removing the last geo point.")
            delete_last_activity_geo_point(activity_path)
            dist, enjoy_time = compute_activity_stats(activity_path)
        if dist > float(configuration["max_dist"]):
            print(" Cannot Fix activity " + activity_path + " , dist=" + str(
                dist) + " km and time=" + str(enjoy_time) + " minutes. Max activity distance is"
                  + configuration["max_dist"] + " km. Bailing out.")
            exit(1)
        info = push_activity(write_token, activity_path, start_time)
        pushed_infos[info["id_str"]] = (activity_path, dist, enjoy_time)
    for activity_id, value in pushed_infos.items():
        activity_path, dist, enjoy_time = value
        checked = check_upload(write_token, activity_id, activity_path)
        while "processed" in checked["status"]:
            print("Current Status is '" + checked[
                "status"] + "' .Checking new processing status for the id " + activity_id + " associate to the activity " + activity_path)
            # strava advise to wait 8 second before checking if you activity is ready ( increase this value if you're consumming
            # lot of api calls)
            time.sleep(8)
            checked = check_upload(write_token, activity_id, activity_path)
        if "ready" in checked["status"]:
            print("For pushed activity " + activity_path + " dist=" + str(dist) + "km, time=" + str(
                enjoy_time) + "minutes")
        else:
            print("Error when check upload status for activity " + activity_path, checked)
