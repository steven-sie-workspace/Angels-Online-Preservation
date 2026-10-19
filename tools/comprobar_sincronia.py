"""Comprueba que el servidor y el cliente siguen diciendo lo mismo.

POR QUE. El servidor manda numeros (item 83266, npc 512, magia 1) y el
cliente los busca en las tablas de sus .pak. Si alguien toca un .pak y no
vuelve a extraer, los dos lados dejan de coincidir y salen los fallos
raros: objetos que se ven pero no se pueden usar, NPC invisibles, precios
que no cuadran. Esta herramienta lee los .pak DIRECTAMENTE (no hace falta
extracted_paks) con la misma semantica de extract_content.py -- el pak de
numero mas alto pisa al mismo id -- y lo compara con:

  * corpus/content.db                  (las tablas que usa el servidor)
  * server/plantillas/client_tables.json  (magic_xml, npc_sprites, item_cats)

    python tools/comprobar_sincronia.py                 contra el cliente configurado
    python tools/comprobar_sincronia.py --cliente RUTA  contra otro cliente
    python tools/comprobar_sincronia.py --tabla item9 --detalle   ver ids concretos

Sale con codigo 1 si hay diferencias, para poder usarlo antes de arrancar.

El cliente de Global NO vale aqui: guarda las tablas en otro formato
(SETTING\\BASE + ficheros STRING) y se rechaza con un aviso.
"""
import argparse
import json
import pathlib
import re
import sqlite3
import struct
import sys
import zlib

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'tools'))
from extract_content import ARCHIVOS, CLAVES, parse_texto  # noqa: E402

DB = RAIZ / 'corpus' / 'content.db'
JSON = RAIZ / 'server' / 'plantillas' / 'client_tables.json'
TABLAS_ITEM = ['item'] + ['item%d' % i for i in range(2, 10)]


def _cliente_configurado() -> pathlib.Path:
    """RUTA_CLIENTE de configuracion.py, sin importar el servidor entero."""
    txt = (RAIZ / 'server' / 'configuracion.py').read_text(encoding='utf-8')
    m = re.search(r"^RUTA_CLIENTE\s*=\s*r?['\"]([^'\"]+)['\"]", txt, re.M)
    return pathlib.Path(m.group(1)) if m else RAIZ.parent / 'client'


def orden_pak(p: pathlib.Path) -> int:
    """data1 < data2 < data3 < update < update2 < ... < update26.

    Global trae data1/2/3; IGG solo data1. Por nombre NO vale (ver paks.py).
    """
    n = p.stem.lower()
    m = re.fullmatch(r'data(\d+)', n)
    if m:
        return int(m.group(1)) - 100
    if n == 'update':
        return 0
    m = re.fullmatch(r'update(\d+)', n)
    return int(m.group(1)) if m else None


class Pak:
    """Lector de solo lectura del formato OD\\x05\\x06 (ver cliente_local.py).

    Lee solo el directorio y las entradas que se piden: data1 pesa 700 MB.
    """

    def __init__(self, ruta: pathlib.Path):
        self.ruta = ruta
        self.entradas = {}
        with open(ruta, 'rb') as f:
            f.seek(-22, 2)
            fin = f.tell()
            eocd = bytearray(f.read(22))
            if eocd[:4] != b'OD\x05\x06':
                raise ValueError('%s no tiene firma OD\\x05\\x06' % ruta.name)
            for i in range(4, 22):
                eocd[i] ^= (3 * i - 91) & 0xFF
            cd_offset = struct.unpack_from('<I', eocd, 16)[0]
            # El tamano comprimido del directorio es u16 en la cabecera y en
            # los paks grandes no cabe: se lee hasta la cola y zlib para solo.
            f.seek(cd_offset + 4)
            cd_raw = bytearray(f.read(fin - cd_offset - 4))
        cd_raw[0] ^= 0x7A
        cd = zlib.decompressobj().decompress(bytes(cd_raw))
        off = 0
        while off + 46 <= len(cd):
            csize, = struct.unpack_from('<I', cd, off + 20)
            fn_len, ex_len, cm_len = struct.unpack_from('<HHH', cd, off + 28)
            lhoff, = struct.unpack_from('<I', cd, off + 42)
            nombre = cd[off + 46:off + 46 + fn_len].decode('ascii', 'ignore')
            self.entradas[nombre.upper().replace('/', '\\')] = (lhoff, csize)
            off += 46 + fn_len + ex_len + cm_len

    def leer(self, nombre: str) -> bytes:
        lhoff, csize = self.entradas[nombre]
        with open(self.ruta, 'rb') as f:
            f.seek(lhoff)
            return zlib.decompress(f.read(csize), -15)


