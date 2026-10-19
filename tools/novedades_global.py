"""Que trae el cliente oficial de Global que nuestro servidor no tiene.

POR QUE. El cliente de Global (carpeta ../Angels Online Global) se guarda
SOLO como referencia: no se copia nada de el al cliente IGG, porque cliente
y servidor tienen que seguir diciendo lo mismo (ver comprobar_sincronia.py).
Esta herramienta solo LEE y responde a la pregunta "que contenido nuevo hay
alla que valga la pena traer algun dia por el flujo normal de extraccion".

Global parte cada tabla en dos ficheros:
  * SETTING\\BASE\\ITEM.XML           los numeros   <道具 編號="4" .../>
  * SETTING\\ENG\\STRING\\STR_ITEM.XML  los textos    <表格字串 編號="1140000004" 文字1=.. 文字2=../>
El id del texto es PREFIJO + id (item 1140000000, magia 1180000000, ...) y
cada 文字N va a una columna nuestra (MAPEO, medido contra content.db: p.ej.
en item el 98% de los 文字2 coinciden con 基本名稱). Se fusionan los dos por
id y salen registros con la misma forma que los de content.db. level, shop
y quest no estan partidos (SETTING\\LEVEL.XML, SETTING\\SHOP.XML y
SETTING\\ENG\\STRING\\QUEST.XML ya con los textos dentro).

Los paks se aplican en orden data1 < data2 < data3 < update < update2 y el
de numero mas alto pisa al mismo id (la semantica de extract_content.py);
los ficheros de numeros y los de textos se fusionan cada uno por su lado.
Un texto sin registro de numeros se ignora: los STR_ITEMn traen 10.000
textos fijos por fichero (restos de items viejos, p.ej. la Navidad 2014)
pero BASE\\ITEM4..9 solo unos cientos de registros; sin numeros no hay item.

Los item*.xml se comparan como UNA bolsa: Global reparte los ids entre
item..item9 con otros cortes que IGG (su ITEM3 empieza en 20001, el nuestro
no), y por tabla saldrian miles de "nuevos" que solo cambiaron de fichero.

"changed" compara solo las columnas que existen en los dos lados: una columna
que IGG nunca tuvo no es un cambio de valor sino de formato (se cuenta aparte
en --columnas). Un cambio es "text" si solo difieren textos (nombres,
traducciones) y "values" si difiere algun numero.

    python tools/novedades_global.py                       resumen
    python tools/novedades_global.py --detalle             + ids nuevos y cambios
    python tools/novedades_global.py --tabla monster --detalle --max 50
    python tools/novedades_global.py --tabla item --id 87450   un registro
    python tools/novedades_global.py --columnas            columnas que solo tiene Global

No escribe nada: ni los .pak, ni content.db, ni la carpeta de Global.
"""
import argparse
import collections
import pathlib
import re
import sys
import zlib

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'tools'))
from comprobar_sincronia import Pak, orden_pak, tablas_del_servidor, DB  # noqa: E402
from extract_content import CLAVES, parse_texto  # noqa: E402

GLOBAL = RAIZ.parent / 'Angels Online Global'
TABLAS_ITEM = ['item'] + ['item%d' % i for i in range(2, 10)]

