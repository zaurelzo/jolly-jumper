import json
import logging

import dotenv

from APIException import APIBadRequestError


class Configuration:
    CLIENT_ID = "CLIENT_ID"
    CLIENT_SECRET = "CLIENT_SECRET"
    TOKEN = "TOKEN"
    AUTHORIZATION_CODE = "AUTHORIZATION_CODE"

    def __init__(self, path_to_env, path_to_app_conf, required_params):
        self.path_to_env = path_to_env
        self.__check_valid_env_file(path_to_env)
        # load env variable
        env_variables=dotenv.dotenv_values(path_to_env)
        self.client_id = env_variables.get(self.CLIENT_ID)
        self.client_secret = env_variables.get(self.CLIENT_SECRET)
        self.token = env_variables.get(self.TOKEN)
        self.app_conf = self.__load_app_configuration(path_to_app_conf, required_params)

    def __check_valid_env_file(self,path ):
        with  open(path, 'r') as file_content:
            contents = file_content.read()
            if not contents.endswith("\n"):
                raise AssertionError(path + " file must end with an empty line.")

    def __load_app_configuration(self, path, required_params):
        '''load conf file'''

        content = open(path, 'r').read().split("\n")
        # print(type(content))
        conf_as_json = {}
        for line in content:
            key_and_val = line.split(":")
            if len(key_and_val) == 2:
                conf_as_json[key_and_val[0]] = key_and_val[1]
            else:
                logging.warning("Ignore line : '%s' that  must match pattern 'key:value'", line)
        for key, value in required_params.items():
            if key not in conf_as_json:
                raise APIBadRequestError(
                    "Key " + key + " is required in app.properties file. it definition is : " + value)
        return conf_as_json


    def get_app_conf(self):
        return self.app_conf

    def get_client_id(self):
        if self.client_id is None:
            raise AssertionError("Parameter " + self.CLIENT_ID + " must be set in file " + self.path_to_env)
        return self.client_id

    def get_client_secret(self):
        if self.client_secret is None:
            raise AssertionError("Parameter " + self.CLIENT_SECRET +  " must be set in file" + self.path_to_env)
        return self.client_secret

    def get_token(self):
        return self.token

    def save_token(self,value):
        dotenv.set_key(self.path_to_env, self.TOKEN, json.dumps(value))



    # def get_last_activity(read_token):
    #     '''Retrieve last uploaded activity infos from strava in json format '''
    #
    #     url = "https://www.strava.com/api/v3/activities"
    #     access_token = read_token['access_token']
    #     # change per_page (up to 200) and page (1,2,3 etc.) to retrieve more activities
    #     r = requests.get(url + '?access_token=' + access_token + '&per_page=1' + '&page=1')
    #     if r.status_code < 200 or r.status_code > 300:
    #         raise StravaApiException("Cannot retrieve last activity, response message = "
    #                                  + str(r.content), r.status_code)
    #     info = r.content[1:len(r.content) - 1]
    #     return json.loads(info)
    #
    #
    # def push_activity(write_token, activity_path, start_time, start_time_pattern='%Y-%m-%dT%H:%M:%SZ',
    #                   device_name="kalenji", file_format="gpx", on_home_trainer=False):
    #     '''upload an activity to strava '''
    #
    #     files = {'file': open(activity_path, 'rb')}
    #     # now date is local time aware
    #     now_as_string = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    #     now_as_string = now_as_string.split(" ")
    #
    #     # convert start_time using local timezone
    #     start_time_object = datetime.datetime.strptime(start_time, start_time_pattern)
    #     to_zone = tz.tzlocal()
    #     from_zone = tz.tzutc()
    #     start_time_object = start_time_object.replace(tzinfo=from_zone)
    #     start_time_object = start_time_object.astimezone(to_zone)
    #     start_time_as_string = start_time_object.strftime("%d-%m-%Y %H:%M:%S")
    #     start_time_as_string = start_time_as_string.split(" ")
    #
    #     params = {"name": device_name + " ride on " + start_time_as_string[0] + " at " + start_time_as_string[1],
    #               "description": "upload activity using exporter script on " + now_as_string[0] + " at " + now_as_string[1],
    #               "data_type": file_format, "trainer": "Workout"}
    #     if on_home_trainer:
    #         params["trainer"] = " VirtualRide"
    #
    #     r = requests.post('https://www.strava.com/api/v3/uploads?access_token=' + write_token['access_token'],
    #                       files=files, data=params)
    #     if r.status_code < 200 or r.status_code > 300:
    #         raise StravaApiException("Cannot push activity " + activity_path + " response message = " + str(r.content),
    #                                  r.status_code)
    #     return r.json()
    #
    #
    # def check_upload(write_token, activity_id, activity_path):
    #     ''' verifiy the status of an uploaded acitvity (processed, ready , duplicate etc.) '''
    #
    #     r = requests.get(
    #         'https://www.strava.com/api/v3/uploads/' + activity_id + '?access_token=' + write_token['access_token'])
    #     if r.status_code < 200 or r.status_code > 300:
    #         raise StravaApiException("Cannot check upload status for activity " + activity_path + " , response message = " +
    #                                  str(r.content), r.status_code)
    #     return r.json()
    #
    #
    # def haversine(coord1, coord2):
    #     """ compute the distance in meter between two geo points,
    #     taken from https://janakiev.com/blog/gps-points-distance-python/ """
    #
    #     R = 6372800  # Earth radius in meters
    #     lat1, lon1 = coord1
    #     lat2, lon2 = coord2
    #     phi1, phi2 = math.radians(lat1), math.radians(lat2)
    #     dphi = math.radians(lat2 - lat1)
    #     dlambda = math.radians(lon2 - lon1)
    #     a = math.sin(dphi / 2) ** 2 + \
    #         math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    #     return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    #
    #

