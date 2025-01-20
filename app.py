import numpy as np
import pandas as pd

import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import pickle

import datetime

import os

from gridstatusio import GridStatusClient

import requests

import gdown


ercot_username = os.getenv("ERCOT_API_USERNAME")
ercot_password = os.getenv("ERCOT_API_PASSWORD")
ercot_api_key = os.getenv("ERCOT_API_KEY")
gridstatus_api_key = os.getenv("GRIDSTATUS_API_KEY")

# Specify the file path of the saved pickle file
# load_path = 'forecast_results.pkl'
# load_path = 'https://www.kaggle.com/datasets/ishikagupta4568/ercot-live-forecast-trained-models/forecast_results.pkl'
load_path = 'https://drive.google.com/file/d/1V83wwTbIs_8EJn5aUyDmdl4mIqtKgUeC/view?usp=sharing'
file_id = '1V83wwTbIs_8EJn5aUyDmdl4mIqtKgUeC'
file_url = f"https://drive.google.com/uc?id={file_id}"
local_path = "forecast_trained_models.pkl"

gdown.download(file_url, local_path, quiet=False)

# Load the pickle file
with open(local_path, "rb") as f:
    loaded_data = pickle.load(f)

# with gzip.open('forecast_results.pkl.gz', 'rb') as f:
#     loaded_data = pickle.load(f)

# with open(load_path, 'rb') as f:
#     # Load the dictionaries and models
#     loaded_data = pickle.load(f)


models = loaded_data['models']

invalid_units = ['OECCS_CC2_4', 'OECCS_CC2_2', 'LOSTPI_CC1_1', 'OECCS_CC1_2', 'OECCS_CC1_4']

resource_types = []
qses = []
units = []
for u in models.keys():
    resource_types.append(u.split('.')[0].split('_', 2)[0])
    qses.append(u.split('.')[0].split('_', 2)[1])
    unit = u.split('.')[0].split('_', 2)[2]
    if unit not in invalid_units:
        units.append(unit)
    # units.append(u.split('.')[0].split('_', 2)[2])

offer_mw_cols = []
offer_price_cols = []
for i in range(1,11):
    offer_mw_cols.append(f'qseSubmittedCurveMW{i}')
    offer_price_cols.append(f'qseSubmittedCurvePrice{i}')

tomorrow_date = (datetime.date.today() + datetime.timedelta(days=1)).strftime('%Y-%m-%d')

def get_houston_loads(selected_date):
    try:
        USERNAME = ercot_username
        PASSWORD = ercot_password
        SUBSCRIPTION_KEY = ercot_api_key

        # Authorization URL for signing into ERCOT Public API account
        AUTH_URL = ("https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com/"
                    "B2C_1_PUBAPI-ROPC-FLOW/oauth2/v2.0/token"
                    "?username={username}"
                    "&password={password}"
                    "&grant_type=password"
                    "&scope=openid+fec253ea-0d06-4272-a5e6-b478baeecd70+offline_access"
                    "&client_id=fec253ea-0d06-4272-a5e6-b478baeecd70"
                    "&response_type=id_token")

        # Sign In/Authenticate
        auth_response = requests.post(AUTH_URL.format(username=USERNAME, password=PASSWORD))
        auth_response.raise_for_status()  # Raise an HTTPError for bad responses (4xx and 5xx)

        # Retrieve access token
        access_token = auth_response.json().get("access_token")
        if not access_token:
            raise ValueError("Access token not retrieved from the authentication response (ERCOT Houston).")

        apiurl = "https://api.ercot.com/api/public-reports/np6-346-cd/act_sys_load_by_fzn"
        headers = {"Authorization": "Bearer " + access_token, "Ocp-Apim-Subscription-Key": SUBSCRIPTION_KEY}

        selected_date_obj = pd.to_datetime(selected_date)
        days_122_ago = selected_date_obj - pd.to_timedelta(122, unit='d')
        days_122_ago_str = days_122_ago.strftime('%Y-%m-%d')
        days_1_day_ago = selected_date_obj - pd.to_timedelta(1, unit='d')
        days_1_ago_str = days_1_day_ago.strftime('%Y-%m-%d')

        params = {
            "operatingDayFrom": days_122_ago_str,
            "operatingDayTo": days_1_ago_str
        }
        response = requests.get(apiurl, headers=headers, params=params)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx and 5xx)

        data = response.json()
        print("ERCOT Houston Data successfully retrieved!")
        col_names = [field['name'] for field in data.get('fields', [])]
        if 'data' not in data or not col_names:
            raise KeyError("Missing required data or column names in API response (ERCOT Houston).")

        houston_df = pd.DataFrame(data['data'], columns=col_names)
        houston_df['hour'] = houston_df['hourEnding'].apply(lambda x: int(x.split(':')[0]))
        houston_df_1 = houston_df[['operatingDay', 'hour', 'houston']]
        houston_df_1 = houston_df_1.sort_values(by=['operatingDay', 'hour'])
        print("houston_df:")
        print(houston_df_1)
        print()
        return houston_df_1

    except requests.exceptions.RequestException as e:
        error_message = f"ERCOT Houston Network error occurred: {str(e)}"
    except ValueError as e:
        error_message = f"ERCOT Houston Value error: {str(e)}"
    except Exception as e:
        error_message = f"ERCOT Houston An unexpected error occurred: {str(e)}"
    
    print(error_message)  # Log the error message
    return {"error": error_message}


