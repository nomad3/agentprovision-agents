#!/bin/bash
set -e

# AgentProvision Production End-to-End Test Suite
# Tests the production environment at agentprovision.com

BASE_URL="${BASE_URL:-https://agentprovision.com}"
API_URL="$BASE_URL/api/v1"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counter
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_TOTAL=0

# Function to print test results
pass() {
    echo -e "${GREEN}✓ PASS${NC}: $1"
    TESTS_PASSED=$((TESTS_PASSED + 1))
    TESTS_TOTAL=$((TESTS_TOTAL + 1))
}

fail() {
    echo -e "${RED}✗ FAIL${NC}: $1"
    echo "  Details: $2"
    TESTS_FAILED=$((TESTS_FAILED + 1))
    TESTS_TOTAL=$((TESTS_TOTAL + 1))
}

info() {
    echo -e "${YELLOW}ℹ INFO${NC}: $1"
}

# Function to test HTTP endpoint
test_endpoint() {
    local name=$1
    local method=$2
    local endpoint=$3
    local expected_code=$4
    local headers=$5
    local data=$6

    local curl_cmd="curl -s -o /tmp/response.json -w '%{http_code}' -X $method"

    if [ -n "$headers" ]; then
        curl_cmd="$curl_cmd $headers"
    fi

    if [ -n "$data" ]; then
        curl_cmd="$curl_cmd -d '$data' -H 'Content-Type: application/json'"
    fi

    curl_cmd="$curl_cmd '$endpoint'"

    local response_code=$(eval $curl_cmd)

    if [ "$response_code" -eq "$expected_code" ]; then
        pass "$name (HTTP $response_code)"
        return 0
    else
        fail "$name" "Expected HTTP $expected_code, got $response_code. Response: $(cat /tmp/response.json)"
        return 1
    fi
}

# Function to extract JSON field
extract_json_field() {
    local json=$1
    local field=$2
    echo "$json" | grep -o "\"$field\":\"[^\"]*\"" | cut -d'"' -f4
}

echo "========================================="
echo "AgentProvision Production E2E Test Suite"
echo "========================================="
echo "Base URL: $BASE_URL"
echo "API URL: $API_URL"
echo ""

# =====================================
# Section 1: Public Endpoints
# =====================================
echo "Section 1: Public Endpoints"
echo "----------------------------"

# Test 1: Homepage loads
info "Testing homepage..."
response=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/")
if [ "$response" -eq 200 ]; then
    pass "Homepage loads successfully"
elif [ "$response" -eq 404 ]; then
    info "Homepage test skipped (testing API directly without web frontend)"
else
    fail "Homepage loads" "Expected HTTP 200 or 404, got $response"
fi

# Test 2: API root
info "Testing API root endpoint..."
response=$(curl -s "$API_URL/")
if echo "$response" | grep -q "AgentProvision API"; then
    pass "API root endpoint responds correctly"
else
    fail "API root endpoint" "Unexpected response: $response"
fi

# Test 3: Public analytics endpoint (if it exists)
info "Testing public analytics endpoint..."
response=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/analytics/public/metrics")
if [ "$response" -eq 200 ] || [ "$response" -eq 404 ]; then
    if [ "$response" -eq 200 ]; then
        pass "Public analytics endpoint exists and responds"
    else
        info "Public analytics endpoint not found (404) - may not be implemented"
    fi
else
    fail "Public analytics endpoint" "Unexpected HTTP code: $response"
fi

echo ""

# =====================================
# Section 2: Authentication Flow
# =====================================
echo "Section 2: Authentication Flow"
echo "-------------------------------"

# Generate unique test user
TEST_EMAIL="e2e-test-$(date +%s)@example.com"
TEST_PASSWORD="TestPassword123!"
TEST_TENANT="E2E Test Tenant $(date +%s)"
TEST_USER_NAME="E2E Test User"

info "Creating test user: $TEST_EMAIL"

