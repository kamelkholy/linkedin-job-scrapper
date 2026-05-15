#requires -Version 5.1
<#
.SYNOPSIS
    Deploys the LinkedIn Scraper to Azure (Container Apps + Cosmos DB).

.DESCRIPTION
    Idempotent end-to-end deployment:
      1. Verifies az CLI + login + subscription
      2. Creates the resource group
      3. Provisions infrastructure via Bicep (ACR, Cosmos, Container Apps Env, Web App, Job)
      4. Builds the Docker image inside ACR (no local Docker required)
      5. Updates the Web App + Job to point to the new image
      6. Triggers the daily Job once so you can verify it works

.PARAMETER SubscriptionId
    Azure subscription ID. Optional — uses current `az account` if omitted.

.PARAMETER Location
    Azure region. Default: westeurope.

.PARAMETER Prefix
    Short prefix for resource names (3-12 lowercase alphanumeric). Default: lkdscraper.

.PARAMETER ResourceGroup
    Resource group name. Default: <prefix>-rg.

.PARAMETER ImageTag
    Container image tag. Default: timestamp like 20260508-1530.

.PARAMETER CronExpression
    UTC cron for the daily scrape (5-field). Default: '0 6 * * *' (06:00 UTC daily).

.PARAMETER SkipBuild
    Skip the ACR image build step (useful when only updating infra).

.PARAMETER TriggerJob
    After deploy, kick off the daily scrape Job once so you can watch logs.

.PARAMETER AuthUsername
    Username for HTTP Basic Auth on the web UI. Default: admin. Ignored when AuthPassword is empty.

.PARAMETER AuthPassword
    Password for HTTP Basic Auth on the web UI (stored as a Container Apps secret).
    If omitted, auth is left disabled. Pass an empty string to keep current value on redeploy.

.EXAMPLE
    ./deploy.ps1 -Location westeurope -Prefix lkdscraper -TriggerJob