def get_ng_prices(selected_date, resource_type):
    try:
        client = GridStatusClient(gridstatus_api_key)
        selected_date_obj = pd.to_datetime(selected_date)
        days_122_ago = selected_date_obj - pd.to_timedelta(122, unit='d')
        days_122_ago_str = days_122_ago.strftime('%Y-%m-%d')
        days_3_ago = selected_date_obj - pd.to_timedelta(3, unit='d')
        days_3_ago_str = days_3_ago.strftime('%Y-%m-%d')

        # Fetch natural gas data
        ng_data = client.get_dataset(
            dataset="eia_henry_hub_natural_gas_spot_prices_daily",
            start=days_122_ago_str,
            end=days_3_ago_str
        )

        # Ensure the required columns exist
        if 'period' not in ng_data.columns or 'price' not in ng_data.columns:
            raise KeyError("Missing required columns 'period' or 'price' in the dataset (Gridstatus NG).")

        ng_df = ng_data[['period', 'price']]

        # Perform calculations based on resource type
        if resource_type == 'CCGT90':
            ng_df['NG Price in Dollar Per MW'] = ng_df['price'] * 7000
        elif resource_type == 'SCGT90':
            ng_df['NG Price in Dollar Per MW'] = ng_df['price'] * 9000
        else:
            raise ValueError(f"Invalid resource type: {resource_type}. Allowed values: 'CCGT90', 'SCGT90'.")
        
        print("Grid Status NG data retrieved successfully!")
        ng_df = ng_df.sort_values(by='period')
        print("ng_df:")
        print(ng_df)
        print()
        return ng_df

    except KeyError as e:
        error_message = f"Gridstatus NG Dataset error: {str(e)}"
    except ValueError as e:
        error_message = f"Gridstatus NG Value error: {str(e)}"
    except Exception as e:
        error_message = f"Gridstatus NG An unexpected error occurred: {str(e)}"

    print(error_message)  # Log the error for debugging
    return {"error": error_message}




