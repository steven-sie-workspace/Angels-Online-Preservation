"""Nombres de NPC, monstruos, items y habilidades en el idioma del cliente.

El NPC_SPAWN (0x0008) lleva el nombre en el offset 16 (16 bytes) y el cliente
pinta ESE texto, no el de su monster.xml. Con language.ini en chino
tradicional, el East Playground seguia diciendo "Fire Elf" aunque
setting\\cht\\monster.xml diga 火元素 (23/10/2026): el nombre salia de la
plantilla de la captura.

Lo mismo pasa con los carteles 0x000D: la plantilla es del cliente
("獲得%s。", "%s技能獲得%s經驗值。") pero el %s lo pone el servidor, y salia
"獲得Blue Potion" o "Life技能獲得2000經驗值". `texto()` traduce ese %s cuando
es entero un nombre que el cliente tiene (item, habilidad, hechizo, NPC,
monstruo), o "N Gold", o un nombre con su cantidad ("3x Blue Potion").

El servidor es local, asi que se mira el language.ini del cliente (1 cht,
2 chs, 3 jpn, 4 eng; ver tools/idioma_cliente.py) y las tablas de ese idioma
que tools/idioma_cliente.py metio en sus paks (SETTING\\<L>\\...), y el texto
va en el charset del manifiesto de ese idioma (big5, gbk, shift-jis).

En el 0x0008 solo se traduce si el nombre que manda el servidor es el de
setting\\eng para ese npc_type (entero o cortado a 16, como viene en las
capturas): uno puesto a mano ("Monster Hatching Machine") se queda igual.
Sin language.ini, con Language=4 o sin tablas, todo sigue en ASCII como antes.
"""
import collections
import html
import logging
import pathlib
import re
import struct
import threading
import time
import zlib

import paks_cliente

log = logging.getLogger('nombres_cliente')

# language.ini -> (carpeta en los paks, charset del cliente, el oro)
IDIOMAS = {'1': ('CHT', 'cp950', '金幣'), '2': ('CHS', 'gbk', '金币'),
           '3': ('JPN', 'cp932', 'Gold')}
_ITEMS = ['ITEM.XML'] + [f'ITEM{i}.XML' for i in range(2, 10)]
# fichero -> (etiqueta, atributo del nombre). NPC y MONSTER comparten
# numeracion: son los npc_type del 0x0008.
TABLAS = {'NPC.XML': ('npc', '名稱'), 'MONSTER.XML': ('npc', '名稱'),
          'SKILL.XML': ('技能', '名稱'), 'MAGIC.XML': ('法術', '名稱'),
          'QUEST.XML': ('任務', '任務名稱'), 'STAGE.XML': ('場景', '名稱'),
          **{f: ('道具', '基本名稱') for f in _ITEMS}}
LARGO = 16
REVISAR_CADA = 30.0          # segundos entre miradas al language.ini y a los paks
# Los tests que leen el nombre de los bytes del 0x0008 lo ponen a False: si
# no, dependen del language.ini del cliente de quien los corra.
ACTIVO = True

_estado = {'firma': None, 'visto': 0.0, 'codec': None, 'oro': None,
           'nombres': {}, 'textos': {}, 'habilidades': {}, 'cargando': False}


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
        # Solo el directorio del final y las entradas pedidas: leer el pak
        # entero (data1 y update26 pasan de 60 MB) paraba el servidor segundos.
        with open(pak, 'rb') as f:
            f.seek(0, 2)
            largo = f.tell()
            f.seek(largo - 22)
            eocd = bytearray(f.read(22))
            for i in range(4, 22):
                eocd[i] ^= (3 * i - 91) & 0xFF
            cd_off = struct.unpack_from('<I', eocd, 16)[0]
            f.seek(cd_off)
            cola = f.read()
            # _directorio solo mira el final y los offsets del directorio:
            # se le da la cola con un relleno delante para que cuadren.
            for nombre, crc, csize, usize, lhoff in paks_cliente._directorio(_Cola(cd_off, cola)):
                if nombre.upper() in quedan:
                    quedan.discard(nombre.upper())
                    f.seek(lhoff)
                    raw = zlib.decompressobj(-15).decompress(f.read(csize))
                    salida[nombre.upper()] = raw.decode('utf-8-sig', errors='replace')
    return salida


