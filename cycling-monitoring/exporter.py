import datetime
import json
import os
import time
from typing import Dict, List

from flask import render_template

import dotenv
import requests
from flask import Flask
from pymongo import MongoClient
from pymongo.errors import BulkWriteError

# env variables
ENV_PATH = ".env"
CLIENT_ID = "CLIENT_ID"
CLIENT_SECRET = "CLIENT_SECRET"
# TODO :  when get_authorization_code will be implemented, you will not need this var anymore
READ_AUTHORIZATION_CODE = "READ_AUTHORIZATION_CODE"
WRITE_AUTHORIZATION_CODE = "WRITE_AUTHORIZATION_CODE"
READ_TOKEN = "READ_TOKEN"
WRITE_TOKEN = "WRITE_TOKEN"


########################################## strava request  ################################"
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


# retrieve activities that are after a timestamp
# to retrieve all activites, put a timestamp that is in the past (for example 01/01/1970)
def get_summary_activities(r_token: dict, page_number: int, after: int = None) -> List[Dict]:
    if after is None:
        print(" After parameters cannot be  null")
        exit(1)
    else:
        time_param = "&after=" + str(after)
    url = "https://www.strava.com/api/v3/activities"
    access_token = r_token['access_token']
    # change per_page (up to 200) and page (1,2,3 etc.) to retrieve more activities
    r = requests.get(
        url + '?access_token=' + access_token + '&per_page=200' + '&page=' + str(page_number) + time_param)
    if r.status_code < 200 or r.status_code > 300:
        print("Cannot activities ", r.content)
        return [{"error": r.content}]
    return r.json()


def get_details_activity(r_token: dict, activity_id: str) -> ({}, str, str):
    url = "https://www.strava.com/api/v3/activities/" + activity_id
    access_token = r_token['access_token']
    r = requests.get(url + '?access_token=' + access_token + '&per_page=1' + '&page=1')
    X_RateLimit_Usage = None
    if r.headers.get('X-RateLimit-Usage') is not None:
        X_RateLimit_Usage = r.headers.get('X-RateLimit-Usage')
    X_RateLimit_Limit = None
    if r.headers.get('X-RateLimit-Limit') is not None:
        X_RateLimit_Limit = r.headers.get('X-RateLimit-Limit')
    if r.status_code < 200 or r.status_code > 300:
        return {"error": r.content}, X_RateLimit_Usage, X_RateLimit_Limit
    return json.loads(r.content), X_RateLimit_Usage, X_RateLimit_Limit


################################### mongo ####################################################################
def insert_activities_to_mongo(activities: List[Dict], collection) -> List:
    try:
        for act in activities:
            collection.update_one({"id": act["id"]}, {"$set": act}, True)
    except BulkWriteError as bwe:
        return [{"error": bwe.details}]


# TODO : better handling of errors.
def update_activity_into_mongo(doc_to_update: {}, new_values: {}, collection):
    return collection.update_one(doc_to_update, {"$set": new_values}, True).acknowledged


def get_ids_activities_to_update_from_mongo(collection):
    match = collection.find({"segment_efforts": {"$exists": False}}, {"_id": 0, "id": 1})
    return [m for m in match]


def get_last_downloaded_activity_from_mongo(collection):
    match = collection.find({}, {"start_date_local": 1, "_id": 0}).sort("start_date_local", -1).limit(1)
    date_array = [m for m in match]
    if len(date_array) == 0:
        return "1970-01-01T00:00:00Z"
    else:
        return (date_array[0]["start_date_local"]).split("T")[0]


def get_average_speed_from_mongo(collection):
    match = collection.find({"average_speed": {"$exists": True}},
                            {"_id": 0, "average_speed": 1, "start_date_local": 1}).sort(
        "start_date_local", 1)
    res = []
    for m in match:
        doc = {}
        doc["speed"] = m["average_speed"] * 3.6
        doc["date"] = (m["start_date_local"]).split("T")[0]
        res.append(doc)
    return res


###################################### APP LOGIC  ################################################################"