# Test 4: User registration
info "Testing user registration..."
REGISTER_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$API_URL/auth/register" \
    -H "Content-Type: application/json" \
    -d "{
        \"user_in\": {
            \"email\": \"$TEST_EMAIL\",
            \"password\": \"$TEST_PASSWORD\",
            \"full_name\": \"$TEST_USER_NAME\"
        },
        \"tenant_in\": {
            \"name\": \"$TEST_TENANT\"
        }
    }")

HTTP_CODE=$(echo "$REGISTER_RESPONSE" | tail -n 1)
RESPONSE_BODY=$(echo "$REGISTER_RESPONSE" | sed '$d')

if [ "$HTTP_CODE" -eq 201 ] || [ "$HTTP_CODE" -eq 200 ]; then
    if echo "$RESPONSE_BODY" | grep -q "$TEST_EMAIL"; then
        pass "User registration successful (HTTP $HTTP_CODE)"
        USER_ID=$(echo "$RESPONSE_BODY" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
        TENANT_ID=$(echo "$RESPONSE_BODY" | grep -o '"tenant_id":"[^"]*"' | cut -d'"' -f4)
        info "User ID: $USER_ID"
        info "Tenant ID: $TENANT_ID"
    else
        fail "User registration" "Response doesn't contain expected email: $RESPONSE_BODY"
    fi
else
    fail "User registration" "Expected HTTP 200/201, got $HTTP_CODE. Response: $RESPONSE_BODY"
fi

# Test 5: User login
info "Testing user login..."
LOGIN_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$API_URL/auth/login" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=$TEST_EMAIL&password=$TEST_PASSWORD")

HTTP_CODE=$(echo "$LOGIN_RESPONSE" | tail -n 1)
RESPONSE_BODY=$(echo "$LOGIN_RESPONSE" | sed '$d')

if [ "$HTTP_CODE" -eq 200 ]; then
    ACCESS_TOKEN=$(echo "$RESPONSE_BODY" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)
    if [ -n "$ACCESS_TOKEN" ]; then
        pass "User login successful"
        info "Access token obtained (${ACCESS_TOKEN:0:20}...)"
    else
        fail "User login" "No access token in response: $RESPONSE_BODY"
    fi
else
    fail "User login" "Expected HTTP 200, got $HTTP_CODE. Response: $RESPONSE_BODY"
fi

# Test 6: Get current user (users/me)
info "Testing authenticated endpoint /auth/users/me..."
if [ -n "$ACCESS_TOKEN" ]; then
    ME_RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "$API_URL/auth/users/me" \
        -H "Authorization: Bearer $ACCESS_TOKEN")

    HTTP_CODE=$(echo "$ME_RESPONSE" | tail -n 1)
    RESPONSE_BODY=$(echo "$ME_RESPONSE" | sed '$d')

    if [ "$HTTP_CODE" -eq 200 ]; then
        if echo "$RESPONSE_BODY" | grep -q "$TEST_EMAIL"; then
            pass "Get current user endpoint works"
        else
            fail "Get current user" "Response doesn't contain user email: $RESPONSE_BODY"
        fi
    else
        fail "Get current user" "Expected HTTP 200, got $HTTP_CODE. Response: $RESPONSE_BODY"
    fi
fi

echo ""

# =====================================
# Section 3: Core API Endpoints
# =====================================
echo "Section 3: Core API Endpoints (Authenticated)"
echo "----------------------------------------------"

if [ -z "$ACCESS_TOKEN" ]; then
    echo -e "${RED}Skipping authenticated tests - no access token available${NC}"
