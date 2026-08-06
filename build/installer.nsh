; Updates must overlay packaged files without deleting user-managed files.
; This keeps the separately downloaded asserts/ tree and any future external
; data in place while the installer writes the new package over it.
!macro customRemoveFiles
  ${If} ${isUpdated}
    DetailPrint "Keeping existing installation files during update."
  ${Else}
    SetOutPath $TEMP
    RMDir /r $INSTDIR
  ${EndIf}
!macroend
