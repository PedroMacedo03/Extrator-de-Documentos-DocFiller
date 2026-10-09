; Script Inno Setup para DocFiller v1.0.0
#define MyAppName "DocFiller"
#define MyAppVersion "1.0.1"
#define MyAppPublisher "DocFiller Team"
#define MyAppExeName "DocFiller.exe"

[Setup]
; Identificador único da aplicação (GUID)
AppId={{D0CF111E-8A3B-4C9D-9E12-F5A7B8C9D0E1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableProgramGroupPage=yes
; Permissões de usuário padrão: instala no LocalAppData sem solicitar privilégios de Admin (UAC)
PrivilegesRequired=lowest
OutputDir=installer_output
OutputBaseFilename=DocFiller_Setup_v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Origem dos arquivos compilados pelo PyInstaller em dist\DocFiller
Source: "dist\DocFiller\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
