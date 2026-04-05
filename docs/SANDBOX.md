# Sandbox testing

`ads-copilot` ships with integration tests and a smoke script that exercise the connectors against **real sandbox APIs**. Unit tests cover all the branching logic; sandbox tests catch the things unit tests can't — schema drift, auth edge cases, report polling timing, agency-account header behavior.

Integration tests are **skipped by default** (they're marked with `@pytest.mark.integration` and excluded via `addopts` in `pyproject.toml`). Run them explicitly when you want to hit live endpoints.

---

## Yandex Direct sandbox

Yandex hosts a full sandbox at `api-sandbox.direct.yandex.com`. It mirrors the production API but uses fake data and never spends real money.

### 1. Get a sandbox token

1. Go to https://oauth.yandex.com/client/new and create an app.
2. Under **Platforms**, add a web service with callback URL `https://oauth.yandex.com/verification_code`.
3. Under **Permissions**, select **Yandex Direct API — использование API Яндекс.Директа**.
4. Save and note the **ClientID**.
5. Open `https://oauth.yandex.com/authorize?response_type=token&client_id=<YOUR_CLIENT_ID>` in your browser, approve the permissions, and copy the token from the URL fragment.

The same token works for both production and sandbox — the sandbox flag on the connector just swaps the base URL.

### 2. Populate sandbox with fake campaigns

Sandbox accounts start empty. Yandex provides a UI at https://direct.yandex.ru/sandbox to create campaigns, ad groups, keywords, and simulate impressions/clicks. Create at least one campaign with a few adgroups and run a simulation so reports return non-empty data.

### 3. Export env vars

```bash
export YANDEX_SANDBOX_TOKEN="y0_xxx..."
export YANDEX_SANDBOX_LOGIN="your-yandex-login"
```

### 4. Run the tests

```bash
pytest tests/integration/test_yandex_sandbox.py -v -m integration
```

Or use the smoke script for a human-readable walkthrough:

```bash
python scripts/smoke.py yandex
```

---

## Google Ads test account

Google doesn't have a separate sandbox URL — instead, you create a **test manager account** (MCC) that uses the production API but with pretend data. API calls go to `googleads.googleapis.com` but no budget is spent.

### 1. Create a test MCC

1. Sign in at https://ads.google.com/ with a Google account not already associated with a manager account.
2. Create a new manager account. During setup, tick **"This manager account will be used for test purposes only"**.
3. Under this test MCC, create a **test child account** (Settings → Sub-account settings → Create new account → Test account).
4. Note the 10-digit customer ID of the test child account.

### 2. Get a developer token

1. In your test MCC, go to **Tools & Settings → API Center**.
2. Accept the terms and note your **developer token**. Test-account tokens don't require Google approval.

### 3. Set up OAuth

Follow https://developers.google.com/google-ads/api/docs/oauth/cloud-project to create OAuth credentials (client ID + secret) and generate a refresh token. The official `google-ads` Python library ships a helper:

```bash
pip install google-ads
python -m google.ads.googleads.util.oauth2_installed_application_flow \
    --client_secrets_path=/path/to/client_secret.json \
    --additional_scopes=https://www.googleapis.com/auth/adwords
```

### 4. Write `google-ads.yaml`

```yaml
developer_token: "XXXXXXXXXXXXXXXXXXXXXX"
client_id: "xxx.apps.googleusercontent.com"
client_secret: "XXXXXXXXXXXXXX"
refresh_token: "1//xxx"
login_customer_id: "1234567890"   # test MCC id, no dashes
use_proto_plus: true
```

### 5. Populate the test account with data

Log in to the test MCC web UI and create a campaign, an ad group, a handful of keywords, and a text ad. You don't need to enable the campaign — structure queries work against paused campaigns too.

### 6. Export env vars

```bash
export GOOGLE_ADS_TEST_CUSTOMER_ID="1234567890"         # test child account
export GOOGLE_ADS_CREDENTIALS_FILE="./google-ads.yaml"
```

### 7. Run the tests

```bash
pytest tests/integration/test_google_sandbox.py -v -m integration
python scripts/smoke.py google
```

---

## Run everything

```bash
# All integration tests (will skip platforms whose env vars are unset)
pytest tests/integration/ -v -m integration

# Smoke both
python scripts/smoke.py both
```

---

## Troubleshooting

**Yandex report polling hangs:** sandbox sometimes takes 30–60s to generate reports. The connector retries up to 60 times with the `retryIn` hint from Yandex. If you're hitting the cap, check the sandbox UI — reports can fail silently if the campaign has no data at all.

**Google `AuthenticationError.NOT_ADS_USER`:** the login_customer_id in `google-ads.yaml` must be the MCC (manager) that the test child account lives under, not the child account itself.

**Google `USER_PERMISSION_DENIED`:** the OAuth-generating Google account needs Admin access to the test MCC.

**Yandex returns 429:** sandbox rate limits are lower than production. Back off and retry.