def tablas_del_cliente(carpeta: pathlib.Path) -> dict:
    """{tabla: {id: (registro, pak)}} con la fusion de extract_content.py."""
    paks = sorted((p for p in carpeta.iterdir()
                   if p.suffix.lower() == '.pak' and orden_pak(p) is not None),
                  key=orden_pak)
    if not paks:
        raise SystemExit('no hay .pak en %s' % carpeta)
    abiertos = []
    for p in paks:
        try:
            abiertos.append(Pak(p))
        except (ValueError, zlib.error) as e:
            print('  aviso: %s no se pudo leer (%s)' % (p.name, e))
    # Global parte cada tabla en dos: los numeros en SETTING\BASE\ y los
    # nombres en SETTING\<idioma>\STRING\STR_*.XML. Leido como si fuera IGG
    # solo encuentra restos viejos de SETTING\ y da miles de falsos avisos.
    if any(k.startswith('SETTING\\BASE\\') for pak in abiertos for k in pak.entradas):
        raise SystemExit('%s uses the Global layout (SETTING\\BASE + STRING '
                         'files); this check only understands the IGG layout.'
                         % carpeta)
    salida = {}
    for archivo in ARCHIVOS:
        tabla = {'drop': 'drop_table'}.get(archivo[:-4], archivo[:-4])
        fusion = {}
        for pak in abiertos:
            for sub in ('SETTING\\ENG\\', 'SETTING\\'):
                clave = sub + archivo.upper()
                if clave not in pak.entradas:
                    continue
                txt = pak.leer(clave).decode('utf-8', errors='replace')
                for r in parse_texto(txt)[1]:
                    rid = next((r[k] for k in CLAVES if r.get(k) is not None), None)
                    if rid is None or not str(rid).strip().lstrip('-').isdigit():
                        continue
                    fusion[rid] = (r, pak.ruta.stem)
                break
        if fusion:
            salida[tabla] = fusion
    return salida


def tablas_del_servidor() -> dict:
    """{tabla: {id: registro}} de content.db, sin la columna _pak."""
    con = sqlite3.connect('file:%s?mode=ro' % DB.as_posix(), uri=True)
    con.row_factory = sqlite3.Row
    salida = {}
    for (t,) in con.execute("select name from sqlite_master where type='table'"):
        filas = con.execute('select * from "%s"' % t).fetchall()
        if not filas:
            continue
        clave = next((k for k in CLAVES if k in filas[0].keys()), None)
        if clave is None:
            continue
        salida[t] = {str(f[clave]): {k: f[k] for k in f.keys()
                                    if k != '_pak' and f[k] is not None}
                     for f in filas}
    con.close()
    return salida


# Lo que el propio servidor le cambia al cliente a proposito (cliente_local.py)
# y por que no es un desajuste:
#   * 收購價格 = precio//2 en el equipo ligado: es justo lo que el servidor
#     ya cobra cuando content.db no trae la columna (_precio_venta en app.py);
#   * 天氣 / 裝飾地圖檔 de stage: la nieve y los decorados de temporada, que
#     son solo de pantalla.
SOLO_PANTALLA = {'stage': {'天氣', '裝飾地圖檔'}}


