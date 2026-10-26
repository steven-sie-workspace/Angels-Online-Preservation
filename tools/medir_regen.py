"""Cuanta HP/MP regenera el personaje, sentado y de pie, en una grabacion.

Lee un *_orden.jsonl (tools/proxy.py lo deja en logs/proxy/, y el servidor
en logs/sesiones/): los dos sentidos mezclados y con la marca de tiempo 't'.
Los .bin de corpus/ no sirven para esto porque no traen tiempo.

    python tools/medir_regen.py logs/proxy/mundo_XXXXXX_XXXXXX_orden.jsonl
    python tools/medir_regen.py RUTA --entidad 981      si adivina mal la suya

Lo que mira:
  s2c 0x0013  [u32 entidad][u8 n][(u8 tipo, u32 valor) x n]; tipo 0 = HP,
              2 = MP. Una subida es un tick de regeneracion (o una pocion).
  s2c 0x0002  la ficha: nivel en +65; HP, HP max, MP, MP max en +102.
  s2c 0x0042  HP, HP max, MP, MP max en +0 (stats recalculados).
  c2s 0x0016  accion 4 = sentarse, 5 = levantarse (Angel.exe 0x5BED00).
  s2c 0x000A  [entidad][objetivo][accion]: 8 sentado, 0 de pie.

Saca, por postura y por HP/MP: el paso mas comun, cada cuantos segundos
llega (mediana entre pasos seguidos de ese tamano) y que % del maximo es.
Las subidas mas grandes que 3 veces el paso comun se cuentan aparte: son
pociones, curas o buffs, no la regeneracion.
"""
import argparse
import collections
import json
import pathlib
import statistics
import struct
import sys

HP, MP = 0, 2


def leer(ruta):
    with open(ruta, encoding='utf-8') as f:
        for linea in f:
            if linea.strip():
                e = json.loads(linea)
                e['b'] = bytes.fromhex(e.get('hex', ''))
                yield e


def entidad_propia(eventos):
    """La que recibe mas actualizaciones de HP/MP."""
    cuenta = collections.Counter()
    for e in eventos:
        if e['dir'] == 's2c' and e['opcode'] == 0x13 and len(e['b']) >= 10:
            eid, n = struct.unpack_from('<IB', e['b'], 0)
            for i in range(n):
                if 5 + 5 * i + 5 <= len(e['b']) and e['b'][5 + 5 * i] in (HP, MP):
                    cuenta[eid] += 1
    return cuenta.most_common(1)[0][0] if cuenta else None


def medir(eventos, yo):
    sentado = False
    nivel = None
    maximo = {HP: 0, MP: 0}
    previo = {}
    subidas = []          # (t, postura, tipo, paso, maximo, nivel)
    cambios = []          # (t, 'sentado'/'de pie', origen)
    for e in eventos:
        b, op, t = e['b'], e['opcode'], e['t']
        if e['dir'] == 'c2s' and op == 0x16 and b and b[0] in (4, 5):
            cambios.append((t, 'pide sentarse' if b[0] == 4 else 'pide levantarse'))
        elif e['dir'] == 's2c' and op == 0x0A and len(b) >= 12:
            eid, _obj, acc = struct.unpack_from('<III', b, 0)
            if eid == yo and acc in (0, 8) and sentado != (acc == 8):
                sentado = acc == 8
                cambios.append((t, 'sentado' if sentado else 'de pie'))
        elif e['dir'] == 's2c' and op == 0x02 and len(b) >= 118:
            nivel = struct.unpack_from('<I', b, 65)[0]
            _h, maximo[HP], _m, maximo[MP] = struct.unpack_from('<IIII', b, 102)
        elif e['dir'] == 's2c' and op == 0x42 and len(b) >= 16:
            _h, maximo[HP], _m, maximo[MP] = struct.unpack_from('<IIII', b, 0)
        elif e['dir'] == 's2c' and op == 0x13 and len(b) >= 10:
            eid, n = struct.unpack_from('<IB', b, 0)
            if eid != yo:
                continue
            for i in range(n):
                if 5 + 5 * i + 5 > len(b):
                    break
                k, v = struct.unpack_from('<BI', b, 5 + 5 * i)
                if k not in (HP, MP):
                    continue
                if k in previo and v > previo[k]:
                    subidas.append((t, 'sentado' if sentado else 'de pie', k,
                                    v - previo[k], maximo[k], nivel))
                previo[k] = v
    return subidas, cambios, nivel, maximo


def resumen(subidas):
    filas = []
    for postura in ('sentado', 'de pie'):
        for k, nombre in ((HP, 'HP'), (MP, 'MP')):
            s = [x for x in subidas if x[1] == postura and x[2] == k]
            if not s:
                continue
            pasos = collections.Counter(x[3] for x in s)
            comun = pasos.most_common(1)[0][0]
            regen = [x for x in s if x[3] <= 3 * comun]
            # Intervalo: entre dos ticks seguidos del paso comun (los de un
            # buff o una cura en medio lo falsearian).
            justos = [x for x in s if x[3] == comun]
            dts = [b[0] - a[0] for a, b in zip(justos, justos[1:]) if 0 < b[0] - a[0] < 30]
            maxs = [x[4] for x in regen if x[4]]
            mx = statistics.median(maxs) if maxs else 0
            filas.append(dict(
                postura=postura, que=nombre, ticks=len(regen), paso=comun,
                pasos=pasos.most_common(5),
                cada=statistics.median(dts) if dts else None,
                maximo=mx, pct=(100.0 * comun / mx) if mx else None,
                otras=len(s) - len(regen)))
    return filas


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('ruta', type=pathlib.Path)
    ap.add_argument('--entidad', type=int, help='entity_id propio si no se adivina bien')
    ap.add_argument('--cambios', action='store_true', help='lista cada sentarse/levantarse')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')

    eventos = list(leer(a.ruta))
    yo = a.entidad or entidad_propia(eventos)
    if yo is None:
        raise SystemExit('no hay actualizaciones de HP/MP (0x0013) en la grabacion')
    subidas, cambios, nivel, maximo = medir(eventos, yo)
    dur = eventos[-1]['t'] - eventos[0]['t'] if eventos else 0
    print(f'{a.ruta.name}: {len(eventos)} mensajes, {dur:.0f} s, entidad {yo}, '
          f'nivel {nivel}, max HP {maximo[HP]} MP {maximo[MP]}')
    print(f'sentarse/levantarse: {sum(1 for c in cambios if c[1] == "sentado")} veces sentado')
    if a.cambios:
        for t, que in cambios:
            print(f'  {t:9.2f}  {que}')
    print()
    print(f'{"postura":8} {"":3} {"ticks":>5} {"paso":>6} {"cada (s)":>8} {"max":>7} {"% max":>6}  otros pasos')
    for f in resumen(subidas):
        cada = f'{f["cada"]:.2f}' if f['cada'] is not None else '-'
        pct = f'{f["pct"]:.2f}' if f['pct'] is not None else '-'
        print(f'{f["postura"]:8} {f["que"]:3} {f["ticks"]:5} {f["paso"]:6} {cada:>8} '
              f'{f["maximo"]:7.0f} {pct:>6}  {f["pasos"]}'
              + (f'  (+{f["otras"]} subidas grandes)' if f['otras'] else ''))


if __name__ == '__main__':
    main()
