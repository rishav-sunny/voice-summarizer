@echo off
setlocal EnableDelayedExpansion

REM ---------------------------------------------
REM Voice Summarizer - K3s Deployment (Windows CMD)
REM Requires: kubectl; Rancher Desktop (nerdctl) or Docker
REM Uses secrets from backend\.env and applies deploy\k8s.yaml
REM ---------------------------------------------

set NAMESPACE=voice-summarizer
set ENV_FILE=backend\.env
set K8S_MANIFEST=deploy\k8s.yaml
set BACKEND_IMAGE=voice-summarizer-backend:local
set FRONTEND_IMAGE=voice-summarizer-frontend:local

echo [1/6] Checking prerequisites...
where kubectl >nul 2>&1
if errorlevel 1 (
  echo ERROR: kubectl not found in PATH. Install kubectl and try again.
  exit /b 1
)

where nerdctl >nul 2>&1
if %ERRORLEVEL%==0 (
  set BUILDER=nerdctl
  echo Using nerdctl to build images (recommended for Rancher Desktop/K3s).
) else (
  where docker >nul 2>&1
  if errorlevel 1 (
    echo ERROR: Neither nerdctl nor docker found in PATH.
    echo Install Rancher Desktop (nerdctl) or Docker, then retry.
    exit /b 1
  )
  set BUILDER=docker
  echo Using docker to build images.
  echo NOTE: If your Kubernetes uses containerd (K3s/Rancher Desktop), docker-built images won't be visible to the cluster.
  echo       Prefer nerdctl or push to a registry and update images in the manifest.
)

echo [2/6] Validating env file at "%ENV_FILE%"...
if not exist "%ENV_FILE%" (
  echo ERROR: %ENV_FILE% not found. Create it with DEEPGRAM_API_KEY, GEMINI_API_KEY, SUMMARIZER_MODEL.
  exit /b 1
)

echo [3/6] Building container images with %BUILDER% ...
%BUILDER% build -t %BACKEND_IMAGE% backend
if errorlevel 1 (
  echo ERROR: Backend image build failed.
  exit /b 1
)
%BUILDER% build -t %FRONTEND_IMAGE% frontend
if errorlevel 1 (
  echo ERROR: Frontend image build failed.
  exit /b 1
)

echo [4/6] Ensuring namespace "%NAMESPACE%" exists...
kubectl get ns %NAMESPACE% >nul 2>&1 || kubectl create ns %NAMESPACE%
if errorlevel 1 (
  echo ERROR: Failed to create or access namespace %NAMESPACE%.
  exit /b 1
)

echo [5/6] Applying/Updating secret "app-secrets" from %ENV_FILE% ...
kubectl -n %NAMESPACE% create secret generic app-secrets --from-env-file="%ENV_FILE%" --dry-run=client -o yaml | kubectl apply -f -
if errorlevel 1 (
  echo ERROR: Failed to create/apply secret app-secrets.
  exit /b 1
)

echo [6/6] Applying Kubernetes manifests: %K8S_MANIFEST%
kubectl apply -f "%K8S_MANIFEST%"
if errorlevel 1 (
  echo ERROR: kubectl apply failed. Check your manifest and context.
  exit /b 1
)

echo.
echo Success: Manifests applied. Verify rollout and access the app:
echo   - Check pods:  kubectl -n %NAMESPACE% get pods -w
echo   - Frontend NodePort (expected): http://localhost:30080
echo     If 30080 differs, run: kubectl -n %NAMESPACE% get svc -o wide

echo.
echo Troubleshooting tips:
echo   - If images can't be pulled, ensure the manifest uses %BACKEND_IMAGE% and %FRONTEND_IMAGE%.
echo   - On K3s/containerd, prefer nerdctl to build images visible to the cluster.
echo   - Ensure your current kubectl context points to Rancher Desktop/K3s (kubectl config current-context).

endlocal
exit /b 0
