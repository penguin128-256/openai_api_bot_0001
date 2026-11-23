# Windows用: 毎週土曜 7:15 に実行するタスクを登録します。
# nikkei_business_pdf フォルダで PowerShell を開き、 .\schedule\register_windows_task.ps1 を実行。
$dir = Split-Path -Parent $PSScriptRoot
$py  = Join-Path $dir ".venv\Scripts\python.exe"
$action  = New-ScheduledTaskAction -Execute $py -Argument "`"$dir\nb2pdf.py`" run" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At 7:15am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName "NikkeiBusinessPDF" -Action $action -Trigger $trigger -Settings $settings -Force
