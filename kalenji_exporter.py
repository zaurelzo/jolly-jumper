import datetime
import json
import os
import time
import webbrowser

import bs4 as bs
import requests
import dotenv

from flask import Flask, url_for, request, jsonify
from stravalib import Client

from APIException import APIBadRequestError, StravaApiException
from utils import get_last_activity, push_activity, check_upload, haversine, load_conf_file, check_valid_env_file, \
    refresh_token




# authenticate the user and return a read or write token api


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


app = Flask(__name__)


@app.errorhandler(StravaApiException)
@app.errorhandler(APIBadRequestError)
def handle_exception(err):
    response = {"error": err.description, "message": ""}
    if len(err.args) > 0:
        response["message"] = err.args[0]
    # Add some logging so that we can monitor different types of errors
    return jsonify(response), err.code


@app.errorhandler(500)
def handle_exception(err):
    response = {"error": "Unknown Exception", "message": str(err)}
    return jsonify(response), 500


@app.route('/authorization')
def authorization():
    authorization_code = request.args.get('code')
    token = refresh_token(authorization_code)
    uploaded_activities = internal_upload(token)
    # TODO return uploaded_activities as json


def retrieve_new_token(authorization_code):
    client_id = os.getenv(CLIENT_ID)
    if client_id is None:
        raise AssertionError(
            "Env var " + CLIENT_ID + " is required. Copy its value from your strava account")
    client_secret = os.getenv(CLIENT_SECRET)
    if client_secret is None:
        raise AssertionError(
            "Env var " + CLIENT_SECRET + " is required. Copy its value from your strava account")

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
        raise StravaApiException(
            "Cannot retrieve new token, http response content" + str(res.content),
            res.status_code)
    token = res.json()
    # Save new tokens to file
    dotenv.set_key(ENV_PATH, TOKEN, json.dumps(token))
    return token


def upload_with_new_authoriaztion_code():
    client = Client()
    client_id = os.getenv(CLIENT_ID)
    if client_id is None:
        raise AssertionError(
            "Env var " + CLIENT_ID + " is required. Copy its value from your strava account")
    client_secret = os.getenv(CLIENT_SECRET)
    if client_secret is None:
        raise AssertionError(
            "Env var " + CLIENT_SECRET + " is required. Copy its value from your strava account")
    authorize_url = client.authorization_url(client_id=client_id,
                                             redirect_uri=url_for(".authorization", _external=True),
                                             scope=["profile:read_all", "activity:read_all", "profile:write",
                                                    "activity:write"])
    # ask a user to provide access to his strava account, then code the authorization endpoint to upload  activities
    #TODO: open is the same tab
    webbrowser.open(authorize_url, new=0)


@app.route("/upload")
def upload():
    check_valid_env_file(ENV_PATH)
    # load env variable
    dotenv.load_dotenv(ENV_PATH)
    try:
        token = refresh_token()
        uploaded_activities = internal_upload(token)
        # TODO return uploaded_activities as json
    except ValueError as e:
        print(e)
        upload_with_new_authoriaztion_code()


def internal_upload(token,last):
    configuration = load_conf_file([("activities_folder", "Path to folder which contains activities"),
                                    ("max_dist",
                                     "up to this distance in km, consider that the acitivity may contain a bad geopoint")])
    last_activity_info = get_last_activity(token)
    print("Computing from " + configuration["activities_folder"] + " activities to upload. Last activity date is " +
          last_activity_info['start_date'])
    activities = select_activities_to_upload(configuration, last_activity_info['start_date'])
    if len(activities) == 0:
        return {"message": "No activity to upload"}, 200

    print("Trying to upload these activities ", activities)
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
            raise APIBadRequestError(" Cannot Fix activity " + activity_path + " , dist=" + str(
                dist) + " km and time=" + str(enjoy_time) + " minutes. Max activity distance is"
                                     + configuration["max_dist"] + " km. Bailing out.")
        info = push_activity(token, activity_path, start_time)
        pushed_infos[info["id_str"]] = (activity_path, dist, enjoy_time)
    for activity_id, value in pushed_infos.items():
        activity_path, dist, enjoy_time = value
        checked = check_upload(token, activity_id, activity_path)
        # TODO : build result list to return
        while "processed" in checked["status"]:
            print("Current Status is '" + checked[
                "status"] + "' .Checking new processing status for the id " + activity_id + " associate to the activity " + activity_path)
            # strava advise to wait 8 second before checking if you activity is ready ( increase this value if you're consumming
            # lot of api calls)
            time.sleep(8)
            checked = check_upload(token, activity_id, activity_path)
        if "ready" in checked["status"]:
            print("For pushed activity " + activity_path + " dist=" + str(dist) + "km, time=" + str(
                enjoy_time) + "minutes")
        else:
            print("Error when check upload status for activity " + activity_path, checked)
