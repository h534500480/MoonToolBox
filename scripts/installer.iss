; 功能说明：安装内置运行库的 ROS 平台；个人数据与程序目录分离，卸载保留用户数据。
#define MyAppName "ROSPlatform"
#define MyAppVersion "0.2.0"
#define MyAppPublisher "TreeMoon"
#define MyAppExeName "runtime\ROSPlatform.exe"

#ifndef PackageSourceDir
  #define PackageSourceDir "..\release\ROSPlatform"
#endif

#ifexist "{#PackageSourceDir}\MoonToolBox.ico"
  #define MyAppShortcutIconFile "{#PackageSourceDir}\MoonToolBox.ico"
#endif

#ifexist "..\release\MoonToolBoxSetup.ico"
  #define MySetupIconFile "..\release\MoonToolBoxSetup.ico"
#endif

[Setup]
AppId={{80335628-4D7D-4070-B604-0A89324FB5D0}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\release
OutputBaseFilename=ROSPlatformSetup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupLogging=yes
MinVersion=10.0
CloseApplications=yes
RestartApplications=no
SetupMutex=ROSPlatformInstaller
#ifdef MySetupIconFile
SetupIconFile={#MySetupIconFile}
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#PackageSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
#ifdef MyAppShortcutIconFile
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\MoonToolBox.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\MoonToolBox.ico"; Tasks: desktopicon
#else
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
#endif

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent; WorkingDir: "{app}"