def _parche_conocido(tabla, rc, rs) -> bool:
    difs = {k for k in set(rc) | set(rs) if rc.get(k) != rs.get(k)}
    if difs and difs <= SOLO_PANTALLA.get(tabla, set()):
        return True
    if difs == {'收購價格'} and rs.get('收購價格') is None:
        try:
            return int(rc['收購價格']) == max(1, int(rc.get('price', 0)) // 2)
        except (TypeError, ValueError):
            return False
    return False


def _muestra(ids, n=12) -> str:
    ids = sorted(ids, key=lambda x: int(x) if x.lstrip('-').isdigit() else 0)
    txt = ', '.join(ids[:n])
    return txt + (' ... (+%d)' % (len(ids) - n) if len(ids) > n else '')


def comparar(cliente: dict, servidor: dict, solo=None, detalle=False) -> int:
    problemas = 0
    print('\n%-12s %8s %8s %11s %11s %8s %9s' % ('table', 'client', 'server',
                                               'client-only', 'server-only',
                                               'changed', 'expected'))
    for tabla in sorted(set(cliente) | set(servidor)):
        if solo and tabla != solo:
            continue
        c, s = cliente.get(tabla, {}), servidor.get(tabla, {})
        solo_c = set(c) - set(s)
        solo_s = set(s) - set(c)
        cambiados, esperados = [], 0
        for rid in set(c) & set(s):
            rc = {k: v for k, v in c[rid][0].items() if v is not None}
            if rc == s[rid]:
                continue
            if _parche_conocido(tabla, rc, s[rid]):
                esperados += 1
            else:
                cambiados.append(rid)
        n = len(solo_c) + len(solo_s) + len(cambiados)
        problemas += n
        print('%-12s %8d %8d %11d %11d %8d %9d%s' % (
            tabla, len(c), len(s), len(solo_c), len(solo_s), len(cambiados),
            esperados, '' if n else '  ok'))
        if detalle and n:
            if solo_c:
                print('    only in client: ' + _muestra(solo_c))
            if solo_s:
                print('    only in server: ' + _muestra(solo_s))
            for rid in sorted(cambiados, key=int)[:5]:
                rc, rs = c[rid][0], s[rid]
                difs = sorted(k for k in set(rc) | set(rs) if rc.get(k) != rs.get(k))
                print('    id %s (client pak %s):' % (rid, c[rid][1]))
                for k in difs[:6]:
                    print('      %s: client=%r server=%r' % (k, rc.get(k), rs.get(k)))
    return problemas


def comparar_json(cliente: dict, detalle=False) -> int:
    """Los ids de client_tables.json tienen que existir en el cliente."""
    if not JSON.exists():
        return 0
    d = json.loads(JSON.read_text(encoding='utf-8'))
    items = set().union(*(cliente.get(t, {}).keys() for t in TABLAS_ITEM))
    npcs = set(cliente.get('npc', {})) | set(cliente.get('monster', {}))
    pruebas = [('magic_xml', set(cliente.get('magic', {}))),
               ('npc_sprites', npcs),
               ('item_cats', items),
               ('invest_items', items)]
    problemas = 0
    print('\nclient_tables.json')
    for clave, validos in pruebas:
        if clave not in d or not validos:
            continue
        faltan = set(map(str, d[clave])) - validos
        problemas += len(faltan)
        print('  %-14s %6d ids, %5d missing in client%s'
              % (clave, len(d[clave]), len(faltan), '' if faltan else '  ok'))
        if detalle and faltan:
            print('    ' + _muestra(faltan))
    return problemas


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--cliente', type=pathlib.Path, default=None)
    ap.add_argument('--tabla', help='only this table (e.g. item9, npc, drop_table)')
    ap.add_argument('--detalle', action='store_true', help='list the ids that differ')
    a = ap.parse_args()

    carpeta = a.cliente or _cliente_configurado()
    print('client: %s' % carpeta)
    print('server: %s' % DB.relative_to(RAIZ))
    cliente = tablas_del_cliente(carpeta)
    servidor = tablas_del_servidor()
    n = comparar(cliente, servidor, a.tabla, a.detalle)
    if not a.tabla:
        n += comparar_json(cliente, a.detalle)
    print('\n%s' % ('IN SYNC' if n == 0 else
                    '%d differences -- re-extract (tools/extract_content.py) '
                    'or check the last .pak edit' % n))
    return 1 if n else 0


if __name__ == '__main__':
    sys.exit(main())
