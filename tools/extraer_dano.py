"""Saca de una captura cada golpe con su dano, para ajustar las formulas.

Para que sirve. El dano lo calcula el servidor y el cliente solo dibuja el
numero, asi que la formula no esta en ningun xml: hay que sacarla de lo que
manda un servidor real. Esto lee el _orden.jsonl del proxy y deja una fila por
golpe, con quien pego, a quien, con que ataque y los stats del monstruo de
monster.xml, y al final un resumen por monstruo y ataque.

Como se reconoce un golpe, medido en las capturas:

  - s2c 0x0008  [u4 entidad]..[16:32 nombre]..[u4 klass @40][u2 npc_type @45]
                klass 1 = monstruo
  - c2s 0x0016  [u1 accion 0x0c][u4 objetivo]       golpe basico
  - c2s 0x0006  [u2 ataque][u4 objetivo]..           habilidad
  - s2c 0x000A  [u4 origen][u4 objetivo][u2 tipo][u2 animacion]
  - s2c 0x0011  [u1 efecto][u1 fase][u4 origen][u4 objetivo]..[u2 ataque @21]
  - s2c 0x000B  [u4 entidad][u1 tipo][u4 cantidad]   EL NUMERO QUE SE VE
                tipo 1 normal, 2 critico; 3/4/7 son curas y no cuentan
  - s2c 0x0013  [u4 entidad][u1 n] y n veces [u1 kind][u4 valor]
                kind 0: HP del jugador, o % de vida del monstruo

El 0x000B no dice QUIEN pego. Se le asigna el ultimo 0x0011 o 0x000A que
apunto a esa entidad en los VENTANA segundos anteriores; si no hay ninguno
(sangrados, venenos) sale como origen 0.

    python tools/extraer_dano.py logs/proxy/mundo_201655_173169_orden.jsonl
    python tools/extraer_dano.py <captura> --csv dano.csv --yo 1001
"""
import argparse
import collections
import csv
import json
import pathlib
import sqlite3
import struct
import sys

RAIZ = pathlib.Path(__file__).parent.parent

VENTANA = 2.5
DANO = {1: 'normal', 2: 'critico'}
ATAQUE_NORMAL = 656


def _monstruos():
    """npc_type -> fila de monster.xml (via corpus/content.db)."""
    db = RAIZ / 'corpus' / 'content.db'
    if not db.exists():
        return {}
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    out = {}
    for r in con.execute("select id, name, level, hp, atk_avg, atk_var, def, "
                         "matk, mdef, accuracy, agility, crit_rate "
                         "from monster where id glob '[0-9]*'"):
        out[int(r['id'])] = dict(r)
    return out


def _magias():
    db = RAIZ / 'corpus' / 'content.db'
    if not db.exists():
        return {}
    con = sqlite3.connect(db)
    try:
        return {int(i): n for i, n in con.execute(
            "select id, name from magic where id glob '[0-9]*'")}
    except sqlite3.Error:
        return {}


