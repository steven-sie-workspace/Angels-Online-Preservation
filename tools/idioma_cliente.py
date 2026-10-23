"""Idioma del cliente IGG: language.ini como en Global, tabla a tabla.

COMO CARGA EL CLIENTE SUS TEXTOS. Angel.exe no lleva rutas de datos: lee un
manifiesto, setting\\system_eng.xml (la cadena esta fija en el exe, VA
0x8B53E4), que dice que fichero cargar para cada cosa y con que juego de
caracteres y fuente:

    <語系 語系="英文"/>                               charset (DEFINE: 繁體中文=0
                                                     簡體中文=1 日文=2 英文=4)
    <技能定義檔 load="setting\\eng\\skill.xml"/>        y asi cada tabla
    <字型 編號="1" ... 雙位元字型="font\\cht12.fnt"/>   fuente de doble byte

data1.pak trae aun los manifiestos viejos (SYSTEM.XML en big5, SYSTEM_GB,
SYSTEM_SJIS) y las fuentes de los tres idiomas (FONT\\CHT*, CHS*, JAP*).

LO QUE HACE ESTO. Por cada idioma (cht, chs, jpn) mete en update26.pak:

    SETTING\\SYSTEM_<L>.XML   el SYSTEM_ENG vigente con el charset y la fuente
                             del idioma, y las tablas de TABLAS apuntando a
                             setting\\<L>
    SETTING\\<L>\\<TABLA>.XML  el XML ingles de IGG con los textos de Global
                             (SETTING\\<BIG5|GB|SJIS>\\STRING\\...) por el MISMO
                             id; todo lo demas (numeros, iconos) es el de IGG.
                             Hoy: skill.xml (skills), magic.xml (法術: Shock
                             Wave I...) y string.xml (textos de la interfaz)

Un texto solo entra si sus %s/%d/... salen igual y en el mismo orden que en
el ingles: el cliente los pasa a sprintf, y uno de mas, de menos o de otro
tipo lo tumba. Y en magic.xml solo si el registro de Global tiene el mismo
介面圖號 (icono): asi un id que en Global sea otro hechizo se queda en ingles.
Lo que no entra va a tools/idioma/formato_distinto_<L>.txt.

El dinput8.dll de tools/idioma (proxy) lee language.ini al arrancar y
cambia en memoria "system_eng" por "system_<L>". Language=4, o sin
language.ini, deja el cliente como estaba. Las tablas que no estan en TABLAS
siguen en setting\\eng.

    python tools/idioma_cliente.py              genera y mete en update26.pak
    python tools/idioma_cliente.py --quitar     saca lo que se metio
    python tools/idioma_cliente.py --seco       genera en tools/idioma/salida sin tocar el pak

Antes de tocar el pak deja una copia, update26.pak.antes_idioma, una sola vez.
El cliente es ../client (o --cliente RUTA). Global (../Angels Online Global)
solo se lee.
"""
import argparse
import collections
import html
import pathlib
import re
import shutil
import struct
import sys
import zlib

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'tools'))
from comprobar_sincronia import Pak, orden_pak  # noqa: E402
from novedades_global import GLOBAL, _registros, abrir_paks  # noqa: E402

CLIENTE = RAIZ.parent / 'client'
PAK_DESTINO = 'update26.pak'
BS = '\\'

# codigo -> (carpeta de textos en Global, charset del manifiesto, fuente)
IDIOMAS = {
    'cht': ('BIG5', '繁體中文', 'cht'),
    'chs': ('GB', '簡體中文', 'chs'),
    'jpn': ('SJIS', '日文', 'jap'),
}


def paks_cliente(cliente):
    return sorted((p for p in cliente.iterdir()
                   if p.suffix.lower() == '.pak' and orden_pak(p) is not None),
                  key=orden_pak)


def vigente(cliente, nombre):
    """El fichero tal como lo ve el cliente: el del pak de numero mas alto."""
    for p in reversed(paks_cliente(cliente)):
        pak = Pak(p)
        if nombre in pak.entradas:
            return pak.leer(nombre), p.name
    raise SystemExit('%s no esta en ningun pak de %s' % (nombre, cliente))


