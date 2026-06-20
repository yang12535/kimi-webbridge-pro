[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $Action,

    [object] $ActionArgs = @{},

    [string] $ArgsFile,

    [string] $Session,

    [string] $DaemonUrl = "http://127.0.0.1:10086",

    [ValidateRange(1, 300)]
    [int] $TimeoutSec = 30,

    [switch] $DryRun,

    [switch] $Force
)

if ($Action -eq "close_session" -and -not $Force) {
    throw "Refusing close_session without -Force; verify every tab is task-owned."
}
if ($Action -eq "close_session" -and $Force) {
    Write-Warning "Forced close_session can close every tab attached to this session. Run list_tabs first and verify they are task-owned."
}

if ($ArgsFile) {
    $hasInlineArgs = $false
    if ($null -ne $ActionArgs) {
        if ($ActionArgs -is [System.Collections.IDictionary]) {
            $hasInlineArgs = $ActionArgs.Count -gt 0
        }
        else {
            $hasInlineArgs = $true
        }
    }
    if ($hasInlineArgs) {
        throw "Use either -ActionArgs or -ArgsFile, not both."
    }
    if (-not (Test-Path -LiteralPath $ArgsFile -PathType Leaf)) {
        throw "Arguments file not found: $ArgsFile"
    }
    $argsJson = Get-Content -LiteralPath $ArgsFile -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($argsJson)) {
        throw "Arguments file is empty: $ArgsFile"
    }
    try {
        $ActionArgs = $argsJson | ConvertFrom-Json
    }
    catch {
        throw "Arguments file must contain valid UTF-8 JSON: $($_.Exception.Message)"
    }
    if ($null -eq $ActionArgs -or $ActionArgs -is [array] -or $ActionArgs -is [string] -or $ActionArgs -is [ValueType]) {
        throw "Arguments file must contain a JSON object."
    }
}

# Keep the daemon envelope consistent across every action.
$body = [ordered]@{
    action = $Action
    args = $ActionArgs
}

if ($Session) {
    $body.session = $Session
}

# Send explicit UTF-8 bytes so non-ASCII input survives Windows PowerShell.
$json = $body | ConvertTo-Json -Depth 20 -Compress
if ($DryRun) {
    $json
    return
}

$response = Invoke-RestMethod `
    -Method Post `
    -Uri "$DaemonUrl/command" `
    -ContentType "application/json; charset=utf-8" `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($json)) `
    -TimeoutSec $TimeoutSec

if ($null -ne $response.ok -and -not $response.ok) {
    $message = if ($response.error) { $response.error } else { "Kimi WebBridge command failed." }
    throw $message
}

$response | ConvertTo-Json -Depth 50 -Compress
