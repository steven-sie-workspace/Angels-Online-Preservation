"""Que casillas se pueden pisar, para que los monstruos no atraviesen paredes.

Los datos salen de la capa de casillas del .mpc del cliente; los prepara
tools/transitable.py en plantillas/transitable.bin (ahi esta explicado de
donde sale y como se comprobo). Un mapa que no este en el fichero se trata
como todo transitable, que es como iba antes.
"""
import logging
import pathlib
import struct

log = logging.getLogger(__name__)

_MAPAS = None
FICHERO = pathlib.Path(__file__).parent / 'plantillas' / 'transitable.bin'


def _cargar():
    global _MAPAS
    if _MAPAS is None:
        _MAPAS = {}
        try:
            b = FICHERO.read_bytes()
            n, p = struct.unpack_from('<I', b, 0)[0], 4
            for _ in range(n):
                st, w, h = struct.unpack_from('<HHH', b, p)
                p += 6
                largo = (w * h + 7) // 8
                _MAPAS[st] = (w, h, b[p:p + largo])
                p += largo
        except Exception:
            _MAPAS = {}
    return _MAPAS


def se_pisa(stage, x, y):
    m = _cargar().get(int(stage or 0))
    if m is None:
        return True
    w, h, bits = m
    if not (0 <= x < w and 0 <= y < h):
        return False
    i = y * w + x
    return bool(bits[i >> 3] & (1 << (i & 7)))


def conocido(stage):
    return int(stage or 0) in _cargar()


def _linea(desde, hasta):
    (x0, y0), (x1, y1) = desde, hasta
    n = max(abs(x1 - x0), abs(y1 - y0))
    for k in range(1, n + 1):
        yield (x0 + round((x1 - x0) * k / n), y0 + round((y1 - y0) * k / n))


def linea_libre(stage, desde, hasta):
    """Si se puede ir en linea recta de una casilla a otra sin pisar pared."""
    if not conocido(stage):
        return True
    anterior = desde
    for x, y in _linea(desde, hasta):
        if not se_pisa(stage, x, y):
            return False
        if x != anterior[0] and y != anterior[1]:
            if not (se_pisa(stage, x, anterior[1]) and se_pisa(stage, anterior[0], y)):
                return False
        anterior = x, y
    return True


def paso_hacia(stage, desde, hasta, limite=4096):
    """Un unico segmento seguro de regreso; BFS acotada para rodear paredes."""
    from collections import deque
    desde, hasta = tuple(desde), tuple(hasta)
    if desde == hasta:
        return desde
    cola, anterior = deque([desde]), {desde: None}
    while cola and len(anterior) < limite:
        x, y = cola.popleft()
        for dx, dy in ((0,1),(1,0),(0,-1),(-1,0), (1,1),(1,-1),(-1,1),(-1,-1)):
            t = x+dx, y+dy
            if t in anterior or not linea_libre(stage, (x,y), t):
                continue
            anterior[t] = (x,y)
            if t == hasta:
                while anterior[t] != desde:
                    t = anterior[t]
                return t
            cola.append(t)
    return desde


def avanzar(stage, desde, objetivo, pasos, parar_a=0):
    """Hasta `pasos` casillas desde `desde` hacia `objetivo`, bordeando paredes.

    Cada paso va a la vecina transitable que mas acerca (las ocho), y solo si
    acerca de verdad: contra una pared que no se puede rodear se queda quieto
    en vez de atravesarla o ponerse a oscilar. Para a `parar_a` casillas del
    objetivo (el alcance del ataque). Devuelve la casilla final.
    """
    x, y = int(desde[0]), int(desde[1])
    tx, ty = int(objetivo[0]), int(objetivo[1])
    if not conocido(stage):
        for _ in range(pasos):
            if max(abs(tx - x), abs(ty - y)) <= parar_a:
                break
            x += (tx > x) - (tx < x)
            y += (ty > y) - (ty < y)
        return x, y
    for _ in range(pasos):
        if max(abs(tx - x), abs(ty - y)) <= parar_a:
            break
        actual = (tx - x) ** 2 + (ty - y) ** 2
        mejor = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if not dx and not dy:
                    continue
                nx, ny = x + dx, y + dy
                if not se_pisa(stage, nx, ny):
                    continue
                # En diagonal, que no corte una esquina de pared.
                if dx and dy and not (se_pisa(stage, x + dx, y) and se_pisa(stage, x, y + dy)):
                    continue
                d = (tx - nx) ** 2 + (ty - ny) ** 2
                if d < actual and (mejor is None or d < mejor[0]):
                    mejor = (d, nx, ny)
        if mejor is None:
            break
        if not linea_libre(stage, desde, (mejor[1], mejor[2])):
            break  # Un MOVE solo dibuja un segmento, no una ruta doblada.
        _, x, y = mejor
    return x, y


# --------------------------------------------------------------------------
# CASILLAS ALCANZABLES
#
# Que una casilla se pise no basta: hay trozos sueltos de suelo en mitad de un
# lago o en el tejado de una casa a los que ningun jugador llega andando. Se
# parte el suelo en zonas conexas (a cuatro vecinas) y una zona cuenta como
# alcanzable si tiene un portal o una llegada de portal (portales.json) o si es
# grande. Lo de grande es por las salas de mazmorra a las que se entra por un
# salto del propio mapa: la Gulp Room 4 tiene salas de 1184 y 3230 casillas
# sin ningun portal. Los trozos sueltos medidos no pasan de ~360 casillas.

ZONA_GRANDE = 500
PORTALES = pathlib.Path(__file__).parent / 'plantillas' / 'portales.json'
JUMPMAP = pathlib.Path(__file__).parent / 'plantillas' / 'jumpmap.json'
_ZONAS = {}
_ANCLAS = None
_CERCANAS = {}


