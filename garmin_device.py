import logging
import os

from fitparse import FitFile


class garmin_device():

    def __init__(self, configuration,client):
        self.configuration = configuration
        self.client =client
        self.date_pattern = '%Y-%m-%d %H:%M:%S'

    def select_activities_to_upload(self, date_last_activity):
        """ select activities to upload base on the date of the last uploaded activity
                   return an array of the following tuple : (activity_path, starting_time_of_the_activity)
               """
        activities_path = self.configuration.get_app_conf["garmin_activities_folder"]
        folder = os.listdir(activities_path)
        activities_to_upload = []
        for file in folder:
            file_path = os.path.join(activities_path, file)
            fit_file = FitFile(file_path)
            records = []
            for r in fit_file.get_messages('record'):
                records.append(r)
                break
            if len(records) > 0:
                for record_data in records[0]:
                    if record_data.name == "timestamp":
                        starting_time = record_data.value
                        if starting_time > date_last_activity:
                            activities_to_upload.append((file_path, starting_time.strftime(self.date_pattern)))
            else:
                logging.error("No record for this activity " + file_path)

        # sort on activity name, older activity will be uploaded first
        activities_to_upload.sort(key=lambda elt: elt[0])
        return activities_to_upload

    def export(self, date_last_activity):
        logging.info("Last activity date is %s. Computing from %s activities to upload.",
                     date_last_activity.strftime(self.date_pattern), self.configuration.get_app_conf[
                         "garmin_activities_folder"])

        activities = self.select_activities_to_upload(date_last_activity)
        if len(activities) == 0:
            logging.info("No activity to upload")
            return {}

        logging.info("Trying to upload these activities {}".format(activities))
        pushed_info = {}
        for activity_path, start_time in activities:
            #self.client.upload_activity( activity_file=activity_path, data_type, name=None, description=None,
             #           activity_type=None, private=None, external_id=None)
            info = utils.push_activity(write_token, activity_path, start_time, start_time_pattern='%Y-%m-%d %H:%M:%S',
                                       device_name="Garmin", file_format="fit", on_home_trainer=on_home_trainer)
            pushed_info[info["id_str"]] = (activity_path, dist, enjoy_time)
        for activity_id, value in pushed_info.items():
            activity_path, dist, enjoy_time = value
            checked = utils.check_upload(write_token, activity_id, activity_path)
            while "processed" in checked["status"]:
                print("Current Status is '" + checked[
                    "status"] + "' .Checking new processing status for the id " + activity_id + " associate to the activity " + activity_path)
                # strava advise to wait 8 second before checking if you activity is ready ( increase this value if you're consumming
                # lot of api calls)
                time.sleep(8)
                checked = utils.check_upload(write_token, activity_id, activity_path)
            if "ready" in checked["status"]:
                print("For pushed activity " + activity_path + " dist=" + str(dist) + "km, time=" + str(
                    enjoy_time) + "minutes")
            else:
                print("Error when check upload status for activity " + activity_path, checked)
