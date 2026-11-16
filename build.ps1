# Crea l'installer MSI di CleanCraftNas in dist\. Uso:  powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path .venv\Scripts\python.exe)) {
    py -3.13 -m venv .venv
    .venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements-build.txt
}
if (-not (Test-Path assets\icon.ico)) { .venv\Scripts\python.exe tools\make_icon.py }

Remove-Item build, dist -Recurse -Force -ErrorAction SilentlyContinue
.venv\Scripts\python.exe setup.py bdist_msi
if ($LASTEXITCODE -ne 0) { throw "build failed" }
Get-ChildItem dist\*.msi
