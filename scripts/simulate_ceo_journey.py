import requests
import json
import time

BASE_URL = "https://agentprovision.com/api/v1"
USERNAME = "test@example.com"
PASSWORD = "password"

def login():
    response = requests.post(
        f"{BASE_URL}/auth/login",
        data={"username": USERNAME, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    response.raise_for_status()
    return response.json()["access_token"]

def list_datasets(token):
    response = requests.get(f"{BASE_URL}/datasets/", headers={"Authorization": f"Bearer {token}"})
    response.raise_for_status()
    return response.json()

def create_dataset_group(token, name, description, dataset_ids):
    payload = {
        "name": name,
        "description": description,
        "dataset_ids": dataset_ids
    }
    response = requests.post(f"{BASE_URL}/dataset-groups/", json=payload, headers={"Authorization": f"Bearer {token}"})
    response.raise_for_status()
    return response.json()

def list_agent_kits(token):
    response = requests.get(f"{BASE_URL}/agent-kits/", headers={"Authorization": f"Bearer {token}"})
    response.raise_for_status()
    return response.json()

def create_chat_session(token, agent_kit_id, dataset_group_id):
    payload = {
        "agent_kit_id": agent_kit_id,
        "dataset_group_id": dataset_group_id,
        "title": "CEO Group Analysis Session"
    }
    response = requests.post(f"{BASE_URL}/chat/sessions", json=payload, headers={"Authorization": f"Bearer {token}"})
    if response.status_code not in [200, 201]:
        print(f"Failed to create chat session: {response.text}")
    response.raise_for_status()
    return response.json()

def send_message(token, session_id, message):
    payload = {"content": message}
    response = requests.post(f"{BASE_URL}/chat/sessions/{session_id}/messages", json=payload, headers={"Authorization": f"Bearer {token}"})
    response.raise_for_status()
    return response.json()

def main():
    print("Logging in...")
    token = login()
    print("Logged in.")

    print("Listing datasets...")
    datasets = list_datasets(token)

    # Filter for NetSuite datasets
    netsuite_datasets = [d for d in datasets if "TransactionDetail" in d["name"] or "Operations Report" in d["name"]]
    print(f"Found {len(netsuite_datasets)} NetSuite datasets.")

    if len(netsuite_datasets) < 2:
        print("Not enough NetSuite datasets found to create a group. Need at least 2.")
        # Fallback to using any datasets if needed for testing
        if len(datasets) >= 2:
            print("Falling back to using any available datasets.")
            netsuite_datasets = datasets[:3]
        else:
            return

    dataset_ids = [d["id"] for d in netsuite_datasets]
    dataset_names = [d["name"] for d in netsuite_datasets]
    print(f"Grouping datasets: {dataset_names}")

    print("Creating dataset group...")
    group = create_dataset_group(token, "NetSuite Consolidated Financials", "Grouped financial data for CEO analysis", dataset_ids)
    group_id = group["id"]
    print(f"Dataset group created: {group['name']} ({group_id})")

    print("Listing agent kits...")
    agent_kits = list_agent_kits(token)
    # Use "Customer Support Agent Kit" as it's likely available from previous tests, or find a relevant one
    target_kit = next((k for k in agent_kits if "Analyst" in k["name"] or "Support" in k["name"]), None)

    if not target_kit:
        if agent_kits:
            target_kit = agent_kits[0]
            print(f"No specific Analyst kit found, using first available: {target_kit['name']}")
        else:
            print("No Agent Kits found! Please create an agent kit first.")
            return
    else:
        print(f"Using Agent Kit: {target_kit['name']}")

    agent_kit_id = target_kit["id"]

    print("Creating chat session with dataset group...")
    session = create_chat_session(token, agent_kit_id, group_id)
    session_id = session["id"]
    print(f"Chat session created: {session['title']} ({session_id})")

    message = "Compare the expenses across these datasets and identify which subsidiary has the highest operational costs."
    print(f"Sending message: '{message}'...")

    try:
        response = send_message(token, session_id, message)
        print("Response received:")
        print(json.dumps(response, indent=2))
    except Exception as e:
        print(f"Error sending message: {e}")

if __name__ == "__main__":
    main()