B = 'SETTING\\BASE\\'
S = 'SETTING\\ENG\\STRING\\'
_ITEM_TXT = {'文字1': '原型名稱', '文字2': '基本名稱', '文字3': '說明定義'}
# tabla nuestra: (ficheros de numeros, fichero de textos, prefijo, 文字N -> columna)
FUENTES = {
    'level':      (['SETTING\\LEVEL.XML'], None, 0, {}),
    'shop':       (['SETTING\\SHOP.XML'], None, 0, {}),
    'quest':      ([S + 'QUEST.XML'], None, 0, {}),
    'monster':    ([B + 'MONSTER.XML'], S + 'STR_MONSTER.XML', 1200000000, {'文字1': 'name'}),
    'npc':        ([B + 'NPC.XML'], S + 'STR_NPC.XML', 1200000000, {'文字1': 'name'}),
    'magic':      ([B + 'MAGIC.XML'], S + 'STR_MAGIC.XML', 1180000000,
                   {'文字1': 'name', '文字2': 'desc'}),
    'drop_table': ([B + 'DROP.XML'], S + 'STR_DROP.XML', 1100000000, {'文字1': 'monster_name'}),
    'stage':      ([B + 'STAGE.XML'], S + 'STR_STAGE.XML', 1290000000, {'文字1': 'name'}),
    'simpleai':   ([B + 'SIMPLEAI.XML'], None, 0, {}),
    'petattrib':  ([B + 'PETATTRIB.XML'], None, 0, {}),
    'doll':       ([B + 'DOLL.XML'], None, 0, {}),
    # Los nueve ficheros de items van juntos (ver arriba); cada STR_ITEMn
    # lleva los textos de su ITEMn con el mismo prefijo.
    'item':       ([B + t.upper() + '.XML' for t in TABLAS_ITEM],
                   [S + 'STR_' + t.upper() + '.XML' for t in TABLAS_ITEM],
                   1140000000, _ITEM_TXT),
}
# Columnas que se ensenan junto al id en el detalle, si existen.
RESUMEN = ('name', '基本名稱', '原型名稱', 'monster_name', '任務名稱', 'level',
           '物品等級', '物品類別', 'sprite_id')


def _es_numero(v) -> bool:
    return v is not None and re.fullmatch(r'-?\d+(\.\d+)?', str(v).strip()) is not None


def _registros(pak: Pak, nombre: str):
    """[(id, registro)] de un fichero del pak; ignora filas de encabezado."""
    try:
        txt = pak.leer(nombre).decode('utf-8', errors='replace').lstrip('﻿')
    except zlib.error:
        return []
    salida = []
    for r in parse_texto(txt)[1]:
        rid = next((r[k] for k in CLAVES if r.get(k) is not None), None)
        if rid is not None and str(rid).strip().lstrip('-').isdigit():
            salida.append((str(rid).strip(), r))
    return salida


def abrir_paks(carpeta: pathlib.Path) -> list:
    paks = sorted((p for p in carpeta.iterdir()
                   if p.suffix.lower() == '.pak' and orden_pak(p) is not None),
                  key=orden_pak)
    if not paks:
        raise SystemExit('no .pak files in %s' % carpeta)
    abiertos = []
    for p in paks:
        try:
            abiertos.append(Pak(p))
        except (ValueError, zlib.error) as e:
            print('  warning: %s could not be read (%s)' % (p.name, e))
    if not any(k.startswith(B) for pak in abiertos for k in pak.entradas):
        raise SystemExit('%s has no SETTING\\BASE files: not the Global layout '
                         '(use tools/comprobar_sincronia.py for IGG clients)' % carpeta)
    return abiertos


def tablas_de_global(paks: list) -> dict:
    """{tabla: {id: (registro, ultimo pak, primer pak)}}, numeros y textos fusionados.

    Los BASE\\*.XML de Global son acumulativos (update2 trae todo otra vez),
    asi que el pak que dice "desde cuando existe" es el primero.
    """
    salida = {}
    for tabla, (numeros, textos, prefijo, mapeo) in FUENTES.items():
        fusion = {}
        for pak in paks:
            for nombre in numeros:
                if nombre in pak.entradas:
                    for rid, r in _registros(pak, nombre):
                        primero = fusion[rid][2] if rid in fusion else pak.ruta.stem
                        fusion[rid] = (r, pak.ruta.stem, primero)
        if not fusion:
            continue
        cadenas = {}
        for pak in paks:
            for nombre in ([textos] if isinstance(textos, str) else textos or []):
                if nombre in pak.entradas:
                    for sid, r in _registros(pak, nombre):
                        cadenas[int(sid) - prefijo] = r
        for rid, (r, *_) in fusion.items():
            c = cadenas.get(int(rid))
            if c:
                for k, col in mapeo.items():
                    if c.get(k):
                        r[col] = c[k]
        salida[tabla] = fusion
    return salida


def servidor_unido() -> dict:
    """content.db con los item* en una sola bolsa, como en tablas_de_global."""
    s = tablas_del_servidor()
    items = {}
    for t in TABLAS_ITEM:
        items.update(s.pop(t, {}))
    if items:
        s['item'] = items
    return s


