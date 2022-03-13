import webbrowser

from flask import Flask, jsonify, url_for, request
from stravalib.client import Client

from APIException import StravaApiException, APIBadRequestError
from utils.configuration import Configuration

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
    client = Client()
    configuration = Configuration(path_to_env="configuration/.env",
                                  path_to_app_conf="configuration/app.properties",
                                  required_params={
                                      "garmin_activities_folder": "Path to folder which contains activities"})
    token_response = client.exchange_code_for_token(client_id=configuration.get_client_id(),
                                                    client_secret=configuration.get_client_secret(),
                                                    code=authorization_code)
    activities = client.get_activities(limit=1)
    for activity in activities:
        print("==============", type(activity.start_date))


# def retrieve_new_token(authorization_code):
#     client_id = os.getenv(CLIENT_ID)
#     if client_id is None:
#         raise AssertionError(
#             "Env var " + CLIENT_ID + " is required. Copy its value from your strava account")
#     client_secret = os.getenv(CLIENT_SECRET)
#     if client_secret is None:
#         raise AssertionError(
#             "Env var " + CLIENT_SECRET + " is required. Copy its value from your strava account")
#
#     res = requests.post(
#         url='https://www.strava.com/oauth/token',
#         data={
#             'client_id': int(client_id),
#             'client_secret': client_secret,
#             'code': authorization_code,
#             'grant_type': 'authorization_code',
#         }
#     )
#     if res.status_code < 200 or res.status_code > 300:
#         raise StravaApiException(
#             "Cannot retrieve new token, http response content" + str(res.content),
#             res.status_code)
#     token = res.json()
#     # Save new tokens to file
#     dotenv.set_key(ENV_PATH, TOKEN, json.dumps(token))
#     return token
#

#
@app.route("/upload")
def upload():
    configuration = Configuration(path_to_env="configuration/.env",
                                  path_to_app_conf="configuration/app.properties",
                                  required_params={
                                      "garmin_activities_folder": "Path to folder which contains activities"})

    token = configuration.get_token()
    if token is None:
        client = Client()
        # authorization() will be call after redirection
        authorize_url = client.authorization_url(client_id=configuration.get_client_id(),
                                                 redirect_uri=url_for(".authorization", _external=True),
                                                 scope=["profile:read_all", "activity:read_all", "profile:write",
                                                        "activity:write"])
        webbrowser.open(authorize_url, new=0)
    else:
        pass
