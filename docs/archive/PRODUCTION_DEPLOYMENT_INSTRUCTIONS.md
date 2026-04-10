# Production Deployment Instructions

## Critical: Add Anthropic API Key to Production

Your API key has been tested locally and is working correctly. Follow these steps to deploy to production.

---

## Step 1: SSH to Your GCP VM

```bash
ssh your-gcp-vm-name
```

## Step 2: Navigate to Project

```bash
cd /path/to/agentprovision
# Replace /path/to/agentprovision with your actual project path
```

## Step 3: Add API Key to Production Environment

```bash
# Edit the API environment file
vi apps/api/.env
```

Add or update the following lines:

```bash
# LLM Configuration
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
LLM_MODEL=claude-3-5-sonnet-20241022
LLM_MAX_TOKENS=4096
LLM_TEMPERATURE=0.7
```

**Important**: Replace the `xxxxxxxxx` with your actual Anthropic API key from your `.env` file or Anthropic dashboard.

**In vi editor:**
- Press `i` to enter insert mode
- Add/edit the lines above
- Press `ESC` to exit insert mode
- Type `:wq` and press Enter to save and quit

## Step 4: Deploy with Automated Testing

```bash
./deploy.sh
```

This will:
1. Stop existing services
2. Build new containers with updated API key
3. Start services
4. Configure Nginx/SSL
5. **Wait for API to be ready**
6. **Run 22 automated E2E tests**
7. Report results

## Step 5: Verify Success

You should see at the end:

```
=========================================
Test Results Summary
=========================================
Total tests: 22
Passed: 22
Failed: 0

✅ All E2E tests passed!

=========================================
Deployment Complete!
=========================================
```

**Before the fix:** 21/22 tests passed (chat failing)
**After the fix:** 22/22 tests pass ✅

---

## What Changed

### Local Environment ✅
- API key added to `apps/api/.env`
- Docker containers restarted
- Chat functionality tested and working
- Result: **All 21/21 tests passing**

### Production Environment (Next)
- Same API key needs to be added
- Deploy script will handle everything
- Automated tests will verify it works
- Expected: **All 22/22 tests passing**

---

## Troubleshooting

### If Tests Still Fail

1. **Check logs:**
   ```bash
   docker-compose logs -f api | grep -i anthropic
   ```

2. **Verify environment variable:**
   ```bash
   docker-compose exec api env | grep ANTHROPIC
   ```

   Should show:
   ```
   ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

   (Your actual API key value will be displayed)

3. **Test chat manually:**
   ```bash
   # Get the test script output during deployment
   # Or re-run tests:
   ./scripts/e2e_test_production.sh
   ```

### If API Key is Invalid

Error message will show:
```
authentication_error: Invalid API Key
```

If this happens, double-check the API key was copied correctly.

---

## Security Notes

✅ **Already Done:**
- `.env` files added to `.gitignore` (won't be committed)
- API key tested locally first
- Automated tests verify functionality

⚠️ **Important:**
- Never commit `.env` files to git
- Never share API keys in chat/email
- Rotate API key if accidentally exposed
- Monitor API usage in Anthropic dashboard

---

## Expected Timeline

1. SSH to VM: **30 seconds**
2. Add API key: **2 minutes**
3. Run deploy script: **5-7 minutes**
4. Automated tests: **~30 seconds**
5. Verify in browser: **1 minute**

**Total: ~10 minutes**

---

## After Deployment

### Test Chat in the UI

1. Go to https://agentprovision.com
2. Log in with your account
3. Navigate to "Ask AI" (Chat)
4. Create a new chat session
5. Send a message
6. You should get an AI-powered response!

### Monitor Logs

For the first 24 hours, keep an eye on:

```bash
# On GCP VM
docker-compose logs -f api | grep -E 'ERROR|WARNING'
```

### Check API Usage

1. Go to https://console.anthropic.com
2. Check your API usage
3. Monitor costs

---

## Rollback Plan

If something goes wrong:

```bash
# On GCP VM
cd /path/to/agentprovision

# Remove the API key
vi apps/api/.env
# Delete or comment out the ANTHROPIC_API_KEY line

# Redeploy
./deploy.sh
```

Chat will fail again (expected), but rest of platform works.

---

## Next Steps After Successful Deployment

1. ✅ Verify all 22/22 tests pass
2. ✅ Test chat in production UI
3. ✅ Monitor for 24 hours
4. Consider:
   - Set up usage alerts in Anthropic dashboard
   - Add error monitoring (Sentry)
   - Review API costs weekly

---

## Quick Reference

### Files Modified
- `apps/api/.env` - Added ANTHROPIC_API_KEY
- `.gitignore` - Ensured .env files are not tracked

### Test Results
- **Local (before):** 21/21 pass (no homepage test)
- **Production (before):** 21/22 pass (chat failing)
- **Local (after):** 21/21 pass ✅
- **Production (expected):** 22/22 pass ✅

### Support
- Test results: `TEST_RESULTS_SUMMARY.md`
- Detailed findings: `E2E_TEST_FINDINGS.md`
- Deployment guide: `DEPLOYMENT_TESTING_README.md`
- Development guide: `CLAUDE.md`

---

**Ready to deploy!** 🚀

The API key is working perfectly in local testing. Production deployment should complete successfully with all tests passing.
