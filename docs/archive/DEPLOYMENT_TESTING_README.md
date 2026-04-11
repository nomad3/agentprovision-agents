# Automated Deployment Testing for AgentProvision

This document describes the automated testing integrated into the deployment process.

## Overview

The `deploy.sh` script now includes automatic end-to-end testing that runs immediately after deployment to verify everything is working correctly.

## How It Works

### Deployment Flow

1. **Stop existing services**
2. **Build & start containers** (API, Web, DB, Temporal)
3. **Configure Nginx** with SSL
4. **Wait for API to be ready** ⭐ NEW
   - Polls `https://agentprovision.com/api/v1/` for up to 60 seconds
   - Ensures services are fully started before testing
5. **Run E2E tests automatically** ⭐ NEW
   - Executes `scripts/e2e_test_production.sh`
   - Tests all core functionality (22 tests)
6. **Report results**
   - ✅ Green output if all tests pass
   - ❌ Red output + exit code 1 if any tests fail

### What Gets Tested

The E2E test suite validates:

- ✅ **Public Endpoints** (2 tests)
  - Homepage accessibility
  - API root response

- ✅ **Authentication** (3 tests)
  - User registration
  - Login with JWT
  - Token validation

- ✅ **Core Resources** (14 tests)
  - All resource listing endpoints
  - Agent creation
  - Analytics summary

- ✅ **Features** (3 tests)
  - Dataset ingestion
  - Agent kit creation
  - Chat session creation

**Total: 22 automated tests**

## Usage

### Standard Deployment

Simply run the deploy script as usual:

```bash
./deploy.sh
```

The tests will run automatically at the end. You'll see output like:

```
=========================================
Running End-to-End Tests
=========================================

Section 1: Public Endpoints
----------------------------
✓ PASS: Homepage loads successfully
✓ PASS: API root endpoint responds correctly

Section 2: Authentication Flow
-------------------------------
✓ PASS: User registration successful
...

=========================================
Test Results Summary
=========================================
Total tests: 22
Passed: 21
Failed: 1

⚠️  Some E2E tests failed. Please review the output above.
```

### If Tests Fail

The deployment script will:
1. Show which tests failed
2. Display error details
3. Exit with code 1 (indicating failure)
4. Print helpful troubleshooting commands

**Important**: If tests fail, the deployment is considered incomplete. Fix the issues before considering it successful.

### Manual Test Execution

You can run tests manually anytime:

```bash
# Test production
./scripts/e2e_test_production.sh

# Test against staging
BASE_URL=https://staging.agentprovision.com ./scripts/e2e_test_production.sh

# Test local development
BASE_URL=http://localhost:8001 ./scripts/e2e_test_production.sh
```

## Known Issues (Current Test Results)

Based on the latest test run (see `E2E_TEST_FINDINGS.md`):

### ❌ Critical Issue: Chat Message Endpoint
- **Status**: HTTP 500 Internal Server Error
- **Endpoint**: `POST /api/v1/chat/sessions/{id}/messages`
- **Cause**: Likely missing `ANTHROPIC_API_KEY` in production
- **Fix**: Set environment variable in `apps/api/.env`

### ⚠️ Minor Issues
1. Public analytics endpoint returns 404 (may not be implemented)
2. User registration returns HTTP 200 instead of 201 (cosmetic)

**Current Pass Rate**: 21/22 tests (95.5%)

## Troubleshooting

### Tests Time Out or Fail to Connect

Check if services are running:

```bash
docker-compose ps
docker-compose logs api
```

### API Health Check Fails

The deploy script waits up to 60 seconds for the API. If it times out:

```bash
# Check API logs
docker-compose logs -f api

# Check Nginx logs
sudo tail -f /var/log/nginx/error.log

# Test API directly
curl https://agentprovision.com/api/v1/
```

### Tests Pass Locally but Fail in Production

Common causes:
- Missing environment variables (especially `ANTHROPIC_API_KEY`)
- Database not initialized properly
- SSL certificate issues
- Port conflicts

Check:

```bash
# View all environment variables in API container
docker-compose exec api env | grep -E 'ANTHROPIC|DATABASE|SECRET'

# Check database connectivity
docker-compose exec api python -c "from app.db.session import SessionLocal; db = SessionLocal(); print('DB OK')"
```

## Skipping Tests (Not Recommended)

If you need to deploy without running tests (emergencies only), you can modify the script or:

```bash
# Temporarily disable the test script
mv scripts/e2e_test_production.sh scripts/e2e_test_production.sh.disabled
./deploy.sh
mv scripts/e2e_test_production.sh.disabled scripts/e2e_test_production.sh
```

**Warning**: Skipping tests defeats the purpose of automated validation.

## Benefits

1. **Catch issues immediately** - No waiting to discover problems
2. **Confidence in deployments** - Know if something broke
3. **Documentation** - Tests serve as living documentation
4. **Regression prevention** - Catch breaking changes early
5. **Faster debugging** - Specific test failures point to exact issues

## Files Added/Modified

### New Files
- `scripts/e2e_test_production.sh` - Main test suite (executable)
- `E2E_TEST_FINDINGS.md` - Detailed test results and analysis
- `DEPLOYMENT_TESTING_README.md` - This document

### Modified Files
- `deploy.sh` - Added health check wait and automated testing
- `CLAUDE.md` - Updated deployment and testing documentation

## Future Enhancements

Potential improvements:

1. **Smoke tests** - Quick subset of critical tests for faster feedback
2. **Performance benchmarks** - Track response times over deployments
3. **Email notifications** - Alert on test failures
4. **Test history** - Track pass/fail rates over time
5. **Parallel testing** - Speed up test execution
6. **More test coverage** - Add UPDATE/DELETE operations

## Support

For issues or questions:
1. Check `E2E_TEST_FINDINGS.md` for known issues
2. Run tests manually with verbose output
3. Review deployment logs
4. Check `CLAUDE.md` for development commands

---

**Remember**: The tests failing is a **good thing** - they're protecting you from deploying broken code to production!
