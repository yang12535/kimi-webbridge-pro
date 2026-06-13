[CmdletBinding()]
param(
    [string] $Session,

    [string] $OutputPath,

    [ValidateSet("png", "jpeg")]
    [string] $Format = "png",

    [ValidateRange(0, 100)]
    [int] $Quality = 80,

    [string] $Selector,

    [string] $DaemonUrl = "http://127.0.0.1:10086",

    [ValidateRange(1, 300)]
    [int] $TimeoutSec = 30
)

# Build only the options supported by the selected image format.
$actionArgs = [ordered]@{ format = $Format }
if ($Format -eq "jpeg") {
    $actionArgs.quality = $Quality
}
if ($Selector) {
    $actionArgs.selector = $Selector
}

$body = [ordered]@{
    action = "screenshot"
    args = $actionArgs
}
if ($Session) {
    $body.session = $Session
}

$json = $body | ConvertTo-Json -Depth 20 -Compress
$response = Invoke-RestMethod `
    -Method Post `
    -Uri "$DaemonUrl/command" `
    -ContentType "application/json; charset=utf-8" `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($json)) `
    -TimeoutSec $TimeoutSec

if ($null -ne $response.ok -and -not $response.ok) {
    $message = if ($response.error) { $response.error } else { "Kimi WebBridge screenshot failed." }
    throw $message
}

# New daemons save screenshots locally; older ones return base64 image data.
if ($response.data.path) {
    $sourcePath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath(
        [string] $response.data.path
    )
    if (-not (Test-Path -LiteralPath $sourcePath)) {
        throw "Kimi WebBridge returned a screenshot path that does not exist: $sourcePath"
    }

    if (-not $OutputPath) {
        $sourcePath
        return
    }
}

if (-not $OutputPath) {
    $outputDirectory = Join-Path $env:TEMP "kimi-webbridge-screenshots"
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
    $extension = if ($Format -eq "jpeg") { "jpg" } else { "png" }
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
    $OutputPath = Join-Path $outputDirectory "$timestamp.$extension"
}

$resolvedOutputPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)
$parentDirectory = Split-Path -Parent $resolvedOutputPath
if ($parentDirectory) {
    New-Item -ItemType Directory -Path $parentDirectory -Force | Out-Null
}

# Normalize both protocol versions to one local output path.
if ($sourcePath) {
    Copy-Item -LiteralPath $sourcePath -Destination $resolvedOutputPath -Force
}
else {
    $encodedImage = $response.data.data
    if (-not $encodedImage) {
        throw "Kimi WebBridge returned neither a screenshot path nor image data."
    }

    [System.IO.File]::WriteAllBytes(
        $resolvedOutputPath,
        [System.Convert]::FromBase64String($encodedImage)
    )
}

$resolvedOutputPath
