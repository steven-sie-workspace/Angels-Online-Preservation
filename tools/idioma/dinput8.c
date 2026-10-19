/*
 * dinput8.dll de proxy para el cliente IGG: language.ini como en Global.
 *
 * Angel.exe/angel.dat importa de DINPUT8.dll una sola funcion,
 * DirectInput8Create, y Windows busca esa dll primero en la carpeta del
 * juego. Esta la sustituye: reenvia DirectInput8Create a la de sistema y,
 * al cargarse, lee language.ini y cambia en memoria el nombre del
 * manifiesto "setting\system_eng.xml" por system_cht / system_chs /
 * system_jpn (mismo largo). Los manifiestos los mete en update26.pak
 * tools/idioma_cliente.py.
 *
 *   [SETTING]
 *   Language=1    1 繁體中文  2 简体中文  3 日本語  4 English (igual que Global)
 *
 * Sin language.ini, o con 4, no toca nada. Deja lo que hizo en idioma.log.
 *
 * angel.dat va con UPX y ahi la cadena NO esta todavia cuando se carga esta
 * dll: la tabla de imports de UPX lista una funcion de cada dll original,
 * asi que Windows nos carga antes de que el stub descomprima nada. Lo que
 * el stub si importa es KERNEL32!GetProcAddress, y lo llama justo despues
 * de descomprimir, para rellenar los imports del juego. Asi que si la
 * cadena no aparece aqui se engancha ese hueco del IAT: la primera llamada
 * con la imagen ya descomprimida parchea y deja el IAT como estaba. Con
 * Angel.exe (sin UPX) la cadena ya esta y se parchea directamente. Se busca
 * en vez de usar la VA fija (0x8B53E4) para valer con los dos.
 *
 * Compilar: build.bat (x86, Build Tools de Visual Studio).
 */
#include <windows.h>
#include <string.h>

static HMODULE g_real;
static const char AGUJA[] = "setting\\system_eng.xml";

typedef HRESULT(WINAPI *DI8Create)(HINSTANCE, DWORD, REFIID, LPVOID *, LPUNKNOWN);

HRESULT WINAPI DirectInput8Create(HINSTANCE inst, DWORD ver, REFIID iid,
                                  LPVOID *out, LPUNKNOWN outer)
{
    DI8Create f;
    if (!g_real) {
        char ruta[MAX_PATH];
        GetSystemDirectoryA(ruta, MAX_PATH);   /* SysWOW64 en un proceso de 32 bits */
        lstrcatA(ruta, "\\dinput8.dll");
        g_real = LoadLibraryA(ruta);
    }
    f = g_real ? (DI8Create)GetProcAddress(g_real, "DirectInput8Create") : NULL;
    return f ? f(inst, ver, iid, out, outer) : E_FAIL;
}

static void carpeta_juego(char *buf, const char *fichero)
{
    char *barra;
    GetModuleFileNameA(NULL, buf, MAX_PATH);
    barra = strrchr(buf, '\\');
    if (barra) barra[1] = 0; else buf[0] = 0;
    lstrcatA(buf, fichero);
}

/* Cambia "eng" por `codigo` en cada aparicion de AGUJA dentro de la imagen. */
static int parchear(const char *codigo)
{
    BYTE *base = (BYTE *)GetModuleHandleA(NULL);
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    BYTE *p = base, *fin = base + nt->OptionalHeader.SizeOfImage;
    size_t n = sizeof(AGUJA);   /* con el 0 final */
    int hechos = 0;

    while (p < fin) {
        MEMORY_BASIC_INFORMATION mbi;
        BYTE *ini, *lim, *q;
        if (!VirtualQuery(p, &mbi, sizeof(mbi))) break;
        ini = (BYTE *)mbi.BaseAddress;
        lim = ini + mbi.RegionSize;
        if (lim > fin) lim = fin;
        if (mbi.State == MEM_COMMIT && !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD))) {
            for (q = ini; q + n <= lim; q++) {
                if (*q == 's' && memcmp(q, AGUJA, n) == 0) {
                    DWORD viejo;
                    BYTE *eng = q + (n - 1) - 7;   /* "eng.xml" */
                    if (VirtualProtect(eng, 3, PAGE_EXECUTE_READWRITE, &viejo)) {
                        memcpy(eng, codigo, 3);
                        VirtualProtect(eng, 3, viejo, &viejo);
                        hechos++;
                    }
                }
            }
        }
        p = lim;
    }
    return hechos;
}