def get_past_offers(selected_date, selected_unit):
    try:
        selected_date_obj = pd.to_datetime(selected_date)
        days_122_ago = selected_date_obj - pd.to_timedelta(122, unit='d')
        days_122_ago_str = days_122_ago.strftime('%Y-%m-%d')
        days_60_ago = selected_date_obj - pd.to_timedelta(60, unit='d')
        days_60_ago_str = days_60_ago.strftime('%Y-%m-%d')

        USERNAME = ercot_username
        PASSWORD = ercot_password
        SUBSCRIPTION_KEY = ercot_api_key

        # Authorization URL for signing into ERCOT Public API account
        AUTH_URL = (
            "https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com/"
            "B2C_1_PUBAPI-ROPC-FLOW/oauth2/v2.0/token"
            "?username={username}&password={password}&grant_type=password&"
            "scope=openid+fec253ea-0d06-4272-a5e6-b478baeecd70+offline_access&"
            "client_id=fec253ea-0d06-4272-a5e6-b478baeecd70&response_type=id_token"
        )

        # Authenticate and get access token
        auth_response = requests.post(AUTH_URL.format(username=USERNAME, password=PASSWORD))
        if auth_response.status_code != 200:
            raise Exception(f"Authentication failed: {auth_response.text}")

        access_token = auth_response.json().get("access_token")
        if not access_token:
            raise Exception("Failed to retrieve access token from authentication response (ERCOT offers).")

        # API request for past offers
        apiurl = "https://api.ercot.com/api/public-reports/np3-966-er/60_dam_gen_res_data"
        headers = {
            "Authorization": "Bearer " + access_token,
            "Ocp-Apim-Subscription-Key": SUBSCRIPTION_KEY,
        }

        params = {
            "deliveryDateFrom": days_122_ago_str,
            "deliveryDateTo": days_60_ago_str,
            "hourEndingFrom": 1,
            "hourEndingTo": 24,
            "resourceName": selected_unit,
        }

        response = requests.get(apiurl, headers=headers, params=params)
        if response.status_code != 200:
            raise Exception(f"ERCOT Offer API request failed with status code {response.status_code}: {response.text}")

        # Parse data
        data = response.json()
        col_names = [field['name'] for field in data.get('fields', [])]
        if 'data' not in data or not col_names:
            raise KeyError("Missing required data or column names in API response (ERCOT Offer).")

        offer_df = pd.DataFrame(data['data'], columns=col_names)
        offer_df = offer_df.sort_values(by=['deliveryDate', 'hourEnding'])
        print("ERCOT offer data retrieved successfully!")
        print("offer_df:")
        print(offer_df)
        print()
        print('offer_df_columns:')
        print(offer_df.columns)
        print()
        return offer_df

    except KeyError as e:
        error_message = f"ERCOT Offer Key error: {str(e)}"
    except ValueError as e:
        error_message = f"ERCOT Offer Value error: {str(e)}"
    except Exception as e:
        error_message = f"ERCOT Offer An unexpected error occurred: {str(e)}"

    print(error_message)  # Log the error for debugging
    return {"error": error_message}

# def get_all_historical_data(selected_date, selected_unit):
#     try:
#         # Initialize variables
#         day_intervals = [60, 61, 62, 90, 91, 92, 120, 121, 122]
#         short_day_intervals_ng = [3, 4, 5]
#         short_day_intervals_houston = [1, 2, 3, 4, 5]
#         hour_offsets = [0, 1, 2]

#         selected_date_obj = pd.to_datetime(selected_date)

#         # Get past offers
#         offer_df = get_past_offers(selected_date, selected_unit)
#         if "error" in offer_df:
#             raise ValueError(f"Error retrieving past offers: {offer_df['error']}")
#         print("offer_df column datatype:", offer_df['deliveryDate'].dtype)
#         # offer_df['deliveryDate'] = pd.to_datetime(offer_df['deliveryDate'])

#         # Get resource type
#         resource_type = list(offer_df['resourceType'].unique())[0]

#         # Get Houston loads
#         houston_df = get_houston_loads(selected_date)
#         if "error" in houston_df:
#             raise ValueError(f"Error retrieving Houston loads: {houston_df['error']}")
#         print("houston_df column datatype:", houston_df['operatingDay'].dtype)
#         # houston_df['operatingDay'] = pd.to_datetime(houston_df['operatingDay'])

#         # Get NG prices
#         ng_df = get_ng_prices(selected_date, resource_type)
#         if "error" in ng_df:
#             raise ValueError(f"Error retrieving NG prices: {ng_df['error']}")
#         print("ng_df column datatype:", ng_df['period'].dtype)
#         # ng_df['period'] = pd.to_datetime(ng_df['period'])

#         # Extract unique values for return
#         qse = offer_df['qseName'].unique()[0]
#         print("qse:",qse)
#         r_type = offer_df['resourceType'].unique()[0]
#         print("resource_type:", r_type)
#         unit = offer_df['resourceName'].unique()[0]
#         print("unit:", unit)
#         print()

#         # Prepare input dataframe
#         input_df = pd.DataFrame({})
#         input_df['selected_date'] = [selected_date] * 24
#         input_df['selected_date'] = pd.to_datetime(input_df['selected_date'])
#         input_df['hour'] = list(range(1, 25))
#         input_df['day_of_week'] = input_df['selected_date'].dt.dayofweek + 1
#         input_df['day_of_month'] = input_df['selected_date'].dt.day
#         input_df['month'] = input_df['selected_date'].dt.month
#         input_df['year'] = input_df['selected_date'].dt.year

#         print("added time related features!")


