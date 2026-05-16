; INTEMO - Enterprise Windows Installer
; Version 14.0.1B
; Build with: scripts\build_installer.bat
;
; This installer is intentionally self-contained and offline-capable.

#define MyAppName "INTEMO"
#define MyAppVersion "14.0.1B"
#define MyAppPublisher "INTEMO"
#define MyAppURL "https://intemo.ai"
#define MyAppExeName "INTEMO.exe"
#define PayloadDir "..\production_runtime\AIEmailOrganizer"

#ifnexist PayloadDir + "\start.bat"
  #error "Installer payload is missing or incomplete. Run build_installer.bat from the project root so production_runtime\AIEmailOrganizer is prepared before compiling this script."
#endif

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\INTEMO
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=..\LICENSE
OutputDir=..\installers
OutputBaseFilename=INTEMO-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
MinVersion=10.0
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupLogging=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "startup"; Description: "Start INTEMO silently in the background when Windows starts"; GroupDescription: "Startup Options:"; Flags: checkedonce
Name: "firewall"; Description: "Add Windows Firewall exception for local dashboard (port 4597)"; GroupDescription: "System Integration:"; Flags: unchecked
Name: "installofflinepythondeps"; Description: "Install bundled Python dependencies if executable fallback is used"; GroupDescription: "Runtime Options:"; Flags: checkedonce

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{app}\data"
Name: "{app}\database"
Name: "{app}\logs"
Name: "{app}\cache"
Name: "{app}\models"
Name: "{app}\backups"
Name: "{app}\runtime"
Name: "{app}\updates"
Name: "{app}\reports\evidence"
Name: "{app}\packages\wheels"
Name: "{localappdata}\INTEMO"
Name: "{localappdata}\INTEMO\data"
Name: "{localappdata}\INTEMO\logs"
Name: "{localappdata}\INTEMO\cache"
Name: "{localappdata}\INTEMO\models"
Name: "{localappdata}\INTEMO\database"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\start.bat"; WorkingDir: "{app}"
Name: "{group}\Start Background Service"; Filename: "{win}\System32\wscript.exe"; Parameters: "//B //Nologo ""{app}\start_background.vbs"""; WorkingDir: "{app}"
Name: "{group}\Service Manager"; Filename: "{app}\service_manager.bat"; WorkingDir: "{app}"
Name: "{group}\Dashboard"; Filename: "{app}\open_dashboard.bat"; WorkingDir: "{app}"
Name: "{group}\Admin Center"; Filename: "{app}\admin.bat"; WorkingDir: "{app}"
Name: "{group}\API Docs"; Filename: "{app}\open_docs.bat"; WorkingDir: "{app}"
Name: "{group}\Stop Background Service"; Filename: "{app}\stop.bat"; WorkingDir: "{app}"
Name: "{group}\Enable Start with Windows"; Filename: "{app}\enable_startup.bat"; WorkingDir: "{app}"
Name: "{group}\Disable Start with Windows"; Filename: "{app}\disable_startup.bat"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\INTEMO"; Filename: "{app}\open_dashboard.bat"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\INTEMO"; Filename: "{win}\System32\wscript.exe"; Parameters: "//B //Nologo ""{app}\start_background.vbs"""; WorkingDir: "{app}"; Tasks: startup

[Registry]
Root: HKLM; Subkey: "Software\INTEMO"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\INTEMO"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"
Root: HKLM; Subkey: "Software\INTEMO"; ValueType: string; ValueName: "InstallDate"; ValueData: "{code:GetInstallDate}"
Root: HKCU; Subkey: "Software\INTEMO"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"
Root: HKCU; Subkey: "Software\INTEMO"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "INTEMO"; ValueData: """{win}\System32\wscript.exe"" //B //Nologo ""{app}\start_background.vbs"""; Flags: uninsdeletevalue; Tasks: startup
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "INTEMO"; ValueData: """{win}\System32\wscript.exe"" //B //Nologo ""{app}\start_background.vbs"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{cmd}"; Parameters: "/C """"{app}\install_runtime_deps.bat"""""; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; StatusMsg: "Installing bundled Python dependencies..."; Tasks: installofflinepythondeps; Check: NeedsOfflineDependencyInstall
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""INTEMO Local Dashboard"" dir=in action=allow protocol=TCP localport=4597 enable=yes profile=any"; Flags: runhidden; Tasks: firewall
Filename: "{app}\enable_startup.bat"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; Tasks: startup
Filename: "{win}\System32\wscript.exe"; Parameters: "//B //Nologo ""{app}\start_background.vbs"""; WorkingDir: "{app}"; Flags: runhidden nowait skipifsilent
Filename: "{app}\open_dashboard.bat"; Description: "Open INTEMO Dashboard"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden waituntilterminated; RunOnceId: "KillINTEMOExe"
Filename: "{app}\stop.bat"; Flags: runhidden waituntilterminated; RunOnceId: "StopINTEMOBackground"
Filename: "taskkill"; Parameters: "/F /FI ""WINDOWTITLE eq INTEMO*"""; Flags: runhidden waituntilterminated; RunOnceId: "KillINTEMOConsole"
Filename: "{app}\disable_startup.bat"; Flags: runhidden waituntilterminated; RunOnceId: "DisableINTEMOStartup"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\cache"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\runtime\tmp"

[Code]
function GetInstallDate(Param: String): String;
begin
  Result := GetDateTimeString('yyyy-mm-dd', '-', ':');
end;

function HasPackagedExe(): Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\{#MyAppExeName}'));
end;

function HasOfflineWheelhouse(): Boolean;
begin
  Result := DirExists(ExpandConstant('{app}\packages\wheels')) and FileExists(ExpandConstant('{app}\service\requirements.txt'));
end;

function NeedsOfflineDependencyInstall(): Boolean;
begin
  Result := (not HasPackagedExe()) and HasOfflineWheelhouse();
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  VersionFile: String;
begin
  if CurStep = ssPostInstall then
  begin
    ForceDirectories(ExpandConstant('{app}\data'));
    ForceDirectories(ExpandConstant('{app}\database'));
    ForceDirectories(ExpandConstant('{app}\logs'));
    ForceDirectories(ExpandConstant('{app}\cache'));
    ForceDirectories(ExpandConstant('{app}\models'));
    ForceDirectories(ExpandConstant('{app}\backups'));
    ForceDirectories(ExpandConstant('{app}\runtime'));
    ForceDirectories(ExpandConstant('{app}\updates'));
    ForceDirectories(ExpandConstant('{app}\reports\evidence'));
    ForceDirectories(ExpandConstant('{localappdata}\INTEMO'));
    ForceDirectories(ExpandConstant('{localappdata}\INTEMO\data'));
    ForceDirectories(ExpandConstant('{localappdata}\INTEMO\logs'));
    ForceDirectories(ExpandConstant('{localappdata}\INTEMO\cache'));
    ForceDirectories(ExpandConstant('{localappdata}\INTEMO\models'));
    ForceDirectories(ExpandConstant('{localappdata}\INTEMO\database'));

    VersionFile := ExpandConstant('{app}\version.json');
    if FileExists(VersionFile) then
      Log('Installed version metadata: ' + VersionFile)
    else
      Log('Warning: version.json was not found in installer payload');
  end;
end;
