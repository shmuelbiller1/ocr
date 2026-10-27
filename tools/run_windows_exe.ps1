<#
.SYNOPSIS
    Runs the packaged executable and reports what it did.

.DESCRIPTION
    The build needs three facts about the packaged program: its exit code,
    what it wrote to the standard output and what it wrote to the
    standard error.

    The program is started with Start-Process, which takes the path of the
    program and the paths of the files as separate values.  That way
    a path with a space in it is not broken by the quoting rules of the
    command line.  If Start-Process is not available, the program is
    started through cmd, which waits for it and returns its exit code.

    The wait has a limit, and a program that does not stop in time is
    stopped, so that a build cannot hang for ever.  Every fact is
    written to a file, so that a build that fails can still publish them.
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

function Write-ExitFile([string]$code, [string]$note) {
    @("exit code: $code", "exe: $exePath", $note) |
        Out-File -Encoding utf8 $exitPath
}

function Stop-ProcessTree($process) {
    # The program may have started processes of its own.  They have to
    # be stopped as well, or they keep the files of the build open after
    # this script has ended.
    if ($null -eq $process) { return }
    try {
        # taskkill with /T stops the children of the program as well.
        & taskkill.exe /PID $process.Id /T /F 2>&1 | Out-Null
    } catch { }
    try { $process.Kill() } catch { }
}

$code = $null
try {
    # The path of the report is given in quotes, because Start-Process
    # puts the values of the list together without quoting them.
    $process = Start-Process -FilePath $exePath `
        -ArgumentList @('--selftest', '--selftest-report', ('"' + $reportPath + '"')) `
        -RedirectStandardOutput $outPath `
        -RedirectStandardError $errPath `
        -NoNewWindow `
        -PassThru `
        -ErrorAction Stop
    # The wait has a limit: a program that does not stop in time is
    # stopped, and the build says that it did not stop.
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        Stop-ProcessTree $process
        Write-ExitFile 'timeout' "the program did not stop within $TimeoutSeconds seconds"
        Write-Output "::error title=Self-test::the packaged executable did not finish within $TimeoutSeconds seconds"
        exit 1
    }
    $code = $process.ExitCode
} catch {
    Write-Output "::error title=Self-test::Start-Process failed: $_"
    # The program is started through cmd, which waits for it and gives
    # back its exit code.  It is started with Start-Process as well, so
    # that its process can be stopped when it does not finish in time.
    $fallback = $null
    try {
        $fallback = Start-Process -FilePath 'cmd.exe' `
            -ArgumentList @('/c', ('"' + $exePath + '" --selftest --selftest-report "' + $reportPath + '"')) `
            -RedirectStandardOutput $outPath `
            -RedirectStandardError $errPath `
            -NoNewWindow `
            -PassThru `
            -ErrorAction Stop
    } catch {
        cmd /c "`"$exePath`" --selftest --selftest-report `"$reportPath`" > `"$outPath`" 2> `"$errPath`""
        $code = $LASTEXITCODE
    }
    if ($null -ne $fallback) {
        if (-not $fallback.WaitForExit($TimeoutSeconds * 1000)) {
            Stop-ProcessTree $fallback
            Write-ExitFile 'timeout' "the program did not stop within $TimeoutSeconds seconds"
            Write-Output "::error title=Self-test::the packaged executable did not finish within $TimeoutSeconds seconds"
            exit 1
        }
        $code = $fallback.ExitCode
    }
}

if ($null -eq $code) {
    # The program did not report an exit code, so the build failed.
    $code = 1
}

Write-ExitFile "$code" "exe size: $((Get-Item $exePath).Length) bytes"
Write-Host "exit code: $code"

if (Test-Path $outPath) {
    Get-Content $outPath | ForEach-Object { Write-Host "out: $_" }
}
if (Test-Path $errPath) {
    Get-Content $errPath | ForEach-Object { Write-Output "::error title=Self-test::$_" }
}

exit $code