# Las tablas que se traducen. Cada una:
#   ficheros   los de IGG en setting\eng (y los de setting\<L> que se generan);
#              en el manifiesto ingles se cambia setting\eng\<fichero> por
#              setting\<L>\<fichero>
#   etiqueta   la de cada registro en esos ficheros
#   textos     los de Global en SETTING\<BIG5|GB|SJIS>\STRING (se juntan por id)
#   prefijo    id del texto = prefijo + id del registro
#   campos     文字N de Global -> atributo de IGG
#   clave      atributo con el id del registro (編號 si no se dice)
#   guarda     ([ficheros BASE de Global], atributo de IGG[, clave en Global])
#              que tiene que valer lo mismo en los dos para fiarse de que el
#              id es el mismo registro (la clave de Global puede venir
#              renombrada por extract_content.TRAD: 圖號 -> sprite_id)
#   juntos     (atributo principal, [atributos que van con el]): si el
#              principal se traduce, esos se ponen al valor de Global, o se
#              vacian si Global no trae; para que no salga "Apprentice短劍"
#   completo   el registro solo se traduce si Global trae texto para TODOS
#              los campos que tiene en IGG (una mision a medias no sirve)
#   respaldo   (fichero, [atributos], atributo guarda): solo para cht, lo que
#              Global no trae se busca en el chino VIEJO del propio IGG,
#              data1.pak SETTING\BIG5\<fichero> (Taiwan, mismo formato que
#              setting\eng y mismos ids). La guarda es un atributo que tiene
#              que valer lo mismo alli y en el ingles de hoy.
#   por_nombre atributo del nombre. Global dejo en ingles cientos de nombres
#              en su tabla china (la copia de un evento, "Bloody Sickle"):
#              un texto suyo sin letra del idioma cuenta como que no trae, y
#              lo que siga en ingles se busca 1) por el MISMO nombre ingles
#              en las tablas por_nombre (registros ya traducidos de IGG y
#              pares ENG/<L> de Global), si al menos el 80% dice lo mismo, y
#              2) solo cht: el texto de Global GB del mismo id (con su guarda)
#              pasado a tradicional con un mapa sacado de Global GB/BIG5.
_ITEMS = ['ITEM.XML'] + [f'ITEM{i}.XML' for i in range(2, 10)]
_N = [f'{i:02d}' for i in range(1, 9)]
# Lo que se ve de una mision. Fuera quedan 承接人員 y 可否重接, que el DEFINE
# de quest.xml convierte en numeros (個人/隊伍/社團, 不可重接/可重接).
_MISION = (['任務名稱', '任務類型', '任務前言', '任務結語', '地點', '承接']
           + [f'步驟{n}' for n in _N] + [f'地點{n}' for n in _N] + [f'承接{n}' for n in _N])
