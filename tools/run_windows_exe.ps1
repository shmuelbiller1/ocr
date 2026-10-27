<#
.SYNOPSIS
    Runs the packaged executable and reports what it did.

.DESCRIPTION
    The build needs three facts about the packaged program: its exit code,
    what it wrote to the standard output and what it wrote to the
    standard error.

    The program is started with Start-Process, which takes the path of
    the program and the paths of the files as separate values.  That way
    a path with a space in it is not broken by the quoting rules of the
    command line.  If Start-Process is not available, the program is
    started through cmd, which waits for it and returns its exit code.

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

# A packaged program starts in the folder it was unpacked into, so a
# relative path would end up in a temporary folder.  The report is
# therefore always given as an absolute path.
$reportPath = if ([System.IO.Path]::IsPathRooted($Report)) {
    $Report
} else {
    Join-Path $root $Report
}

$job = Start-Job -ScriptBlock {
    param($root, $exe, $report, $out, $err)
    Set-Location $root
    try {
        # The path of the report is given in quotes, because
        # Start-Process puts the values of the list together without
        # quoting them.
        $process = Start-Process -FilePath $exe `
            -ArgumentList @('--selftest', '--selftest-report', ('"' + $report + '"')) `
            -RedirectStandardOutput $out `
            -RedirectStandardError $err `
            -NoNewWindow `
            -Wait `
            -PassThru `
            -ErrorAction Stop
        $process.ExitCode
    } catch {
        cmd /c "`"$exe`" --selftest --selftest-report `"$report`" > `"$out`" 2> `"$err`""
        $LASTEXITCODE
    }
} -ArgumentList $root, $exePath, $reportPath, $outPath, $errPath

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
if ($null -eq $code) {
    # The program did not report an exit code, so the build failed.
    $code = 1
}

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