#         # Generate historical features
#         for day in day_intervals:
#             past_date = selected_date_obj - pd.to_timedelta(day, unit='d')
#             past_date = past_date.strftime('%Y-%m-%d')
#             for hour in hour_offsets:
#                 col_name = f'houston_{day}_days_ago_{hour}_offset'
#                 input_df[col_name] = houston_df[(houston_df['operatingDay'] == past_date) & (houston_df['hour'] == hour)]['houston']
        
#         print("added houston hourly offsets!")
        
#         grouped_df = houston_df.groupby('operatingDay', as_index=False)['houston'].mean()
#         for day in day_intervals:
#             past_date = selected_date_obj - pd.to_timedelta(day, unit='d')
#             past_date = past_date.strftime('%Y-%m-%d')
#             col_name = f'houston_{day}_days_ago'
#             input_df[col_name] = grouped_df[past_date]
        
#         print("added houston daily long term offsets")
        
#         for day in short_day_intervals_houston:
#             past_date = selected_date_obj - pd.to_timedelta(day, unit='d')
#             past_date = past_date.strftime('%Y-%m-%d')
#             col_name = f'houston_{day}_days_ago'
#             input_df[col_name] = grouped_df[past_date]
        
#         print("added houston daily short term offsets")
        
#         grouped_df = ng_df.groupby('period', as_index=False)['NG Price in Dollar Per MW'].mean()
#         for day in day_intervals:
#             past_date = selected_date_obj - pd.to_timedelta(day, unit='d')
#             past_date = past_date.strftime('%Y-%m-%d')
#             col_name = f'NG Price in Dollar Per MW_{day}_days_ago'
#             input_df[col_name] = grouped_df[past_date]
        
#         print("added ng price daily long term offsets")
        
#         for day in short_day_intervals_ng:
#             past_date = selected_date_obj - pd.to_timedelta(day, unit='d')
#             past_date = past_date.strftime('%Y-%m-%d')
#             col_name = f'NG Price in Dollar Per MW_{day}_days_ago'
#             input_df[col_name] = grouped_df[past_date]
        
#         print("added ng price daily short term offsets")
        
#         for day in day_intervals:
#             past_date = selected_date_obj - pd.to_timedelta(day, unit='d')
#             past_date = past_date.strftime('%Y-%m-%d')
#             for hour in hour_offsets:
#                 for col in offer_price_cols:
#                     col_name = f'{col}_{day}_days_ago_{hour}_offset'
#                     input_df[col_name] = offer_df[(offer_df['deliveryDate'] == past_date) & (houston_df['hourEnding'] == hour)][col]
        
#         print("added offer price hourly data")
        
#         for day in day_intervals:
#             past_date = selected_date_obj - pd.to_timedelta(day, unit='d')
#             past_date = past_date.strftime('%Y-%m-%d')
#             for col in offer_price_cols:
#                 col_name = f'{col}_{day}_days_ago'
#                 grouped_df = offer_df.groupby('deliveryDate', as_index=False)[col].mean()
#                 input_df[col_name] = grouped_df[past_date]
        
#         print("added offer price daily data")

        
#         for day in day_intervals:
#             past_date = selected_date_obj - pd.to_timedelta(day, unit='d')
#             past_date = past_date.strftime('%Y-%m-%d')
#             for hour in hour_offsets:
#                 for col in offer_mw_cols:
#                     col_name = f'{col}_{day}_days_ago_{hour}_offset'
#                     input_df[col_name] = offer_df[(offer_df['deliveryDate'] == past_date) & (houston_df['hourEnding'] == hour)][col]
        
#         print("added offer mw hourly data")
        

#         for day in day_intervals:
#             past_date = selected_date_obj - pd.to_timedelta(day, unit='d')
#             past_date = past_date.strftime('%Y-%m-%d')
#             for col in offer_mw_cols:
#                 col_name = f'{col}_{day}_days_ago'
#                 grouped_df = offer_df.groupby('deliveryDate', as_index=False)[col].mean()
#                 input_df[col_name] = grouped_df[past_date]
        
#         print("added offer mw daily data")

#         # Rolling averages
#         input_df['Houston_1_day_rolling_avg'] = houston_df['houston'].rolling(window=24).mean()
#         input_df['Houston_3_day_rolling_avg'] = houston_df['houston'].rolling(window=72).mean()
#         input_df['NG_Price_3_day_rolling_avg'] = ng_df['NG Price in Dollar Per MW'].rolling(window=72).mean()

#         print("added short term moving avgs")

