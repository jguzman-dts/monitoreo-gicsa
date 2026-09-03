' Lanza el monitor sin abrir ninguna ventana.
'
' La opcion "Hidden" de una tarea programada solo la oculta en la interfaz
' del Programador de tareas: no suprime la consola del proceso. Un .cmd
' lanzado en la sesion interactiva parpadea una ventana de cmd cada minuto,
' que es justo lo que estorba. Esta capa la elimina: WScript.Shell.Run con
' estilo de ventana 0 ejecuta el proceso completamente oculto.
'
' El tercer parametro en False significa que no espera a que termine, para
' que la tarea no quede colgada si una revision se alarga.

Option Explicit

Dim shell, fso, carpeta, comando

Set shell = CreateObject("WScript.Shell")
Set fso   = CreateObject("Scripting.FileSystemObject")

' Carpeta de este script, para no depender del directorio de trabajo.
carpeta = fso.GetParentFolderName(WScript.ScriptFullName)

comando = "cmd /c """ & carpeta & "\run.cmd"""

' 0 = ventana oculta, False = no esperar
shell.Run comando, 0, False
