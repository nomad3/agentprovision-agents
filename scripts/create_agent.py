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
    )
    response.raise_for_status()
    return response.json()["access_token"]

def create_agent(token):
    headers = {"Authorization": f"Bearer {token}"}

    # First, get the Claude 4.5 Sonnet model ID
    # We can list providers or just guess/hardcode if we know the seed data
    # But let's try to list providers to be safe, or just use the string if the API accepts it.
    # The API usually expects a model_provider and model_name string or ID.

    # Let's create the agent
    data = {
        "name": "NetSuite Analyst",
        "role": "Financial Analyst",
        "description": "Expert in analyzing NetSuite financial data.",
        "model_provider": "anthropic",
        "model_name": "claude-3-5-sonnet-20240620", # Using the ID we seeded
        "temperature": 0.1,
        "system_prompt": "You are a financial analyst. You have access to NetSuite transaction data. Analyze it carefully."
    }

    response = requests.post(f"{BASE_URL}/agents/", json=data, headers=headers)
    if response.status_code in [200, 201]:
        print("Agent created successfully!")
        agent = response.json()
        print(f"Agent ID: {agent['id']}")
        return agent['id']
    else:
        print(f"Failed to create agent: {response.text}")
        return None

if __name__ == "__main__":
    try:
        token = get_token()
        create_agent(token)
    except Exception as e:
        print(f"Error: {e}")