TABLAS = [
    dict(ficheros=['SKILL.XML'], etiqueta='技能', textos=['STR_SKILL.XML'],
         prefijo=1280000000, campos={'文字1': '名稱', '文字2': '說明'}),
    dict(ficheros=['MAGIC.XML'], etiqueta='法術', textos=['STR_MAGIC.XML'],
         prefijo=1180000000, campos={'文字1': '名稱', '文字2': '說明'},
         guarda=(['MAGIC.XML'], '介面圖號')),
    dict(ficheros=['STRING.XML'], etiqueta='字串', textos=['STRING.XML'],
         prefijo=0, campos={'文字': '文字'}),
    dict(ficheros=_ITEMS, etiqueta='道具', textos=['STR_' + f for f in _ITEMS],
         prefijo=1140000000, campos={'文字1': '原型名稱', '文字2': '基本名稱', '文字3': '說明定義'},
         guarda=(_ITEMS, '原型介面'), juntos=('基本名稱', ['原型名稱']),
         respaldo=('ITEM.XML', ['原型名稱', '基本名稱', '說明定義'], '原型介面')),
    dict(ficheros=['PET.XML'], etiqueta='pet', textos=['STR_PET.XML'],
         prefijo=1210000000, campos={'文字1': '名稱'},
         guarda=(['PET.XML'], '圖號1')),
    # Textos de ventanas y botones. Solo se cambian title/tooltext que IGG ya
    # tenga: uno que Global ponga y IGG no, no se anade (la ventana es la de IGG).
    dict(ficheros=[f'WNDTEXT0{i}.XML' for i in range(1, 6)], etiqueta='window',
         textos=['WNDTEXT.XML'], prefijo=0, clave='id',
         campos={'title': 'title', 'tooltext': 'tooltext'}),
    dict(ficheros=['MSG.XML'], etiqueta='字串', textos=['MSG.XML'],
         prefijo=0, campos={'文字': '文字'}),
    dict(ficheros=['NPC.XML'], etiqueta='npc', textos=['STR_NPC.XML'],
         prefijo=1200000000, campos={'文字1': '名稱'},
         guarda=(['NPC.XML'], '圖號', 'sprite_id'),
         respaldo=('NPC.XML', ['名稱'], '圖號'), por_nombre='名稱'),
    dict(ficheros=['MONSTER.XML'], etiqueta='npc', textos=['STR_MONSTER.XML'],
         prefijo=1200000000, campos={'文字1': '名稱'},
         guarda=(['MONSTER.XML'], '圖號', 'sprite_id'),
         respaldo=('MONSTER.XML', ['名稱'], '圖號'), por_nombre='名稱'),
    # stage.xml lo vuelve a escribir el servidor al cambiar de estacion
    # (cliente_local.aplicar_modo_estacion), tambien las copias de cada idioma.
    dict(ficheros=['STAGE.XML'], etiqueta='場景', textos=['STR_STAGE.XML'],
         prefijo=1290000000, campos={'文字1': '名稱'},
         guarda=(['STAGE.XML'], '地圖檔')),
    # quest.xml de Global no esta partido: trae los textos dentro, por 編號.
    dict(ficheros=['QUEST.XML'], etiqueta='任務', textos=['QUEST.XML'],
         prefijo=0, campos={a: a for a in _MISION}, completo=True,
         respaldo=('QUEST.XML', _MISION, None)),
    # Cartas: Global no las tiene; solo el chino viejo de data1.
    dict(ficheros=['CARD.XML'], etiqueta='card', textos=[], prefijo=0,
         campos={a: a for a in ('卡片名稱', '卡片說明', '卡片提示')},
         respaldo=('CARD.XML', ['卡片名稱', '卡片說明', '卡片提示'], '圖號')),
    dict(ficheros=['CARDSET.XML'], etiqueta='cardset', textos=[], prefijo=0,
         campos={a: a for a in ('套卡名稱', '套卡說明')},
         respaldo=('CARDSET.XML', ['套卡名稱', '套卡說明'], '卡片1')),
    dict(ficheros=['CLASS.XML'], etiqueta='class', textos=['STR_CLASS.XML'],
         prefijo=1060000000, clave='id',
         campos={'文字1': 'name', '文字2': 'adv_name', '文字3': 'help'}),
    dict(ficheros=['ITEMSET.XML'], etiqueta='套裝', textos=['STR_ITEMSET.XML'],
         prefijo=1150000000, campos={'文字1': '名稱'},
         guarda=(['ITEMSET.XML'], '兩樣')),
    # 主類別/次類別 los comparten cientos de logros: van por diccionario.
    dict(ficheros=['ACHIEVEMENT.XML'], etiqueta='成就', textos=['STR_ACHIEVEMENT.XML'],
         prefijo=1010000000,
         campos={'文字1': '主類別', '文字2': '次類別', '文字3': '名稱', '文字4': '說明'},
         valores=('主類別', '次類別'), numeros=('說明',),
         guarda=(['ACHIEVEMENT.XML'], '封號')),
    # 珍貴等級 ("_平凡") es la clave; 珍貴程度 ("Common") lo que se ve.
    dict(ficheros=['CROWN.XML'], etiqueta='crown', textos=['STR_CROWN.XML'],
         prefijo=1090000000, campos={'文字1': '封號', '文字2': '珍貴程度'},
         valores=('珍貴程度',), guarda=(['CROWN.XML'], '聲望值')),
    dict(ficheros=['COLLECTION.XML'], etiqueta='collection', textos=['STR_COLLECTION.XML'],
         prefijo=1070000000, campos={'文字1': '說明'}, numeros=('說明',),
         guarda=(['COLLECTION.XML'], '收藏值')),
    # 場景名稱 ya viene en chino en IGG (y puede ser clave): solo el 傳點名稱.
    dict(ficheros=['JUMPMAP.XML'], etiqueta='跳地圖', textos=['STR_JUMPMAP.XML'],
         prefijo=1160000000, campos={'文字2': '傳點名稱'},
         guarda=(['JUMPMAP.XML'], '場景編號')),
    dict(ficheros=['JUMPMAPCLASS.XML'], etiqueta='跳地圖類別', textos=['STR_JUMPMAPCLASS.XML'],
         prefijo=1170000000, campos={'文字1': '類別名稱'}),
]


def _global(ficheros):
    """{id: registro} de unos ficheros de Global; el pak posterior gana."""
    salida = {}
    for fichero in ficheros:
        for pak in abrir_paks(GLOBAL):
            if fichero in pak.entradas:
                for rid, r in _registros(pak, fichero):
                    salida[int(rid)] = r
    return salida


_DATA1 = {}


def textos_data1(cliente, tabla):
    """{id: {atributo: texto, '__guarda__': (atributo, valor)}} del chino viejo
    de data1.pak (SETTING\\BIG5\\<fichero>), con el mismo formato que setting\\eng."""
    fichero, attrs, guarda = tabla['respaldo']
    nombre = f'SETTING{BS}BIG5{BS}{fichero}'
    if nombre not in _DATA1:
        pak = Pak(cliente / 'data1.pak')
        _DATA1[nombre] = (pak.leer(nombre).decode('utf-8-sig', 'replace')
                          if nombre in pak.entradas else '')
    clave = tabla.get('clave', '編號')
    salida = {}
    for t in re.findall(f'<{tabla["etiqueta"]}\\b[^>]*/>', _DATA1[nombre]):
        sid = _buscar(t, clave)
        if not sid or not sid.group(1).isdigit():
            continue
        r = {}
        for a in attrs:
            m = _buscar(t, a)
            if m and m.group(1):
                r[a] = html.unescape(m.group(1))
        if r and guarda:
            g = _buscar(t, guarda)
            r['__guarda__'] = (guarda, g.group(1) if g else None)
        if r:
            salida[int(sid.group(1))] = r
    return salida


