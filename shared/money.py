"""Importes exactos compatibles con DECIMAL(18,4)."""
import re
from decimal import Decimal, InvalidOperation, DecimalException, ROUND_HALF_EVEN

UNIT = Decimal('0.0001')
MAX_MONEY = Decimal('99999999999999.9999')


def parse_money(value, *, rate=False):
    text = str(value).strip()
    if not text or len(text) > 100:
        raise ValueError('Importe vacío o demasiado largo')
    # Un punto es decimal; varios puntos son miles estrictamente agrupados.
    if ',' in text and '.' in text:
        if not re.fullmatch(r'[+-]?\d{1,3}(?:,\d{3})+\.\d+', text):
            raise ValueError('Separadores ambiguos; use punto decimal sin miles')
        text = text.replace(',', '')
    elif ',' in text:
        text = text.replace(',', '.')
    elif text.count('.') > 1:
        if not re.fullmatch(r'[+-]?\d{1,3}(?:\.\d{3}){2,}', text):
            raise ValueError('Agrupación de miles inválida')
        text = text.replace('.', '')
    if not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', text):
        raise ValueError('Importe no numérico o no finito')
    try:
        number = Decimal(text)
        if not number.is_finite() or number.copy_abs() > MAX_MONEY:
            raise ValueError('Importe fuera de DECIMAL(18,4)')
        rounded = number.quantize(UNIT, rounding=ROUND_HALF_EVEN)
        if number != rounded:
            raise ValueError('Importe con más de cuatro decimales significativos')
    except InvalidOperation as exc:
        raise ValueError('Importe fuera de rango') from exc
    if rate and rounded <= 0:
        raise ValueError('La cotización debe ser positiva')
    return rounded


def convert_money(balance, rate):
    try:
        result = (parse_money(balance) * parse_money(rate, rate=True)).quantize(UNIT, rounding=ROUND_HALF_EVEN)
        return parse_money(result)
    except DecimalException as exc:
        raise ValueError('Saldo convertido fuera de DECIMAL(18,4)') from exc
