# Kalenji Ride Exporter
I am the happy owner of a kalenji watch that I use to record my bike activities.
I wrote this little script to export my last rides from my watch (gpx files) to my strava account. 
To export the activities from the watch to gpx files, I used this open source project [kalenji-gps-watch-reader.](https://github.com/ColinPitrat/kalenji-gps-watch-reader) 
[This article](https://medium.com/swlh/using-python-to-connect-to-stravas-api-and-analyse-your-activities-dummies-guide-5f49727aac86) 
and [strava documentation]( https://developers.strava.com/docs/reference/) help me to understand how to use the API.

# How to run ?
Plug your watch and run the tiny little script
 ```
./exporter.sh
```

# How It work?
exporter.sh creates the gpx files using the below configuration and then run exporter.py.
```
source=Path
path=/media/zaurelzo/ONMOVE-220/DATA
device=OnMove200
filters=FixElevation,ComputeInstantSpeed
gpx_extensions=none
```
exporter.py reads the gpx file, does some checks on them to be sure that they are valid and uploads them to strava. 
You must create a file named .env into the repository project which contain these variable
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