def textos_global(carpeta_global, ficheros, prefijo, campos):
    """{id del registro: {atributo IGG: texto}}."""
    regs = _global([f'SETTING{BS}{carpeta_global}{BS}STRING{BS}{f}' for f in ficheros])
    return {rid - prefijo: {attr: r[t] for t, attr in campos.items() if r.get(t)}
            for rid, r in regs.items()}


# Lo que sprintf consume: %s, %d, %lu, %02d, %-5s, %I64d... (%% no consume nada).
# Sin el flag ' ': ningun texto del juego lo usa y con el "5% collection"
# salia como un %c. Los %0 %1 %2 de magic.xml no son de sprintf y no cuentan.
# Y los %1400% de quest.xml (el contador de un item en un paso de mision): si
# cambian, el paso cuenta otra cosa, asi que tambien tienen que ser los mismos.
_FORMATO = re.compile(r'%\d+%|%[-+#0]*(?:\d+|\*)?(?:\.(?:\d+|\*))?'
                      r'(?:hh|h|ll|l|I64|I32|L)?[diouxXcsSfeEgGpn]')


def formatos(texto):
    return _FORMATO.findall(texto.replace('%%', ''))


def _attr(v):
    # IGG escribe los saltos como los dos caracteres \n; algunos textos de
    # Global los traen de verdad, y un salto crudo dentro de un atributo XML
    # el parser lo convierte en espacio.
    v = v.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\\n')
    return html.escape(v, quote=True)


# Las teclas son las del cliente IGG, no las de Global: el 104 en Global dice
# [Ctrl+Z] y aqui la tecla es Alt+Z. Si los dos textos traen el mismo numero
# de atajos, se ponen los del ingles.
_ATAJO = re.compile(r'(?:Alt|Ctrl|Shift|ALT|CTRL|SHIFT)\s*\+\s*[^\]\)）】\s]+')


_ATAJO_ENTRE = re.compile(r'\s*[\[［]\s*(?:Alt|Ctrl|Shift|ALT|CTRL|SHIFT)\s*\+[^\]］]*[\]］]')


def _atajos_de_igg(valor, ingles):
    suyos, mios = _ATAJO.findall(valor), _ATAJO.findall(ingles)
    if suyos and not mios:
        # Un atajo que este cliente no tiene ("活動總覽[Ctrl+E]"): fuera.
        return _ATAJO_ENTRE.sub('', valor)
    if not suyos or len(suyos) != len(mios) or suyos == mios:
        return valor
    piezas = iter(mios)
    return _ATAJO.sub(lambda _: next(piezas), valor)


def _buscar(t, attr):
    return re.search(f'(?<![^ <]){attr}="([^"]*)"', t)


def _numeros(texto):
    # "1,000" en ingles es "1000" en chino
    return sorted(re.findall(r'\d+', re.sub(r'(?<=\d),(?=\d{3})', '', texto)))


