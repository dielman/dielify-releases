; Dielify installer (Inno Setup 6). Built by packaging\build.py, which passes:
;   /DAppVersion=x.y.z  /DFFmpegDir=...  /DDenoDir=...
; Per-user install: no admin rights needed, so updates can install silently too.

#ifndef AppVersion
  #error Build with packaging\build.py
#endif

[Setup]
AppId={{8F1B6C42-3D7E-4A5B-9C21-D1E1F7A0B5C3}
AppName=Dielify
AppVersion={#AppVersion}
AppVerName=Dielify {#AppVersion}
AppPublisher=Josh
DefaultDirName={localappdata}\Programs\Dielify
DisableDirPage=auto
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Dielify-setup-{#AppVersion}
SetupIconFile=dielify.ico
UninstallDisplayIcon={app}\Dielify.exe
UninstallDisplayName=Dielify
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Close a running Dielify before replacing its files.
AppMutex=Local\dielify-desktop
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "autostart"; Description: "Start Dielify when I sign in to Windows (it waits in the tray)"; Flags: unchecked

[Files]
Source: "..\dist\Dielify\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#FFmpegDir}\ffmpeg.exe"; DestDir: "{app}\bin"; Flags: ignoreversion
Source: "{#FFmpegDir}\ffprobe.exe"; DestDir: "{app}\bin"; Flags: ignoreversion
Source: "{#DenoDir}\deno.exe"; DestDir: "{app}\bin"; Flags: ignoreversion

[InstallDelete]
; Files from an older version that the new one no longer has.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Dielify"; Filename: "{app}\Dielify.exe"
Name: "{autodesktop}\Dielify"; Filename: "{app}\Dielify.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
  ValueName: "Dielify"; ValueData: """{app}\Dielify.exe"" --tray"; Tasks: autostart
; Whoever turned it on (installer or the app's setting), remove it on uninstall.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; \
  ValueName: "Dielify"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Dielify.exe"; Description: "Open Dielify"; Flags: nowait postinstall skipifsilent
; After a silent update (Dielify runs the installer with /RESTARTAPP=1), start it again.
Filename: "{app}\Dielify.exe"; Flags: nowait; Check: RestartAfterUpdate

[Code]
function RestartAfterUpdate: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:RESTARTAPP|0}') = '1');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
    if MsgBox('Also delete Dielify''s settings, sign-ins and library index on this PC?' + #13#10#13#10 +
              'Your music files are never deleted.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{localappdata}\Dielify'), True, True, True);
end;
