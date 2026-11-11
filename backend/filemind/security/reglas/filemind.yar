/*
  Reglas YARA de FileMind (control "yara" de security/controls.py).

  Cada regla declara:
    severidad = "alta" | "media"   (alta suma 75 puntos, media 20; ver docs/protocolo_riesgo.md)
    tipo      = "ransomware" | "phishing"
    claro     = explicación en lenguaje claro (RNF7)

  Se aplican al archivo completo y a su contenido desempaquetado (entradas de
  comprimidos y de documentos Office, flujos PDF descomprimidos y código VBA).
  Se pueden agregar reglas propias en cualquier archivo .yar de esta carpeta.
*/

rule EICAR_Archivo_Prueba
{
    meta:
        severidad = "alta"
        tipo = "ransomware"
        claro = "Es el archivo de prueba estándar que todos los antivirus reconocen como virus."
    strings:
        $e = "X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    condition:
        $e
}

rule PE_Incrustado
{
    meta:
        severidad = "alta"
        tipo = "ransomware"
        claro = "Dentro del archivo hay un programa de Windows escondido."
    strings:
        $dos = "This program cannot be run in DOS mode"
    condition:
        uint16(0) != 0x5A4D and $dos
}

rule PE_En_Base64
{
    meta:
        severidad = "alta"
        tipo = "ransomware"
        claro = "El archivo esconde un programa de Windows codificado como texto."
    strings:
        $a = "TVqQAAMAAAAEAAAA"
        $b = "TVpQAAIAAAAEAA8A"
        $c = "TVoAAAAAAAAAAAAA"
        $d = "4d5a90000300000004000000ffff" nocase
    condition:
        any of them
}

