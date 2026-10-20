"""Logros, titulos y puntos (achievement.xml).

4.351 logros en 74 tipos de regla. Cada fila dice su categoria, el texto,
cuantos puntos da, si anuncia al servidor y, 543 de ellas, que titulo
desbloquea.

Las reglas son el campo 規法 de la tabla. Aqui se implementan las que se
pueden comprobar con lo que el servidor ya sabe; las demas quedan
registradas y se dan por un aviso externo (`otorgar`), para que la tabla
este entera aunque la condicion todavia no se vigile.

Reglas que SI se comprueban solas:

    達指定等級        llegar a nivel N
    技能到達指定等級    una habilidad a nivel N
    殺指定編號怪物      matar N veces un npc_type
    角色素質          un stat por encima de N
    成就積分          acumular N puntos de logro
    達成成就          tener otros logros (param1 y param2)
    任務完成          terminar la quest param1
    擁有遊戲幣        tener N de oro

Las que NO, y por que:

    融合相關 (361)    la fusion de mascotas
    NPC觸發 (297)     que el servidor avise al hablar con el NPC
    房屋系統 (79)     el sistema de casas

EL CLIENTE NO CALCULA NADA. La ventana de logros (Ctrl+A) solo pinta lo que
le manda el servidor al entrar en el 0x0155, que el proyecto tomo por
"tablas de probabilidad" porque las barras de progreso parecen curvas
(100, 50, 33, 25, 20 es "nivel 20" visto desde los logros de 20, 40, 60...).
Comprobado contra las dos capturas del servidor privado:

    +0     800 B   bitset de conseguidos: el bit `id` (byte id//8, bit id%8)
    +800  6400 B   un byte por logro, en el offset 800+id: progreso 0..100
    +7200  U32     puntos de logro (la suma de `puntos` de los conseguidos)

En las dos capturas los 35 y 37 bits encendidos son justo los que estan al
100, y la cola vale 36 y 38, la suma exacta de sus puntos.
"""
import json
import pathlib
import struct

_TABLA = None
_POR_REGLA = None
_POR_ID = None

BITS = 800              # bytes del bitset
TOTAL = 6400            # logros que caben en el mensaje
OPCODE = 0x0155


def tabla() -> list:
    global _TABLA
    if _TABLA is None:
        f = pathlib.Path(__file__).parent / 'plantillas' / 'logros.json'
        try:
            _TABLA = json.loads(f.read_text(encoding='utf-8'))['filas']
        except Exception:
            _TABLA = []
    return _TABLA


def por_regla(regla: str) -> list:
    global _POR_REGLA
    if _POR_REGLA is None:
        _POR_REGLA = {}
        for f in tabla():
            _POR_REGLA.setdefault(f.get('regla'), []).append(f)
    return _POR_REGLA.get(regla, [])


def de_id(lid: int):
    global _POR_ID
    if _POR_ID is None:
        _POR_ID = {f.get('id'): f for f in tabla()}
    return _POR_ID.get(lid)


def puntos_de(conseguidos) -> int:
    """La suma de puntos de los logros que ya tiene."""
    ids = set(int(x) for x in (conseguidos or []))
    return sum(_num(f.get('puntos')) for f in tabla() if f.get('id') in ids)


def titulos_de(conseguidos) -> list:
    """Los titulos que desbloquean esos logros."""
    ids = set(int(x) for x in (conseguidos or []))
    return sorted({int(f['titulo']) for f in tabla()
                   if f.get('id') in ids and f.get('titulo')})


