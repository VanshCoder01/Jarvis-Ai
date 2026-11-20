; ============================================================
;  J.A.R.V.I.S  --  Windows installer (Inno Setup 6)
;
;  Don't compile this by hand: run build.bat in the project folder. It
;  builds dist\Jarvis with PyInstaller first, then compiles this with the
;  version number from config.py.
;
;  What the user gets:
;   * no Python needed -- Jarvis ships as a self-contained app
;   * installs per-user by default (no admin prompt), or for everyone
;   * Start Menu entry, optional desktop shortcut, optional start-with-Windows
;   * closes a running Jarvis before upgrading it
;   * a clean uninstaller in Settings > Apps, which asks whether to keep
;     your keys, memory and chat history
; ============================================================

#ifndef AppVersion
  #define AppVersion "0.0"
#endif
#define AppName      "J.A.R.V.I.S"
#define AppPublisher "VanshCoder01"
#define AppURL       "https://github.com/VanshCoder01/Jarvis-Ai"
#define AppExeName   "Jarvis.exe"

[Setup]
AppId={{8F3C1A94-6B2E-4D77-9A15-2C8E7F4B1D06}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\Jarvis
DefaultGroupName=Jarvis
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=..\LICENSE.txt
SetupIconFile=..\jarvis.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
OutputDir=..\installer_output
OutputBaseFilename=JarvisSetup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=110
AppMutex=JarvisAssistantSingleInstance
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startup";     Description: "Start Jarvis when I sign in to Windows"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "..\dist\Jarvis\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md";     DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "..\LICENSE";       DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; files from the old script-based installer, if it was used before
Type: files;          Name: "{app}\*.py"
Type: filesandordirs; Name: "{app}\__pycache__"

[Icons]
Name: "{autoprograms}\Jarvis";            Filename: "{app}\{#AppExeName}"; Comment: "Voice assistant that operates your PC"
Name: "{autodesktop}\Jarvis";             Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; Same value startup.py writes, so the LAUNCH AT STARTUP switch in Jarvis
; and this checkbox stay in agreement. Removed again on uninstall.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Jarvis"; \
    ValueData: """{app}\{#AppExeName}"""; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch Jarvis now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    { The Run value is removed by [Registry] only if setup created it; the
      in-app switch may have created it too. }
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Jarvis');

    DataDir := ExpandConstant('{userappdata}\Jarvis');
    if DirExists(DataDir) and not UninstallSilent then
      if MsgBox('Also delete your Jarvis data?' + #13#10 + #13#10 +
                'That is your API keys, what Jarvis remembers about you, and your chat history ' +
                '(' + DataDir + ').' + #13#10 + #13#10 +
                'Choose No to keep it for a future reinstall.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
