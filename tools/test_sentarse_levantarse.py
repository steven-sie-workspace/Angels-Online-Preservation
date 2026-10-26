"""0x0016 accion 4 = sentarse, 5 = levantarse (no es un interruptor).

Angel.exe 0x5BED00 (tecla Insert) y 0x55A34C (descanso del Angel Guardian)
mandan 4 o 5 segun lo que quieren. El descanso repite el 5 cada segundo
hasta que el servidor contesta con el 0x000A de levantarse.
"""
import os, sys, struct
sys.path.insert(0, os.path.abspath('server'))
sys.path.insert(0, os.path.abspath('tools'))
import app
from test_sitting_and_regen import MockSession

addr = ('127.0.0.1', 1)


def mandar(srv, ses, accion):
    ses.salida.clear()
    srv.manejar(ses, 0x0016, None, {}, addr, cuerpo=struct.pack('<IB', accion, 0))
    return [struct.unpack('<HIII', p)[3] for p in ses.salida
            if len(p) == 14 and p[:2] == b'\x0a\x00']


def main():
    srv = app.Servidor(16768, 16769, 21238)
    ses = MockSession()
    assert mandar(srv, ses, 4) == [8] and ses.sentado
    # un segundo 4 no lo levanta (antes era un interruptor)
    assert mandar(srv, ses, 4) == [8] and ses.sentado
    assert mandar(srv, ses, 5) == [0] and not ses.sentado
    # el 5 repetido estando de pie se sigue contestando y no lo sienta
    assert mandar(srv, ses, 5) == [0] and not ses.sentado
    print('test_sentarse_levantarse passed!')


if __name__ == '__main__':
    main()