# --------------------------------------------------------------- reglas
def _num(v, d=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


# param1 de 角色素質 -> clave del dict `stats` (ver stats_de_0042)
STATS = {
    'HP最大值': 'hp_max', 'MP最大值': 'mp_max', '主手攻擊': 'atk',
    '防禦': 'dfs', '魔攻': 'matk', '魔防': 'mdef',
    '精準': 'rigor', '靈敏': 'agilidad', '最大負重': 'carga',
}


def stats_de_0042(sub: bytes) -> dict:
    """Los stats efectivos tal como el cliente los ve, sacados del 0x0042
    que arma inventario.stats (con el opcode delante)."""
    b = sub[2:]
    if len(b) < 96:
        return {}
    u32 = lambda o: struct.unpack_from('<I', b, o)[0]
    u16 = lambda o: struct.unpack_from('<H', b, o)[0]
    return {'hp_max': u32(4), 'mp_max': u32(12), 'atk': u32(24),
            'dfs': u32(36), 'matk': u32(44), 'mdef': u32(52),
            'rigor': u16(58), 'agilidad': u16(62), 'carga': u32(92)}


def _pct(tiene, pide) -> int:
    if pide <= 0:
        return 0
    return max(0, min(100, tiene * 100 // pide))


def progreso(personaje, conseguidos, *, muertos=None, stats=None,
             quest_hecha=None) -> dict:
    """{id: 0..100} de los logros cuyas reglas el servidor sabe medir.

    `muertos` es {npc_type: cuantos}, `stats` el dict de stats_de_0042 y
    `quest_hecha(qid) -> bool` dice si una quest esta terminada.
    """
    ya = set(int(x) for x in (conseguidos or []))
    muertos = muertos or {}
    stats = stats or {}
    res = {}
    nivel = _num(getattr(personaje, 'nivel', 0))
    habs = [_num(h[1], 1) for h in (getattr(personaje, 'habilidades', None) or [])
            if isinstance(h, (list, tuple)) and len(h) >= 2]
    hab_max = max(habs) if habs else 0
    oro = _num(getattr(personaje, 'oro', 0))

    for f in por_regla('達指定等級'):
        res[f['id']] = _pct(nivel, _num(f.get('param1')))
    for f in por_regla('技能到達指定等級'):
        res[f['id']] = _pct(hab_max, _num(f.get('param1')))
    for f in por_regla('殺指定編號怪物'):
        tipo = _num(f.get('param1'))
        if tipo:
            res[f['id']] = _pct(_num(muertos.get(tipo, muertos.get(str(tipo), 0))),
                                max(1, _num(f.get('param2'), 1)))
    for f in por_regla('角色素質'):
        clave = STATS.get(str(f.get('param1') or ''))
        if clave and clave in stats:
            res[f['id']] = _pct(_num(stats.get(clave)), _num(f.get('param2')))
    for f in por_regla('擁有遊戲幣'):
        res[f['id']] = _pct(oro, _num(f.get('param1')))
    if quest_hecha is not None:
        for f in por_regla('任務完成'):
            q = _num(f.get('param1'))
            if q:
                try:
                    res[f['id']] = 100 if quest_hecha(q) else 0
                except Exception:
                    pass

    # Las que dependen de otros logros: se repiten hasta que no cambie nada,
    # porque conseguir uno puede completar un 達成成就 o un 成就積分.
    tiene = set(ya) | {i for i, v in res.items() if v >= 100}
    for _ in range(10):
        pts = puntos_de(tiene)
        antes = len(tiene)
        for f in por_regla('成就積分'):
            res[f['id']] = _pct(pts, _num(f.get('param1')))
        for f in por_regla('達成成就'):
            pide = [x for x in (_num(f.get('param1')), _num(f.get('param2'))) if x]
            if pide:
                res[f['id']] = 100 * sum(1 for x in pide if x in tiene) // len(pide)
        tiene |= {i for i, v in res.items() if v >= 100}
        if len(tiene) == antes:
            break
    return res


def comprobar(personaje, conseguidos, *, muertos=None, stats=None,
              quest_hecha=None) -> list:
    """Los logros que el personaje cumple y todavia no tiene."""
    ya = set(int(x) for x in (conseguidos or []))
    pr = progreso(personaje, conseguidos, muertos=muertos, stats=stats,
                  quest_hecha=quest_hecha)
    return sorted(i for i, v in pr.items() if v >= 100 and i not in ya)


def otorgar(conseguidos, lid: int) -> bool:
    """Da un logro a mano. Para las reglas que el servidor no vigila."""
    lid = int(lid)
    if de_id(lid) is None or lid in set(int(x) for x in (conseguidos or [])):
        return False
    conseguidos.append(lid)
    return True


# --------------------------------------------------------------- 0x0155
def paquete(conseguidos, prog=None) -> bytes:
    """El 0x0155 entero (con opcode): conseguidos, progreso y puntos."""
    b = bytearray(BITS + TOTAL + 4)
    ya = {int(x) for x in (conseguidos or []) if 0 <= int(x) < TOTAL}
    for i, v in (prog or {}).items():
        if 0 <= i < TOTAL:
            b[BITS + i] = max(0, min(100, int(v)))
    for i in ya:
        b[i // 8] |= 1 << (i % 8)
        b[BITS + i] = 100
    struct.pack_into('<I', b, BITS + TOTAL, min(puntos_de(ya), 0xFFFFFFFF))
    return struct.pack('<H', OPCODE) + bytes(b)


def muertos_de(personaje) -> dict:
    """{npc_type: cuantos} de los contadores guardados del personaje."""
    c = getattr(personaje, 'contadores', None) or {}
    return {int(k[5:]): _num(v) for k, v in c.items()
            if str(k).startswith('mata:') and str(k)[5:].isdigit()}


_TIPOS_QUE_CUENTAN = None


def cuenta_muerte(personaje, npc_type: int) -> bool:
    """Suma una muerte de ese npc_type. True si algun logro la mira, para
    que el llamador sepa si merece la pena guardar y refrescar."""
    global _TIPOS_QUE_CUENTAN
    if _TIPOS_QUE_CUENTAN is None:
        _TIPOS_QUE_CUENTAN = {_num(f.get('param1')) for f in por_regla('殺指定編號怪物')}
    npc_type = _num(npc_type)
    if npc_type not in _TIPOS_QUE_CUENTAN:
        return False
    if getattr(personaje, 'contadores', None) is None:
        personaje.contadores = {}
    k = 'mata:%d' % npc_type
    personaje.contadores[k] = _num(personaje.contadores.get(k)) + 1
    return True


def actualizar(personaje, bolsa=None, *, stats=None):
    """Mide todo, apunta los logros nuevos en personaje.logros y devuelve
    (paquete 0x0155, [ids nuevos])."""
    import inventario as _inv
    import misiones as _mis
    if getattr(personaje, 'logros', None) is None:
        personaje.logros = []
    if stats is None:
        b = bolsa if bolsa is not None else getattr(personaje, 'inventario', None)
        try:
            stats = stats_de_0042(_inv.stats(
                b, getattr(personaje, 'habilidades', None),
                hp=getattr(personaje, 'hp', 0), hp_max=getattr(personaje, 'hp_max', 0),
                mp=getattr(personaje, 'mp', 0), mp_max=getattr(personaje, 'mp_max', 0),
                buffs=getattr(personaje, 'buffs', None),
                mejoras=getattr(personaje, 'mejoras', None)))
        except Exception:
            stats = {}
    pr = progreso(personaje, personaje.logros, muertos=muertos_de(personaje),
                  stats=stats, quest_hecha=lambda q: _mis.mision_completada(personaje, q))
    ya = set(int(x) for x in personaje.logros)
    nuevos = sorted(i for i, v in pr.items() if v >= 100 and i not in ya)
    personaje.logros.extend(nuevos)
    if nuevos:
        # Lo guarda quien tenga la sesion (al entrar no la hay a mano).
        personaje._logros_sin_guardar = True
    return paquete(personaje.logros, pr), nuevos
