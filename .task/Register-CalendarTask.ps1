# lewagon-calendar scheduled updater — Task Scheduler setup
# Run ONCE as admin-ish (your user, highest not required). Creates task:
#   name:     lewagon-calendar-updater
#   schedule: every 3 days (repetition interval 72h), run ASAP when PC was off/missed
#   action:   dsh --profile calendar "<PROMPT>" with cwd C:\code\lewagon-calendar
#   logs to:  C:\code\lewagon-calendar\.logs\run-<timestamp>.log
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File Register-CalendarTask.ps1
#   powershell -ExecutionPolicy Bypass -File Register-CalendarTask.ps1 -Unregister   # remove
#   powershell -ExecutionPolicy Bypass -File Register-CalendarTask.ps1 -RunNow        # register + run once now

param(
  [switch]$Unregister,
  [switch]$RunNow
)

$ErrorActionPreference = 'Stop'
$TaskName   = 'lewagon-calendar-updater'
$RepoDir    = 'C:\code\lewagon-calendar'
$LogDir     = Join-Path $RepoDir '.logs'
$RunnerPath = Join-Path $RepoDir '.task\run-updater.ps1'
$DshExe     = 'C:\Users\rif42\.bun\bin\dsh.exe'

if ($Unregister) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host "removed $TaskName"
  exit 0
}

# --- 1. task prompt (single-quoted here-string: no expansion, safe to paste) ---
$Prompt = @'
In C:\code\lewagon-calendar: discovery window = today through +14d only. Pipeline prune stays rolling 60d — do not change prune logic.

1) Run `python updater/update.py` (README sections 4 and 7: data flow, merge rules, parser asserts). Check `data/last_run.json` per-source status. Enforce parser assert: each source yielded >=1 dated link, else error status. Validate `data/events.json` against `events.schema.json` (required: uid sha1hex, name, start_utc Z, source, source_url, status; enums area/category; finish_utc null when unknown). Verify `data/bali-events.ics` regenerated same run from same merged list (subscribe feed, must match JSON). Fix violations, never hand-write events or uids. Recurring series: expand to dated instances inside window, never store bare "every Saturday".

2) Read https://docs.google.com/spreadsheets/d/1bLfnXMuwO5dnVEPsoiqmhD9uFU4d3xLehJ09S7ehOkU/edit?usp=sharing (also try csv export https://docs.google.com/spreadsheets/d/1bLfnXMuwO5dnVEPsoiqmhD9uFU4d3xLehJ09S7ehOkU/export?format=csv). Sheet is public read/write. For each row: hoax-check via kestrel deep research + web search (official venue/organizer page or 2 independent sources; reject past dates, vague venue, no verifiable organizer). Schema-check. If valid merge into `data/events.json` (new append, changed SEQUENCE+1, missing stays stale per README). If valid set sheet row status to DONE. If sheet write fails, list DONE-candidates in report with reasons.

3) Find 1 new credible Bali events source (especially Canggu). Verify parseable server-side (no browser/login/JS). If good, add row to README section 6 table with URL pattern + parse notes. Never add bot-wall/login-wall/JS-shell sources (see README rejected list).

4) Stage, commit, push WHOLE REPO (`git add -A`, commit "data: scheduled events update YYYY-MM-DD", `git push origin main`). Commit always, even on failure (keep-alive: at least `data/last_run.json`). Report: updater result, events added/updated/rejected, sheet rows accepted/rejected, new source verdict, commit sha, push result.
'@

# --- 2. runner script (task action calls this; handles log + env + push-safe exit) ---
# Prompt travels as base64 to avoid quoting hell (em-dashes, parens, backticks).
$Runner = @'
$ErrorActionPreference = 'Continue'
$RepoDir = 'C:\code\lewagon-calendar'
$LogDir  = Join-Path $RepoDir '.logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir ('run-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
$Prompt = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('PROMPT-B64'))
$Prompt | Out-File -FilePath (Join-Path $LogDir 'last-prompt.txt') -Encoding utf8
Start-Transcript -Path $Log -Append | Out-Null
try {
  Set-Location $RepoDir
  & 'C:\Users\rif42\.bun\bin\dsh.exe' --profile calendar $Prompt
  $code = $LASTEXITCODE
  "EXITCODE=$code" | Out-File -FilePath $Log -Append -Encoding utf8
  exit $code
} finally { Stop-Transcript | Out-Null }
'@

New-Item -ItemType Directory -Force -Path (Split-Path $RunnerPath) | Out-Null
$B64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Prompt))
$Runner.Replace('PROMPT-B64', $B64) | Set-Content -Path $RunnerPath -Encoding UTF8

# --- 3. task: every 3 days, run ASAP after missed start, only when net available ---
$Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$RunnerPath`"" -WorkingDirectory $RepoDir
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date '03:00') -RepetitionInterval (New-TimeSpan -Hours 72) -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description 'lewagon-calendar: dsh calendar profile updater, every 3 days' -Force | Out-Null

# require network: set RunOnlyIfNetworkAvailable via XML patch (no cmdlet flag exists)
$Path = "\$TaskName"
$Xml = Export-ScheduledTask -TaskName $TaskName
[xml]$Doc = $Xml
$ns = New-Object Xml.XmlNamespaceManager($Doc.NameTable)
$ns.AddNamespace('t', 'http://schemas.microsoft.com/windows/2004/02/mit/task')
$node = $Doc.SelectSingleNode('//t:Settings', $ns)
if ($node -and -not $node.RunOnlyIfNetworkAvailable) {
  $el = $Doc.CreateElement('RunOnlyIfNetworkAvailable', 'http://schemas.microsoft.com/windows/2004/02/mit/task')
  $el.InnerText = 'true'
  $node.AppendChild($el) | Out-Null
  Register-ScheduledTask -TaskName $TaskName -Xml $Doc.OuterXml -Force | Out-Null
}

Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State, @{n='NextRun';e={(Get-ScheduledTaskInfo -TaskName $TaskName).NextRunTime}}
Write-Host "runner: $RunnerPath"
Write-Host "logs:   $LogDir"

if ($RunNow) { Start-ScheduledTask -TaskName $TaskName; Write-Host 'started now' }