def _limpio(r: dict) -> dict:
    return {k: v for k, v in r.items() if v not in (None, '')}


def comparar(glob: dict, serv: dict) -> dict:
    """{tabla: {'nuevos', 'solo_serv', 'texto', 'valores', 'cols_nuevas'}}."""
    salida = {}
    for tabla in FUENTES:
        g, s = glob.get(tabla, {}), serv.get(tabla, {})
        if not g and not s:
            continue
        cols_s = set().union(*(r.keys() for r in s.values())) if s else set()
        cols_g = collections.Counter(k for r, *_ in g.values() for k in _limpio(r))
        texto, valores = [], []
        for rid in set(g) & set(s):
            rg, rs = _limpio(g[rid][0]), s[rid]
            difs = [k for k in (set(rg) | set(rs)) & cols_s & set(cols_g)
                    if rg.get(k) != rs.get(k)]
            if not difs:
                continue
            if any(_es_numero(rg.get(k)) or _es_numero(rs.get(k)) for k in difs):
                valores.append(rid)
            else:
                texto.append(rid)
        salida[tabla] = {
            'global': len(g), 'servidor': len(s),
            'nuevos': sorted(set(g) - set(s), key=int),
            'pruebas': sum(1 for i in set(g) - set(s) if _es_prueba(g[i][0])),
            'solo_serv': sorted(set(s) - set(g), key=int),
            'texto': sorted(texto, key=int), 'valores': sorted(valores, key=int),
            'cols_nuevas': {k: n for k, n in cols_g.items() if k not in cols_s},
        }
    return salida


# Huecos y registros de prueba de los desarrolladores: 測試 (prueba), 空號
# (numero vacio), 編號上限 / 用到 / 用完 (marcas de "hasta aqui llega el rango").
PRUEBA = re.compile(r'測試|空號|編號上限|用到|用完|^test', re.I)


def _es_prueba(r: dict) -> bool:
    nombre = r.get('name') or r.get('基本名稱') or r.get('monster_name') or ''
    return bool(PRUEBA.search(nombre))


def _etiqueta(r: dict) -> str:
    partes = []
    for k in RESUMEN:
        if r.get(k) and k not in ('原型名稱',):
            v = r[k]
            if k == '基本名稱' and r.get('原型名稱'):
                v = '%s %s' % (r['原型名稱'], v)
            partes.append('%s=%s' % (k, v))
    return ', '.join(partes[:4])


def _difs(rg: dict, rs: dict, cols: set) -> list:
    return sorted(k for k in (set(rg) | set(rs)) & cols if rg.get(k) != rs.get(k))


