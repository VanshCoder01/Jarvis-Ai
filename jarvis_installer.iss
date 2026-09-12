; ============================================================
;  J.A.R.V.I.S  —  Windows Installer
;  Build with Inno Setup 6.1+  (https://jrsoftware.org/isdl.php)
;
;  Produces a proper Windows setup wizard: language selection,
;  licence page, install location, desktop icon option, progress
;  bar, and an uninstaller registered in Add/Remove Programs.
;
;  BEFORE BUILDING: run build_installer.bat once so dist\Jarvis.exe
;  exists, OR set BundleSource to yes below to ship the .py files
;  and use the system Python instead.
; ============================================================

#define AppName        "J.A.R.V.I.S"
#define AppVersion     "1.06"
#define AppPublisher   "Vansh"
#define AppURL         "https://github.com/VanshCoder01/Jarvis-Ai"
#define AppExeName     "Jarvis.exe"

[Setup]
AppId={{8F3C1A94-6B2E-4D77-9A15-2C8E7F4B1D06}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\Jarvis
DefaultGroupName={#AppName}
AllowNoIcons=yes
LicenseFile=LICENSE.txt
OutputDir=installer_output
OutputBaseFilename=JarvisSetup-v{#AppVersion}
SetupIconFile=jarvis.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog

; Show the language picker even when only one language would match
ShowLanguageDialog=yes

[Languages]
Name: "english";      MessagesFile: "compiler:Default.isl"
Name: "french";       MessagesFile: "compiler:Languages\French.isl"
Name: "german";       MessagesFile: "compiler:Languages\German.isl"
Name: "spanish";      MessagesFile: "compiler:Languages\Spanish.isl"
Name: "italian";      MessagesFile: "compiler:Languages\Italian.isl"
Name: "dutch";        MessagesFile: "compiler:Languages\Dutch.isl"
Name: "portuguese";   MessagesFile: "compiler:Languages\Portuguese.isl"
Name: "russian";      MessagesFile: "compiler:Languages\Russian.isl"
Name: "japanese";     MessagesFile: "compiler:Languages\Japanese.isl"
Name: "polish";       MessagesFile: "compiler:Languages\Polish.isl"
Name: "turkish";      MessagesFile: "compiler:Languages\Turkish.isl"
Name: "czech";        MessagesFile: "compiler:Languages\Czech.isl"
Name: "danish";       MessagesFile: "compiler:Languages\Danish.isl"
Name: "finnish";      MessagesFile: "compiler:Languages\Finnish.isl"
Name: "norwegian";    MessagesFile: "compiler:Languages\Norwegian.isl"
Name: "ukrainian";    MessagesFile: "compiler:Languages\Ukrainian.isl"

[CustomMessages]
english.LaunchApp=Launch %1
english.CreateDesktopIcon=Create a &desktop shortcut
english.InstallingDeps=Installing Python dependencies. This may take a few minutes...
english.PythonMissing=Python 3.10 or newer wasn't found on this PC.%n%nJarvis needs it to run. Install Python from python.org (tick "Add python.exe to PATH" during setup), then run this installer again.%n%nContinue anyway?

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; --- The application itself ---
Source: "main.py";           DestDir: "{app}"; Flags: ignoreversion
Source: "server.py";         DestDir: "{app}"; Flags: ignoreversion
Source: "brain.py";          DestDir: "{app}"; Flags: ignoreversion
Source: "llm.py";            DestDir: "{app}"; Flags: ignoreversion
Source: "memory.py";         DestDir: "{app}"; Flags: ignoreversion
Source: "history.py";        DestDir: "{app}"; Flags: ignoreversion
Source: "pc_control.py";     DestDir: "{app}"; Flags: ignoreversion
Source: "tts.py";            DestDir: "{app}"; Flags: ignoreversion
Source: "image_gen.py";      DestDir: "{app}"; Flags: ignoreversion
Source: "config.py";         DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist
Source: "index.html";        DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt";  DestDir: "{app}"; Flags: ignoreversion
Source: "jarvis.ico";        DestDir: "{app}"; Flags: ignoreversion
Source: "README.md";         DestDir: "{app}"; Flags: ignoreversion
Source: "CHANGELOG.md";      DestDir: "{app}"; Flags: ignoreversion

; --- Optional: ship the compiled exe too if it was built ---
Source: "dist\Jarvis.exe";   DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#AppName}";                Filename: "{code:GetPythonW}"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\jarvis.ico"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";          Filename: "{code:GetPythonW}"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\jarvis.ico"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#AppName}"; Filename: "{code:GetPythonW}"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\jarvis.ico"; Tasks: quicklaunchicon

[Run]
; Install dependencies with a visible progress message
Filename: "{code:GetPython}"; Parameters: "-m pip install --upgrade pip"; \
    StatusMsg: "{cm:InstallingDeps}"; Flags: runhidden waituntilterminated
Filename: "{code:GetPython}"; Parameters: "-m pip install -r ""{app}\requirements.txt"""; \
    StatusMsg: "{cm:InstallingDeps}"; Flags: runhidden waituntilterminated

; Offer to launch when finished
Filename: "{code:GetPythonW}"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; \
    Description: "{cm:LaunchApp,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
var
  PythonPath: String;
  PythonWPath: String;

{ Find a usable Python on this machine. Checks PATH first, then the
  standard per-user and machine-wide install locations, then the py
  launcher. Returns '' if nothing is found. }
function FindPython(const ExeName: String): String;
var
  Paths: TArrayOfString;
  I: Integer;
  Candidate: String;
  ResultCode: Integer;
begin
  Result := '';

  { 1. Registry — the official install locations }
  SetArrayLength(Paths, 8);
  Paths[0] := ExpandConstant('{localappdata}\Programs\Python\Python313\') + ExeName;
  Paths[1] := ExpandConstant('{localappdata}\Programs\Python\Python312\') + ExeName;
  Paths[2] := ExpandConstant('{localappdata}\Programs\Python\Python311\') + ExeName;
  Paths[3] := ExpandConstant('{localappdata}\Programs\Python\Python310\') + ExeName;
  Paths[4] := 'C:\Python313\' + ExeName;
  Paths[5] := 'C:\Python312\' + ExeName;
  Paths[6] := 'C:\Python311\' + ExeName;
  Paths[7] := 'C:\Python310\' + ExeName;

  for I := 0 to GetArrayLength(Paths) - 1 do
  begin
    if FileExists(Paths[I]) then
    begin
      Result := Paths[I];
      Exit;
    end;
  end;

  { 2. Fall back to bare name and let PATH resolve it }
  Candidate := ExeName;
  if Exec('cmd.exe', '/C where ' + ExeName, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    if ResultCode = 0 then
      Result := Candidate;
end;

function GetPython(Param: String): String;
begin
  if PythonPath = '' then
    PythonPath := FindPython('python.exe');
  if PythonPath = '' then
    PythonPath := 'python.exe';
  Result := PythonPath;
end;

function GetPythonW(Param: String): String;
begin
  if PythonWPath = '' then
    PythonWPath := FindPython('pythonw.exe');
  if PythonWPath = '' then
    PythonWPath := 'pythonw.exe';
  Result := PythonWPath;
end;

{ Warn early if Python is missing, rather than failing silently at the
  dependency step and leaving a half-installed app behind. }
function InitializeSetup(): Boolean;
begin
  Result := True;
  if FindPython('python.exe') = '' then
  begin
    if MsgBox(ExpandConstant('{cm:PythonMissing}'), mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;
end;
