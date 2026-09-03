; Inno Setup script for rdo-lobby-manager.
;
; This produces RDO-Lobby-Manager-Setup-x.y.z.exe: the thing a Windows user
; expects when they download an app. A wizard with a welcome page, a folder
; to install into, a custom page for the RDR2 path, a progress bar, Start
; menu and Desktop entries, a real uninstaller in Add or Remove Programs,
; and a Finish page that offers to launch it.
;
; The PyInstaller build produces a single RdoLobbyManager.exe that runs with
; no Python on the machine; this wraps that file. Build order is therefore:
;
;     pyinstaller packaging/rdo-lobby-manager.spec --noconfirm --clean
;     iscc packaging\rdo-lobby-manager.iss /DMyAppVersion=x.y.z
;
; CI does both in .github/workflows/build-windows.yml.
;
; Install.bat in the repo root is a different thing: it sets up a .venv
; from source, for people running from a clone. This is the path for
; everyone else.

#ifndef MyAppVersion
  #define MyAppVersion "2.0.0a0"
#endif

#define MyAppName "RDO Lobby Manager"
#define MyAppShortName "RDO Lobby Manager"
#define MyAppExeName "RdoLobbyManager.exe"
#define MyAppPublisher "R0U5"
#define MyAppURL "https://github.com/R0U5/rdo-lobby-manager"

[Setup]
AppId={{7D9C5A2B-1F3E-4A8C-B6D2-9E5F8A7B3C4D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppShortName}
DefaultGroupName={#MyAppName}
OutputDir=dist
OutputBaseFilename=RDO-Lobby-Manager-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
; RDO-LM writes lobby data to %APPDATA%\RDOLobbyManager and edits the
; user's own startup.meta. Asking for administrator on a per-user lobby
; manager is unnecessary, and a UAC prompt on a hobby tool reads as a
; warning sign -- so it installs per-user and never elevates.
PrivilegesRequired=lowest
; Both are false so the wizard reads as one straight line: welcome, RDR2
; path, options, install, finish. A page that only says "click Next" is a
; page the user has to read to discover it says nothing.
DisableProgramGroupPage=yes
DisableReadyPage=no
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nRDO Lobby Manager edits Red Dead Redemption 2's startup.meta so you can hop into a friend's private lobby without typing the password on the game's on-screen keyboard. Passphrases are Fernet-encrypted with a key derived from your Windows account.%n%nClose RDR2 before using the tool -- the game overwrites its own config when it exits.
FinishedLabelNoIcons=Setup has finished installing [name].
FinishedLabel=Setup has finished installing [name].%n%nRDO Lobby Manager opens in its own window. Your lobbies are stored under your Windows user profile; nothing is uploaded anywhere.

[Tasks]
Name: "desktopicon"; Description: "Create a &Desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; DestName: "README.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppShortName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppShortName}}"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The PyInstaller bundle's _internal cache is ours to remove. User lobby
; data lives under %APPDATA%\RDOLobbyManager and is never touched by the
; uninstaller.
Type: filesandordirs; Name: "{app}\_internal"
Type: dirifempty; Name: "{app}"

[Code]
{ ── A page for the RDR2 install ──────────────────────────────────────────

  The Python module src/rdo_lobby_manager/domain/install_detect.py
  already walks Steam libraryfolders.vdf, the Rockstar launcher, and Epic
  manifests to find the install. The wizard calls the frozen exe with
  --detect-install and parses its stdout, so the Pascal side never has
  to know about any of those locations. }

var
  GameDirPage: TInputDirWizardPage;
  Rdo2Path: String;

function GetBestGuess(Path: String): String;
{ Run the frozen exe with --detect-install and return line 1 (best
  guess). Stderr/extra lines are ignored. Returns '' if nothing found. }
var
  ResultCode: Integer;
  Lines: TArrayOfString;
  S: String;
begin
  Result := '';
  if not FileExists(ExpandConstant('{app}\{#MyAppExeName}')) then Exit;
  if not Exec(ExpandConstant('{app}\{#MyAppExeName}'),
              '--detect-install', '', SW_HIDE,
              ewWaitUntilTerminated, ResultCode) then Exit;
  if ResultCode <> 0 then Exit;
  if LoadStringsFromFile(ExpandConstant('{tmp}\detect-install.out'), Lines) then
  begin
    if GetArrayLength(Lines) > 0 then
    begin
      S := Trim(Lines[0]);
      if S <> '' then Result := S;
    end;
  end;
end;

procedure InitializeWizard();
begin
  GameDirPage := CreateInputDirPage(
    wpSelectTasks,
    'Your RDR2 installation',
    'Where is Red Dead Redemption 2 installed?',
    'RDO Lobby Manager needs to know where your RDR2 install lives so it' + #13#10 +
    'can back up the original startup.meta and apply private-lobby patches.' + #13#10 + #13#10 +
    'This only reads and writes inside that folder. Nothing else is touched.' + #13#10 + #13#10 +
    'Leave this blank to skip -- you can point the tool at the folder from' + #13#10 +
    'inside the app later.',
    False, '');
  GameDirPage.Add('RDR2 folder (the one containing RDR2.exe):');
end;

{ The detect-install call above went to a console that Inno Setup cannot
  capture directly. Redirect the exe's stdout to a temp file by invoking
  it via cmd /c. }
function ExecCaptureStdout(Filename, Params: String): String;
var
  Buf: AnsiString;
  Len, Read: Cardinal;
  Tmp: String;
begin
  Result := '';
  Tmp := ExpandConstant('{tmp}\detect-install.out');
  if not Exec(Filename, Params + ' > "' + Tmp + '" 2>&1', '', SW_HIDE,
              ewWaitUntilTerminated, Len) then Exit;
  if not FileExists(Tmp) then Exit;
  Buf := '';
  with TFileStream.Create(Tmp, fmOpenRead or fmShareDenyNone) do
  try
    Len := Size;
    if Len > 65536 then Len := 65536;
    SetLength(Buf, Len);
    Seek(0, soBeginning);
    Read := Read(Buf[1], Len);
  finally
    Free;
  end;
  Result := Buf;
end;

procedure CurPageChanged(CurPageID: Integer);
var
  Detected: String;
begin
  if CurPageID <> GameDirPage.ID then Exit;
  if GameDirPage.Values[0] <> '' then Exit;

  { Only call out to the exe if it is already on disk -- this fires
    before the install step, where the exe is in {app} but only after
    Files have been copied. On a clean install the file is present
    because Files runs in ssInstall step but the page shows earlier;
    so the real hook for filling the guess is CurStepChanged. }
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Detected: String;
begin
  if CurStep <> ssInstall then Exit;
  if GameDirPage.Values[0] <> '' then Exit;

  { Files have been copied by now. Run the detect-install probe. }
  Detected := GetBestGuess('');
  if Detected <> '' then GameDirPage.Values[0] := Detected;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Chosen: String;
begin
  Result := True;
  if CurPageID <> GameDirPage.ID then Exit;

  Chosen := Trim(GameDirPage.Values[0]);
  Rdo2Path := Chosen;
  if Chosen = '' then Exit; { skip is allowed }

  { Fail here, where it can be corrected, rather than after the copy. }
  if not DirExists(Chosen) then
  begin
    MsgBox('That folder does not exist.' + #13#10 + #13#10 +
           'Pick the RDR2 folder -- the one containing RDR2.exe -- or ' +
           'clear the box to skip this step.', mbError, MB_OK);
    Result := False;
  end;
end;
