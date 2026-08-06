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

!macro customRemoveFiles
  ${If} ${isUpdated}
    DetailPrint "Keeping existing installation files during update."
  ${Else}
    SetOutPath $TEMP
    RMDir /r $INSTDIR
  ${EndIf}
!macroend