#         input_df['Houston_60_day_rolling_avg'] = houston_df['houston'].rolling(window=1440).mean()
#         input_df['Houston_90_day_rolling_avg'] = houston_df['houston'].rolling(window=2160).mean()
#         input_df['Houston_120_day_rolling_avg'] = houston_df['houston'].rolling(window=2880).mean()

#         print("added houston rolling avgs")

#         input_df['NG_Price_60_day_rolling_avg'] = ng_df['NG Price in Dollar Per MW'].rolling(window=1440).mean()
#         input_df['NG_Price_90_day_rolling_avg'] = ng_df['NG Price in Dollar Per MW'].rolling(window=2160).mean()
#         input_df['NG_Price_120_day_rolling_avg'] = ng_df['NG Price in Dollar Per MW'].rolling(window=2880).mean()

#         print("added ng price moving avgs")

#         print("input_df:")
#         print(input_df)

#         return input_df, qse, r_type, unit

#     except ValueError as e:
#         # Log and return structured error
#         error_message = str(e)
#         print(f"ValueError: {error_message}")  # For debugging
#         return {}, "", "", ""

#     except Exception as e:
#         # Handle unexpected errors
#         error_message = f"An unexpected error occurred: {str(e)}"
#         print(f"Exception: {error_message}")  # For debugging
#         return {}, "", "", ""

