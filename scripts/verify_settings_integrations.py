import requests
import json
import sys

BASE_URL = "https://agentprovision.com/api/v1"
USERNAME = "test@example.com"
PASSWORD = "password"

def login():
    print("Logging in...")
    try:
        response = requests.post(
            f"{BASE_URL}/auth/login",
            data={"username": USERNAME, "password": PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        response.raise_for_status()
        token = response.json()["access_token"]
        print("Logged in successfully.")
        return token
    except Exception as e:
        print(f"Login failed: {e}")
        sys.exit(1)

def verify_postgres(token):
    print("\n--- Verifying PostgreSQL Integration ---")
    try:
        response = requests.get(
            f"{BASE_URL}/postgres/status",
            headers={"Authorization": f"Bearer {token}"}
        )
        if response.status_code == 200:
            data = response.json()
            print("PostgreSQL Status:")
            print(json.dumps(data, indent=2))
            if data.get("enabled"):
                print("✅ PostgreSQL integration is ENABLED.")
            else:
                print("⚠️ PostgreSQL integration is DISABLED (expected if env vars not set).")
        else:
            print(f"❌ Failed to get PostgreSQL status: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error verifying PostgreSQL: {e}")

def verify_branding(token):
    print("\n--- Verifying Branding ---")
    try:
        response = requests.get(
            f"{BASE_URL}/branding",
            headers={"Authorization": f"Bearer {token}"}
        )
        if response.status_code == 200:
            data = response.json()
            print("Branding Configuration:")
            print(json.dumps(data, indent=2))
            print("✅ Branding endpoint is working.")
        else:
            print(f"❌ Failed to get Branding: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error verifying Branding: {e}")

def verify_llm_settings(token):
    print("\n--- Verifying LLM Settings ---")
    try:
        response = requests.get(
            f"{BASE_URL}/llm/providers/status",
            headers={"Authorization": f"Bearer {token}"}
        )
        if response.status_code == 200:
            data = response.json()
            print(f"Found {len(data)} LLM Providers:")
            for provider in data:
                status = "Configured" if provider['configured'] else "Not Configured"
                print(f"- {provider['display_name']} ({provider['name']}): {status}")
            print("✅ LLM Settings endpoint is working.")
        else:
            print(f"❌ Failed to get LLM Providers: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error verifying LLM Settings: {e}")

def main():
    token = login()
    verify_postgres(token)
    verify_branding(token)
    verify_llm_settings(token)

if __name__ == "__main__":
    main()