def informe(res: dict, glob: dict, serv: dict, detalle: bool, maximo: int, columnas: bool):
    print('\n%-11s %8s %8s %6s %6s %9s %9s %11s' % ('table', 'global', 'server', 'NEW',
                                                   'test', 'chg-vals', 'chg-text', 'server-only'))
    for tabla, d in res.items():
        print('%-11s %8d %8d %6d %6d %9d %9d %11d' % (
            tabla, d['global'], d['servidor'], len(d['nuevos']), d['pruebas'],
            len(d['valores']), len(d['texto']), len(d['solo_serv'])))
    print('\nNEW = id only in Global (test = of those, dev placeholders like 測試/空號);'
          '\nchg-vals = same id, some number differs; chg-text = only names/descriptions'
          '\ndiffer; server-only = IGG ids Global lacks.')

    if columnas:
        print('\nColumns only Global has (records using them):')
        for tabla, d in res.items():
            if d['cols_nuevas']:
                cols = sorted(d['cols_nuevas'].items(), key=lambda x: -x[1])
                print('  %-11s %s' % (tabla, ', '.join('%s(%d)' % c for c in cols[:15])
                                     + (' ...' if len(cols) > 15 else '')))

    if not detalle:
        return
    for tabla, d in res.items():
        g, s = glob.get(tabla, {}), serv.get(tabla, {})
        cols_s = set().union(*(r.keys() for r in s.values())) if s else set()
        if d['nuevos']:
            por_pak = collections.Counter(g[i][2] for i in d['nuevos'])
            print('\n[%s] %d new ids (first seen in: %s)' % (
                tabla, len(d['nuevos']), ', '.join('%s=%d' % x for x in sorted(por_pak.items()))))
            # Lo real antes que las pruebas; dentro, lo mas reciente primero.
            orden = sorted(d['nuevos'], key=lambda i: (_es_prueba(g[i][0]),
                                                       -orden_pak(pathlib.Path(g[i][2])), -int(i)))
            for rid in orden[:maximo]:
                print('    %-8s [%s]%s %s' % (rid, g[rid][2], ' (test)' if _es_prueba(g[rid][0]) else '',
                                           _etiqueta(_limpio(g[rid][0]))))
            if len(orden) > maximo:
                print('    ... (+%d, use --max)' % (len(orden) - maximo))
        if d['valores']:
            print('\n[%s] %d ids with changed values' % (tabla, len(d['valores'])))
            campos = collections.Counter(k for rid in d['valores']
                                         for k in _difs(_limpio(g[rid][0]), s[rid], cols_s)
                                         if _es_numero(g[rid][0].get(k)) or _es_numero(s[rid].get(k)))
            print('    most changed columns: ' + ', '.join('%s(%d)' % c for c in campos.most_common(8)))
            for rid in d['valores'][:min(maximo, 5)]:
                rg = _limpio(g[rid][0])
                print('    id %s [%s] %s' % (rid, g[rid][1], _etiqueta(s[rid])))
                for k in _difs(rg, s[rid], cols_s)[:6]:
                    print('      %s: global=%r server=%r' % (k, rg.get(k), s[rid].get(k)))


def un_registro(tabla: str, rid: str, glob: dict, serv: dict):
    rg = _limpio(glob.get(tabla, {}).get(rid, ({}, None))[0])
    rs = serv.get(tabla, {}).get(rid, {})
    _, ultimo, primero = glob.get(tabla, {}).get(rid, (None, '-', '-'))
    print('\n%s %s   global: first in %s, last in %s   on server: %s'
          % (tabla, rid, primero, ultimo, 'yes' if rs else 'no'))
    if not rg and not rs:
        print('  not found on either side')
        return
    for k in sorted(set(rg) | set(rs)):
        a, b = rg.get(k), rs.get(k)
        marca = '  ' if a == b else ('+ ' if b is None else ('- ' if a is None else '* '))
        print('  %s%-14s global=%-30r server=%r' % (marca, k, a, b))
    print('  (+ only Global, - only server, * differs)')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--global', dest='carpeta', type=pathlib.Path, default=GLOBAL,
                    help='Global client folder (default: ../Angels Online Global)')
    ap.add_argument('--tabla', help='only this table (item, monster, npc, magic, quest, shop, ...)')
    ap.add_argument('--detalle', action='store_true', help='list new ids and value changes')
    ap.add_argument('--max', type=int, default=20, help='ids per list in --detalle (default 20)')
    ap.add_argument('--id', help='show one record side by side (needs --tabla)')
    ap.add_argument('--columnas', action='store_true', help='columns only Global has')
    a = ap.parse_args()
    if a.tabla and a.tabla.startswith('item'):
        a.tabla = 'item'
    if a.tabla and a.tabla not in FUENTES:
        raise SystemExit('unknown table %s (one of: %s)' % (a.tabla, ', '.join(FUENTES)))
    if a.id and not a.tabla:
        raise SystemExit('--id needs --tabla')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    print('global: %s' % a.carpeta)
    print('server: %s' % DB.relative_to(RAIZ))
    paks = abrir_paks(a.carpeta)
    print('paks:   %s' % ' < '.join(p.ruta.name for p in paks))
    glob = tablas_de_global(paks)
    serv = servidor_unido()
    if a.tabla:
        glob = {a.tabla: glob.get(a.tabla, {})}
        serv = {a.tabla: serv.get(a.tabla, {})}
    if a.id:
        un_registro(a.tabla, a.id, glob, serv)
        return 0
    informe(comparar(glob, serv), glob, serv, a.detalle, a.max, a.columnas)
    return 0


if __name__ == '__main__':
    sys.exit(main())
