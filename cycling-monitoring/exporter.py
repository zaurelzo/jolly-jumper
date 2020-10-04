import datetime
import json
import math
import os
import time

import requests
import dotenv
from dateutil import tz

from flask import Flask, render_template
from pymongo import MongoClient

from typing import Dict, List

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


# retrieve activities that are before or after a timestamp
def get_activities(read_token, before=None, after=None):
    if (before is not None) and (after is not None):
        print("incohrent parameters, before and after parameters cannot be specified on the same call")
        exit(1)
    elif (before is None) and (after is None):
        print("incohrent parameters, before and after parameters cannot be both null")
        exit(1)
    else:
        time_param = "&"
        if before is not None:
            time_param = time_param + "before=" + before
        else:
            time_param = time_param + "after=" + after
    url = "https://www.strava.com/api/v3/activities"
    access_token = read_token['access_token']
    keep_running = True
    page_number = 1
    list_activities = []
    while keep_running:
        # change per_page (up to 200) and page (1,2,3 etc.) to retrieve more activities
        r = requests.get(
            url + '?access_token=' + access_token + '&per_page=200' + '&page=' + str(page_number) + time_param)
        if r.status_code < 200 or r.status_code > 300:
            print("Cannot retrieve last activity ", r.content)
            exit(1)
        r = r.json()
        if not r:
            keep_running = False
        else:
            # Todo add Them to the list
            page_number = page_number + 1
    return list_activities
    # return json.loads(info)


# upload an activity to strava
def push_activity(write_token, activity_path, start_time):
    files = {'file': open(activity_path, 'rb')}
    # now date is local time aware
    now_as_string = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    now_as_string = now_as_string.split(" ")

    # convert start_time using local timezone
    start_time_object = datetime.datetime.strptime(start_time, '%Y-%m-%dT%H:%M:%SZ')
    to_zone = tz.tzlocal()
    from_zone = tz.tzutc()
    start_time_object = start_time_object.replace(tzinfo=from_zone)
    start_time_object = start_time_object.astimezone(to_zone)
    start_time_as_string = start_time_object.strftime("%d-%m-%Y %H:%M:%S")
    start_time_as_string = start_time_as_string.split(" ")

    params = {"name": "ride on " + start_time_as_string[0] + " at " + start_time_as_string[1],
              "description": "upload activity using exporter script on " + now_as_string[0] + " at " + now_as_string[1],
              "data_type": "gpx"}
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


def check_valid_env_file(path_to_file):
    with  open(path_to_file, 'r') as file_content:
        contents = file_content.read()
        if not contents.endswith("\n"):
            print(path_to_file + " file must end with an empty line.")
            exit(1)


app = Flask(__name__)
client = MongoClient('localhost', 27017)
col = client.test.movie


def build_batch_activities(strava_activities: List[Dict]) -> List[List[Dict]]:
    if len(strava_activities) == 0:
        return []

    batch_docs_to_insert: List = []
    current_batch = []
    for activity in strava_activities:
        current_doc = {}
        # level 1
        level1_keys = ['name', 'distance', 'moving_time', 'elapsed_time', 'total_elevation_gain', 'start_date_local',
                       'start_latlng', 'start_latlng', 'end_latlng', 'average_speed', 'max_speed', 'average_watts',
                       'description']
        for k in level1_keys:
            if activity.get(k) is not None:
                current_doc[k] = activity[k]
            # add logging if key not found

        level2_keys = [('gear', 'id'), ('gear', 'name')]
        for k1, k2 in level2_keys:
            if activity.get(k1) is not None:
                if activity.get(k1).get(k2) is not None:
                    if current_doc.get(k1) is None:
                        current_doc[k1] = {}
                    current_doc[k1][k2] = activity[k1][k2]
            # add logging if key not found

        # keep interesting key in segments efforts.
        list_of_segments = activity['segment_efforts']
        if list_of_segments is not None:
            current_doc['segment_efforts'] = []
            for i in range(len(list_of_segments)):
                current_doc['segment_efforts'].append({})
            segments_keys = ['name', 'moving_time', 'elapsed_time', 'start_date_local', 'distance', 'average_watts']
            for i, seg in enumerate(list_of_segments):
                for k in segments_keys:
                    if seg.get(k) is not None:
                        current_doc['segment_efforts'][i][k] = seg[k]

                # get segment_efforts.segment.id'
                if seg.get('segment') is not None:
                    if seg.get('segment').get('id') is not None:
                        current_doc['segment_efforts'][i]['segment'] = {'id': seg.get('segment').get('id')}
                # add logging if key not found

        # add doc to new list
        if current_doc is not {}:
            # to effiently insert docs, build batch of size below 1000 elements
            if len(current_batch) > 900:
                batch_docs_to_insert.append(current_batch)
                current_batch = []
            current_batch.append(current_doc)
    if len(current_batch) != 0:
        batch_docs_to_insert.append(current_batch)
    return batch_docs_to_insert


