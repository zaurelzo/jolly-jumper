from unittest import TestCase

import dotenv

from utils.configuration import Configuration


class TestConfiguration(TestCase):

    def test_load_unvalid_env(self):
        with self.assertRaises(AssertionError):
            conf = Configuration(path_to_env="utils/test-resources/.unvalid_env",
                                 path_to_app_conf="utils/test-resources/app.properties",
                                 required_params={
                                     "garmin_activities_folder": "Path to folder which contains activities"})

    def test_missing_key_client_id(self):
        with self.assertRaises(AssertionError):
            other = Configuration(path_to_env="utils/test-resources/.missing_key_env",
                                  path_to_app_conf="utils/test-resources/app.properties",
                                  required_params={
                                      "garmin_activities_folder": "Path to folder which contains activities"})
            other.get_client_id()

    def test_missing_key_client_secret(self):
        with self.assertRaises(AssertionError):
            other = Configuration(path_to_env="utils/test-resources/.missing_key_env",
                                  path_to_app_conf="utils/test-resources/app.properties",
                                  required_params={
                                      "garmin_activities_folder": "Path to folder which contains activities"})
            other.get_client_secret()

    def test_missing_key_token(self):
        other = Configuration(path_to_env="utils/test-resources/.missing_key_env",
                              path_to_app_conf="utils/test-resources/app.properties",
                              required_params={
                                  "garmin_activities_folder": "Path to folder which contains activities"})
        self.assertIsNone(other.get_token())

    def test_load_valid_env(self):
        conf = Configuration(path_to_env="utils/test-resources/.valid_env",
                             path_to_app_conf="utils/test-resources/app.properties",
                             required_params={
                                 "garmin_activities_folder": "Path to folder which contains activities"})
        self.assertEqual(conf.get_client_id(), "some-id")
        self.assertEqual(conf.get_client_secret(), "some-secret")
        self.assertEqual(conf.get_token(), "some-token")
        self.assertEqual(conf.get_app_conf(), {"activities_folder": "/home/zaurelzo/kalenji_activities/",
                                               "max_dist": "100"
            , "garmin_activities_folder": "/media/zaurelzo/GARMIN/Garmin/Activities"})
