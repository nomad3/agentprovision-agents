#!/bin/bash

# AgentProvision Critical Flows Test Script
# Tests all major user flows via API endpoints

set -e

BASE_URL="https://agentprovision.com/api/v1"
TEST_EMAIL="test@example.com"
TEST_PASSWORD="password"

echo "🧪 Testing AgentProvision Critical Flows"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counter
TESTS_PASSED=0
TESTS_FAILED=0

# Helper function to test endpoint
test_endpoint() {
    local name=$1
    local method=$2
    local endpoint=$3
    local data=$4
    local expected_status=$5
    local auth_header=$6

    echo -n "Testing: $name... "

    if [ -z "$data" ]; then
        if [ -z "$auth_header" ]; then
            response=$(curl -s -w "\n%{http_code}" -X $method "$BASE_URL$endpoint")
        else
            response=$(curl -s -w "\n%{http_code}" -X $method -H "$auth_header" "$BASE_URL$endpoint")
        fi
    else
        if [ -z "$auth_header" ]; then
            response=$(curl -s -w "\n%{http_code}" -X $method -H "Content-Type: application/json" -d "$data" "$BASE_URL$endpoint")
        else
            response=$(curl -s -w "\n%{http_code}" -X $method -H "Content-Type: application/json" -H "$auth_header" -d "$data" "$BASE_URL$endpoint")
        fi
    fi

    status_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')

    if [ "$status_code" = "$expected_status" ]; then
        echo -e "${GREEN}✓ PASSED${NC} (HTTP $status_code)"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        echo -e "${RED}✗ FAILED${NC} (Expected HTTP $expected_status, got $status_code)"
        echo "Response: $body"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
}

echo "1️⃣  Authentication Flow"
echo "----------------------"

# Login with form data (OAuth2PasswordRequestForm)
login_response=$(curl -s -X POST -H "Content-Type: application/x-www-form-urlencoded" -d "username=$TEST_EMAIL&password=$TEST_PASSWORD" "$BASE_URL/auth/login")
ACCESS_TOKEN=$(echo "$login_response" | jq -r '.access_token')

if [ "$ACCESS_TOKEN" != "null" ] && [ -n "$ACCESS_TOKEN" ]; then
    echo -e "${GREEN}✓ Login successful${NC}"
    TESTS_PASSED=$((TESTS_PASSED + 1))
    AUTH_HEADER="Authorization: Bearer $ACCESS_TOKEN"
else
    echo -e "${RED}✗ Login failed${NC}"
    echo "Response: $login_response"
    TESTS_FAILED=$((TESTS_FAILED + 1))
    exit 1
fi

echo ""
echo "2️⃣  LLM Provider & Model Flow"
echo "----------------------------"

test_endpoint "Get LLM Providers" "GET" "/llm/providers" "" "200"
test_endpoint "Get LLM Models" "GET" "/llm/models" "" "200"

# Check for Claude 4.5 models
claude_models=$(curl -s "$BASE_URL/llm/models" | jq '[.[] | select(.model_id | contains("claude-4-5"))] | length')
if [ "$claude_models" -ge 2 ]; then
    echo -e "${GREEN}✓ Claude 4.5 models available${NC} ($claude_models models)"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    echo -e "${RED}✗ Claude 4.5 models missing${NC}"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi

echo ""
echo "3️⃣  Dataset Management Flow"
echo "--------------------------"

test_endpoint "List Datasets" "GET" "/datasets/" "" "200" "$AUTH_HEADER"

echo ""
echo "4️⃣  Agent Management Flow"
echo "------------------------"

test_endpoint "List Agents" "GET" "/agents/" "" "200" "$AUTH_HEADER"

# Create a test agent with Claude 4.5
agent_data='{"name":"Test Agent Claude 4.5","description":"Automated test agent","model":"claude-4-5-sonnet","system_prompt":"You are a helpful assistant.","temperature":0.7,"max_tokens":2000}'
create_response=$(curl -s -w "\n%{http_code}" -X POST -H "Content-Type: application/json" -H "$AUTH_HEADER" -d "$agent_data" "$BASE_URL/agents/")
create_status=$(echo "$create_response" | tail -n1)
create_body=$(echo "$create_response" | sed '$d')

if [ "$create_status" = "200" ] || [ "$create_status" = "201" ]; then
    AGENT_ID=$(echo "$create_body" | jq -r '.id')
    echo -e "${GREEN}✓ Create Agent with Claude 4.5${NC} (HTTP $create_status)"
    TESTS_PASSED=$((TESTS_PASSED + 1))

    # Clean up - delete the test agent
    delete_response=$(curl -s -w "\n%{http_code}" -X DELETE -H "$AUTH_HEADER" "$BASE_URL/agents/$AGENT_ID")
    delete_status=$(echo "$delete_response" | tail -n1)
    if [ "$delete_status" = "200" ] || [ "$delete_status" = "204" ]; then
        echo -e "${GREEN}✓ Delete Test Agent${NC} (HTTP $delete_status)"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        echo -e "${YELLOW}⚠ Could not delete test agent${NC} (HTTP $delete_status)"
    fi
else
    echo -e "${RED}✗ Create Agent failed${NC} (HTTP $create_status)"
    echo "Response: $create_body"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi

echo ""
echo "5️⃣  Agent Kit Flow"
echo "-----------------"

test_endpoint "List Agent Kits" "GET" "/agent-kits/" "" "200" "$AUTH_HEADER"

echo ""
echo "6️⃣  Chat Session Flow"
echo "--------------------"

test_endpoint "List Chat Sessions" "GET" "/chat/sessions" "" "200" "$AUTH_HEADER"

echo ""
echo "7️⃣  Analytics Dashboard"
echo "----------------------"

test_endpoint "Get Dashboard Analytics" "GET" "/analytics/dashboard" "" "200" "$AUTH_HEADER"

echo ""
echo "8️⃣  PostgreSQL Integration"
echo "-------------------------"

test_endpoint "Get PostgreSQL Status" "GET" "/postgres/status" "" "200" "$AUTH_HEADER"

echo ""
echo "=========================================="
echo "📊 Test Results Summary"
echo "=========================================="
echo -e "Tests Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Tests Failed: ${RED}$TESTS_FAILED${NC}"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}✗ Some tests failed${NC}"
    exit 1
fi