def traducir(ingles: str, etiqueta: str, textos: dict, guarda: dict = None,
             attr_guarda=None, juntos=None, clave='編號', clave_guarda=None,
             completo=None, numeros=(), valores=(), respaldo=None,
             escritura=None, extra=None):
    """El XML de IGG con los textos de Global; todo lo demas igual.

    Un texto solo entra si sus %s/%d/... son los mismos y en el mismo orden
    que los del ingles (el cliente los pasa a sprintf) y, si hay guarda, si
    el registro de Global tiene el mismo valor en ese atributo. Con
    `completo` (lista de atributos), o entran todos los que el registro de
    IGG tenga con texto, o ninguno. En los atributos de `numeros` las cifras
    tienen que ser las mismas: Global rebalanceo cosas y su "魔攻+140" no
    vale para un registro de IGG que da MATK+70. Los de `valores` son
    categorias que comparten muchos registros (主類別 "Celebrity"): se
    traducen con un diccionario sacado de los registros que cuadran y se
    aplican a TODOS, para no partir una categoria en una pestana inglesa y
    otra china.

    Con `escritura` (regex de las letras del idioma), un registro de Global
    sin ninguna cuenta como que no trae. `extra` ({id: textos}) es lo ultimo
    que se mira, tras Global y data1.
    """
    cuenta = {'registros': 0, 'traducidos': 0, 'formato distinto': 0,
              'sin texto': 0, 'guarda distinta': 0, 'incompleto': 0,
              'cifras distintas': 0}
    clave_guarda = clave_guarda or attr_guarda
    distintos = []
    principal, acompanan = juntos or (None, [])
    patron = re.compile(f'<{etiqueta}\\b[^>]*/>')

    def de_respaldo(t, rid):
        """El texto de data1 si su guarda vale lo mismo que en el ingles de hoy."""
        r = (respaldo or {}).get(rid)
        if not r:
            return None
        if '__guarda__' in r:
            attr, suyo = r['__guarda__']
            mio = _buscar(t, attr)
            if not mio or mio.group(1) != suyo:
                return None
        r = {k: v for k, v in r.items() if k != '__guarda__'}
        if escritura and not any(escritura.search(v) for v in r.values()):
            return None
        return r

    def registro(t):
        """(id, textos) si el registro es el mismo en los dos; False si la guarda
        no cuadra. Primero Global; si no trae o no cuadra, data1."""
        sid = _buscar(t, clave)
        if not sid or not sid.group(1).isdigit():
            return None, None
        rid = int(sid.group(1))
        nuevos = textos.get(rid)
        if nuevos and escritura and not any(escritura.search(v) for v in nuevos.values()):
            nuevos = None
        ultimo = (extra or {}).get(rid)
        if nuevos and guarda is not None:
            mio = _buscar(t, attr_guarda)
            suyo = (guarda.get(rid) or {}).get(clave_guarda)
            if mio and suyo is not None and mio.group(1) != suyo:
                return rid, de_respaldo(t, rid) or ultimo or False
        return rid, nuevos or de_respaldo(t, rid) or ultimo

    # Diccionario de categorias: valor de IGG -> el valor de Global que le
    # toca al menos en el 80% de los registros. Por debajo (el "World" de IGG
    # Global lo partio en tres) la categoria entera se queda en ingles.
    pares = {}
    for m in patron.finditer(ingles):
        _, nuevos = registro(m.group(0))
        for attr in valores:
            orig = _buscar(m.group(0), attr)
            if nuevos and orig and nuevos.get(attr):
                pares.setdefault(html.unescape(orig.group(1)), collections.Counter())[nuevos[attr]] += 1
    mapa = {}
    for k, c in pares.items():
        valor, n = c.most_common(1)[0]
        if n >= 0.8 * sum(c.values()):
            mapa[k] = valor

    def tag(m):
        t = m.group(0)
        cuenta['registros'] += 1
        for attr in valores:
            orig = _buscar(t, attr)
            if orig and html.unescape(orig.group(1)) in mapa:
                t = t[:orig.start(1)] + _attr(mapa[html.unescape(orig.group(1))]) + t[orig.end(1):]
        rid, nuevos = registro(t)
        if nuevos is False:
            cuenta['guarda distinta'] += 1
            return t
        if not nuevos:
            cuenta['sin texto'] += 1
            return t
        if completo:
            for attr in completo:
                orig = _buscar(t, attr)
                if not orig or not orig.group(1):
                    continue
                valor = _atajos_de_igg(nuevos.get(attr, ''), html.unescape(orig.group(1)))
                if not valor or formatos(html.unescape(orig.group(1))) != formatos(valor):
                    cuenta['incompleto'] += 1
                    if valor:
                        distintos.append((rid, attr, html.unescape(orig.group(1)), valor))
                    return t
        hechos = set()
        for attr, valor in nuevos.items():
            if attr in acompanan or attr in valores:
                continue
            orig = _buscar(t, attr)
            if not orig:
                continue
            viejo = html.unescape(orig.group(1))
            valor = _atajos_de_igg(valor, viejo)
            if formatos(viejo) != formatos(valor):
                cuenta['formato distinto'] += 1
                distintos.append((rid, attr, viejo, valor))
                continue
            # Si el ingles no trae cifras no hay nada que comparar ("the
            # highest level" -> "排名第 1 名" esta bien).
            if attr in numeros and _numeros(viejo) and _numeros(viejo) != _numeros(valor):
                cuenta['cifras distintas'] += 1
                distintos.append((rid, attr, viejo, valor))
                continue
            t = t[:orig.start(1)] + _attr(valor) + t[orig.end(1):]
            hechos.add(attr)
        if principal in hechos:
            for attr in acompanan:
                valor = nuevos.get(attr, '')
                orig = _buscar(t, attr)
                if orig:
                    t = t[:orig.start(1)] + _attr(valor) + t[orig.end(1):]
                elif valor:
                    p = _buscar(t, principal)
                    t = t[:p.start()] + f'{attr}="{_attr(valor)}" ' + t[p.start():]
        if hechos:
            cuenta['traducidos'] += 1
        return t

    return patron.sub(tag, ingles), cuenta, distintos