def _num(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def leer(f):
    regs = []
    for linea in open(f, encoding='utf-8'):
        if linea.strip():
            try:
                regs.append(json.loads(linea))
            except ValueError:
                pass
    return regs


def adivinar_yo(regs):
    """El jugador es quien pega justo despues de cada pedido de ataque.

    Con otros jugadores al lado el 0x000A de todos llega igual, asi que se
    cuenta solo el origen de los que apuntan al objetivo que acabamos de
    pedir, y en el segundo y medio siguiente."""
    votos = collections.Counter()
    pedidos = {}
    for r in regs:
        b = bytes.fromhex(r.get('hex') or '')
        op, t = r.get('opcode'), r.get('t', 0)
        if r.get('dir') == 'c2s':
            if op == 0x16 and len(b) >= 5 and b[0] == 0x0C:
                pedidos[struct.unpack_from('<I', b, 1)[0]] = t
            elif op == 0x06 and len(b) >= 6:
                pedidos[struct.unpack_from('<I', b, 2)[0]] = t
        elif op == 0x0A and len(b) >= 8:
            src, tgt = struct.unpack_from('<II', b, 0)
            if tgt and t - pedidos.get(tgt, -99) <= 1.5:
                votos[src] += 1
        elif op == 0x11 and len(b) >= 10:
            src, tgt = struct.unpack_from('<II', b, 2)
            if tgt and t - pedidos.get(tgt, -99) <= 1.5:
                votos[src] += 1
    return votos.most_common(1)[0][0] if votos else None


def extraer(regs, yo, todos=False):
    mon = _monstruos()
    spawn = {}                 # entidad -> (nombre, npc_type, klass)
    ultimo = {}                # objetivo -> (t, origen, ataque, magia)
    pedido_hab = {}            # objetivo -> (t, ataque) del ultimo 0x0006
    hp_yo = None
    golpes = []
    for r in regs:
        b = bytes.fromhex(r.get('hex') or '')
        op, t, d = r.get('opcode'), r.get('t', 0), r.get('dir')
        if d == 'c2s':
            if op == 0x06 and len(b) >= 6:
                atq, tgt = struct.unpack_from('<HI', b, 0)
                pedido_hab[tgt] = (t, atq)
            continue
        if op == 0x08 and len(b) >= 47:
            ent = struct.unpack_from('<I', b, 0)[0]
            nom = b[16:32].split(b'\0')[0].decode('latin1', 'replace')
            klass = struct.unpack_from('<I', b, 40)[0]
            spawn[ent] = (nom, struct.unpack_from('<H', b, 45)[0], klass)
        elif op == 0x0A and len(b) >= 12:
            src, tgt, tipo, anim = struct.unpack_from('<IIHH', b, 0)
            if tgt and src != tgt:
                # El 0x000A no trae el ataque: si ya habia un 0x0011 del mismo
                # origen se respeta el suyo.
                prev = ultimo.get(tgt)
                atq = prev[2] if prev and prev[1] == src and t - prev[0] < VENTANA else 0
                ultimo[tgt] = (t, src, atq, prev[3] if prev and prev[1] == src else False)
        elif op == 0x11 and len(b) >= 23:
            src, tgt = struct.unpack_from('<II', b, 2)
            atq = struct.unpack_from('<H', b, 21)[0]
            if tgt and src != tgt:
                ultimo[tgt] = (t, src, atq, b[20] == 1)
        elif op == 0x13 and len(b) >= 6:
            ent, n = struct.unpack_from('<IB', b, 0)
            for k in range(n):
                off = 5 + 5 * k
                if off + 5 > len(b):
                    break
                kind, val = struct.unpack_from('<BI', b, off)
                if ent == yo and kind == 0:
                    hp_yo = val
        elif op == 0x0B and len(b) >= 9:
            ent, tipo, cant = struct.unpack_from('<IBI', b, 0)
            if tipo not in DANO:
                continue
            u = ultimo.get(ent)
            src, atq, magia = 0, 0, False
            if u and t - u[0] <= VENTANA:
                _, src, atq, magia = u
            if not todos and yo not in (src, ent):
                continue
            if src == yo and not atq:
                ph = pedido_hab.get(ent)
                atq = ph[1] if ph and t - ph[0] <= VENTANA else ATAQUE_NORMAL
            if ent == yo:
                sentido, otro = 'mob->yo', src
            elif src == yo:
                sentido, otro = 'yo->mob', ent
            else:
                sentido, otro = 'otros', ent
            nom, npc, klass = spawn.get(otro, ('?', 0, 0))
            m = mon.get(npc, {})
            golpes.append({
                't': round(t, 3), 'sentido': sentido,
                'origen': src, 'objetivo': ent,
                'monstruo': m.get('name') or nom, 'npc_type': npc,
                'nivel': _num(m.get('level')),
                'ataque': atq, 'magia': int(bool(magia)),
                'critico': int(tipo == 2), 'dano': cant,
                'hp_yo_antes': hp_yo if ent == yo else '',
                'mob_atk': _num(m.get('atk_avg')), 'mob_var': _num(m.get('atk_var')),
                'mob_def': _num(m.get('def')), 'mob_mdef': _num(m.get('mdef')),
                'mob_matk': _num(m.get('matk')),
            })
    return golpes


def resumen(golpes, magias):
    grupos = collections.defaultdict(list)
    for g in golpes:
        clave = (g['sentido'], g['monstruo'], g['nivel'], g['ataque'] if g['sentido'] == 'yo->mob' else 0,
                 g['critico'])
        grupos[clave].append(g)
    print()
    print('%-8s %-20s %4s %-24s %4s %4s %7s %7s %8s   %s' % (
        'dir', 'monster', 'lv', 'attack', 'crit', 'n', 'min', 'max', 'mean', 'monster stats'))
    for (s, nom, lv, atq, crit), gs in sorted(grupos.items()):
        ds = [g['dano'] for g in gs]
        media = sum(ds) / len(ds)
        g0 = gs[0]
        if s == 'mob->yo':
            # Con la formula "atk - def" de la defensa del jugador sale esto:
            stats = 'atk %d+-%d -> your DEF would be ~%d' % (
                g0['mob_atk'], g0['mob_var'], g0['mob_atk'] - media)
            nom_atq = ''
        else:
            de = g0['mob_mdef'] if g0['magia'] else g0['mob_def']
            stats = '%s %d -> your ATK would be ~%d' % (
                'mdef' if g0['magia'] else 'def', de, media + de)
            nom_atq = '%d %s' % (atq, magias.get(atq, ''))
        print('%-8s %-20.20s %4s %-24.24s %4s %4d %7d %7d %8.1f   %s' % (
            s, nom, lv or '', nom_atq, 'yes' if crit else '', len(ds),
            min(ds), max(ds), media, stats))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('capturas', nargs='+', help='uno o mas *_orden.jsonl')
    ap.add_argument('--yo', type=int, help='entidad del jugador; si no, se adivina')
    ap.add_argument('--csv', help='escribe todos los golpes en este .csv')
    ap.add_argument('--todos', action='store_true',
                    help='incluye golpes entre otros jugadores y monstruos')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')

    # En Windows la consola no expande el comodin: logs/proxy/mundo_*_orden.jsonl
    # llegaba tal cual.
    import glob
    capturas = [x for p in a.capturas for x in (sorted(glob.glob(p)) or [p])]
    magias = _magias()
    todos = []
    for f in capturas:
        regs = leer(f)
        yo = a.yo or adivinar_yo(regs)
        if yo is None:
            print('%s: no attacks found (no 0x0016/0x0006 followed by a hit)' % f)
            continue
        gs = extraer(regs, yo, a.todos)
        for g in gs:
            g['captura'] = pathlib.Path(f).name
        print('%s: player entity %d, %d hits (%d dealt, %d taken)' % (
            pathlib.Path(f).name, yo, len(gs),
            sum(g['sentido'] == 'yo->mob' for g in gs),
            sum(g['sentido'] == 'mob->yo' for g in gs)))
        todos += gs
    if not todos:
        return 1
    resumen(todos, magias)
    if a.csv:
        with open(a.csv, 'w', newline='', encoding='utf-8') as fh:
            w = csv.DictWriter(fh, fieldnames=list(todos[0].keys()))
            w.writeheader()
            w.writerows(todos)
        print('\n%d rows -> %s' % (len(todos), a.csv))
    return 0


if __name__ == '__main__':
    sys.exit(main())
