# Sandbox testing

`ads-copilot` ships with integration tests and a smoke script that exercise the connectors against **real sandbox APIs**. Unit tests cover all the branching logic; sandbox tests catch the things unit tests can't — schema drift, auth edge cases, report polling timing, agency-account header behavior.

Integration tests are **skipped by default** (they're marked with `@pytest.mark.integration` and excluded via `addopts` in `pyproject.toml`). Run them explicitly when you want to hit live endpoints.

---

## Yandex Direct sandbox

Yandex hosts a full sandbox at `api-sandbox.direct.yandex.com`. It mirrors the production API, uses fake data, and never spends real money. The catch is **getting a sandbox token is non-trivial** for anyone outside Russia.

### Access restrictions (read this first)

As of 2024, registering a new OAuth app with the `direct:api` scope on Yandex is gated behind:

- **yandex.ru**: requires Gosuslugi (Russian government ID) verification — effectively only accessible to Russian citizens / legal entities.
- **yandex.com**: the `direct:api` scope is not offered at all in the permission picker for non-CIS accounts.

If you're outside Russia, there are two realistic paths:

1. **Use a production token from an agency/client account you already manage.** The connector supports agency mode (`client_login` header) out of the box. Set `sandbox: false` in the config and point tests at a real account — preferably a low-traffic one where read-only GAQL-equivalent queries are safe. Skip the `add_negative_keywords` dry-run test just to be safe.
2. **Defer sandbox testing to first real engagement.** The connector is unit-tested at the parsing layer (TSV BOM, minor-unit arithmetic, null handling, report-polling state machine). The remaining failure modes are predictable — schema drift, auth edge cases, rate limits — and surface loudly at first real use. This is the path taken in this repo until access is resolved.

### If you do have access

1. Register an OAuth app at https://oauth.yandex.ru/client/new with the `direct:api` scope and callback URL `https://oauth.yandex.ru/verification_code`.
2. Open `https://oauth.yandex.ru/authorize?response_type=token&client_id=<YOUR_CLIENT_ID>`, approve, and copy the token from the URL fragment.
3. Populate sandbox with fake data at https://direct.yandex.ru/sandbox — log in with the same account, create one campaign with a couple of adgroups and keywords, and run the simulation so reports return non-empty data.
4. Export env vars and run the tests:
   ```bash
   export YANDEX_SANDBOX_TOKEN="y0_xxx..."
   export YANDEX_SANDBOX_LOGIN="your-yandex-login"
   pytest tests/integration/test_yandex_sandbox.py -v -m integration
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

**Yandex `Unknown client with such client_id`** on the authorize URL: the client ID in the URL doesn't match a real registered app. You need to create your own OAuth app — there are no shared public client IDs for Direct API.

**Yandex OAuth scope picker doesn't list Direct API:** on `yandex.com`, the scope isn't available to non-CIS accounts at all. On `yandex.ru`, creating a new app with Direct permissions requires Gosuslugi verification. See the "Access restrictions" section above.

**Yandex report polling hangs:** reports sometimes take 30–60s to generate. The connector retries up to 60 times with the `retryIn` hint from Yandex. If you're hitting the cap, check the web UI — reports can fail silently if the campaign has no data at all.

**Yandex returns 429:** sandbox rate limits are lower than production. Back off and retry.

**Google `AuthenticationError.NOT_ADS_USER`:** the `login_customer_id` in `google-ads.yaml` must be the MCC (manager) that the test child account lives under, not the child account itself.

**Google `USER_PERMISSION_DENIED`:** the OAuth-generating Google account needs Admin access to the test MCC.
