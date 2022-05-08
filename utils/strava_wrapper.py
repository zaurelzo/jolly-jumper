import json
import webbrowser
from datetime import datetime

from flask import url_for, request
from stravalib import Client


class Strava_wrapper():

    def __init__(self, configuration, device_exporter):
        self.configuration = configuration
        self.device_exporter = device_exporter
        self.client = Client()

    def initial_upload(self):
        token = self.configuration.get_token()
        if token is None:
            # authorization endpoint  will be call after redirection
            authorize_url = self.client.authorization_url(client_id=self.configuration.get_client_id(),
                                                          redirect_uri=url_for(".authorization", _external=True),
                                                          scope=["profile:read_all", "activity:read_all",
                                                                 "profile:write",
                                                                 "activity:write"])
            webbrowser.open(authorize_url, new=0)
            return "The authorization has been initiated"
        else:
            token = json.loads(token)
            return self.device_exporter.export(token, self.__get_last_activity())

    def __get_last_activity(self):
        activities = self.client.get_activities(limit=1)
        for activity in activities:
            return activity.start_date
        return datetime.strptime("1970-01-01T00:00:00Z", '%Y-%m-%dT%H:%M:%SZ')

    def authorization(self):
        authorization_code = request.args.get('code')
        token_response = self.client.exchange_code_for_token(client_id=self.configuration.get_client_id(),
                                                             client_secret=self.configuration.get_client_secret(),
                                                             code=authorization_code)
        self.configuration.save_token(token_response)
        return self.device_exporter.export(token_response, self.__get_last_activity())