else
    AUTH_HEADER="-H 'Authorization: Bearer $ACCESS_TOKEN'"

    # Test 7: Analytics summary
    info "Testing analytics summary..."
    ANALYTICS_RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "$API_URL/analytics/summary" \
        -H "Authorization: Bearer $ACCESS_TOKEN")

    HTTP_CODE=$(echo "$ANALYTICS_RESPONSE" | tail -n 1)
    RESPONSE_BODY=$(echo "$ANALYTICS_RESPONSE" | sed '$d')

    if [ "$HTTP_CODE" -eq 200 ]; then
        if echo "$RESPONSE_BODY" | grep -q "total_agents"; then
            pass "Analytics summary endpoint works"
        else
            fail "Analytics summary" "Missing expected fields in response: $RESPONSE_BODY"
        fi
    else
        fail "Analytics summary" "Expected HTTP 200, got $HTTP_CODE. Response: $RESPONSE_BODY"
    fi

    # Test 8: List agents
    info "Testing list agents..."
    AGENTS_RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "$API_URL/agents/" \
        -H "Authorization: Bearer $ACCESS_TOKEN")

    HTTP_CODE=$(echo "$AGENTS_RESPONSE" | tail -n 1)

    if [ "$HTTP_CODE" -eq 200 ]; then
        pass "List agents endpoint works"
    else
        fail "List agents" "Expected HTTP 200, got $HTTP_CODE"
    fi

    # Test 9: Create agent
    info "Testing create agent..."
    CREATE_AGENT_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$API_URL/agents/" \
        -H "Authorization: Bearer $ACCESS_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{
            \"name\": \"E2E Test Agent\",
            \"description\": \"Agent created by E2E test\",
            \"type\": \"chat\",
            \"config\": {}
        }")

    HTTP_CODE=$(echo "$CREATE_AGENT_RESPONSE" | tail -n 1)
    RESPONSE_BODY=$(echo "$CREATE_AGENT_RESPONSE" | sed '$d')

    if [ "$HTTP_CODE" -eq 201 ] || [ "$HTTP_CODE" -eq 200 ]; then
        AGENT_ID=$(echo "$RESPONSE_BODY" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
        pass "Create agent endpoint works"
        info "Created agent ID: $AGENT_ID"
    else
        fail "Create agent" "Expected HTTP 200/201, got $HTTP_CODE. Response: $RESPONSE_BODY"
    fi

    # Test 10: List agent kits
    info "Testing list agent kits..."
    KITS_RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "$API_URL/agent_kits/" \
        -H "Authorization: Bearer $ACCESS_TOKEN")

    HTTP_CODE=$(echo "$KITS_RESPONSE" | tail -n 1)

    if [ "$HTTP_CODE" -eq 200 ]; then
        pass "List agent kits endpoint works"
    else
        fail "List agent kits" "Expected HTTP 200, got $HTTP_CODE"
    fi

    # Test 11: List deployments
    info "Testing list deployments..."
    DEPLOYMENTS_RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "$API_URL/deployments/" \
        -H "Authorization: Bearer $ACCESS_TOKEN")

    HTTP_CODE=$(echo "$DEPLOYMENTS_RESPONSE" | tail -n 1)

    if [ "$HTTP_CODE" -eq 200 ]; then
        pass "List deployments endpoint works"
    else
        fail "List deployments" "Expected HTTP 200, got $HTTP_CODE"
    fi

    # Test 12: List data sources
    info "Testing list data sources..."
    DATA_SOURCES_RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "$API_URL/data_sources/" \
        -H "Authorization: Bearer $ACCESS_TOKEN")

    HTTP_CODE=$(echo "$DATA_SOURCES_RESPONSE" | tail -n 1)

    if [ "$HTTP_CODE" -eq 200 ]; then
        pass "List data sources endpoint works"
    else
        fail "List data sources" "Expected HTTP 200, got $HTTP_CODE"
    fi

    # Test 13: List data pipelines
    info "Testing list data pipelines..."
    PIPELINES_RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "$API_URL/data_pipelines/" \
        -H "Authorization: Bearer $ACCESS_TOKEN")

    HTTP_CODE=$(echo "$PIPELINES_RESPONSE" | tail -n 1)

    if [ "$HTTP_CODE" -eq 200 ]; then
        pass "List data pipelines endpoint works"
    else
        fail "List data pipelines" "Expected HTTP 200, got $HTTP_CODE"
    fi

    # Test 14: List notebooks
    info "Testing list notebooks..."
    NOTEBOOKS_RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "$API_URL/notebooks/" \
        -H "Authorization: Bearer $ACCESS_TOKEN")

    HTTP_CODE=$(echo "$NOTEBOOKS_RESPONSE" | tail -n 1)

    if [ "$HTTP_CODE" -eq 200 ]; then
        pass "List notebooks endpoint works"
    else
        fail "List notebooks" "Expected HTTP 200, got $HTTP_CODE"
    fi

    # Test 15: List datasets
    info "Testing list datasets..."
    DATASETS_RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "$API_URL/datasets/" \
        -H "Authorization: Bearer $ACCESS_TOKEN")

    HTTP_CODE=$(echo "$DATASETS_RESPONSE" | tail -n 1)

    if [ "$HTTP_CODE" -eq 200 ]; then
        pass "List datasets endpoint works"
    else
        fail "List datasets" "Expected HTTP 200, got $HTTP_CODE"
    fi

    # Test 16: List tools
    info "Testing list tools..."
    TOOLS_RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "$API_URL/tools/" \
        -H "Authorization: Bearer $ACCESS_TOKEN")

    HTTP_CODE=$(echo "$TOOLS_RESPONSE" | tail -n 1)

    if [ "$HTTP_CODE" -eq 200 ]; then
        pass "List tools endpoint works"
    else
        fail "List tools" "Expected HTTP 200, got $HTTP_CODE"
    fi

    # Test 17: List connectors
    info "Testing list connectors..."
    CONNECTORS_RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "$API_URL/connectors/" \
        -H "Authorization: Bearer $ACCESS_TOKEN")

    HTTP_CODE=$(echo "$CONNECTORS_RESPONSE" | tail -n 1)

    if [ "$HTTP_CODE" -eq 200 ]; then
        pass "List connectors endpoint works"
    else
        fail "List connectors" "Expected HTTP 200, got $HTTP_CODE"
    fi

    # Test 18: List vector stores
    info "Testing list vector stores..."
    VECTOR_STORES_RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "$API_URL/vector_stores/" \
        -H "Authorization: Bearer $ACCESS_TOKEN")

    HTTP_CODE=$(echo "$VECTOR_STORES_RESPONSE" | tail -n 1)

    if [ "$HTTP_CODE" -eq 200 ]; then
        pass "List vector stores endpoint works"
    else
        fail "List vector stores" "Expected HTTP 200, got $HTTP_CODE"
    fi

    # Test 19: List chat sessions
    info "Testing list chat sessions..."
    CHAT_RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "$API_URL/chat/sessions" \
        -H "Authorization: Bearer $ACCESS_TOKEN")

    HTTP_CODE=$(echo "$CHAT_RESPONSE" | tail -n 1)

    if [ "$HTTP_CODE" -eq 200 ]; then
        pass "List chat sessions endpoint works"
    else
        fail "List chat sessions" "Expected HTTP 200, got $HTTP_CODE"
    fi