rule PowerShell_Codificado_O_Descarga
{
    meta:
        severidad = "alta"
        tipo = "ransomware"
        claro = "El archivo trae instrucciones para que Windows descargue o ejecute comandos ocultos."
    strings:
        $enc = /powershell(\.exe)?[^\r\n]{0,80}\s-(e|en|enc|enco|encodedcommand)\s+[A-Za-z0-9+\/=]{16,}/ nocase
        $iex1 = /(iex|invoke-expression)\s*\(?\s*\(?\s*new-object\s+(system\.)?net\.webclient/ nocase
        $iex2 = /downloadstring\s*\(\s*['"]https?:/ nocase
        $hid = /powershell(\.exe)?[^\r\n]{0,40}-w(indowstyle)?\s+hidden/ nocase
    condition:
        any of them
}

rule VBA_Autoejecucion_Con_Comandos
{
    meta:
        severidad = "alta"
        tipo = "ransomware"
        claro = "Las macros se ejecutan solas al abrir el documento y lanzan comandos del sistema."
    strings:
        $a1 = "AutoOpen" nocase
        $a2 = "Document_Open" nocase
        $a3 = "Workbook_Open" nocase
        $a4 = "Auto_Open" nocase
        $s1 = "WScript.Shell" nocase
        $s2 = /\bShell\s*\(?\s*["A-Za-z]/ nocase
        $s3 = "ShellExecute" nocase
        $s4 = "CallByName" nocase
    condition:
        any of ($a*) and any of ($s*)
}

rule VBA_Descarga_Y_Guarda
{
    meta:
        severidad = "alta"
        tipo = "ransomware"
        claro = "Las macros descargan un archivo de internet y lo guardan en el equipo."
    strings:
        $d1 = "URLDownloadToFile" nocase
        $d2 = "MSXML2.XMLHTTP" nocase
        $d3 = "WinHttp.WinHttpRequest" nocase
        $w1 = "ADODB.Stream" nocase
        $w2 = "SaveToFile" nocase
    condition:
        $d1 or (any of ($d2, $d3) and any of ($w*))
}

rule Binarios_Del_Sistema_Abusados
{
    meta:
        severidad = "alta"
        tipo = "ransomware"
        claro = "El archivo usa herramientas de Windows para descargar o ejecutar programas sin que se note."
    strings:
        $c1 = /certutil(\.exe)?\s+[^\r\n]{0,30}-(urlcache|decode)/ nocase
        $c2 = /bitsadmin(\.exe)?\s+[^\r\n]{0,20}\/transfer/ nocase
        $c3 = /mshta(\.exe)?\s+["']?(https?:|vbscript:|javascript:)/ nocase
        $c4 = /regsvr32(\.exe)?\s+[^\r\n]{0,40}\/i:https?:/ nocase
        $c5 = /rundll32(\.exe)?\s+javascript:/ nocase
    condition:
        any of them
}

rule Ransomware_Borra_Copias_De_Seguridad
{
    meta:
        severidad = "alta"
        tipo = "ransomware"
        claro = "El archivo intenta borrar las copias de seguridad de Windows, algo típico del ransomware."
    strings:
        $v1 = /vssadmin(\.exe)?\s+delete\s+shadows/ nocase
        $v2 = /wmic(\.exe)?\s+shadowcopy\s+delete/ nocase
        $v3 = /bcdedit(\.exe)?\s+\/set\s+[^\r\n]{0,30}recoveryenabled\s+no/ nocase
        $v4 = /wbadmin(\.exe)?\s+delete\s+catalog/ nocase
        $v5 = /cipher(\.exe)?\s+\/w:/ nocase
    condition:
        any of them
}

rule Nota_De_Rescate
{
    meta:
        severidad = "alta"
        tipo = "ransomware"
        claro = "El contenido es una nota que pide un pago para devolver archivos cifrados."
    strings:
        $p1 = "bitcoin" nocase
        $p2 = "monero" nocase
        $p3 = " BTC"
        $t1 = ".onion" nocase
        $t2 = "Tor Browser" nocase
        $c1 = "cifrad" nocase
        $c2 = "encrypted" nocase
        $c3 = "descifrar" nocase
        $c4 = "decrypt" nocase
    condition:
        any of ($p*) and any of ($t*) and any of ($c*)
}

rule Office_DDE
{
    meta:
        severidad = "alta"
        tipo = "ransomware"
        claro = "El documento tiene un campo oculto que puede ejecutar comandos."
    strings:
        $d1 = /DDEAUTO\s/ nocase
        $d2 = /<w:instrText[^>]*>\s*DDE\s/ nocase
    condition:
        any of them
}

rule Excel4_Macro_Ejecuta
{
    meta:
        severidad = "alta"
        tipo = "ransomware"
        claro = "La hoja de cálculo tiene macros antiguas (Excel 4.0) que ejecutan programas."
    strings:
        $f1 = /=\s*EXEC\s*\(/ nocase
        $f2 = /=\s*CALL\s*\(\s*"(urlmon|kernel32|shell32)/ nocase
        $f3 = /=\s*REGISTER\s*\(\s*"(urlmon|kernel32|shell32)/ nocase
        $f4 = /<f>\s*EXEC\(/ nocase
    condition:
        any of them
}

rule PDF_Lanza_Programa
{
    meta:
        severidad = "alta"
        tipo = "ransomware"
        claro = "El PDF intenta abrir la consola de comandos de Windows."
    strings:
        $l = "/Launch"
        $c1 = "cmd.exe" nocase
        $c2 = "powershell" nocase
        $c3 = "mshta" nocase
    condition:
        $l and any of ($c*)
}

rule HTML_Contrabando_De_Archivos
{
    meta:
        severidad = "alta"
        tipo = "ransomware"
        claro = "La página arma y descarga un archivo escondido apenas se abre (técnica de contrabando HTML)."
    strings:
        $b1 = "atob(" nocase
        $b2 = "new Blob(" nocase
        $d1 = "createObjectURL" nocase
        $d2 = "msSaveOrOpenBlob" nocase
        $d3 = ".download" nocase
        $d4 = "download=" nocase
    condition:
        all of ($b*) and 2 of ($d*)
}

rule Script_WSH_Ejecuta
{
    meta:
        severidad = "media"
        tipo = "ransomware"
        claro = "El archivo contiene un script de Windows capaz de ejecutar programas."
    strings:
        $o1 = "ActiveXObject(\"WScript.Shell\")" nocase
        $o2 = "CreateObject(\"WScript.Shell\")" nocase
        $o3 = "ActiveXObject('WScript.Shell')" nocase
        $r1 = ".Run(" nocase
        $r2 = ".Exec(" nocase
        $r3 = ".Run " nocase
    condition:
        any of ($o*) and any of ($r*)
}

rule JavaScript_Ofuscado
{
    meta:
        severidad = "media"
        tipo = "ransomware"
        claro = "El archivo contiene código escondido o disfrazado."
    strings:
        $e1 = /eval\s*\(\s*(unescape|atob|String\.fromCharCode)\s*\(/ nocase
        $e2 = /String\.fromCharCode\s*\(\s*\d{2,3}\s*(,\s*\d{2,3}\s*){10,}/
        $e3 = /document\.write\s*\(\s*unescape\s*\(/ nocase
        $e4 = /(%u[0-9a-f]{4}){4,}/ nocase
    condition:
        any of them
}

rule HTML_Formulario_De_Credenciales
{
    meta:
        severidad = "media"
        tipo = "phishing"
        claro = "La página tiene un formulario que pide usuario y contraseña."
    strings:
        $f = /<form[^>]{0,200}action\s*=\s*["']?https?:\/\// nocase
        $p = /type\s*=\s*["']?password/ nocase
    condition:
        $f and $p
}

rule RTF_Objeto_Exploit
{
    meta:
        severidad = "alta"
        tipo = "ransomware"
        claro = "El documento trae un objeto usado en ataques conocidos contra Office."
    strings:
        $r = "{\\rt"
        $o = "\\objdata" nocase
        $c1 = "Equation.3" nocase
        $c2 = "4571756174696f6e2e33" nocase
        $c3 = "OLE2Link" nocase
        $c4 = "4f4c45324c696e6b" nocase
    condition:
        $r at 0 and $o and any of ($c*)
}

rule Acceso_Directo_LNK
{
    meta:
        severidad = "media"
        tipo = "ransomware"
        claro = "Es un acceso directo de Windows, que puede ejecutar comandos al abrirlo."
    condition:
        uint32(0) == 0x0000004C and uint32(4) == 0x00021401
}