class _Cola:
    """Los bytes de un pak desde `inicio`, indexables como si fuera entero."""

    def __init__(self, inicio, datos):
        self.inicio, self.datos = inicio, datos

    def __len__(self):
        return self.inicio + len(self.datos)

    def __getitem__(self, k):
        if isinstance(k, slice):
            a = len(self) + k.start if k.start is not None and k.start < 0 else (k.start or 0)
            b = len(self) if k.stop is None else (len(self) + k.stop if k.stop < 0 else k.stop)
            return self.datos[a - self.inicio: b - self.inicio]
        return self.datos[k - self.inicio]


def _nombres(texto: str, etiqueta='npc', attr='名稱') -> dict:
    salida = {}
    for t in re.findall(f'<{etiqueta}\\b[^>]*/>', texto):
        i = re.search(r'(?<![^ <])編號="(\d+)"', t)
        n = re.search(f'(?<![^ <]){attr}="([^"]*)"', t)
        if i and n:
            salida[int(i.group(1))] = html.unescape(n.group(1))
    return salida


def _clave(s: str) -> str:
    return ' '.join(s.split()).lower()


def _construir(firma, idioma, paks):
    """Lee las tablas y las pone en _estado de una vez."""
    try:
        if not idioma:
            _estado.update(firma=firma, codec=None, oro=None, nombres={}, textos={},
                           habilidades={})
            return
        carpeta, codec, oro = idioma
        textos = _leer(paks, [f'SETTING\\{c}\\{t}' for c in ('ENG', carpeta) for t in TABLAS])
        nombres = {}
        votos = collections.defaultdict(collections.Counter)
        votos_hab = collections.defaultdict(collections.Counter)
        for t, (etiqueta, attr) in TABLAS.items():
            ingles = _nombres(textos.get(f'SETTING\\ENG\\{t}', ''), etiqueta, attr)
            local = _nombres(textos.get(f'SETTING\\{carpeta}\\{t}', ''), etiqueta, attr)
            for i, n in local.items():
                if i in ingles and n != ingles[i] and ingles[i].strip():
                    votos[_clave(ingles[i])][n] += 1
                    if t in ('SKILL.XML', 'MAGIC.XML'):
                        votos_hab[_clave(ingles[i])][n] += 1
                    if etiqueta == 'npc':
                        nombres[i] = (ingles[i].strip().lower(), n)
        # Un mismo nombre ingles puede tener varios (dos "Axeman Lucky Bag"):
        # el que mas sale.
        diccionario = {k: c.most_common(1)[0][0] for k, c in votos.items()}
        # En los carteles de habilidad manda skill.xml/magic.xml: la habilidad
        # "Sword" es 劍術, el item "Sword" es 細劍.
        habilidades = {k: c.most_common(1)[0][0] for k, c in votos_hab.items()}
        _estado.update(firma=firma, codec=codec, oro=oro, nombres=nombres,
                       textos=diccionario, habilidades=habilidades)
        log.info('nombres en %s: %d NPC/monstruos, %d textos', carpeta,
                 len(nombres), len(diccionario))
    except Exception:
        _estado['firma'] = firma
        log.exception('no se pudieron leer los nombres del cliente; van en ingles')
    finally:
        _estado['cargando'] = False


def _cargar(esperar=False):
    """Mira cada REVISAR_CADA si cambiaron el language.ini o los paks. Leer las
    tablas tarda un par de segundos: salvo con `esperar` (al arrancar) se hace
    en un hilo y mientras tanto siguen valiendo las de antes."""
    ahora = time.monotonic()
    if not esperar and (ahora - _estado['visto'] < REVISAR_CADA or _estado['cargando']):
        return
    _estado['visto'] = ahora
    try:
        cliente = _cliente()
        idioma = _idioma(cliente)
        paks = _paks(cliente) if idioma else []
        firma = (idioma, tuple((p.name, p.stat().st_mtime_ns) for p in paks))
    except Exception:
        log.exception('no se pudo mirar el cliente')
        return
    if firma == _estado['firma']:
        return
    _estado['cargando'] = True
    if esperar:
        _construir(firma, idioma, paks)
    else:
        threading.Thread(target=_construir, args=(firma, idioma, paks),
                         name='nombres_cliente', daemon=True).start()


