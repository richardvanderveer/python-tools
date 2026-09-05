; -*- coding: utf-8 -*-
; Inno Setup script voor Transcribe NL-ENG
; Bouwt een installer rond dist\transcribe-nlen.exe + dist\ffmpeg.exe + dist\ffprobe.exe
; Installeert zonder adminrechten naar %LOCALAPPDATA%, zet Bureaublad-snelkoppeling.
;
; Compileren:
;   1. Installeer Inno Setup (gratis): https://jrsoftware.org/isdl.php
;   2. Dubbelklik dit bestand (transcribe-nlen.iss) -> opent in Inno Setup IDE
;   3. Menu Build > Compile (of F9)
;   4. Resultaat: installer_output\TranscribeApp-Setup.exe
; Of via de command line (na installatie van Inno Setup):
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" transcribe-nlen.iss

#define MyAppName "Transcribe NL-ENG"
#define MyAppVersion "2.2.6"
#define MyAppPublisher "Richard van der Veer"
#define MyAppExeName "transcribe-nlen.exe"

[Setup]
AppId={{75656011-5089-4FA2-BD4E-190CBB789B07}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\TranscribeApp
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Geen adminrechten nodig: installeert in het profiel van de gebruiker
PrivilegesRequired=lowest
OutputDir=installer_output
OutputBaseFilename=TranscribeApp-Setup
SetupIconFile=transcribe-nlen.ico
UninstallDisplayIcon={app}\transcribe-nlen.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
DisableWelcomePage=no

[Languages]
Name: "dutch"; MessagesFile: "compiler:Languages\Dutch.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\transcribe-nlen.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\ffmpeg.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\ffprobe.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "transcribe-nlen.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\transcribe-nlen.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\transcribe-nlen.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