def manifiesto(ingles: str, codigo: str, charset: str, fuente: str):
    cambios = [
        ('<語系 語系="英文"/>', f'<語系 語系="{charset}"/>'),
        ('雙位元字型="font\\cht12.fnt"', f'雙位元字型="font\\{fuente}12.fnt"'),
        ('雙位元字型="font\\cht16.fnt"', f'雙位元字型="font\\{fuente}16.fnt"'),
    ]
    for viejo, nuevo in cambios:
        if ingles.count(viejo) != 1:
            raise SystemExit('el manifiesto ingles ya no trae %r una vez: revisar' % viejo)
        ingles = ingles.replace(viejo, nuevo)
    for tabla in TABLAS:
        for f in tabla['ficheros']:
            ruta = re.compile(r'setting\\eng\\(%s)(?=["<])' % re.escape(f.lower()), re.I)
            ingles, n = ruta.subn(lambda m: f'setting\\{codigo}\\{m.group(1)}', ingles)
            if n != 1:
                raise SystemExit('el manifiesto ingles carga setting\\eng\\%s %d veces: revisar'
                                 % (f.lower(), n))
    return ingles


def _texto(raw):
    bom = b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    return bom, raw.decode('utf-8-sig')


def ficheros_generados():
    return [f for tabla in TABLAS for f in tabla['ficheros']]


# Letras de chino o japones: un nombre "traducido" sin ninguna sigue en ingles.
_ESCRITURA = re.compile(r'[぀-ヿ㐀-鿿ｦ-ﾟ]')
# Y en chino no se rellena con nada que traiga kana ("福のの袋" en Global GB).
_KANA = re.compile(r'[぀-ヿｦ-ﾟ]')


def _nombres(etiqueta, attr, texto):
    """{id: nombre} de un XML de IGG."""
    salida = {}
    for t in re.findall(f'<{etiqueta}\\b[^>]*/>', texto):
        sid, n = _buscar(t, '編號'), _buscar(t, attr)
        if sid and n and sid.group(1).isdigit():
            salida[int(sid.group(1))] = html.unescape(n.group(1))
    return salida


_S2T = {}


def a_tradicional(texto):
    """Simplificado -> tradicional, caracter a caracter, con el mapa que sale de
    juntar los textos GB y BIG5 de Global de igual largo por id. None si
    queda algo que el big5 del cliente (cp950) no tiene."""
    if not _S2T:
        votos = collections.defaultdict(collections.Counter)
        nombres = {n for pak in abrir_paks(GLOBAL) for n in pak.entradas
                   if n.startswith(f'SETTING{BS}GB{BS}STRING{BS}')}
        for n in sorted(nombres):
            gb, b5 = _global([n]), _global([n.replace(f'{BS}GB{BS}', f'{BS}BIG5{BS}')])
            for rid, r in gb.items():
                for k, s in r.items():
                    t = (b5.get(rid) or {}).get(k)
                    if k.startswith('文字') and s and t and len(s) == len(t) and s != t:
                        for a, b in zip(s, t):
                            votos[a][b] += 1
        _S2T.update({a: c.most_common(1)[0][0] for a, c in votos.items()})
    salida = ''.join(_S2T.get(c, c) for c in texto)
    try:
        salida.encode('cp950')
    except UnicodeEncodeError:
        return None
    return salida


def rellenos(codigo, tablas, ingleses, hechos):
    """{fichero: {id: {attr: nombre}}} para los registros de las tablas
    por_nombre que siguen en ingles tras la primera pasada (`hechos`)."""
    votos = collections.defaultdict(collections.Counter)
    pendientes = []
    for tabla, g in tablas:
        attr = tabla['por_nombre']
        for f in tabla['ficheros']:
            loc = _nombres(tabla['etiqueta'], attr, hechos[f])
            for t in re.findall(f'<{tabla["etiqueta"]}\\b[^>]*/>', ingleses[f][0][1]):
                sid, n = _buscar(t, '編號'), _buscar(t, attr)
                if not sid or not n or not sid.group(1).isdigit():
                    continue
                rid, n = int(sid.group(1)), html.unescape(n.group(1))
                if _ESCRITURA.search(loc.get(rid, '')) and (codigo == 'jpn' or not _KANA.search(loc[rid])):
                    votos[' '.join(n.lower().split())][loc[rid]] += 1
                elif _ESCRITURA.search(n) is None:
                    pendientes.append((tabla, g, f, rid, n, t))
    salida = collections.defaultdict(dict)
    cuenta = collections.Counter()
    gb = {}
    for tabla, g, f, rid, n, tag in pendientes:
        attr = tabla['por_nombre']
        c = votos.get(' '.join(n.lower().split()))
        if c and c.most_common(1)[0][1] >= 0.8 * sum(c.values()):
            salida[f][rid] = {attr: c.most_common(1)[0][0]}
            cuenta['mismo nombre'] += 1
            continue
        if codigo != 'cht':
            continue
        if id(tabla) not in gb:
            texto = next(k for k, v in tabla['campos'].items() if v == attr)
            gb[id(tabla)] = {r: v[attr] for r, v in textos_global(
                'GB', tabla['textos'], tabla['prefijo'], {texto: attr}).items() if v.get(attr)}
        s = gb[id(tabla)].get(rid)
        if not s or not _ESCRITURA.search(s) or _KANA.search(s):
            continue
        if g is not None:
            # la guarda de la tabla, como en traducir: si falta en uno, pasa
            mio = _buscar(tag, tabla['guarda'][1])
            clave = tabla['guarda'][2] if len(tabla['guarda']) > 2 else tabla['guarda'][1]
            suyo = (g.get(rid) or {}).get(clave)
            if mio and suyo is not None and mio.group(1) != suyo:
                continue
        t = a_tradicional(s)
        if t:
            salida[f][rid] = {attr: t}
            cuenta['de GB'] += 1
    print(f'    nombres que Global dejo en ingles: {len(pendientes)}, rellenados {dict(cuenta)}')
    return salida


