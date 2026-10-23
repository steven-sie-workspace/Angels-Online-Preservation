"""Nombres de NPC y monstruos en el idioma del cliente, para el 0x0008.

El NPC_SPAWN lleva el nombre en el offset 16 (16 bytes) y el cliente pinta
ESE texto, no el de su monster.xml. Con language.ini en chino tradicional, el
East Playground seguia diciendo "Fire Elf" aunque setting\\cht\\monster.xml
diga 火元素 (23/10/2026): el nombre salia de la plantilla de la captura.

El servidor es local, asi que se mira el language.ini del cliente (1 cht,
2 chs, 3 jpn, 4 eng; ver tools/idioma_cliente.py) y las tablas de ese idioma
que tools/idioma_cliente.py metio en sus paks (SETTING\\<L>\\NPC.XML y
MONSTER.XML, que comparten numeracion), y el nombre va en el charset del
manifiesto de ese idioma (big5, gbk, shift-jis), cortado a 16 bytes sin
partir un caracter.

Solo se traduce si el nombre que manda el servidor es el de setting\\eng para
ese npc_type (entero o cortado a 16, como viene en las capturas): uno puesto a mano ("Monster Hatching Machine") se queda igual.
Sin language.ini, con Language=4 o sin tablas, todo sigue en ASCII como antes.
"""
import html
import logging
import pathlib
import re
import time
import zlib

import paks_cliente

log = logging.getLogger('nombres_cliente')

# language.ini -> (carpeta en los paks, charset del cliente)
IDIOMAS = {'1': ('CHT', 'cp950'), '2': ('CHS', 'gbk'), '3': ('JPN', 'cp932')}
TABLAS = ('NPC.XML', 'MONSTER.XML')
LARGO = 16
REVISAR_CADA = 30.0          # segundos entre miradas al language.ini y a los paks
# Los tests que leen el nombre de los bytes del 0x0008 lo ponen a False: si
# no, dependen del language.ini del cliente de quien los corra.
ACTIVO = True

_estado = {'firma': None, 'visto': 0.0, 'codec': None, 'nombres': {}}


def _cliente() -> pathlib.Path:
    import cliente_local
    return cliente_local.ruta_cliente()


def _idioma(cliente: pathlib.Path):
    try:
        texto = (cliente / 'language.ini').read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None
    m = re.search(r'^\s*Language\s*=\s*(\d+)', texto, re.M | re.I)
    return IDIOMAS.get(m.group(1)) if m else None


def _paks(cliente: pathlib.Path):
    return sorted((p for p in cliente.glob('*') if p.suffix.lower() == '.pak'
                   and paks_cliente.numero(p.name) >= -1),
                  key=lambda p: paks_cliente.numero(p.name))


def _leer(paks, nombres):
    """{nombre: texto} con la version vigente (la del pak de numero mas alto)."""
    quedan = {n.upper() for n in nombres}
    salida = {}
    for pak in reversed(paks):
        if not quedan:
            break
        data = pak.read_bytes()
        for nombre, crc, csize, usize, lhoff in paks_cliente._directorio(data):
            if nombre.upper() in quedan:
                quedan.discard(nombre.upper())
                raw = zlib.decompress(data[lhoff: lhoff + csize], -15)
                salida[nombre.upper()] = raw.decode('utf-8-sig', errors='replace')
    return salida


def _nombres(texto: str) -> dict:
    salida = {}
    for t in re.findall(r'<npc\b[^>]*/>', texto):
        i = re.search(r'(?<![^ <])編號="(\d+)"', t)
        n = re.search(r'(?<![^ <])名稱="([^"]*)"', t)
        if i and n:
            salida[int(i.group(1))] = html.unescape(n.group(1))
    return salida


def _cargar():
    """Rehace la tabla si cambiaron el language.ini o los paks."""
    ahora = time.monotonic()
    if ahora - _estado['visto'] < REVISAR_CADA:
        return
    _estado['visto'] = ahora
    try:
        cliente = _cliente()
        idioma = _idioma(cliente)
        paks = _paks(cliente) if idioma else []
        firma = (idioma, tuple((p.name, p.stat().st_mtime_ns) for p in paks))
        if firma == _estado['firma']:
            return
        _estado.update(firma=firma, codec=None, nombres={})
        if not idioma:
            return
        carpeta, codec = idioma
        pedidos = [f'SETTING\\{c}\\{t}' for c in ('ENG', carpeta) for t in TABLAS]
        textos = _leer(paks, pedidos)
        ingles, local = {}, {}
        for t in TABLAS:
            ingles.update(_nombres(textos.get(f'SETTING\\ENG\\{t}', '')))
            local.update(_nombres(textos.get(f'SETTING\\{carpeta}\\{t}', '')))
        nombres = {i: (ingles[i].strip().lower(), n) for i, n in local.items()
                   if i in ingles and n != ingles[i]}
        _estado.update(codec=codec, nombres=nombres)
        log.info('nombres de NPC/monstruo en %s: %d', carpeta, len(nombres))
    except Exception:
        log.exception('no se pudieron leer los nombres del cliente; van en ingles')


def _cortar(texto: str, codec: str) -> bytes:
    salida = b''
    for c in texto:
        b = c.encode(codec, errors='replace')
        if len(salida) + len(b) > LARGO:
            break
        salida += b
    return salida


def en_paquete(nombre, npc_type) -> bytes:
    """Los bytes del nombre para el offset 16 del 0x0008."""
    nombre = str(nombre)
    if not ACTIVO:
        return nombre.encode('ascii', 'replace')[:LARGO]
    _cargar()
    par = _estado['nombres'].get(npc_type) if _estado['codec'] else None
    # Las capturas traen el nombre ya cortado a 16 ("Bird Sharpshoote").
    if par and nombre.strip().lower() in (par[0], par[0][:LARGO].strip()):
        return _cortar(par[1], _estado['codec'])
    return nombre.encode('ascii', 'replace')[:LARGO]
