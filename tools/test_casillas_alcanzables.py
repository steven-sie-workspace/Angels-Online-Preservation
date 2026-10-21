"""Monstruos y saltos del Chaos Mage solo en casillas a las que se llega.

Contra los datos de verdad de plantillas/transitable.bin y las plantillas
de los mapas. Antes, en el Phoenix Palace 144 de los 307 monstruos que se
mueven salian dentro de una pared o del agua, y Swiftness Spell / Dimension
Shift dejaban al jugador en mitad de un lago.

    python -m pytest tools/test_casillas_alcanzables.py
"""
import inspect
import json
import pathlib
import struct
import sys

SERVER = pathlib.Path(__file__).resolve().parent.parent / 'server'
sys.path.insert(0, str(SERVER))

import app
import combate
import login
import transitable as tr

PHOENIX_PALACE, SILENT_LAKESIDE, PRISTINE_LAKE, LYCEUM = 199, 382, 356, 41


def _plantilla(stage):
    f = SERVER / 'plantillas' / app.mapas_poblados()[stage]
    return json.loads(f.read_text(encoding='utf-8'))['spawns']


def _se_mueve(e):
    return (combate._datos(e['npc_type']) or {}).get('move_speed', 50) > 0


# --- 1. Donde salen los monstruos ------------------------------------------

def test_monstruos_de_plantilla_en_suelo_alcanzable():
    for stage in (PHOENIX_PALACE, SILENT_LAKESIDE, PRISTINE_LAKE):
        spawns = _plantilla(stage)
        casillas = login.casillas_de_plantilla(stage, spawns)
        moviles = [e for e in spawns if e['entity_id'] in casillas
                   and not e.get('apagado') and _se_mueve(e)]
        mal_antes = [e for e in moviles if not tr.alcanzable(stage, *e['tile'])]
        assert mal_antes, f'{stage}: la plantilla ya no trae puntos en agua o pared'
        mal = [(e['nombre'], e['tile'], casillas[e['entity_id']]) for e in moviles
               if not tr.alcanzable(stage, *casillas[e['entity_id']])]
        assert not mal, f'{stage}: siguen fuera del suelo: {mal[:5]}'


def test_spawn_del_cliente_y_monstruo_del_servidor_coinciden():
    # El 0x0008 de login.poblar: [u16 op][u32 entidad][u32][u32 x][u32 y].
    vistos = {}
    for pkt in login.poblar(PHOENIX_PALACE):
        if pkt[:2] == struct.pack('<H', 0x0008) and len(pkt) >= 18:
            eid, _, x, y = struct.unpack_from('<IIII', pkt, 2)
            vistos[eid] = (x, y)
    bichos = app._monstruos_de(PHOENIX_PALACE)
    assert len(bichos) > 100
    distintos = [(eid, vistos.get(eid), (m.tile_x, m.tile_y)) for eid, m in bichos.items()
                 if vistos.get(eid) != (m.tile_x, m.tile_y)]
    assert not distintos, distintos[:5]
    for m in bichos.values():
        if not getattr(m, 'es_estatico', False):
            assert tr.alcanzable(PHOENIX_PALACE, m.tile_x, m.tile_y), (m.nombre, m.tile_x, m.tile_y)


def test_reaparece_en_suelo_alcanzable():
    spawns = _plantilla(PHOENIX_PALACE)
    casillas = login.casillas_de_plantilla(PHOENIX_PALACE, spawns)
    e = next(e for e in spawns if e['entity_id'] in casillas and _se_mueve(e)
             and not tr.alcanzable(PHOENIX_PALACE, *e['tile']))
    m = combate.Monstruo(e['entity_id'], e['npc_type'], e['nombre'],
                         list(casillas[e['entity_id']]), stage=PHOENIX_PALACE)
    for _ in range(40):
        m.vivo = False
        m.revivir()
        assert tr.alcanzable(PHOENIX_PALACE, m.tile_x, m.tile_y), (m.tile_x, m.tile_y)


def test_generado_en_el_lago_sale_en_la_orilla():
    # (209, 10) es agua de Silent Lakeside; la orilla esta en (202, 10).
    assert not tr.se_pisa(SILENT_LAKESIDE, 209, 10)
    x, y = combate.casilla_de_aparicion(SILENT_LAKESIDE, (209, 10))
    assert tr.alcanzable(SILENT_LAKESIDE, x, y)
    assert max(abs(x - 209), abs(y - 10)) <= 20
    # Lo que ya esta bien no se toca, y un mapa sin datos tampoco.
    assert combate.casilla_de_aparicion(SILENT_LAKESIDE, (199, 10)) == [199, 10]
    assert combate.casilla_de_aparicion(999999, (5, 5)) == [5, 5]


def test_trozo_suelto_no_cuenta_como_alcanzable():
    # Lyceum: (196, 66) se pisa pero es una isla de 115 casillas sin portal.
    assert tr.se_pisa(LYCEUM, 196, 66)
    assert not tr.alcanzable(LYCEUM, 196, 66)
    assert tr.alcanzable(LYCEUM, 201, 64)


# --- 2. Los saltos del Chaos Mage ------------------------------------------

def test_saltos_del_chaos_mage():
    # Swiftness Spell I..V y Dimension Shift I..V: los dos del 混亂技能,
    # 射程 12 y objetivo el suelo.
    for tipo in sorted(combate.SWIFTNESS_SPELL) + list(range(13595, 13600)):
        d = combate.datos_magia(tipo)
        assert d['rango'] == 12 and d['es_terreno'], tipo


def test_salto_al_lago_cae_en_la_orilla():
    desde, lago = (199, 10), (209, 10)
    assert not tr.se_pisa(SILENT_LAKESIDE, *lago)
    x, y = tr.destino_de_salto(SILENT_LAKESIDE, desde, lago, 12)
    assert (x, y) == (202, 10)
    assert tr.alcanzable(SILENT_LAKESIDE, x, y)


def test_salto_respeta_el_alcance():
    # De (163, 9) a (193, 9) todo es suelo: se acorta a 12 casillas.
    assert tr.destino_de_salto(SILENT_LAKESIDE, (163, 9), (193, 9), 12) == (175, 9)
    assert tr.destino_de_salto(SILENT_LAKESIDE, (163, 9), (170, 9), 12) == (170, 9)


def test_salto_a_un_tejado_no_se_hace():
    # Toda la linea hasta la isla del Lyceum es pared o isla: no salta.
    assert tr.destino_de_salto(LYCEUM, (201, 64), (196, 66), 12) == (201, 64)


def test_el_hechizo_usa_el_destino_comprobado():
    fuente = inspect.getsource(app)
    i = fuente.index('_transitable.destino_de_salto(')
    for marca in ('if 13595 <= tipo <= 13599 and cx > 0',
                  'if tipo in _cb.SWIFTNESS_SPELL and cx > 0'):
        j = fuente.index(marca)
        assert i < j and j - i < 6000, marca
