; ==============================================================
; Webineer – Installer (Inno Setup 6, Modern Wizard + Welcome/Finished BGs)
; ==============================================================

#define MyAppName        "Webineer"
#define MyAppVersion     "1.0.0"
#define MyAppPublisher   "Webineer"
#define MyAppExeName     "Webineer.exe"
; Generate this once via IDE: Tools -> Generate GUID
#define MyAppId          "{{8B8D2F0C-4B6C-4D6F-93D7-4E911E4F9A22}}"

; Project root (this .iss is here): C:\Users\curph\OneDrive\Documents\GitHub\Webineer
; PyInstaller exe:  .\dist\Webineer.exe
; Icon:              .\icon.ico
; Banner image:      .\Assets\installerthemeBanner.png
; Welcome BG image:  .\Assets\InstllerWelcomeScreen.png
; Output installer:  .\Installer\out\Webineer-Setup-1.0.0.exe

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}

DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableDirPage=no
DisableProgramGroupPage=no

; ----- Look & Feel -----
WizardStyle=modern
; Top banner (PNG is OK; if it ever errors, export to BMP and reference that)
WizardImageFile={#SourcePath}\Assets\installerthemeBanner.bpm
SetupIconFile={#SourcePath}\icon.ico

Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64

; ----- Output -----
OutputDir=Installer\out
OutputBaseFilename=Webineer-Setup-{#MyAppVersion}
PrivilegesRequired=admin

; ----- Uninstall -----
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"
Name: "startafterinstall"; Description: "Launch {#MyAppName} after setup"; GroupDescription: "Additional options:"

[Files]
; Main application
Source: "dist\Webineer.exe"; DestDir: "{app}"; Flags: ignoreversion

; Welcome/Finished background (used during setup only; not copied to {app})
; If PNG causes a GDI+ error at runtime, save it as BMP in Paint and switch to the BMP line.
Source: "Assets\InstllerWelcomeScreen.png"; Flags: dontcopy
; Source: "Assets\InstllerWelcomeScreen.bmp"; Flags: dontcopy

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[InstallDelete]
Type: files;           Name: "{localappdata}\Webineer\recents.json"
Type: files;           Name: "{localappdata}\Webineer\settings.json"
Type: filesandordirs;  Name: "{localappdata}\Webineer\Previews"
Type: filesandordirs;  Name: "{localappdata}\Webineer\Covers"
Type: filesandordirs;  Name: "{localappdata}\Webineer\logs"

[Run]
; Run as the logged-in (original) user so it wipes *their* app data
Filename: "{app}\{#MyAppExeName}"; \
  Parameters: "--reset-appdata"; \
  RunAsOriginalUser: yes; \
  Flags: skipifsilent nowait postinstall

; ==============================================================
; Code: Draw a full-page background on Welcome and Finished pages
; ==============================================================

[Code]
var
  WelcomeBg, FinishedBg: TBitmapImage;

procedure MakePageBackground(Page: TWizardPage; const FileName: string; var Img: TBitmapImage);
begin
  Img := TBitmapImage.Create(Page);
  Img.Parent := Page;      { attach directly to the page panel }
  Img.Stretch := True;
  Img.AutoSize := False;
  Img.Center := False;
  Img.Align := alClient;   { fill the whole page; no resize handler needed }
  try
    Img.Bitmap.LoadFromFile(FileName);
    Img.SendToBack;        { keep native labels/buttons on top }
  except
    Img.Free;
    Img := nil;
  end;
end;

procedure InitializeWizard;
var
  BgPng, BgBmp, UseFile: string;
begin
  { Extract whichever format you added to [Files] }
  ExtractTemporaryFile('InstllerWelcomeScreen.png');
  BgPng := ExpandConstant('{tmp}\InstllerWelcomeScreen.png');

  { If you decide to ship BMP instead, comment the two lines above and uncomment below: }
  { ExtractTemporaryFile('InstllerWelcomeScreen.bmp');
    BgBmp := ExpandConstant('{tmp}\InstllerWelcomeScreen.bmp'); }

  { Prefer PNG if present; else fall back to BMP path if you switched formats }
  if FileExists(BgPng) then
    UseFile := BgPng
  else
    UseFile := BgBmp;

  { Draw both pages (use the same image, or change filename if you have two different assets) }
  MakePageBackground(WizardForm.WelcomePage, UseFile, WelcomeBg);
  MakePageBackground(WizardForm.FinishedPage, UseFile, FinishedBg);
end;