#>
[CmdletBinding()]
param(
    [string]$SubscriptionId,
    [string]$Location = 'westeurope',
    [ValidateLength(3, 12)]
    [string]$Prefix = 'lkdscraper',
    [string]$ResourceGroup,
    [string]$ImageTag = (Get-Date -Format 'yyyyMMdd-HHmm'),
    [string]$CronExpression = '0 6 * * *',
    [switch]$SkipBuild,
    [switch]$TriggerJob,
    [string]$AuthUsername = 'admin',
    [string]$AuthPassword
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Force the Azure CLI's Python child process to emit UTF-8 — otherwise
# `az acr build` log streaming crashes on Windows (cp1252) when ACR sends
# unicode characters like '→' in build output.
$env:PYTHONIOENCODING = 'utf-8'

if (-not $ResourceGroup) { $ResourceGroup = "$Prefix-rg" }

function Write-Step($msg) {
    Write-Host ''
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Invoke-Az {
    param([Parameter(ValueFromRemainingArguments)] $Args)
    $output = az @Args
    if ($LASTEXITCODE -ne 0) {
        throw "az $($Args -join ' ') failed (exit $LASTEXITCODE)"
    }
    return $output
}

# ── Pre-flight ──────────────────────────────────────────────────────────
Write-Step "Verifying Azure CLI"
$null = Get-Command az -ErrorAction Stop
$cliVer = (az version --output json | ConvertFrom-Json).'azure-cli'
Write-Host "Azure CLI version: $cliVer"

# Make sure the containerapp extension is installed/up to date.
$null = az extension add --name containerapp --upgrade --only-show-errors 2>&1
$null = az provider register --namespace Microsoft.App --only-show-errors 2>&1
$null = az provider register --namespace Microsoft.OperationalInsights --only-show-errors 2>&1
$null = az provider register --namespace Microsoft.DocumentDB --only-show-errors 2>&1
$null = az provider register --namespace Microsoft.ContainerRegistry --only-show-errors 2>&1

Write-Step "Verifying login"
try {
    $account = az account show --output json 2>$null | ConvertFrom-Json
} catch { $account = $null }
if (-not $account) {
    throw "You are not logged in. Run: az login"
}

if ($SubscriptionId -and ($account.id -ne $SubscriptionId)) {
    Invoke-Az account set --subscription $SubscriptionId | Out-Null
    $account = az account show --output json | ConvertFrom-Json
}
Write-Host ("Subscription : {0} ({1})" -f $account.name, $account.id)
Write-Host ("Tenant       : {0}" -f $account.tenantId)
Write-Host ("Location     : $Location")
Write-Host ("ResourceGroup: $ResourceGroup")
Write-Host ("Prefix       : $Prefix")
Write-Host ("Image tag    : $ImageTag")
Write-Host ("Cron         : $CronExpression")

# ── Resource group ──────────────────────────────────────────────────────
Write-Step "Ensuring resource group '$ResourceGroup' in $Location"
$existingRg = az group show --name $ResourceGroup --query location -o tsv 2>$null
if ($existingRg) {
    if ($existingRg -ne $Location) {
        Write-Host "Resource group already exists in '$existingRg' (resources can still be deployed to '$Location')." -ForegroundColor Yellow
    }
} else {
    Invoke-Az group create --name $ResourceGroup --location $Location --output none
}

# ── ACR (created before Bicep so the image build can target it) ─────────
# Derive a deterministic ACR name from the RG id (lowercase alphanumeric, ≤50 chars).
$rgId = (az group show -n $ResourceGroup --query id -o tsv)
$sha  = [System.Security.Cryptography.SHA1]::Create()
$hash = [System.BitConverter]::ToString($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($rgId))).Replace('-', '').ToLower()
$acrName = ('{0}acr{1}' -f $Prefix.ToLower(), $hash.Substring(0, 6))
if ($acrName.Length -gt 50) { $acrName = $acrName.Substring(0, 50) }

Write-Step "Ensuring ACR '$acrName'"
Invoke-Az acr create `
    --name $acrName `
    --resource-group $ResourceGroup `
    --location $Location `
    --sku Basic `
    --admin-enabled false `
    --output none
$acrLoginServer = (az acr show -n $acrName -g $ResourceGroup --query loginServer -o tsv)
Write-Host "ACR login server: $acrLoginServer"

# ── Build image in ACR ──────────────────────────────────────────────────
if (-not $SkipBuild) {
    Write-Step "Building image in ACR (this can take 3-6 min)"
    # --no-logs avoids streaming output (which has hit a Windows CLI unicode
    # bug); we poll the run instead.
    Invoke-Az acr build `
        --registry $acrName `
        --image "linkedin-scraper:$ImageTag" `
        --image "linkedin-scraper:latest" `
        --file Dockerfile `
        --no-logs `
        . | Out-Null
    Write-Host ("Image pushed: $acrLoginServer/linkedin-scraper:$ImageTag")
} else {
    Write-Host "Skipping image build (--SkipBuild)"
}

# ── Bicep deploy (references the existing ACR + freshly built image) ────
Write-Step "Deploying infrastructure (Bicep)"
$bicepPath = Join-Path $PSScriptRoot 'infra/main.bicep'
$deploymentName = "lkd-deploy-$ImageTag"

Invoke-Az deployment group create `
    --resource-group $ResourceGroup `
    --name $deploymentName `
    --template-file $bicepPath `
    --parameters prefix=$Prefix location=$Location imageTag=$ImageTag cronExpression="$CronExpression" acrName=$acrName authUsername=$AuthUsername authPassword=$AuthPassword `
    --output none

$outputs = (az deployment group show --resource-group $ResourceGroup --name $deploymentName --query properties.outputs --output json) | ConvertFrom-Json
$webUrl         = $outputs.webUrl.value
$jobName        = $outputs.jobName.value
$webAppName     = $outputs.webAppName.value

Write-Host ("Web URL      : $webUrl")
Write-Host ("Job          : $jobName")

# ── Optional: trigger one immediate Job run ─────────────────────────────
if ($TriggerJob) {
    Write-Step "Triggering one-off Job execution"
    $exec = (az containerapp job start --name $jobName --resource-group $ResourceGroup --output json) | ConvertFrom-Json
    Write-Host ("Execution started: $($exec.name)")
    Write-Host ("Tail logs with:")
    Write-Host ("  az containerapp job execution show -n $jobName -g $ResourceGroup --job-execution-name $($exec.name)")
}

Write-Step "Done"
Write-Host "Web UI       : $webUrl"
Write-Host "Cosmos       : $($outputs.cosmosEndpoint.value)"
Write-Host "Daily cron   : $CronExpression (UTC)"
if ($AuthPassword) {
    Write-Host "Auth         : enabled (user: $AuthUsername)"
} else {
    Write-Host "Auth         : DISABLED (pass -AuthPassword '...' to enable Basic Auth)"
}
Write-Host ""
Write-Host "Useful follow-ups:"
Write-Host "  az containerapp job start             -n $jobName -g $ResourceGroup"
Write-Host "  az containerapp job execution list    -n $jobName -g $ResourceGroup --output table"
Write-Host "  az containerapp logs show             -n $webAppName -g $ResourceGroup --follow"