static void anotar(const char *texto)
{
    char log[MAX_PATH];
    HANDLE h;
    DWORD escritos;
    carpeta_juego(log, "idioma.log");
    h = CreateFileA(log, FILE_APPEND_DATA, FILE_SHARE_READ, NULL, OPEN_ALWAYS,
                    FILE_ATTRIBUTE_NORMAL, NULL);
    if (h != INVALID_HANDLE_VALUE) {
        WriteFile(h, texto, lstrlenA(texto), &escritos, NULL);
        CloseHandle(h);
    }
}

/* --- gancho al GetProcAddress del stub de UPX --- */
static const char *g_codigo;
static FARPROC *g_hueco;          /* entrada del IAT enganchada */
static FARPROC g_original;        /* GetProcAddress de verdad */

static void desenganchar(void)
{
    DWORD viejo;
    if (g_hueco && VirtualProtect(g_hueco, sizeof(*g_hueco), PAGE_READWRITE, &viejo)) {
        *g_hueco = g_original;
        VirtualProtect(g_hueco, sizeof(*g_hueco), viejo, &viejo);
    }
    g_hueco = NULL;
}

static FARPROC WINAPI gancho_gpa(HMODULE mod, LPCSTR nombre)
{
    if (g_hueco) {
        int hechos = parchear(g_codigo);
        if (hechos) {
            char linea[96];
            wsprintfA(linea, "  tras descomprimir (GetProcAddress): %d sitio(s)\r\n", hechos);
            anotar(linea);
            desenganchar();
        }
    }
    return ((FARPROC(WINAPI *)(HMODULE, LPCSTR))g_original)(mod, nombre);
}

/* Busca en el IAT del exe el hueco que apunta a GetProcAddress y lo cambia. */
static int enganchar(void)
{
    BYTE *base = (BYTE *)GetModuleHandleA(NULL);
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    IMAGE_IMPORT_DESCRIPTOR *d = (IMAGE_IMPORT_DESCRIPTOR *)(base + dir.VirtualAddress);
    FARPROC real = GetProcAddress(GetModuleHandleA("kernel32.dll"), "GetProcAddress");

    if (!dir.VirtualAddress) return 0;
    for (; d->Name; d++) {
        FARPROC *t = (FARPROC *)(base + d->FirstThunk);
        for (; *t; t++) {
            DWORD viejo;
            if (*t != real) continue;
            if (!VirtualProtect(t, sizeof(*t), PAGE_READWRITE, &viejo)) return 0;
            g_original = real;
            g_hueco = t;
            *t = (FARPROC)gancho_gpa;
            VirtualProtect(t, sizeof(*t), viejo, &viejo);
            return 1;
        }
    }
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD motivo, LPVOID reservado)
{
    char ini[MAX_PATH], linea[160];
    int idioma, hechos = 0, enganchado = 0;

    if (motivo != DLL_PROCESS_ATTACH) return TRUE;
    DisableThreadLibraryCalls(inst);

    carpeta_juego(ini, "language.ini");
    idioma = GetPrivateProfileIntA("SETTING", "Language", 4, ini);
    if (idioma == 1) g_codigo = "cht";
    else if (idioma == 2) g_codigo = "chs";
    else if (idioma == 3) g_codigo = "jpn";
    if (g_codigo) {
        hechos = parchear(g_codigo);
        if (!hechos) enganchado = enganchar();
    }

    carpeta_juego(ini, "idioma.log");
    DeleteFileA(ini);
    wsprintfA(linea, "Language=%d -> %s, manifiesto cambiado en %d sitio(s)%s\r\n",
              idioma, g_codigo ? g_codigo : "eng (sin cambios)", hechos,
              enganchado ? ", esperando a que UPX descomprima" :
              (g_codigo && !hechos ? ", NO SE ENCONTRO (se queda en ingles)" : ""));
    anotar(linea);
    return TRUE;
}
