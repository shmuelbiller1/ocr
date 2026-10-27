<#
.SYNOPSIS
    Runs the packaged executable and reports what it did.

.DESCRIPTION
    The build needs three facts about the packaged program: its exit code,
    what it wrote to the standard output and what it wrote to the standard
    error.  Start-Process cannot report the exit code of a program that has
    already finished, so the program is started through cmd, which waits for
    it and returns its exit code.

    Every fact is written to a file, so that a build that fails can still
    publish them.
#>
param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string]$Report,
    [Parameter(Mandatory = $true)][string]$StdOut,
    [Parameter(Mandatory = $true)][string]$StdErr,
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = 'Continue'
$root = (Get-Location).Path
$exePath = (Resolve-Path $Exe).Path
$outPath = Join-Path $root $StdOut
$errPath = Join-Path $root $StdErr
$exitPath = "$outPath.exit.txt"

$job = Start-Job -ScriptBlock {
    param($root, $exe, $report, $out, $err)
    Set-Location $root
    cmd /c "`"$exe`" --selftest --selftest-report `"$report`" > `"$out`" 2> `"$err`""
    $LASTEXITCODE
} -ArgumentList $root, $exePath, $Report, $outPath, $errPath

$done = Wait-Job $job -Timeout $TimeoutSeconds
if (-not $done) {
    Stop-Job $job -ErrorAction SilentlyContinue
    Remove-Job $job -Force -ErrorAction SilentlyContinue
    @("exit code: timeout", "exe: $exePath") | Out-File -Encoding utf8 $exitPath
    Write-Output "::error title=Self-test::the packaged executable did not finish within $TimeoutSeconds seconds"
    exit 1
}

$code = Receive-Job $job
Remove-Job $job -Force -ErrorAction SilentlyContinue

@("exit code: $code", "exe: $exePath", "exe size: $((Get-Item $exePath).Length) bytes") |
    Out-File -Encoding utf8 $exitPath
Write-Host "exit code: $code"

if (Test-Path $outPath) {
    Get-Content $outPath | ForEach-Object { Write-Host "out: $_" }
}
if (Test-Path $errPath) {
    Get-Content $errPath | ForEach-Object { Write-Output "::error title=Self-test::$_" }
}

exit $code