def get_all_historical_data(selected_date, selected_unit):
    try:
        # Initialize variables
        day_intervals = [60, 61, 62, 90, 91, 92, 120, 121, 122]
        short_day_intervals_ng = [3, 4, 5]
        short_day_intervals_houston = [1, 2, 3, 4, 5]
        hour_offsets = [0, 1, 2]

        selected_date_obj = pd.to_datetime(selected_date)

        # Get past offers
        offer_df = get_past_offers(selected_date, selected_unit)
        if "error" in offer_df:
            raise ValueError(f"Error retrieving past offers: {offer_df['error']}")
        
        resource_type = list(offer_df['resourceType'].unique())[0]

        # Get Houston loads
        houston_df = get_houston_loads(selected_date)
        if "error" in houston_df:
            raise ValueError(f"Error retrieving Houston loads: {houston_df['error']}")

        # Get NG prices
        ng_df = get_ng_prices(selected_date, resource_type)
        if "error" in ng_df:
            raise ValueError(f"Error retrieving NG prices: {ng_df['error']}")

        # Extract unique values for return
        qse = offer_df['qseName'].unique()[0]
        print("qse:", qse)
        r_type = offer_df['resourceType'].unique()[0]
        print("resource type:", r_type)
        unit = offer_df['resourceName'].unique()[0]
        print("unit:", unit)



        # Prepare input dataframe
        input_df = pd.DataFrame({})
        input_df['selected_date'] = [selected_date] * 24
        input_df['selected_date'] = pd.to_datetime(input_df['selected_date'])
        input_df['hour'] = list(range(1, 25))
        input_df['day_of_week'] = input_df['selected_date'].dt.dayofweek + 1
        input_df['day_of_month'] = input_df['selected_date'].dt.day
        input_df['month'] = input_df['selected_date'].dt.month
        input_df['year'] = input_df['selected_date'].dt.year

        print("added time related features!")

        # Generate historical features
        for day in day_intervals:
            past_date = selected_date_obj - pd.to_timedelta(day, unit='d')
            past_date = past_date.strftime('%Y-%m-%d')
            
            # Houston hourly offsets
            for hour in hour_offsets:
                col_name = f'houston_{day}_days_ago_{hour}_offset'
                filtered = houston_df[(houston_df['operatingDay'] == past_date) & (houston_df['hour'] == hour)]
                if not filtered.empty:
                    input_df[col_name] = filtered['houston'].values
                else:
                    input_df[col_name] = None
        
        print("added houston hourly lags")

        # Houston daily averages
        grouped_houston = houston_df.groupby('operatingDay', as_index=False)['houston'].mean()
        for day in day_intervals + short_day_intervals_houston:
            past_date = selected_date_obj - pd.to_timedelta(day, unit='d')
            past_date = past_date.strftime('%Y-%m-%d')
            col_name = f'houston_{day}_days_ago'
            if past_date in grouped_houston['operatingDay'].values:
                input_df[col_name] = grouped_houston.loc[grouped_houston['operatingDay'] == past_date, 'houston'].values[0]
            else:
                input_df[col_name] = None
        
        print("added houston daily lags")

        # NG prices
        grouped_ng = ng_df.groupby('period', as_index=False)['NG Price in Dollar Per MW'].mean()
        for day in day_intervals + short_day_intervals_ng:
            past_date = selected_date_obj - pd.to_timedelta(day, unit='d')
            past_date = past_date.strftime('%Y-%m-%d')
            col_name = f'NG_Price_{day}_days_ago'
            if past_date in grouped_ng['period'].values:
                input_df[col_name] = grouped_ng.loc[grouped_ng['period'] == past_date, 'NG Price in Dollar Per MW'].values[0]
            else:
                input_df[col_name] = None
        
        print("added ng price daily lags")

        
        for day in day_intervals:
            past_date = selected_date_obj - pd.to_timedelta(day, unit='d')
            print("past date obj:", past_date)
            past_date = past_date.strftime('%Y-%m-%d')
            print("past date str:", past_date)
            for hour in hour_offsets:
                for col in offer_price_cols:
                    col_name = f'{col}_{day}_days_ago_{hour}_offset'
                    if past_date in offer_df['deliveryDate'].values:
                        print("past date exists in the offer df")
                        filtered_data = offer_df[(offer_df['deliveryDate'] == past_date) & (offer_df['hourEnding'] == hour)]
                        if not filtered_data.empty:
                            print("adding data")
                            input_df[col_name] = filtered_data[col].values[0]
                            print("added data")
                        else:
                            input_df[col_name] = None
                            print("added none")
                    else:
                        input_df[col_name] = None
                        print("added none")
        
        print("added offer price hourly data")
        
        for day in day_intervals:
            past_date = selected_date_obj - pd.to_timedelta(day, unit='d')
            print("past date obj:", past_date)
            past_date = past_date.strftime('%Y-%m-%d')
            print("past date str:", past_date)
            for col in offer_price_cols:
                col_name = f'{col}_{day}_days_ago'
                grouped_df = offer_df.groupby('deliveryDate', as_index=False)[col].mean()
                if past_date in grouped_df['deliveryDate'].values:
                    input_df[col_name] = grouped_df.loc[grouped_df['deliveryDate'] == past_date, col].values[0]
                else:
                    input_df[col_name] = None
        
        print("added offer price daily data")

        
        for day in day_intervals:
            past_date = selected_date_obj - pd.to_timedelta(day, unit='d')
            past_date = past_date.strftime('%Y-%m-%d')
            for hour in hour_offsets:
                for col in offer_mw_cols:
                    col_name = f'{col}_{day}_days_ago_{hour}_offset'
                    if past_date in offer_df['deliveryDate'].values:
                        filtered_data = offer_df[(offer_df['deliveryDate'] == past_date) & (offer_df['hourEnding'] == hour)]
                        if not filtered_data.empty:
                            input_df[col_name] = filtered_data[col].values[0]
                        else:
                            input_df[col_name] = None
                    else:
                        input_df[col_name] = None
        
        print("added offer mw hourly data")
        

        for day in day_intervals:
            past_date = selected_date_obj - pd.to_timedelta(day, unit='d')
            past_date = past_date.strftime('%Y-%m-%d')
            for col in offer_mw_cols:
                col_name = f'{col}_{day}_days_ago'
                grouped_df = offer_df.groupby('deliveryDate', as_index=False)[col].mean()
                if past_date in grouped_df['deliveryDate'].values:
                    input_df[col_name] = grouped_df.loc[grouped_df['deliveryDate'] == past_date, col].values[0]
                else:
                    input_df[col_name] = None
        
        print("added offer mw daily data")

        # Rolling averages
        input_df['Houston_1_day_rolling_avg'] = houston_df['houston'].rolling(window=24).mean()
        input_df['Houston_3_day_rolling_avg'] = houston_df['houston'].rolling(window=72).mean()
        input_df['NG_Price_3_day_rolling_avg'] = ng_df['NG Price in Dollar Per MW'].rolling(window=3).mean()

        print("added short term moving avgs")

        input_df['Houston_60_day_rolling_avg'] = houston_df['houston'].rolling(window=1440).mean()
        input_df['Houston_90_day_rolling_avg'] = houston_df['houston'].rolling(window=2160).mean()
        input_df['Houston_120_day_rolling_avg'] = houston_df['houston'].rolling(window=2880).mean()

        # input_df['Houston_60_day_rolling_avg'] = None
        # input_df['Houston_90_day_rolling_avg'] = None
        # input_df['Houston_120_day_rolling_avg'] = None


        print("added houston rolling avgs")

        input_df['NG_Price_60_day_rolling_avg'] = ng_df['NG Price in Dollar Per MW'].rolling(window=60).mean()
        input_df['NG_Price_90_day_rolling_avg'] = ng_df['NG Price in Dollar Per MW'].rolling(window=90).mean()
        input_df['NG_Price_120_day_rolling_avg'] = ng_df['NG Price in Dollar Per MW'].rolling(window=120).mean()

        print("added ng price moving avgs")

        print("input_df:")
        print(input_df)

        return input_df, qse, r_type, unit

    except ValueError as e:
        print(f"ValueError: {str(e)}")
        return {}, "", "", ""

    except Exception as e:
        print(f"Exception: {str(e)}")
        return {}, "", "", ""