def _anclas():
    """{stage: [casillas]} donde se sabe que esta o llega un jugador."""
    global _ANCLAS
    if _ANCLAS is None:
        _ANCLAS = {}
        try:
            import json
            mapas = json.loads(PORTALES.read_text(encoding='utf-8')).get('mapas', {})
            for st, lista in mapas.items():
                for por in lista:
                    if por.get('tile'):
                        _ANCLAS.setdefault(int(st), []).append(tuple(por['tile'][:2]))
                    if por.get('llegada') and por.get('destino') is not None:
                        _ANCLAS.setdefault(int(por['destino']), []).append(tuple(por['llegada'][:2]))
            # Y las llegadas de jumpmap.xml (Angels GO!, volver a la ciudad).
            saltos = json.loads(JUMPMAP.read_text(encoding='utf-8')).get('destinos', [])
            for d in saltos:
                if d.get('tile') and d.get('stage') is not None:
                    _ANCLAS.setdefault(int(d['stage']), []).append(tuple(d['tile'][:2]))
        except Exception:
            log.debug('anclas de transitable', exc_info=True)
    return _ANCLAS


def _zonas(stage):
    """(etiqueta por casilla, set de etiquetas alcanzables) del mapa."""
    st = int(stage or 0)
    if st in _ZONAS:
        return _ZONAS[st]
    w, h, bits = _cargar()[st]
    pisa = [bool(bits[i >> 3] & (1 << (i & 7))) for i in range(w * h)]
    lab = [-1] * (w * h)
    tam = []
    for i0 in range(w * h):
        if not pisa[i0] or lab[i0] >= 0:
            continue
        c = len(tam)
        lab[i0] = c
        pila, n = [i0], 0
        while pila:
            i = pila.pop()
            n += 1
            x = i % w
            for j in ((i - 1) if x > 0 else -1, (i + 1) if x < w - 1 else -1, i - w, i + w):
                if 0 <= j < w * h and pisa[j] and lab[j] < 0:
                    lab[j] = c
                    pila.append(j)
        tam.append(n)
    buenas = {c for c, n in enumerate(tam) if n >= ZONA_GRANDE}
    for ax, ay in _anclas().get(st, []):
        # Las llegadas medidas pueden caer una o dos casillas fuera del suelo.
        for r in range(4):
            hit = [lab[(ay + dy) * w + ax + dx]
                   for dy in range(-r, r + 1) for dx in range(-r, r + 1)
                   if 0 <= ax + dx < w and 0 <= ay + dy < h and lab[(ay + dy) * w + ax + dx] >= 0]
            if hit:
                buenas.add(hit[0])
                break
    _ZONAS[st] = (w, lab, buenas)
    return _ZONAS[st]


def alcanzable(stage, x, y):
    """Si un jugador puede llegar andando a esa casilla (ver arriba)."""
    if not conocido(stage):
        return True
    if not se_pisa(stage, x, y):
        return False
    w, lab, buenas = _zonas(stage)
    return lab[int(y) * w + int(x)] in buenas


def casilla_cercana(stage, x, y, radio=20):
    """La casilla alcanzable mas cercana a (x, y); ella misma si ya lo es.

    Para los puntos de aparicion: las plantillas reparten los monstruos de
    cada generador en una rejilla cada 5 casillas sobre el rectangulo de la
    zona, y en los mapas con agua o paredes muchos caian dentro. Entre las de
    la distancia minima (y una mas, para que no se amontonen en la orilla) se
    elige una fija por casilla de origen, asi el spawn que ve el cliente y el
    monstruo del servidor coinciden. None si no hay ninguna en `radio`.
    """
    x, y = int(x), int(y)
    if alcanzable(stage, x, y):
        return x, y
    clave = (int(stage or 0), x, y, radio)
    if clave in _CERCANAS:
        return _CERCANAS[clave]
    hallado, mejor = [], None
    for r in range(1, radio + 1):
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if max(abs(dx), abs(dy)) == r and alcanzable(stage, x + dx, y + dy):
                    hallado.append((dx * dx + dy * dy, x + dx, y + dy))
        if hallado and mejor is None:
            mejor = r
        if mejor is not None and r >= mejor + 1:
            break
    res = None
    if hallado:
        hallado.sort()
        tope = hallado[0][0] + 2 * mejor + 1
        cerca = [(cx, cy) for d, cx, cy in hallado if d <= tope]
        res = cerca[(x * 7919 + y * 104729) % len(cerca)]
    _CERCANAS[clave] = res
    return res


def destino_de_salto(stage, desde, hasta, alcance):
    """Adonde cae un salto (Swiftness Spell, Dimension Shift) de `desde` a `hasta`.

    Primero se acorta al alcance del hechizo (casillas, como el 射程 del
    magic.xml). Si el sitio no es alcanzable -- agua, tejado, pared -- se
    recorre la linea de vuelta hacia el jugador y se cae en la primera casilla
    buena. Si no hay ninguna, el salto no se hace: devuelve `desde`.
    """
    (x0, y0), (x1, y1) = (int(desde[0]), int(desde[1])), (int(hasta[0]), int(hasta[1]))
    n = max(abs(x1 - x0), abs(y1 - y0))
    alcance = max(0, int(alcance or 0))
    if n > alcance:
        x1 = x0 + round((x1 - x0) * alcance / n)
        y1 = y0 + round((y1 - y0) * alcance / n)
    if alcanzable(stage, x1, y1):
        return x1, y1
    for x, y in reversed(list(_linea((x0, y0), (x1, y1)))[:-1]):
        if alcanzable(stage, x, y):
            return x, y
    return x0, y0