fi

echo ""

# =====================================
# Section 4: Feature Tests
# =====================================
echo "Section 4: Feature-Specific Tests"
echo "----------------------------------"

if [ -n "$ACCESS_TOKEN" ]; then
    # Test 20: Create dataset via ingestion (prerequisite for chat)
    info "Testing create dataset via ingestion..."
    CREATE_DATASET_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$API_URL/datasets/ingest" \
        -H "Authorization: Bearer $ACCESS_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{
            \"name\": \"E2E Test Dataset\",
            \"description\": \"Dataset created by E2E test\",
            \"records\": [
                {\"id\": 1, \"name\": \"Test Record 1\", \"value\": 100},
                {\"id\": 2, \"name\": \"Test Record 2\", \"value\": 200}
            ]
        }")

    HTTP_CODE=$(echo "$CREATE_DATASET_RESPONSE" | tail -n 1)
    RESPONSE_BODY=$(echo "$CREATE_DATASET_RESPONSE" | sed '$d')

    if [ "$HTTP_CODE" -eq 201 ] || [ "$HTTP_CODE" -eq 200 ]; then
        DATASET_ID=$(echo "$RESPONSE_BODY" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
        pass "Create dataset via ingestion works"
        info "Dataset ID: $DATASET_ID"
    else
        fail "Create dataset" "Expected HTTP 200/201, got $HTTP_CODE. Response: $RESPONSE_BODY"
        DATASET_ID=""
    fi

    # Test 21: Create agent kit (prerequisite for chat)
    info "Testing create agent kit..."
    CREATE_KIT_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$API_URL/agent_kits/" \
        -H "Authorization: Bearer $ACCESS_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{
            \"name\": \"E2E Test Agent Kit\",
            \"description\": \"Agent kit created by E2E test\",
            \"config\": {
                \"primary_objective\": \"E2E Testing - Data Analysis and Reporting\",
                \"triggers\": [\"user request\", \"scheduled analysis\"],
                \"metrics\": [\"accuracy\", \"response time\"],
                \"constraints\": [\"read-only access\"],
                \"tool_bindings\": [],
                \"vector_bindings\": [],
                \"playbook\": [],
                \"handoff_channels\": []
            }
        }")

    HTTP_CODE=$(echo "$CREATE_KIT_RESPONSE" | tail -n 1)
    RESPONSE_BODY=$(echo "$CREATE_KIT_RESPONSE" | sed '$d')

    if [ "$HTTP_CODE" -eq 201 ] || [ "$HTTP_CODE" -eq 200 ]; then
        AGENT_KIT_ID=$(echo "$RESPONSE_BODY" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
        pass "Create agent kit works"
        info "Agent Kit ID: $AGENT_KIT_ID"
    else
        fail "Create agent kit" "Expected HTTP 200/201, got $HTTP_CODE. Response: $RESPONSE_BODY"
        AGENT_KIT_ID=""
    fi

    # Test 22: Create chat session (requires dataset and agent kit)
    if [ -n "$DATASET_ID" ] && [ -n "$AGENT_KIT_ID" ]; then
        info "Testing create chat session..."
        CREATE_CHAT_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$API_URL/chat/sessions" \
            -H "Authorization: Bearer $ACCESS_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{
                \"title\": \"E2E Test Chat Session\",
                \"dataset_id\": \"$DATASET_ID\",
                \"agent_kit_id\": \"$AGENT_KIT_ID\"
            }")

        HTTP_CODE=$(echo "$CREATE_CHAT_RESPONSE" | tail -n 1)
        RESPONSE_BODY=$(echo "$CREATE_CHAT_RESPONSE" | sed '$d')

        if [ "$HTTP_CODE" -eq 201 ] || [ "$HTTP_CODE" -eq 200 ]; then
            CHAT_SESSION_ID=$(echo "$RESPONSE_BODY" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
            pass "Create chat session works"
            info "Chat session ID: $CHAT_SESSION_ID"

            # Test 23: Send chat message
            if [ -n "$CHAT_SESSION_ID" ]; then
                info "Testing send chat message..."
                SEND_MESSAGE_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$API_URL/chat/sessions/$CHAT_SESSION_ID/messages" \
                    -H "Authorization: Bearer $ACCESS_TOKEN" \
                    -H "Content-Type: application/json" \
                    -d "{
                        \"content\": \"Hello, this is a test message from E2E tests\"
                    }")

                HTTP_CODE=$(echo "$SEND_MESSAGE_RESPONSE" | tail -n 1)
                RESPONSE_BODY=$(echo "$SEND_MESSAGE_RESPONSE" | sed '$d')

                if [ "$HTTP_CODE" -eq 201 ] || [ "$HTTP_CODE" -eq 200 ]; then
                    pass "Send chat message works"
                else
                    fail "Send chat message" "Expected HTTP 200/201, got $HTTP_CODE. Response: $RESPONSE_BODY"
                fi
            fi
        else
            fail "Create chat session" "Expected HTTP 200/201, got $HTTP_CODE. Response: $RESPONSE_BODY"
        fi
    else
        info "Skipping chat session test - missing prerequisites (dataset or agent kit)"
    fi
fi

echo ""

# =====================================
# Final Summary
# =====================================
echo "========================================="
echo "Test Results Summary"
echo "========================================="
echo "Total tests: $TESTS_TOTAL"
echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed: ${RED}$TESTS_FAILED${NC}"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed. Please review the output above.${NC}"
    exit 1
fi
