# Kalenji Ride Exporter

I am the happy owner of a Kalenji watch that I use to record my cycling activities.  
I wrote this small script to export my latest rides (GPX files) from my watch to my Strava account.

To export activities from the watch to GPX files, I used the open-source project [kalenji-gps-watch-reader](https://github.com/ColinPitrat/kalenji-gps-watch-reader).  
[This article](https://medium.com/swlh/using-python-to-connect-to-stravas-api-and-analyse-your-activities-dummies-guide-5f49727aac86) and the [Strava documentation](https://developers.strava.com/docs/reference/) helped me understand how to use the API.

---

# Garmin Exporter

The exporter also supports Garmin devices.  
The script was tested with my Garmin Edge 520+ device, but I am confident it will work with most Garmin devices.

---

# How to Run

Plug in your watch and run the script:

```bash
exporter.sh
```

# How It Works (Kalenji Watch)

`exporter.sh` creates GPX files using the configuration below and then runs exporter.py:
```bash
source=Path
path=/media/zaurelzo/ONMOVE-220/DATA
device=OnMove200
filters=FixElevation,ComputeInstantSpeed
gpx_extensions=none
directory=/home/zaurelzo/kalenji_activities
```
#  How It Works (Garmin GPS Device)

`fit-exporter.py` reads FIT files from the mounted Garmin device, selects those that are more recent than the last Strava activity, and uploads them to Strava.

#  Environment Configuration

For both devices, you must create a .env file in the project repository containing the following variables:
```bash
CLIENT_ID=client_id_of_your_app_created_in_strava
CLIENT_SECRET=client_secret_of_your_strava_app
READ_AUTHORIZATION_CODE=see_below
WRITE_AUTHORIZATION_CODE=see_below
```
Warning: The .env file must end with an empty line (\n).

# Retrieve Authorization Codes

* Retrieve Read Authorization Code

Paste the link below into your browser. Replace {client_id} with your Strava app client ID.
Authenticate and authorize the app with the requested permissions.

http://www.strava.com/oauth/authorize?client_id={client_id}&response_type=code&redirect_uri=http://localhost/exchange_token&approval_prompt=force&scope=profile:read_all,activity:read_all

You will be redirected to a non-working page. Extract the authorization_code from the URL:

http://localhost/exchange_token?state=&code={authorization_code}&scope=read,activity:read_all,profile:read_all

* Retrieve Write Authorization Code

Follow the same procedure as above, but use this link:

http://www.strava.com/oauth/authorize?client_id={client_id}&response_type=code&redirect_uri=http://localhost/exchange_token&approval_prompt=force&scope=profile:write,activity:write

# TODO
1. Automate Initial Authentication. Use this library to retrieve the read/write token: https://github.com/hozn/stravalib/tree/master/examples/strava-oauth
2. Transform the Python script into a Flask app with an authorization endpoint to retrieve the code:
```python
client = Client()
authorize_url = client.authorization_url(client_id=49524, redirect_uri='http://localhost:5000/authorization',
                                              scope=["profile:read_all","activity:read_all","profile:write","activity:write"])

@app.route.route('/authorization')
def authorization():
	code = request.args.get('code') # this a single code for read and write, you can simplify the exporter script 
    # by using this single instead of read and write code.
    # rest of exporter.py main code
```