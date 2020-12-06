from fitparse import FitFile
import exporter
import math, time, datetime, os, dotenv


# select activities to upload base on the date of the last uploaded activity
# return an array of the following tuple : (activity_path, starting_time_of_the_activity)
def select_activities_to_upload(conf, date_last_activity):
    folder = os.listdir(conf["garmin_activities_folder"])
    last_date = datetime.datetime.strptime(date_last_activity, '%Y-%m-%dT%H:%M:%SZ')
    activities_to_upload = []
    for file in folder:
        file_path = os.path.join(conf["garmin_activities_folder"], file)
        fitfile = FitFile(file_path)
        records = [r for r in fitfile.get_messages('record')]
        if len(records) > 0:
            for record_data in records[0]:
                if record_data.name == "timestamp":
                    starting_time = record_data.value
                    # starting_time_as_object = datetime.datetime.strptime(starting_time, '%Y-%m-%d %H:%M:%S')
                    if starting_time > last_date:
                        activities_to_upload.append((file_path, starting_time.strftime('%Y-%m-%d %H:%M:%S')))
        else:
            print("No record for this activity " + file_path)

    # sort on activity name, older activity will be uploaded first
    activities_to_upload.sort(key=lambda elt: elt[0])
    return activities_to_upload


# return the following infos for an activity : (distance in km, time in minutes)
def compute_activity_stats(path_to_file):
    fitfile = FitFile(path_to_file)
    records = [r for r in fitfile.get_messages('record')]
    assert len(records) >= 2, path_to_file + "activity must contain at least two records"
    id1, id2 = 0, 1
    dist_in_meters = 0
    total_activity_time_in_seconds = 0
    while id2 < len(records):
        record_data1 = {r.name: r.value for r in records[id1]}
        record_data2 = {r.name: r.value for r in records[id2]}
        if record_data1.get("position_lat") is not None:
            lat1, long1 = float(record_data1["position_lat"] * 180 / math.pow(2, 31)), float(
                record_data1["position_long"] * 180 / math.pow(2, 31))
            lat2, long2 = float(record_data2["position_lat"] * 180 / math.pow(2, 31)), float(
                record_data2["position_long"] * 180 / math.pow(2, 31))
            dist_in_meters += exporter.haversine((lat1, long1), (lat2, long2))
        if record_data1.get("timestamp"):
            date2 = record_data2["timestamp"]
            date1 = record_data1["timestamp"]
            elapsed_time = date2 - date1
            minutes, seconds = divmod(elapsed_time.total_seconds(), 60)
            # print(date2, date1, "=====", minutes, seconds)
            total_activity_time_in_seconds = total_activity_time_in_seconds + seconds + minutes * 60
            # total_activity_time_in_seconds = total_activity_time_in_seconds + 5
        id1, id2 = id1 + 1, id2 + 1
    return (dist_in_meters / 1000), (total_activity_time_in_seconds / 60)


if __name__ == '__main__':
    exporter.check_valid_env_file(exporter.ENV_PATH)
    # load env variable
    dotenv.load_dotenv(exporter.ENV_PATH)
    configuration = exporter.load_conf_file([("garmin_activities_folder", "Path to folder which contains activities")])
    read_token = exporter.authenticate("READ")
    last_activity_info = exporter.get_last_activity(read_token)
    print("Last activity date is " +
          last_activity_info['start_date'] + ". Computing from " + configuration[
              "garmin_activities_folder"] + " activities to upload.")
    activities = select_activities_to_upload(configuration, last_activity_info['start_date'])
    if len(activities) == 0:
        print("No activity to upload")
        exit(1)
    print("Trying to upload these activities ", activities)
    write_token = exporter.authenticate("WRITE")
    pushed_infos = {}
    for activity_path, start_time in activities:
        dist, enjoy_time = compute_activity_stats(activity_path)
        on_home_trainer = False
        if dist == 0.0:
            on_home_trainer = True
        info = exporter.push_activity(write_token, activity_path, start_time, start_time_pattern='%Y-%m-%d %H:%M:%S',
                                      device_name="Garmin", file_format="fit", on_home_trainer=on_home_trainer)
        pushed_infos[info["id_str"]] = (activity_path, dist, enjoy_time)
    for activity_id, value in pushed_infos.items():
        activity_path, dist, enjoy_time = value
        checked = exporter.check_upload(write_token, activity_id, activity_path)
        while "processed" in checked["status"]:
            print("Current Status is '" + checked[
                "status"] + "' .Checking new processing status for the id " + activity_id + " associate to the activity " + activity_path)
            # strava advise to wait 8 second before checking if you activity is ready ( increase this value if you're consumming
            # lot of api calls)
            time.sleep(8)
            checked = exporter.check_upload(write_token, activity_id, activity_path)
        if "ready" in checked["status"]:
            print("For pushed activity " + activity_path + " dist=" + str(dist) + "km, time=" + str(
                enjoy_time) + "minutes")
        else:
            print("Error when check upload status for activity " + activity_path, checked)
