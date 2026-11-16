<#
Maps a NAS share to a drive letter as soon as the NAS answers, using the password saved in Windows
Credential Manager (cmdkey). Meant to run at logon from Task Scheduler: see the README, "NAS setup".

    powershell -ExecutionPolicy Bypass -File connect-nas.ps1 -Drive Y: -Share \\NAS-NAME\Photos

A log of the last run is written next to the script (connect-nas.log).
#>
param(
    [Parameter(Mandatory)] [string] $Drive,
    [Parameter(Mandatory)] [string] $Share,
    [int] $TimeoutSeconds = 120
)

$nas = ($Share -replace '^\\\\', '').Split('\')[0]
$log = Join-Path $PSScriptRoot 'connect-nas.log'
function Write-Log($text) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $text" | Add-Content -LiteralPath $log -Encoding utf8 }
"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') start: $Drive -> $Share" | Set-Content -LiteralPath $log -Encoding utf8

# Wait for the NAS to answer on the file-sharing port (445)
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    if (Test-NetConnection $nas -Port 445 -InformationLevel Quiet -WarningAction SilentlyContinue) { break }
    Start-Sleep -Seconds 3
}

for ($try = 1; $try -le 5; $try++) {
    # Close the drive and any other connection to the NAS first: a connection left open with another
    # user name makes Windows refuse the new one (error 1219, "multiple connections ... not allowed").
    net use $Drive /delete /y 2>&1 | Out-Null
    net use | Select-String -Pattern "\\\\$([regex]::Escape($nas))\\[^\s]+" -AllMatches |
        ForEach-Object { $_.Matches.Value } | Sort-Object -Unique |
        ForEach-Object { net use $_ /delete /y 2>&1 | Out-Null }

    $result = net use $Drive $Share /persistent:no 2>&1
    Write-Log "try ${try}: $($result -join ' ')"
    if (Test-Path "$Drive\") { break }
    Start-Sleep -Seconds 10
}
Write-Log "drive reachable: $(Test-Path "$Drive\")"
