import clr
clr.AddReference('AlibreScriptAddOn')
from AlibreScript.API import *
from AlibreScript.API import Windows as WindowsAPI

# The supported external-host constructor supplies the active session and
# parent form. Create New selection capture uses DT_Root directly.
Windows = lambda: WindowsAPI(DT_Session.Identifier, DT_ManagerPath, DT_Parent)
CurrentAssembly = lambda: Assembly(DT_Session)
execfile(DT_ManagerPath)