def precargar():
    """Carga las tablas ahora (al arrancar el servidor)."""
    _cargar(esperar=True)


def _cortar(texto: str, codec: str, largo: int = LARGO) -> bytes:
    salida = b''
    for c in texto:
        b = c.encode(codec, errors='replace')
        if len(salida) + len(b) > largo:
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


# "555 Gold", "3x Blue Potion", "Blue Potion x3", "Blue Potion 1"
_ORO = re.compile(r'^([\d,]+) Gold$')
_CANTIDAD = (re.compile(r'^(?P<n>\d+) ?x (?P<nombre>.+)$'),
             re.compile(r'^(?P<nombre>.+?) ?x ?(?P<n>\d+)$'),
             re.compile(r'^(?P<nombre>.+?) (?P<n>\d+)$'))


def traducido(texto: str, habilidad: bool = False):
    """El texto en el idioma del cliente, o None si no es un nombre que conozca.
    Con `habilidad`, los nombres de skill.xml y magic.xml van primero."""
    if not ACTIVO:
        return None
    _cargar()
    if not _estado['codec']:
        return None
    # Sin fusionar los diccionarios: {**textos, **habilidades} copiaba 44000
    # entradas en cada llamada, y la skill exp llama dos veces por golpe.
    textos, habs = _estado['textos'], _estado['habilidades']

    def buscar(nombre):
        k = _clave(nombre)
        if habilidad and k in habs:
            return habs[k]
        return textos.get(k)

    t = str(texto).strip()
    local = buscar(t)
    if local is not None:
        return local
    m = _ORO.match(t)
    if m:
        return f'{m.group(1)} {_estado["oro"]}'
    for patron in _CANTIDAD:
        m = patron.match(t)
        if m:
            local = buscar(m.group('nombre'))
            if local is not None:
                return t[:m.start('nombre')] + local + t[m.end('nombre'):]
    return None


def texto(texto, defecto='ascii', habilidad=False, largo=None) -> bytes:
    """Los bytes de un %s de cartel: traducido si se puede, si no como antes.
    Un texto que ya viene en el idioma del cliente (de `elegir`) va en su
    charset. Con `largo`, cortado a esos bytes sin partir un caracter."""
    t = str(texto)
    local = traducido(t, habilidad)
    if local is None and _estado['codec'] and not t.isascii():
        local = t
    if local is not None:
        b = _cortar(local, _estado['codec'], largo) if largo else             local.encode(_estado['codec'], errors='replace')
    else:
        b = t.encode(defecto, 'replace')
    return b[:largo] if largo else b


def codificar(texto, defecto='latin-1', largo=None) -> bytes:
    """Solo el charset, sin traducir nada: un texto que no es ASCII (una frase
    de `elegir`) va en el del cliente; lo demas como antes."""
    t = str(texto)
    if ACTIVO and not t.isascii():
        _cargar()
        if _estado['codec']:
            return _cortar(t, _estado['codec'], largo) if largo else                 t.encode(_estado['codec'], errors='replace')
    b = t.encode(defecto, 'replace')
    return b[:largo] if largo else b


def idioma():
    """'CHT', 'CHS' o 'JPN' segun el language.ini del cliente; None en ingles."""
    if not ACTIVO:
        return None
    _cargar()
    return _estado['firma'][0][0] if _estado['codec'] and _estado['firma'] and _estado['firma'][0] else None


def elegir(ingles: str, por_idioma: dict) -> str:
    """Una frase propia del servidor (sin texto en el cliente) en el idioma del
    cliente: `por_idioma` es {'CHT': ..., 'CHS': ..., 'JPN': ...}."""
    return (por_idioma or {}).get(idioma()) or ingles
