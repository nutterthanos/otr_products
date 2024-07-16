import requests
import json
import os
import logging
from datetime import datetime
from dateutil import parser

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# URLs and endpoints
list_locations_url = "https://app2.ontherun.com.au/api/v2/listLocations"
list_products_url = "https://app2.ontherun.com.au/api/v2/listOrderingEnabledBrandProductsFull"
login_url = "https://app2.ontherun.com.au/api/v2/login"

# Environment variables
email = os.getenv('EMAIL')
password = os.getenv('PASSWORD')
auth_token = os.getenv('AUTH_TOKEN_PROD')
repo = os.getenv('REPO')
gh_pat = os.getenv('GH_PAT')

# Payloads
locations_payloads = [
    {"ordering_enabled": "0", "api_key": None, "client_version": "3.7.160", "client_os": None, "auth_token": auth_token},
    {"ordering_enabled": "1", "api_key": None, "client_version": "3.7.160", "client_os": None, "auth_token": auth_token}
]

def update_github_secret(secret_name, secret_value):
    logging.debug(f"Updating GitHub secret: {secret_name}")
    headers = {
        "Authorization": f"token {gh_pat}",
        "Accept": "application/vnd.github.v3+json"
    }
    # Get the public key
    response = requests.get(f"https://api.github.com/repos/{repo}/actions/secrets/public-key", headers=headers)
    if response.status_code == 200:
        public_key = response.json()
        key_id = public_key['key_id']
        public_key_value = public_key['key']
        
        from base64 import b64encode
        from nacl import encoding, public

        def encrypt(public_key: str, secret_value: str) -> str:
            public_key = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder())
            sealed_box = public.SealedBox(public_key)
            encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
            return b64encode(encrypted).decode("utf-8")
        
        encrypted_value = encrypt(public_key_value, secret_value)
        
        data = {
            "encrypted_value": encrypted_value,
            "key_id": key_id
        }

        put_response = requests.put(f"https://api.github.com/repos/{repo}/actions/secrets/{secret_name}", headers=headers, json=data)
        if put_response.status_code == 201:
            logging.debug(f"GitHub secret {secret_name} updated successfully.")
        else:
            logging.error(f"Failed to update GitHub secret {secret_name}: {put_response.text}")
    else:
        logging.error(f"Failed to retrieve public key: {response.text}")

def login():
    logging.debug("Logging in to get a new auth token")
    login_payload = {
        "email": email,
        "password": password,
        "facebook_token": None,
        "is_modal_view": False,
        "apple_id": None,
        "apple_token": None,
        "api_key": None,
        "client_version": "3.7.160",
        "client_os": None,
        "auth_token": ""
    }
    response = requests.post(login_url, json=login_payload)
    if response.status_code == 200:
        data = response.json()
        if data.get("status") == 1 and "auth_token" in data:
            new_auth_token = data["auth_token"]
            update_github_secret("AUTH_TOKEN_PROD", new_auth_token)
            return new_auth_token
    logging.error(f"Login failed: {response.text}")
    return None

def fetch_locations():
    locations_data = {}
    for payload in locations_payloads:
        logging.debug(f"Sending request to {list_locations_url} with payload: {payload}")
        response = requests.post(list_locations_url, json=payload)
        logging.debug(f"Response status code: {response.status_code}")
        logging.debug(f"Response data: {response.text}")
        if response.status_code == 200:
            data = response.json()
            ordering_enabled = payload["ordering_enabled"]
            file_name = "locations_ordering_enabled.json" if ordering_enabled == "1" else "locations.json"
            with open(file_name, 'w') as f:
                json.dump(data, f, indent=4)
            locations_data[ordering_enabled] = data
        else:
            logging.error(f"Failed to fetch locations with payload {payload}: {response.status_code} - {response.text}")
            if response.json().get("status") == 6:
                logging.debug("Auth token expired, attempting to login")
                new_auth_token = login()
                if new_auth_token:
                    payload["auth_token"] = new_auth_token
                    logging.debug(f"Retrying request to {list_locations_url} with new auth token")
                    response = requests.post(list_locations_url, json=payload)
                    logging.debug(f"Retry response status code: {response.status_code}")
                    logging.debug(f"Retry response data: {response.text}")
                    if response.status_code == 200:
                        data = response.json()
                        ordering_enabled = payload["ordering_enabled"]
                        file_name = "locations_ordering_enabled.json" if ordering_enabled == "1" else "locations.json"
                        with open(file_name, 'w') as f:
                            json.dump(data, f, indent=4)
                        locations_data[ordering_enabled] = data
                    else:
                        logging.error(f"Retry failed: {response.status_code} - {response.text}")
    return locations_data

def fetch_products(location_ids):
    for location_id in location_ids:
        payload = {
            "location_id": location_id,
            "refresh_cache": "False",
            "api_key": None,
            "client_version": "3.7.160",
            "client_os": None,
            "auth_token": auth_token
        }
        logging.debug(f"Sending request to {list_products_url} with payload: {payload}")
        response = requests.post(list_products_url, json=payload)
        logging.debug(f"Response status code: {response.status_code}")
        logging.debug(f"Response data: {response.text}")
        if response.status_code == 200:
            data = response.json()
            if "location" in data and "name" in data["location"]:
                location_name = data["location"]["name"]
                file_name = f"{location_name}.json"
                logging.debug(f"Saving data to {file_name}")
                if not os.path.exists(file_name) or parser.parse(data['cached_at']) > parser.parse(json.load(open(file_name))['cached_at']):
                    with open(file_name, 'w') as f:
                        json.dump(data, f, indent=4)
                else:
                    logging.debug(f"Data for {location_name} is not newer, skipping.")
        else:
            logging.error(f"Failed to fetch products for location_id {location_id}: {response.status_code} - {response.text}")
            if response.json().get("status") == 6:
                logging.debug("Auth token expired, attempting to login")
                new_auth_token = login()
                if new_auth_token:
                    payload["auth_token"] = new_auth_token
                    logging.debug(f"Retrying request to {list_products_url} with new auth token for location_id {location_id}")
                    response = requests.post(list_products_url, json=payload)
                    logging.debug(f"Retry response status code: {response.status_code}")
                    logging.debug(f"Retry response data: {response.text}")
                    if response.status_code == 200:
                        data = response.json()
                        if "location" in data and "name" in data["location"]:
                            location_name = data["location"]["name"]
                            file_name = f"{location_name}.json"
                            logging.debug(f"Saving data to {file_name}")
                            if not os.path.exists(file_name) or parser.parse(data['cached_at']) > parser.parse(json.load(open(file_name))['cached_at']):
                                with open(file_name, 'w') as f:
                                    json.dump(data, f, indent=4)
                            else:
                                logging.debug(f"Data for {location_name} is not newer, skipping.")
                    else:
                        logging.error(f"Retry failed: {response.status_code} - {response.text}")

def main():
    logging.debug("Starting the download locations and products script")
    locations_data = fetch_locations()
    if locations_data:
        location_ids = set()
        for key, data in locations_data.items():
            for location in data.get('locations', []):
                location_ids.add(location['location_id'])
        logging.debug(f"Fetched location IDs: {location_ids}")
        fetch_products(location_ids)
    else:
        logging.error("Failed to fetch locations data")

if __name__ == "__main__":
    main()