def build_batch_summary_activities(strava_activities: List[Dict]) -> List[Dict]:
    if len(strava_activities) == 0:
        return []
    batch_docs_to_insert: List = []
    for activity in strava_activities:
        current_doc = {}
        # level 1
        level1_keys = ['id', 'name', 'distance', 'moving_time', 'elapsed_time', 'total_elevation_gain',
                       'start_date_local', 'start_latlng', 'start_latlng', 'end_latlng', 'average_speed',
                       'max_speed',
                       'average_watts', ]
        for k in level1_keys:
            if activity.get(k) is not None:
                current_doc[k] = activity[k]
            # add logging if key not found

        if current_doc is not {}:
            batch_docs_to_insert.append(current_doc)
    return batch_docs_to_insert


def build_details_activity_to_update(activity: {}) -> {}:
    current_doc = {}
    for k in ['description']:
        if activity.get(k) is not None:
            current_doc[k] = activity[k]
        # add logging if key not found
    # print("current", current_doc)
    level2_keys = [('gear', 'id'), ('gear', 'name')]
    for k1, k2 in level2_keys:
        if activity.get(k1) is not None:
            if activity.get(k1).get(k2) is not None:
                if current_doc.get(k1) is None:
                    current_doc[k1] = {}
                current_doc[k1][k2] = activity[k1][k2]
        # add logging if key not found

    # keep interesting key in segments efforts.
    if activity.get('segment_efforts'):
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

    return current_doc


def check_valid_env_file(path_to_file):
    with  open(path_to_file, 'r') as file_content:
        contents = file_content.read()
        if not contents.endswith("\n"):
            print(path_to_file + " file must end with an empty line.")
            exit(1)


######################################  web app endpoints ####################################
app = Flask(__name__)
client = MongoClient('localhost', 27017)
collection = client.strava.activities


@app.route('/refresh')
def refresh():
    check_valid_env_file(ENV_PATH)
    # load env variable
    dotenv.load_dotenv(ENV_PATH)
    read_token = authenticate("READ")
    last_date_downloaded_activity = get_last_downloaded_activity_from_mongo(collection)
    time_after = time.mktime(
        datetime.datetime.strptime(last_date_downloaded_activity, "%Y-%m-%d").timetuple())
    activities = get_summary_activities(r_token=read_token, page_number=1, after=time_after)
    li = build_batch_summary_activities(activities)
    # # print(li)
    insert_activities_to_mongo(li, collection)
    ids_to_get_details = get_ids_activities_to_update_from_mongo(collection)
    # print(len(ids_to_get_details))
    for doc_with_id in ids_to_get_details:
        # TODO : stop this loop if we reach api usage limit
        detail, _, _ = get_details_activity(r_token=read_token, activity_id=str(doc_with_id["id"]))
        details_activity = build_details_activity_to_update(detail)
        if details_activity is not {}:
            update_activity_into_mongo(doc_with_id, details_activity, collection)


@app.route('/average_speed')
def average_speed():
    # check_valid_env_file(ENV_PATH)
    # # load env variable
    # dotenv.load_dotenv(ENV_PATH)
    # read_token = authenticate("READ")
    # last_activity_info = get_last_activity(read_token, "4098064182")
    # print(last_activity_info)
    # mov = collection.find(projection={'_id': 0})
    data = get_average_speed_from_mongo(collection)
    return render_template('index.html', datar=data)
    # return mov[0]

# if __name__ == "__main__":
#     check_valid_env_file(ENV_PATH)
#     # load env variable
#     dotenv.load_dotenv(ENV_PATH)
#     read_token = authenticate("READ")
#     client = MongoClient('localhost', 27017)
#     collection = client.strava.activities
#     # last_date_downloaded_activity = get_last_downloaded_activity_from_mongo(collection)
#     # time_after = time.mktime(
#     #     datetime.datetime.strptime(last_date_downloaded_activity, "%Y-%m-%d").timetuple())
#     # activities = get_summary_activities(r_token=read_token, page_number=1, after=time_after)
#     # li = build_batch_summary_activities(activities)
#     # # # print(li)
#     # insert_activities_to_mongo(li, collection)
#     # ids_to_get_details = get_ids_activities_to_update_from_mongo(collection)
#     # print(len(ids_to_get_details))
#     # for doc_with_id in ids_to_get_details:
#     #     detail, _, _ = get_details_activity(r_token=read_token, activity_id=str(doc_with_id["id"]))
#     #     details_activity = build_details_activity_to_update(detail)
#     #     if details_activity is not {}:
#     #         update_activity_into_mongo(doc_with_id, details_activity, collection)
#
#     print(get_average_speed_from_mongo(collection))
