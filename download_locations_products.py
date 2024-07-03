import requests
import json
import os
import base64
from nacl import encoding, public

# API URLs
login_url = "https://app2.ontherun.com.au/api/v2/login"
list_locations_url = "https://app2.ontherun.com.au/api/v2/listLocations"
list_products_url = "https://app2.ontherun.com.au/api/v2/listOrderingEnabledBrandProductsFull"
github_api_url = "https://api.github.com"

# Common payload parameters
is_modal_view = "false"
apple_id = "null"
apple_token = "null"
api_key = "null"
client_version = "3.7.160"
client_os = "null"
facebook_token = "null"
auth_token = os.getenv('AUTH_TOKEN')
email = os.getenv('EMAIL')
password = os.getenv('PASSWORD')
repo = os.getenv('REPO')
gh_pat = os.getenv('GH_PAT')

# Function to log in and get a new auth token
def login():
    global auth_token
    login_payload = {
        "email": email,
        "password": password,
        "facebook_token": facebook_token,
        "is_modal_view": is_modal_view,
        "apple_id": apple_id,
        "apple_token": apple_token,
        "api_key": api_key,
        "client_version": client_version,
        "client_os": client_os,
        "auth_token": ""
    }
    response = requests.post(login_url, json=login_payload)
    if response.status_code == 200:
        response_data = response.json()
        auth_token = response_data.get("auth_token")
        print("Login successful, new auth token obtained")
        update_github_secret("AUTH_TOKEN", auth_token)
    else:
        print(f"Failed to log in. Status code: {response.status_code}")
        response.raise_for_status()

# Function to get the public key for encrypting the secret
def get_public_key():
    url = f"{github_api_url}/repos/{repo}/actions/secrets/public-key"
    headers = {
        "Authorization": f"Bearer {gh_pat}",
        "Accept": "application/vnd.github.v3+json"
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to get public key. Status code: {response.status_code}")
        response.raise_for_status()

# Function to encrypt the secret
def encrypt_secret(public_key, secret_value):
    public_key = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")

# Function to update the GitHub secret
def update_github_secret(secret_name, secret_value):
    public_key_response = get_public_key()
    public_key = public_key_response["key"]
    key_id = public_key_response["key_id"]
    encrypted_value = encrypt_secret(public_key, secret_value)
    url = f"{github_api_url}/repos/{repo}/actions/secrets/{secret_name}"
    headers = {
        "Authorization": f"Bearer {gh_pat}",
        "Accept": "application/vnd.github.v3+json"
    }
    data = {
        "encrypted_value": encrypted_value,
        "key_id": key_id
    }
    response = requests.put(url, headers=headers, json=data)
    if response.status_code == 204:
        print(f"Secret {secret_name} updated successfully")
    else:
        print(f"Failed to update secret. Status code: {response.status_code}")
        response.raise_for_status()

# Function to send a POST request with retry logic for authentication errors
def send_post_request(url, payload, filename, retry=True):
    response = requests.post(url, json=payload)
    response_data = response.json()
    if response.status_code == 200:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(response_data, f, ensure_ascii=False, indent=4)
    elif response_data.get("status") == 6 and retry:
        # Token expired, refresh token and retry request
        login()
        payload["auth_token"] = auth_token
        send_post_request(url, payload, filename, retry=False)
    else:
        print(f"Failed to get data from {url} with payload {payload}. Status code: {response.status_code}")

# Perform initial login to get the auth token if it's not already set
if not auth_token:
    login()

# Fetch and save locations with ordering_enabled = 0
payload_0 = {
    "ordering_enabled": "0",
    "api_key": api_key,
    "client_version": client_version,
    "client_os": client_os,
    "auth_token": auth_token
}
send_post_request(list_locations_url, payload_0, "locations.json")

# Fetch and save locations with ordering_enabled = 1
payload_1 = {
    "ordering_enabled": "1",
    "api_key": api_key,
    "client_version": client_version,
    "client_os": client_os,
    "auth_token": auth_token
}
send_post_request(list_locations_url, payload_1, "locations_ordering_enabled.json")

# Function to extract location_ids from a JSON file
def extract_location_ids(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return [location["location_id"] for location in data.get("locations", [])]

# Extract and deduplicate location_ids
location_ids_0 = extract_location_ids("locations.json")
location_ids_1 = extract_location_ids("locations_ordering_enabled.json")
unique_location_ids = list(set(location_ids_0 + location_ids_1))

# Function to determine if the new data should overwrite the old data
def should_overwrite(filename, new_cached_at):
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
            existing_cached_at = data.get("cached_at", "")
            if existing_cached_at >= new_cached_at:
                return False
    return True

# Fetch brand products for each location_id and save to respective files
for location_id in unique_location_ids:
    payload = {
        "location_id": location_id,
        "refresh_cache": "False",
        "api_key": api_key,
        "client_version": client_version,
        "client_os": client_os,
        "auth_token": auth_token
    }
    response = requests.post(list_products_url, json=payload)
    response_data = response.json()
    if response.status_code == 200:
        location_info = response_data.get("location")
        if location_info:
            location_name = location_info.get("name", f"location_{location_id}")
            filename = f"{location_name.replace(' ', '_')}.json"
            new_cached_at = response_data.get("cached_at")
            if new_cached_at and should_overwrite(filename, new_cached_at):
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(response_data, f, ensure_ascii=False, indent=4)
            else:
                print(f"Skipping file update for {filename}: new data is not newer.")
        else:
            print(f"No 'location' key found in response for location_id {location_id}.")
    elif response_data.get("status") == 6:
        # Token expired, refresh token and retry request
        login()
        payload["auth_token"] = auth_token
        response = requests.post(list_products_url, json=payload)
        response_data = response.json()
        if response.status_code == 200:
            location_info = response_data.get("location")
            if location_info:
                location_name = location_info.get("name", f"location_{location_id}")
                filename = f"{location_name.replace(' ', '_')}.json"
                new_cached_at = response_data.get("cached_at")
                if new_cached_at and should_overwrite(filename, new_cached_at):
                    with open(filename, 'w', encoding='utf-8') as f:
                        json.dump(response_data, f, ensure_ascii=False, indent=4)
                else:
                    print(f"Skipping file update for {filename}: new data is not newer.")
            else:
                print(f"No 'location' key found in response for location_id {location_id}.")
        else:
            print(f"Failed to get data from {list_products_url} with payload {payload}. Status code: {response.status_code}")
    else:
        print(f"Failed to get data from {list_products_url} with payload {payload}. Status code: {response.status_code}")