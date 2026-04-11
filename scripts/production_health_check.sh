#!/bin/bash
set -e

echo "========================================="
echo "AgentProvision Production Health Check"
echo "========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_section() {
    echo ""
    echo "========================================="
    echo "$1"
    echo "========================================="
}

# Check if we're in the right directory
if [ ! -f "docker-compose.yml" ]; then
    print_error "Not in agentprovision directory. Please cd to /opt/agentprovision"
    exit 1
fi

print_section "1. Git Status"
git status --short
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
CURRENT_COMMIT=$(git rev-parse --short HEAD)
echo "Branch: $CURRENT_BRANCH"
echo "Commit: $CURRENT_COMMIT"
echo "Latest remote commit:"
git fetch origin main --quiet
git log origin/main --oneline -1

print_section "2. Environment Files Check"

# Check PRODUCTION.env
if [ -f "PRODUCTION.env" ]; then
    print_success "PRODUCTION.env exists"
    PROD_API_KEY=$(grep ANTHROPIC_API_KEY PRODUCTION.env | cut -d= -f2)
    PROD_KEY_LENGTH=${#PROD_API_KEY}
    if [ $PROD_KEY_LENGTH -eq 86 ]; then
        print_success "PRODUCTION.env has complete API key (86 chars)"
    else
        print_error "PRODUCTION.env API key is truncated ($PROD_KEY_LENGTH chars, should be 86)"
        echo "First 50 chars: ${PROD_API_KEY:0:50}..."
        echo "Last 20 chars: ...${PROD_API_KEY: -20}"
    fi
else
    print_error "PRODUCTION.env not found"
fi

# Check apps/api/.env
if [ -f "apps/api/.env" ]; then
    print_success "apps/api/.env exists"
    API_KEY=$(grep ANTHROPIC_API_KEY apps/api/.env | cut -d= -f2)
    API_KEY_LENGTH=${#API_KEY}
    if [ $API_KEY_LENGTH -eq 86 ]; then
        print_success "apps/api/.env has complete API key (86 chars)"
    else
        print_error "apps/api/.env API key is truncated ($API_KEY_LENGTH chars, should be 86)"
        echo "First 50 chars: ${API_KEY:0:50}..."
        echo "Last 20 chars: ...${API_KEY: -20}"
    fi
else
    print_error "apps/api/.env not found"
fi

print_section "3. Docker Compose Configuration"
# Set environment variables for docker-compose
export API_PORT=8001
export WEB_PORT=8002
export DB_PORT=8003
export REDIS_PORT=8004
export TEMPORAL_GRPC_PORT=7233
export TEMPORAL_WEB_PORT=8233

# Test docker-compose config
if docker-compose config > /dev/null 2>&1; then
    print_success "docker-compose.yml is valid"
else
    print_error "docker-compose.yml has errors:"
    docker-compose config 2>&1 | head -20
fi

print_section "4. Container Status"
echo "Running containers:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep agentprovision || echo "No agentprovision containers running"

echo ""
echo "All agentprovision containers (including stopped):"
docker ps -a --format "table {{.Names}}\t{{.Status}}" | grep agentprovision || echo "No agentprovision containers found"

print_section "5. Container Logs (Last 20 lines each)"

# Check API logs
echo "--- API Container Logs ---"
if docker ps -a | grep -q agentprovision_api; then
    docker logs --tail=20 agentprovision_api_1 2>&1 || echo "Could not fetch API logs"
else
    print_warning "API container not found"
fi

echo ""
echo "--- Temporal Container Logs ---"
if docker ps -a | grep -q agentprovision_temporal; then
    docker logs --tail=20 agentprovision_temporal_1 2>&1 || echo "Could not fetch Temporal logs"
else
    print_warning "Temporal container not found"
fi

print_section "6. Port Availability"
for port in 8001 8002 8003 7233 8233; do
    if netstat -tlnp 2>/dev/null | grep -q ":$port "; then
        print_success "Port $port is in use"
        netstat -tlnp 2>/dev/null | grep ":$port " | awk '{print "  " $7}'
    else
        print_warning "Port $port is not in use"
    fi
done

print_section "7. API Health Check"
echo "Testing API endpoint..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" https://agentprovision.com/api/v1/ 2>/dev/null || echo "000")

if [ "$HTTP_CODE" = "200" ]; then
    print_success "API is responding (HTTP $HTTP_CODE)"
elif [ "$HTTP_CODE" = "502" ]; then
    print_error "API returns 502 Bad Gateway - API container not responding"
elif [ "$HTTP_CODE" = "000" ]; then
    print_error "Cannot connect to API"
else
    print_warning "API returns HTTP $HTTP_CODE"
fi

print_section "8. Nginx Status"
if systemctl is-active --quiet nginx; then
    print_success "Nginx is running"
else
    print_error "Nginx is not running"
fi

echo ""
echo "Nginx configuration test:"
if sudo nginx -t 2>&1 | grep -q "successful"; then
    print_success "Nginx configuration is valid"
else
    print_error "Nginx configuration has errors"
fi

print_section "Summary"
echo ""
echo "Next steps:"
echo "1. If API key is truncated: Run /tmp/fix_env.sh to recreate .env files"
echo "2. If containers are down: Run ./deploy.sh"
echo "3. If API container is crashing: Check 'docker logs agentprovision_api_1' for errors"
echo "4. If all looks good: Run ./scripts/e2e_test_production.sh"
echo ""
