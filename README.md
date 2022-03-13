# Kalenji Ride Exporter
I am the happy owner of a kalenji watch that I use to record my bike activities.
I wrote this little script to export my last rides from my watch (gpx files) to my strava account. 
To export the activities from the watch to gpx files, I used this open source project [kalenji-gps-watch-reader.](https://github.com/ColinPitrat/kalenji-gps-watch-reader) 
[This article](https://medium.com/swlh/using-python-to-connect-to-stravas-api-and-analyse-your-activities-dummies-guide-5f49727aac86) 
and [strava documentation]( https://developers.strava.com/docs/reference/) help me to understand how to use the API.

# Garmin exporter
The exporter also support garmin devices. 
The script was tested with my garmin edge 520+ device but I am pretty confident that It will work for all garmin devices.

# How to run ?
Plug your watch and run the tiny little script ```exporter.sh```

# How It work for the kalenji watch?
exporter.sh creates the gpx files using the below configuration and then run exporter.py.
```
source=Path
path=/media/zaurelzo/ONMOVE-220/DATA
device=OnMove200
filters=FixElevation,ComputeInstantSpeed
gpx_extensions=none
directory=/home/zaurelzo/kalenji_activities
```
```exporter.py``` reads the gpx files, does some checks on them to be sure that they are valid and uploads them to strava.

# How It work for the garmin gps device?
```fit-exporter.py``` reads the fit files from the mounted garmin device, chooses those who are more recent than the last strava activity
and uploads them to strava. 


For both devices, You must create a file named .env into the repository project which contain these variable
```
CLIENT_ID=client_id_of_your_app_created_in_strava
CLIENT_SECRET=client_secret_app_retrieve_from_strava
READ_AUTHORIZATION_CODE=below_how_to_retrieve_the_read_authorization_code
WRITE_AUTHORIZATION_CODE=below_how_to_retrieve_the_write_authorization_code

``` 
**Warning** .env file must finish with an empty line (\n)

* Retrieve read authorization code

Paste the below link into your browser. Don't forget to replace client_id with the id of your app created in strava.
Authenticate and authorize the app with the checked permission.

http://www.strava.com/oauth/authorize?client_id={client_id}&response_type=code&redirect_uri=http://localhost/exchange_token&approval_prompt=force&scope=profile:read_all,activity:read_all
You will be redirect to a non working page. Extract the authorization_code from this page url.

 http://localhost/exchange_token?state=&code={authorization_code}&scope=read,activity:read_all,profile:read_all

* Retrieve write authorization code 

Same procedure as read procedure, but use the below link

http://www.strava.com/oauth/authorize?client_id={client_id}&response_type=code&redirect_uri=http://localhost/exchange_token&approval_prompt=force&scope=profile:write,activity:write

# Configure development environment
```
# create venv and activate it
python3 -m venv venv && source venv/bin/activate
# install libs 
pip install -r requirements.txt 
# run test 
pytest
# launch flask app 
FLASK_APP=garmin_exporter python -m flask run
``` 

# TODO
* how to automate initial authentication ? 
 1) use this [library](https://github.com/hozn/stravalib/tree/master/examples/strava-oauth) to retrieve the read or write token 
 2) transform the python script into a flask app with an authorization endpoint to retrieve the read or write code 
```python
client = Client()
authorize_url = client.authorization_url(client_id=49524, redirect_uri='http://localhost:5000/authorization',
                                              scope=["profile:read_all","activity:read_all","profile:write","activity:write"])

@app.route.route('/authorization')
def authorization():
	code = request.args.get('code') # this a single code for read and write, you can simplify the exporter script 
    # by using this single instead of read and write code.
    # rest of kalenji_exporter.py main code
```