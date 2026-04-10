import requests
import os
import json

BASE_URL = "https://agentprovision.com/api/v1"
EMAIL = "test@example.com"
PASSWORD = "password"

def get_token():
    response = requests.post(
        f"{BASE_URL}/auth/login",
        data={"username": EMAIL, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    response.raise_for_status()
    return response.json()["access_token"]

def ingest_file(token, filepath):
    filename = os.path.basename(filepath)
    print(f"Uploading {filename}...")
    headers = {"Authorization": f"Bearer {token}"}

    # Use the upload endpoint which expects multipart/form-data
    with open(filepath, 'rb') as f:
        files = {'file': (filename, f)}
        data = {'name': filename}
        # Note: requests adds the correct Content-Type for multipart/form-data automatically
        response = requests.post(f"{BASE_URL}/datasets/upload", files=files, data=data, headers=headers)

    if response.status_code in [200, 201]:
        print(f"Successfully uploaded {filename}")
        return True
    else:
        print(f"Failed to upload {filename}: {response.status_code} - {response.text}")
        return False

if __name__ == "__main__":
    try:
        token = get_token()
        print("Authentication successful.")

        # Directory where we unzipped the files
        data_dir = "apps/api/storage/netsuite_data"

        # List all files
        files = [f for f in os.listdir(data_dir) if f.endswith('.csv') or f.endswith('.xlsx')]
        print(f"Found {len(files)} files to upload.")

        # Get existing datasets to avoid duplicates
        response = requests.get(f"{BASE_URL}/datasets/", headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        existing_datasets = {d["name"] for d in response.json()}

        success_count = 0
        for f in files:
            if f in existing_datasets:
                print(f"Skipping {f} (already exists)")
                success_count += 1
                continue

            full_path = os.path.join(data_dir, f)
            if ingest_file(token, full_path):
                success_count += 1

        print(f"Finished. Uploaded {success_count}/{len(files)} datasets.")

    except Exception as e:
        print(f"Error: {e}")
