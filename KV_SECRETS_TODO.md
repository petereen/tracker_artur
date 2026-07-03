# KV Secrets TODO — tracker-artur

FastAPI backend + Vite/React frontend. Backend keys discovered by scanning Python source (Pydantic Settings + os.getenv).

> All secrets for this project live in `kv-bronxtc-dev`. No separate prod KV.

**Total keys needed: 8** (all currently placeholders with value `__TODO_FILL_ME__`)

## scope: `backend` (8 keys)

| KV secret name | env var (in .env) |
| --- | --- |
| `tracker-artur--backend--ACCESS-TOKEN-EXPIRE-HOURS` | `ACCESS_TOKEN_EXPIRE_HOURS` |
| `tracker-artur--backend--ADMIN-EMAIL` | `ADMIN_EMAIL` |
| `tracker-artur--backend--ADMIN-PASSWORD` | `ADMIN_PASSWORD` |
| `tracker-artur--backend--BOT-TOKEN` | `BOT_TOKEN` |
| `tracker-artur--backend--DATABASE-URL` | `DATABASE_URL` |
| `tracker-artur--backend--MANAGER-TG-ID` | `MANAGER_TG_ID` |
| `tracker-artur--backend--SECRET-KEY` | `SECRET_KEY` |
| `tracker-artur--backend--SYNC-DATABASE-URL` | `SYNC_DATABASE_URL` |

## How to fill these in

```bash
az keyvault secret set --vault-name kv-bronxtc-dev \
  --name <kv-secret-name-from-table> \
  --value '<the-actual-value>' \
  --tags project=tracker-artur scope=<scope> status=ok
```

Then to populate the local `.env` file from KV:

```bash
./scripts/kv-pull.sh                # all scopes
./scripts/kv-pull.sh <scope>        # one scope
./scripts/kv-pull.sh --list         # show available scopes
```

## Where to find the actual values

- **GitHub Actions secrets** of this repo (Settings → Secrets and variables → Actions).
- **Local backup** (Bitwarden / 1Password / Apple Keychain).
- **Re-issue** — for fresh API keys: OpenAI, Anthropic, Stripe, Google Cloud, Telegram BotFather, etc.

