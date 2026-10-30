@echo off
rem Creates a KinKeep shortcut with the KinKeep icon on your Desktop (Windows).
set "HERE=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\KinKeep.lnk'); $s.TargetPath='%HERE%KinKeep.html'; $s.IconLocation='%HERE%KinKeep.ico'; $s.Description='KinKeep - Protect What Matters'; $s.Save()"
echo KinKeep shortcut created on your Desktop.
pause
