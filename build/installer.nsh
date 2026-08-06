; Keep the separately downloaded asset directory when NSIS replaces an old install.
; electron-builder's default update path removes the entire $INSTDIR first.
!macro customRemoveFiles
  StrCpy $R9 "$PLUGINSDIR\zz-assets-preserve"

  ${If} ${FileExists} "$INSTDIR\asserts\*.*"
    CreateDirectory "$R9"
    ClearErrors
    Rename "$INSTDIR\asserts" "$R9\asserts"
    ${If} ${Errors}
      Abort "Could not preserve the external asserts directory."
    ${EndIf}
  ${EndIf}

  ${If} ${isUpdated}
    CreateDirectory "$PLUGINSDIR\old-install"
    Push ""
    Call un.atomicRMDir
    Pop $R0

    ${If} $R0 != 0
      DetailPrint "File is busy, aborting: $R0"
      Push ""
      Call un.restoreFiles
      Pop $R0
      Abort "Could not replace the old installation."
    ${EndIf}
  ${EndIf}

  SetOutPath $TEMP
  RMDir /r $INSTDIR

  ${If} ${FileExists} "$R9\asserts\*.*"
    CreateDirectory "$INSTDIR"
    ClearErrors
    Rename "$R9\asserts" "$INSTDIR\asserts"
    ${If} ${Errors}
      Abort "Could not restore the external asserts directory."
    ${EndIf}
  ${EndIf}
!macroend
