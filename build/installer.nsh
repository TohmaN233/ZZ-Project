; Updates must overlay packaged files without deleting user-managed files.
; This keeps the separately downloaded asserts/ tree and any future external
; data in place while the installer writes the new package over it.
!macro customCheckAppRunning
  ; The legacy uninstaller is run before the new files are unpacked. Stop the
  ; whole Electron/server tree first so its process check cannot block updates.
  nsExec::Exec `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance -ClassName Win32_Process | Where-Object {$$_.ExecutablePath -and $$_.ExecutablePath.StartsWith('$INSTDIR', 'CurrentCultureIgnoreCase')} | ForEach-Object { Stop-Process -Id $$_.ProcessId -Force }"`
  Pop $R0
  nsExec::Exec '"$SYSDIR\taskkill.exe" /F /T /IM "ZZ-Project.exe"'
  Pop $R0
  nsExec::Exec '"$SYSDIR\taskkill.exe" /F /T /IM "zz-server.exe"'
  Pop $R0
  Sleep 500

  !ifndef BUILD_UNINSTALLER
    ; Do not invoke a legacy uninstaller during an update. Older releases try
    ; to remove the whole install tree and can fail on the external asserts.
    ${If} ${FileExists} "$INSTDIR\${APP_EXECUTABLE_FILENAME}"
      DeleteRegKey HKCU "${UNINSTALL_REGISTRY_KEY}"
      ClearErrors
      DeleteRegKey HKLM "${UNINSTALL_REGISTRY_KEY}"
      ClearErrors
    ${EndIf}
  !endif
!macroend

; Never grant permissions through a junction/symlink planted in an old install.
; /L below also tells icacls to operate on a link rather than its target.
!macro requireDeckDirectoryNotReparsePoint DIRECTORY
  System::Call 'kernel32::GetFileAttributesW(w "${DIRECTORY}") i .r0'
  ${If} $0 != -1
    IntOp $0 $0 & 0x400
    ${If} $0 != 0
      DetailPrint "Refusing deck permissions on reparse point: ${DIRECTORY}"
      MessageBox MB_OK|MB_ICONSTOP "Cannot prepare deck storage: ${DIRECTORY} is a junction or symbolic link. No deck permissions were changed." /SD IDOK
      SetErrorLevel 1
      Abort "Unsafe deck storage path: ${DIRECTORY}"
    ${EndIf}
  ${EndIf}
!macroend

!macro customInstall
  !insertmacro requireDeckDirectoryNotReparsePoint "$INSTDIR"
  !insertmacro requireDeckDirectoryNotReparsePoint "$INSTDIR\data"
  !insertmacro requireDeckDirectoryNotReparsePoint "$INSTDIR\data\decks"
  ClearErrors
  CreateDirectory "$INSTDIR\data\decks"
  ${If} ${Errors}
    DetailPrint "Cannot create deck storage: $INSTDIR\data\decks"
    MessageBox MB_OK|MB_ICONSTOP "Cannot create deck storage: $INSTDIR\data\decks. Check directory permissions." /SD IDOK
    SetErrorLevel 1
    Abort "Cannot create deck storage."
  ${EndIf}

  ${If} $installMode == "all"
    ; Numeric SID works on localized Windows. Inheritable Modify is confined to
    ; decks: the install root, program files, data parent and asserts stay intact.
    ; No /T: do not explicitly rewrite ACLs of arbitrary existing descendants.
    nsExec::ExecToStack '"$SYSDIR\icacls.exe" "$INSTDIR\data\decks" /grant "*S-1-5-32-545:(OI)(CI)M" /L'
    Pop $R0
    Pop $R1
    DetailPrint "Deck storage permissions (exit $R0): $R1"
    ${If} $R0 != 0
      MessageBox MB_OK|MB_ICONSTOP "Cannot grant Users access to $INSTDIR\data\decks (exit $R0).$\r$\n$R1" /SD IDOK
      SetErrorLevel 1
      Abort "Deck storage permissions failed."
    ${EndIf}
  ${EndIf}
!macroend

!macro customRemoveFiles
  ${If} ${isUpdated}
    DetailPrint "Keeping existing installation files during update."
  ${Else}
    SetOutPath $TEMP
    ; Delete only named product files. Never sweep data, asserts, resources or
    ; the install root: older installs may contain downloaded/user-owned files
    ; anywhere in those trees. Remaining program resources are kept deliberately
    ; until a versioned ownership manifest can identify them safely.
    Delete "$INSTDIR\${APP_EXECUTABLE_FILENAME}"
    Delete "$INSTDIR\${UNINSTALL_FILENAME}"
    Delete "$INSTDIR\uninstallerIcon.ico"
    Delete "$INSTDIR\chrome_100_percent.pak"
    Delete "$INSTDIR\chrome_200_percent.pak"
    Delete "$INSTDIR\d3dcompiler_47.dll"
    Delete "$INSTDIR\dxcompiler.dll"
    Delete "$INSTDIR\dxil.dll"
    Delete "$INSTDIR\ffmpeg.dll"
    Delete "$INSTDIR\icudtl.dat"
    Delete "$INSTDIR\libEGL.dll"
    Delete "$INSTDIR\libGLESv2.dll"
    Delete "$INSTDIR\LICENSE.electron.txt"
    Delete "$INSTDIR\LICENSES.chromium.html"
    Delete "$INSTDIR\resources.pak"
    Delete "$INSTDIR\snapshot_blob.bin"
    Delete "$INSTDIR\v8_context_snapshot.bin"
    Delete "$INSTDIR\vk_swiftshader_icd.json"
    Delete "$INSTDIR\vk_swiftshader.dll"
    Delete "$INSTDIR\vulkan-1.dll"
    RMDir "$INSTDIR"
  ${EndIf}
!macroend