# Function to enforce monotonicity row-wise for a list of columns
def enforce_monotonicity(row, columns):
    for i in range(1, len(columns)):
        # Ensure each column value is at least as large as the previous column's value
        row[columns[i]] = max(row[columns[i]], row[columns[i - 1]])
    return row

# Example placeholder functions for get_predictions and plot_forecasts
def get_predictions(selected_unit, selected_date):
    try:
        input_df, qse, r_type, unit = get_all_historical_data(selected_date, selected_unit)
        model_name = f'{r_type}_{qse}_{unit}.csv'
        if model_name not in models:
            raise KeyError(f"Model '{model_name}' not found in models dictionary.")
        model = models[model_name]
        target_cols = []
        target_cols.extend(offer_price_cols)
        target_cols.extend(offer_mw_cols)
        input_df = input_df.set_index('selected_date')
        for col in input_df.select_dtypes(include='object').columns:
            input_df[col] = pd.to_numeric(input_df[col], errors='coerce')
        predictions = model.predict(input_df)
        predictions_df = pd.DataFrame(predictions, columns=target_cols, index=input_df.index)
        predictions_df[offer_price_cols] = predictions_df[offer_price_cols].apply(lambda row: enforce_monotonicity(row, offer_price_cols), axis=1)
        predictions_df[offer_mw_cols] = predictions_df[offer_mw_cols].apply(lambda row: enforce_monotonicity(row, offer_mw_cols), axis=1)
        print("predictions_df")
        print(predictions_df)
        return predictions_df, qse, r_type, "no_error"
    except KeyError as ke:
        print(f"KeyError: {ke}")
        return pd.DataFrame(), None, None, f"Error: {ke}"
    except Exception as e:
        print(f"An error occurred in get_predictions: {e}")
        return pd.DataFrame(), None, None, f"Error: {e}"

def plot_forecasts(selected_unit, selected_date, predictions_df, resource_type, qse):
    try:
        if predictions_df.empty:
            raise ValueError("Predictions DataFrame is empty.")
        
        fig = make_subplots(rows=4, cols=6, shared_xaxes=False, shared_yaxes=False,
                            subplot_titles=[f'Hour {i+1}' for i in range(24)])
        
        for i, (_, row_data) in enumerate(predictions_df.iterrows()):
            row = i // 6 + 1
            col = i % 6 + 1
            predicted_prices = row_data[offer_price_cols].values
            predicted_supply = row_data[offer_mw_cols].values
            fig.add_trace(go.Scatter(x=predicted_supply, y=predicted_prices,
                                     mode='lines+markers', name='Predicted Offer',
                                     marker=dict(symbol='x', color='red'),
                                     line=dict(dash='dash', color='red'), showlegend=(i == 0)),
                          row=row, col=col)
            # # Update x-axis visibility for the last row
            # for col in range(1, 7):
            #     fig.update_xaxes(visible=True, title_text="Offer MW", row=4, col=col)

            # # Update y-axis visibility for the first column
            # for row in range(1, 5):
            #     fig.update_yaxes(visible=True, title_text="Offer Price in $/MW", row=row, col=1)

            fig.update_xaxes(title_text="Offer MW", row=4, col=3)  # Common x-axis title
            fig.update_yaxes(title_text="Offer Price in $/MW", row=2, col=1)  # Common y-axis title

            fig.update_layout(height=800, width=1200, title_text=f'Predicted Offer Curve of Unit {selected_unit} on {selected_date}, Resource Type: {resource_type}, QSE: {qse}',
                          showlegend=True)
            

        return fig, "no_error"
    except ValueError as ve:
        print(f"ValueError: {ve}")
        return go.Figure(), f"Error: {ve}"  # Return empty figure and error message
    except Exception as e:
        print(f"An error occurred in plot_forecasts: {e}")
        return go.Figure(), f"Error: {e}"  # Return empty figure and error message

