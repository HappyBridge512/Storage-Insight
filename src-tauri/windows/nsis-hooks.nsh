!macro NSIS_HOOK_POSTINSTALL
  CreateShortcut "$DESKTOP\Storage Insight.lnk" "$INSTDIR\storage-insight.exe"
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  Delete "$DESKTOP\Storage Insight.lnk"
!macroend
