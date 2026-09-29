<#
  Deploy Fenxi Proofer to Google Cloud Run from this folder (no GitHub needed).

  One-time setup (once per Google account):
    1. Install the Google Cloud CLI:      winget install Google.CloudSDK      (then open a NEW terminal)
    2. Log in:                            gcloud auth login
    3. Start the free trial at https://cloud.google.com/free  (a card is needed for verification; Google says you are not
       billed during the trial - read the terms on that page first).

  Then, from the repo root:
       .\deploy\cloudrun.ps1 -Project my-proofer-demo -Password "choose-a-password"

  Re-run the same command to deploy an update. The link is printed at the end.
#>
param(
    [Parameter(Mandatory = $true)][string]$Project,      # a Google Cloud project id (lowercase letters, digits, hyphens; must be globally unique)
    [Parameter(Mandatory = $true)][string]$Password,     # what testers must type when the browser asks (user name can be anything)
    [string]$Region = "us-central1",                     # a region that has Cloud Run's free monthly quota
    [string]$Service = "fenxi-proofer"
)
$ErrorActionPreference = "Stop"
if ($Password -match "[,=]") { throw "Use a password without commas or equals signs (they break the environment-variable list)." }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { throw "gcloud not found. Install it first: winget install Google.CloudSDK (then open a new terminal)." }

# create the project if it doesn't exist yet
$exists = gcloud projects list --filter="projectId=$Project" --format="value(projectId)"
if (-not $exists) {
    Write-Host "Creating project $Project ..."
    gcloud projects create $Project
}
gcloud config set project $Project | Out-Null

# the project must be linked to the billing account that carries the free trial
$billing = gcloud billing projects describe $Project --format="value(billingEnabled)"
if ($billing -ne "True") {
    Write-Host "`nThis project has no billing account linked yet. Link the free-trial billing account:"
    gcloud billing accounts list
    throw "Run:  gcloud billing projects link $Project --billing-account=ACCOUNT_ID   (ACCOUNT_ID from the list above), then run this script again."
}

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

# Settings that matter for this app:
#   --no-cpu-throttling  proofs run in the background after the page request; without this Cloud Run starves them of CPU
#   --max-instances 1    a proof's files live on one instance's disk; two instances would lose track of each other's jobs
#   --min-instances 0    scale to zero when nobody is using it (costs nothing while idle)
#   --memory 2Gi         the heaviest single proof peaks near 1 GB; files also live in memory on Cloud Run, hence a short TTL
$env = "APP_PASSWORD=$Password,ISOLATE_SESSIONS=1,JOB_TTL_HOURS=2,MAX_UPLOAD_MB=30,PROOFER_WORKERS=1"
gcloud run deploy $Service `
    --source . `
    --region $Region `
    --memory 2Gi --cpu 2 `
    --no-cpu-throttling `
    --min-instances 0 --max-instances 1 `
    --timeout 900 `
    --allow-unauthenticated `
    --set-env-vars $env

Write-Host "`nDone. The link is the 'Service URL' above. Testers enter any user name and the password you chose."
Write-Host "To stop everything and avoid any charge later:  gcloud run services delete $Service --region $Region"
