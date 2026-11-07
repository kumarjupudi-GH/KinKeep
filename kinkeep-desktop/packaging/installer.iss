; Optional Windows installer (Inno Setup 6). Build after packaging/build.py:  iscc packaging\installer.iss
[Setup]
AppName=KinKeep
AppVersion=2.0.0
DefaultDirName={autopf}\KinKeep
DefaultGroupName=KinKeep
OutputDir=..\dist
OutputBaseFilename=KinKeep-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\KinKeep.exe
; Uninstalling never touches your data: it lives in Documents\KinKeep Data, not in the program folder.
[Files]
Source: "..\dist\KinKeep\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
[Icons]
Name: "{group}\KinKeep"; Filename: "{app}\KinKeep.exe"
Name: "{autodesktop}\KinKeep"; Filename: "{app}\KinKeep.exe"
