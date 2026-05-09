# Deploying to Azure

The daily scrape runs as an **Azure Container Apps Job** (cron-triggered, scales to zero).
The Flask dashboard runs as a **Container App** with public HTTPS ingress.
Persistent state lives in **Azure Cosmos DB** (NoSQL Core API, serverless).

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Resource Group: <prefix>-rg                                    │
│                                                                 │
│  ┌──────────────┐   pulls     ┌────────────────────────────┐    │
│  │ ACR          │ ◄────────── │ Container Apps Environment │    │
│  └──────────────┘             │  ┌──────────────────────┐  │    │
│                               │  │ Web App (public 443) │  │    │
│  ┌──────────────┐             │  └──────────────────────┘  │    │
│  │ Cosmos DB    │ ◄──────┐    │  ┌──────────────────────┐  │    │
│  │ (serverless) │        └──── ── │ Job (cron daily)     │  │    │
│  └──────────────┘             │  └──────────────────────┘  │    │
│         ▲                     └────────────────────────────┘    │
│         │  AAD data-plane RBAC                                  │
│  ┌──────┴───────┐                                               │
│  │ Managed Id.  │ ── AcrPull on ACR                             │
│  └──────────────┘                                               │
└─────────────────────────────────────────────────────────────────┘
```

Both the Web App and the Job run **the same image** (`Dockerfile`). The Job overrides the command to `python runner_job.py`; the Web App runs `gunicorn ... app:app`.

## Prerequisites

- Azure CLI ≥ 2.60 (`az --version`)
- An Azure subscription you can deploy to (`az login`)
- PowerShell 7+ (the deploy script is a `.ps1`; you can also call the same `az` commands by hand)
- **No local Docker required** — the image is built inside ACR via `az acr build`.

## One-shot deployment

```powershell
# From the repo root
az login                            # if not already
az account set --subscription "<your-subscription-id-or-name>"

./deploy.ps1 `
    -Location westeurope `
    -Prefix lkdscraper `
    -CronExpression "0 6 * * *" `
    -TriggerJob                     # optional: kick off one immediate run
```

The script:
1. Validates the CLI + subscription, registers required RPs.
2. Creates the resource group `<prefix>-rg`.
3. Deploys [`infra/main.bicep`](infra/main.bicep) (ACR, Cosmos, Container Apps env/web/job, managed identity + role assignments).
4. Builds the Docker image inside ACR (`az acr build`) with the supplied `-ImageTag`.
5. Updates both the Web App and the Job to the new image tag.
6. (Optional) Calls `az containerapp job start` so you can watch logs immediately.

## Configuration

All runtime settings (keywords, locations, schedule **display**, max pages, etc.) live in the Cosmos `settings` container and are editable from the web UI. The actual cron schedule for the daily Job is set on **the Container Apps Job**, not in the DB — to change it, redeploy with a different `-CronExpression`, or update it in-place:

```powershell
az containerapp job update -n <prefix>-job -g <prefix>-rg `
    --cron-expression "30 5 * * *"
```

### Key environment variables (set automatically by Bicep)

| Variable           | Where set | Purpose                                                     |
|--------------------|-----------|-------------------------------------------------------------|
| `COSMOS_ENDPOINT`  | both      | Cosmos account URL                                          |
| `COSMOS_DB`        | both      | Database name (`linkedinscraper`)                           |
| `AZURE_CLIENT_ID`  | both      | Managed identity client id (used by `DefaultAzureCredential`) |
| `DISABLE_SCHEDULER`| web only  | Stops the in-process APScheduler — Azure owns the cron      |
| `CHROME_BIN`       | image     | `/usr/bin/chromium`                                         |
| `CHROMEDRIVER`     | image     | `/usr/bin/chromedriver`                                     |

## Operating

| Action                         | Command                                                                                  |
|--------------------------------|------------------------------------------------------------------------------------------|
| Trigger an ad-hoc scrape       | `az containerapp job start -n <prefix>-job -g <prefix>-rg`                               |
| List recent job executions     | `az containerapp job execution list -n <prefix>-job -g <prefix>-rg --output table`       |
| Stream web app logs            | `az containerapp logs show -n <prefix>-web -g <prefix>-rg --follow`                      |
| Stream a specific job log      | `az containerapp job logs show -n <prefix>-job -g <prefix>-rg --container scraper --follow` |
| Tear everything down           | `az group delete -n <prefix>-rg --yes --no-wait`                                         |

## Local dev against Cloud Cosmos

```powershell
$env:COSMOS_ENDPOINT = "https://<cosmos>.documents.azure.com:443/"
$env:COSMOS_DB        = "linkedinscraper"
# Auth via DefaultAzureCredential (uses your `az login`)
python app.py
```

If you want to skip Cosmos locally and use TinyDB, simply leave `COSMOS_ENDPOINT` unset — the backend selector falls back to the file-based store.

## Cost estimate (light usage)

- **Cosmos serverless**: pay-per-RU; for ≪1k jobs and a daily scrape, expect cents/month.
- **Container Apps Job**: scales to zero; you pay only for the few minutes it runs each day.
- **Container App (web)**: 1 replica × 0.5 vCPU / 1 GiB ≈ a few dollars/month if always-on (or scale `minReplicas` to 0 to scale to zero with a cold-start penalty).
- **ACR Basic**: ~$5/month.
- **Log Analytics**: pennies for low log volume.

Order of magnitude: **single-digit USD/month** for personal use.