def generar(cliente):
    """{nombre en el pak: bytes} para los tres idiomas."""
    man_raw, man_pak = vigente(cliente, f'SETTING{BS}SYSTEM_ENG.XML')
    man_bom, man = _texto(man_raw)
    print(f'base: SYSTEM_ENG.XML de {man_pak}')
    ingleses, guardas = {}, []
    for tabla in TABLAS:
        for f in tabla['ficheros']:
            raw, pak = vigente(cliente, f'SETTING{BS}ENG{BS}{f}')
            ingleses[f] = (_texto(raw), pak)
        g = tabla.get('guarda')
        guardas.append(_global([f'SETTING{BS}BASE{BS}{x}' for x in g[0]]) if g else None)

    ficheros = {}
    for codigo, (carpeta, charset, fuente) in IDIOMAS.items():
        ficheros[f'SETTING{BS}SYSTEM_{codigo.upper()}.XML'] = \
            man_bom + manifiesto(man, codigo, charset, fuente).encode('utf-8')
        print(f'  {codigo} (Global {carpeta}):')

        def pasar(tabla, g, extra=None):
            textos = textos_global(carpeta, tabla['textos'], tabla['prefijo'], tabla['campos'])
            # Global primero; data1 donde Global no trae o su guarda no cuadra.
            respaldo = (textos_data1(cliente, tabla)
                        if codigo == 'cht' and tabla.get('respaldo') else None)
            salida = {}
            for f in tabla['ficheros']:
                (bom, ingles), pak = ingleses[f]
                salida[f] = (bom,) + traducir(
                    ingles, tabla['etiqueta'], textos, g,
                    tabla['guarda'][1] if g is not None else None, tabla.get('juntos'),
                    tabla.get('clave', '編號'),
                    tabla['guarda'][2] if g is not None and len(tabla['guarda']) > 2 else None,
                    list(tabla['campos'].values()) if tabla.get('completo') else None,
                    tabla.get('numeros', ()), tabla.get('valores', ()), respaldo,
                    _ESCRITURA if tabla.get('por_nombre') else None, (extra or {}).get(f))
            return salida

        # Las tablas por_nombre van dos veces: la primera da los nombres ya
        # traducidos con que rellenar los que siguen en ingles.
        por_nombre = [(tabla, g) for tabla, g in zip(TABLAS, guardas) if tabla.get('por_nombre')]
        hechos = {f: r[1] for tabla, g in por_nombre for f, r in pasar(tabla, g).items()}
        extra = rellenos(codigo, por_nombre, ingleses, hechos)
        informe = []
        for tabla, g in zip(TABLAS, guardas):
            total = {}
            for f, (bom, nuevo, cuenta, distintos) in pasar(tabla, g, extra).items():
                ficheros[f'SETTING{BS}{codigo.upper()}{BS}{f}'] = bom + nuevo.encode('utf-8')
                for k, v in cuenta.items():
                    total[k] = total.get(k, 0) + v
                informe += [f'{f} {i} {a}\n  eng: {e}\n  {codigo}: {c}\n'
                            for i, a, e, c in distintos]
            nombre = tabla['ficheros'][0].lower()
            if len(tabla['ficheros']) > 1:
                nombre += f' (+{len(tabla["ficheros"]) - 1})'
            print(f'    {nombre}: {total}')
        (RAIZ / 'tools' / 'idioma' / f'formato_distinto_{codigo}.txt').write_text(
            ''.join(informe), encoding='utf-8')
    return ficheros


