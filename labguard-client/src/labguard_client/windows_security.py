from __future__ import annotations

import os
from pathlib import Path


def secure_state_directory(path: Path) -> None:
    """Restrict state access to the enrolling account, LocalSystem, and Administrators."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        return
    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    current_sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    system_sid = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None)
    admins_sid = win32security.CreateWellKnownSid(win32security.WinBuiltinAdministratorsSid, None)
    dacl = win32security.ACL()
    inherit = win32security.OBJECT_INHERIT_ACE | win32security.CONTAINER_INHERIT_ACE
    for sid in (system_sid, admins_sid, current_sid):
        dacl.AddAccessAllowedAceEx(win32security.ACL_REVISION_DS, inherit, win32con.GENERIC_ALL, sid)
    def apply(target: Path) -> None:
        win32security.SetNamedSecurityInfo(str(target), win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, dacl, None)

    apply(path)
    for child in path.iterdir():
        if child.is_file():
            apply(child)
