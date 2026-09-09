"""Telemetría acotada del barrido; no modifica las operaciones financieras."""
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from time import perf_counter


class Monitor:
    def __init__(self):
        self.run_id = None
        self.running = False
        self.started = None
        self.started_clock = None
        self.finished = None
        self.result = None
        self.error = None
        self.banks = {}
        self.recent = deque(maxlen=80)

    def begin(self):
        if self.running:
            raise RuntimeError('Ya hay un barrido en ejecución')
        self.__init__()
        self.running = True
        self.started = datetime.now(timezone.utc).isoformat()
        self.started_clock = perf_counter()

    def bank(self, stats, phase, records=()):
        self.banks[stats['banco_id']] = dict(stats, fase=phase)
        for record in records:
            self.recent.append({k: record[k] for k in (
                'banco_id', 'cuenta_id', 'saldo_usd', 'saldo_bs', 'tipo_cambio',
                'timestamp', 'bcb_timestamp', 'codigo_verificacion', 'estado', 'detail'
            ) if k in record})

    def end(self, result=None, error=None):
        self.running = False
        self.finished = perf_counter()
        self.result = result
        self.error = str(error) if error else None

    def snapshot(self):
        elapsed = ((perf_counter() if self.running else self.finished) - self.started_clock) if self.started_clock and (self.running or self.finished) else 0
        banks = list(self.banks.values())
        totals = {key: sum(b.get(key, 0) for b in banks) for key in ('leidas', 'confirmadas', 'ya_confirmadas', 'errores', 'lotes')}
        return deepcopy(dict(en_ejecucion=self.running, inicio=self.started, segundos=round(elapsed, 2),
                             barrido_id=self.run_id, totales=totals, bancos=banks, recientes=list(reversed(self.recent)),
                             resultado=self.result, error=self.error))

monitor = Monitor()