# --- escritura del pak (formato OD\x05\x06, ver comprobar_sincronia.Pak) ---

def _xor_eocd(b):
    b = bytearray(b)
    for i in range(4, 22):
        b[i] ^= (3 * i - 91) & 0xFF
    return b


def _leer_pak(data):
    eocd = _xor_eocd(data[-22:])
    if eocd[:4] != b'OD\x05\x06':
        raise SystemExit('el pak no tiene firma OD\\x05\\x06')
    cd_off = struct.unpack_from('<I', eocd, 16)[0]
    raw = bytearray(data[cd_off + 4:len(data) - 22])
    raw[0] ^= 0x7A
    cd = zlib.decompressobj().decompress(bytes(raw))
    entradas, off = [], 0
    while off + 46 <= len(cd):
        fn_len, ex_len, cm_len = struct.unpack_from('<HHH', cd, off + 28)
        fin = off + 46 + fn_len + ex_len + cm_len
        nombre = cd[off + 46:off + 46 + fn_len].decode('ascii')
        entradas.append([nombre, bytearray(cd[off:fin])])
        off = fin
    return cd_off, entradas


def escribir_pak(ruta, poner: dict, quitar=()):
    """Mete (o cambia) `poner` y saca los nombres de `quitar`. Devuelve True si cambio algo."""
    data = ruta.read_bytes()
    cd_off, entradas = _leer_pak(data)
    plantilla = bytes(entradas[0][1][:46])
    cuerpo = bytearray(data[:cd_off])
    por_nombre = {e[0].upper(): e for e in entradas}
    quitar = {q.upper() for q in quitar}
    cambio = any(q in por_nombre for q in quitar)
    entradas = [e for e in entradas if e[0].upper() not in quitar]
    por_nombre = {e[0].upper(): e for e in entradas}

    for nombre, contenido in poner.items():
        crc = zlib.crc32(contenido) & 0xFFFFFFFF
        e = por_nombre.get(nombre.upper())
        if e and struct.unpack_from('<III', e[1], 16) [::2] == (crc, len(contenido)):
            continue
        c = zlib.compressobj(9, zlib.DEFLATED, -15)
        comp = c.compress(contenido) + c.flush()
        if e is None:
            nb = nombre.encode('ascii')
            reg = bytearray(plantilla) + nb
            struct.pack_into('<HHH', reg, 28, len(nb), 0, 0)
            e = [nombre, reg]
            entradas.append(e)
            por_nombre[nombre.upper()] = e
        struct.pack_into('<III', e[1], 16, crc, len(comp), len(contenido))
        struct.pack_into('<I', e[1], 42, len(cuerpo))
        cuerpo.extend(comp)
        cambio = True

    if not cambio:
        return False
    entradas.sort(key=lambda e: e[0].upper())
    cd = b''.join(bytes(e[1]) for e in entradas)
    cd_comp = bytearray(zlib.compress(cd))
    cd_comp[0] ^= 0x7A
    eocd = b'OD\x05\x06' + struct.pack('<HHHHIIH', len(cd_comp) & 0xFFFF, 0,
                                       len(entradas), len(entradas), len(cd), len(cuerpo), 0)
    salida = bytes(cuerpo) + b'OD\x05\x06' + bytes(cd_comp) + bytes(_xor_eocd(eocd))
    tmp = ruta.with_name(ruta.name + '.tmp')
    tmp.write_bytes(salida)
    tmp.replace(ruta)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--cliente', type=pathlib.Path, default=CLIENTE)
    ap.add_argument('--quitar', action='store_true', help='sacar del pak lo que se metio')
    ap.add_argument('--seco', action='store_true', help='solo generar en tools/idioma/salida')
    a = ap.parse_args()
    pak = a.cliente / PAK_DESTINO

    if a.quitar:
        nombres = []
        for codigo in IDIOMAS:
            nombres.append(f'SETTING{BS}SYSTEM_{codigo.upper()}.XML')
            nombres += [f'SETTING{BS}{codigo.upper()}{BS}{f}' for f in ficheros_generados()]
        print('quitado' if escribir_pak(pak, {}, nombres) else 'no habia nada que quitar')
        return

    ficheros = generar(a.cliente)
    if a.seco:
        salida = RAIZ / 'tools' / 'idioma' / 'salida'
        for nombre, contenido in ficheros.items():
            f = salida / pathlib.PureWindowsPath(nombre)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(contenido)
        print('escrito en', salida)
        return

    copia = pak.with_name(pak.name + '.antes_idioma')
    if not copia.exists():
        shutil.copy2(pak, copia)
        print('copia de seguridad:', copia.name)
    print('update26.pak actualizado' if escribir_pak(pak, ficheros) else 'update26.pak ya estaba al dia')


if __name__ == '__main__':
    main()
