[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $Action,

    [hashtable] $ActionArgs = @{},

    [string] $Session,

    [string] $DaemonUrl = "http://127.0.0.1:10086",

    [ValidateRange(1, 300)]
    [int] $TimeoutSec = 30
)

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