# Initialize the main Dash app
app = dash.Dash(__name__)
server = app.server

# Layout with dropdowns for filtering
app.layout = html.Div([
    html.H1("Forecasts", style={'text-align': 'left', 'margin': '10px 0'}),
    html.Div([
        html.Div([
            html.Label("Unit:", style={'font-weight': 'bold'}),
            dcc.Dropdown(
                id='unit_dropdown',
                options=[{'label': unit, 'value': unit} for unit in units],
                placeholder="Select Unit",
                style={'width': '100%'}
            ),
        ], style={'margin': '10px', 'width': '25%'}),
        html.Div([
            html.Label("Date:", style={'font-weight': 'bold'}),
            dcc.Dropdown(
                id='date_dropdown',
                options=[{'label': tomorrow_date, 'value': tomorrow_date}],
                placeholder="Select Date",
                style={'width': '100%'}
            ),
        ], style={'margin': '10px', 'width': '25%'}),
    ], style={'display': 'flex', 'flex-wrap': 'wrap'}),
    html.Div([
        dcc.Graph(id='graph-placeholder', style={'width': '100%'}),
        html.Div(id='error-message', style={'color': 'red', 'margin-top': '20px'}),  # Error message display
        html.Button("Download Predictions", id='download-button', n_clicks=0, style={'margin-top': '20px'}),
        dcc.Download(id='download-predictions')  # Component to handle file download
    ], style={'margin': '20px'}),
])
#     html.Div([
#         dcc.Graph(id='graph-placeholder', style={'width': '100%'}),
#         html.Div(id='error-message', style={'color': 'red', 'margin-top': '20px'})  # Error message display
#     ], style={'margin': '20px'}),
# ])

# Callback to update the selected graph type and render the appropriate graph
@app.callback(
    [Output('graph-placeholder', 'figure'),
     Output('error-message', 'children')],  # Output for error message
    [Input('unit_dropdown', 'value'),
     Input('date_dropdown', 'value')]
)
def update_graph(selected_unit, selected_date):
    if selected_unit is None or selected_date is None:
        return go.Figure(), "Please select both Unit and Date."
    
    unit_forecast_df, qse, resource_type, error_message = get_predictions(selected_unit, selected_date)
    
    if error_message == 'no_error':
        fig, error_message = plot_forecasts(selected_unit, selected_date, unit_forecast_df, resource_type, qse)
        return fig, error_message
    
    else:
        return go.Figure(), error_message

# Callback to handle file download
@app.callback(
    Output('download-predictions', 'data'),
    Input('download-button', 'n_clicks'),
    [Input('unit_dropdown', 'value'),
     Input('date_dropdown', 'value')]
)
def download_predictions(n_clicks, selected_unit, selected_date):
    if n_clicks > 0:
        if selected_unit is None or selected_date is None:
            return None  # Do nothing if inputs are not selected
        
        unit_forecast_df, qse, resource_type, error_message = get_predictions(selected_unit, selected_date)
        
        if error_message == 'no_error':
            unit_forecast_df['hour'] = list(range(1, 25))
            filename = f"{selected_date}_{selected_unit}_{resource_type}_{qse}_predictions.csv"
            return dcc.send_data_frame(unit_forecast_df.to_csv, filename, index=False)
        
    return None

# Run the app
if __name__ == '__main__':
    app.run_server(debug=True)


# # Callback to update the selected graph type and render the appropriate graph
# @app.callback(
#     Output('graph-placeholder', 'figure'),
#     Output('error-message', 'children'),  # Output for error message
#     Input('unit_dropdown', 'value'),
#     Input('date_dropdown', 'value')
# )
# def update_graph(selected_unit, selected_date):
#     if selected_unit is None or selected_date is None:
#         return go.Figure(), "Please select both Unit and Date."
    
#     unit_forecast_df, qse, resource_type, error_message = get_predictions(selected_unit, selected_date)
    
#     if error_message == 'no_error':
#         fig, error_message = plot_forecasts(selected_unit, selected_date, unit_forecast_df, resource_type, qse)
#         return fig, error_message
    
#     else:
#         return go.Figure(), error_message

# # Run the app
# if __name__ == '__main__':
#     app.run_server(debug=True)

