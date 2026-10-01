import openmeteo_requests

import pandas as pd
import requests_cache
from retry_requests import retry

# Setup the Open-Meteo API client with cache and retry on error
cache_session = requests_cache.CachedSession('.cache', expire_after = -1)
retry_session = retry(cache_session, retries = 5, backoff_factor = 0.2)
openmeteo = openmeteo_requests.Client(session = retry_session)

# Make sure all required weather variables are listed here
# The order of variables in hourly or daily is important to assign them correctly below
url = "https://my-server.tld/v1/archive"
params = {
	"latitude": 52.52,
	"longitude": 13.41,
	"start_date": "2026-09-15",
	"end_date": "2026-09-29",
	"daily": ["weather_code", "temperature_2m_mean", "temperature_2m_max", "temperature_2m_min", "daylight_duration", "apparent_temperature_mean", "apparent_temperature_max", "apparent_temperature_min", "sunshine_duration", "sunrise", "sunset", "precipitation_hours", "precipitation_sum", "wind_speed_10m_max"],
	"hourly": ["temperature_2m", "relative_humidity_2m", "apparent_temperature", "rain", "snowfall", "snow_depth", "weather_code", "cloud_cover", "wind_gusts_10m", "wind_speed_10m"],
}
responses = openmeteo.weather_api(url, params = params)

# Process first location. Add a for-loop for multiple locations or weather models
response = responses[0]
print(f"Coordinates: {response.Latitude()}°N {response.Longitude()}°E")
print(f"Elevation: {response.Elevation()} m asl")
print(f"Timezone difference to GMT+0: {response.UtcOffsetSeconds()}s")

# Process hourly data. The order of variables needs to be the same as requested.
hourly = response.Hourly()
hourly_temperature_2m = hourly.Variables(0).ValuesAsNumpy()
hourly_relative_humidity_2m = hourly.Variables(1).ValuesAsNumpy()
hourly_apparent_temperature = hourly.Variables(2).ValuesAsNumpy()
hourly_rain = hourly.Variables(3).ValuesAsNumpy()
hourly_snowfall = hourly.Variables(4).ValuesAsNumpy()
hourly_snow_depth = hourly.Variables(5).ValuesAsNumpy()
hourly_weather_code = hourly.Variables(6).ValuesAsNumpy()
hourly_cloud_cover = hourly.Variables(7).ValuesAsNumpy()
hourly_wind_gusts_10m = hourly.Variables(8).ValuesAsNumpy()
hourly_wind_speed_10m = hourly.Variables(9).ValuesAsNumpy()

hourly_data = {
	"date": pd.date_range(
		start = pd.to_datetime(hourly.Time(), unit = "s", utc = True),
		end =  pd.to_datetime(hourly.TimeEnd(), unit = "s", utc = True),
		freq = pd.Timedelta(seconds = hourly.Interval()),
		inclusive = "left"
	)
}

hourly_data["temperature_2m"] = hourly_temperature_2m
hourly_data["relative_humidity_2m"] = hourly_relative_humidity_2m
hourly_data["apparent_temperature"] = hourly_apparent_temperature
hourly_data["rain"] = hourly_rain
hourly_data["snowfall"] = hourly_snowfall
hourly_data["snow_depth"] = hourly_snow_depth
hourly_data["weather_code"] = hourly_weather_code
hourly_data["cloud_cover"] = hourly_cloud_cover
hourly_data["wind_gusts_10m"] = hourly_wind_gusts_10m
hourly_data["wind_speed_10m"] = hourly_wind_speed_10m

hourly_dataframe = pd.DataFrame(data = hourly_data)
print("\nHourly data\n", hourly_dataframe)

# Process daily data. The order of variables needs to be the same as requested.
daily = response.Daily()
daily_weather_code = daily.Variables(0).ValuesAsNumpy()
daily_temperature_2m_mean = daily.Variables(1).ValuesAsNumpy()
daily_temperature_2m_max = daily.Variables(2).ValuesAsNumpy()
daily_temperature_2m_min = daily.Variables(3).ValuesAsNumpy()
daily_daylight_duration = daily.Variables(4).ValuesAsNumpy()
daily_apparent_temperature_mean = daily.Variables(5).ValuesAsNumpy()
daily_apparent_temperature_max = daily.Variables(6).ValuesAsNumpy()
daily_apparent_temperature_min = daily.Variables(7).ValuesAsNumpy()
daily_sunshine_duration = daily.Variables(8).ValuesAsNumpy()
daily_sunrise = daily.Variables(9).ValuesInt64AsNumpy()
daily_sunset = daily.Variables(10).ValuesInt64AsNumpy()
daily_precipitation_hours = daily.Variables(11).ValuesAsNumpy()
daily_precipitation_sum = daily.Variables(12).ValuesAsNumpy()
daily_wind_speed_10m_max = daily.Variables(13).ValuesAsNumpy()

daily_data = {
	"date": pd.date_range(
		start = pd.to_datetime(daily.Time(), unit = "s", utc = True),
		end =  pd.to_datetime(daily.TimeEnd(), unit = "s", utc = True),
		freq = pd.Timedelta(seconds = daily.Interval()),
		inclusive = "left"
	)
}

daily_data["weather_code"] = daily_weather_code
daily_data["temperature_2m_mean"] = daily_temperature_2m_mean
daily_data["temperature_2m_max"] = daily_temperature_2m_max
daily_data["temperature_2m_min"] = daily_temperature_2m_min
daily_data["daylight_duration"] = daily_daylight_duration
daily_data["apparent_temperature_mean"] = daily_apparent_temperature_mean
daily_data["apparent_temperature_max"] = daily_apparent_temperature_max
daily_data["apparent_temperature_min"] = daily_apparent_temperature_min
daily_data["sunshine_duration"] = daily_sunshine_duration
daily_data["sunrise"] = pd.to_datetime(daily_sunrise, unit = "s", utc = True)
daily_data["sunset"] = pd.to_datetime(daily_sunset, unit = "s", utc = True)
daily_data["precipitation_hours"] = daily_precipitation_hours
daily_data["precipitation_sum"] = daily_precipitation_sum
daily_data["wind_speed_10m_max"] = daily_wind_speed_10m_max

daily_dataframe = pd.DataFrame(data = daily_data)
print("\nDaily data\n", daily_dataframe)