@app.route('/')
def hello():
    # check_valid_env_file(ENV_PATH)
    # # load env variable
    # dotenv.load_dotenv(ENV_PATH)
    # read_token = authenticate("READ")
    # last_activity_info = get_last_activity(read_token, "4098064182")
    # print(last_activity_info)
    mov = col.find(projection={'_id': 0})
    print("========", mov)
    # return render_template('index.html')
    return mov[0]


if __name__ == "__main__":
    check_valid_env_file(ENV_PATH)
    # load env variable
    dotenv.load_dotenv(ENV_PATH)
    read_token = authenticate("READ")
    last_activity_info = get_activities(read_token, "4098064182")
    li = build_batch_activities(last_activity_info)
    print(li)

# print("Computing from " + configuration["activities_folder"] + " activities to upload. Last activity date is " +
#       last_activity_info['start_date'])
# activities = select_activities_to_upload(configuration, last_activity_info['start_date'])
# if len(activities) == 0:
#     print("No activity to upload")
#     exit(1)
# print("Trying to upload these activities ", activities)
# write_token = authenticate("WRITE")
# pushed_infos = {}
# for activity_path, start_time in activities:
#     dist, enjoy_time = compute_activity_stats(activity_path)
#     # for the moment, let's just delete the last geo point and see if it's fix the activity
#     # if it's not sufficient, we will find another way to deal with this case
#     if dist > float(configuration["max_dist"]):
#         # WARNING
#         print(
#             "For activity " + activity_path + " , dist=" + str(
#                 dist) + " km and time=" + str(enjoy_time) + " minutes. Max activity distance is"
#             + configuration["max_dist"] + " km. Fixing this activity by removing the last geo point.")
#         delete_last_activity_geo_point(activity_path)
#         dist, enjoy_time = compute_activity_stats(activity_path)
#     if dist > float(configuration["max_dist"]):
#         print(" Cannot Fix activity " + activity_path + " , dist=" + str(
#             dist) + " km and time=" + str(enjoy_time) + " minutes. Max activity distance is"
#               + configuration["max_dist"] + " km. Bailing out.")
#         exit(1)
#     info = push_activity(write_token, activity_path, start_time)
#     pushed_infos[info["id_str"]] = (activity_path, dist, enjoy_time)
# for activity_id, value in pushed_infos.items():
#     activity_path, dist, enjoy_time = value
#     checked = check_upload(write_token, activity_id, activity_path)
#     while "processed" in checked["status"]:
#         print("Current Status is '" + checked[
#             "status"] + "' .Checking new processing status for the id " + activity_id + " associate to the activity " + activity_path)
#         # strava advise to wait 8 second before checking if you activity is ready ( increase this value if you're consumming
#         # lot of api calls)
#         time.sleep(8)
#         checked = check_upload(write_token, activity_id, activity_path)
#     if "ready" in checked["status"]:
#         print("For pushed activity " + activity_path + " dist=" + str(dist) + "km, time=" + str(
#             enjoy_time) + "minutes")
#     else:
#         print("Error when check upload status for activity " + activity_path, checked)
