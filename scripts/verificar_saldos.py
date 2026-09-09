"""Comprueba que los saldos cifrados descifran EXACTAMENTE al valor del CSV.

Esta verificación existe porque el 2026-09-09 se detectó que los datos sembrados
tenían los saldos multiplicados hasta por 10.000 (se les había quitado el punto
decimal): una cuenta de 301.716,85 USD figuraba como 3.017.168.517,00 USD.

Se ejecuta automáticamente dentro de Reiniciar-Demo.ps1 antes de cargar las
bases, para que un dataset mal cifrado nunca llegue a los 14 bancos.

Uso:
    python scripts/verificar_saldos.py
    python scripts/verificar_saldos.py --muestra 500 --bancos 1,2,3
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "asfi-service")]

from crypto.key_manager import CipherFactory  # noqa: E402

NOMBRES = {
    1: "Unión (César)", 2: "Mercantil (Atbash)", 3: "BNB (Vigenère)",
    4: "BCP (Playfair)", 5: "BISA (Hill)", 6: "Ganadero (DES)",
    7: "Económico (3DES)", 8: "Prodem (Blowfish)", 9: "Solidario (Twofish)",
    10: "Fortaleza (AES)", 11: "FIE (RSA)", 12: "PYME (ElGamal)",
    13: "BDP (ECC)", 14: "Nación Argentina (ChaCha20)",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", type=Path, default=ROOT / "data" / "dataset.csv")
    ap.add_argument("--seed-dir", type=Path, default=ROOT / "data" / "seed")
    ap.add_argument("--muestra", type=int, default=300,
                    help="Cuentas a verificar por banco (0 = todas)")
    ap.add_argument("--bancos", default=",".join(str(i) for i in range(1, 15)))
    args = ap.parse_args()

    if not args.dataset.exists():
        print(f"No se encontró el dataset: {args.dataset}")
        return 1

    bancos = [int(b) for b in args.bancos.split(",") if b.strip()]

    print("Leyendo el dataset original...")
    original: dict[str, str] = {}
    with args.dataset.open(encoding="utf-8-sig", newline="") as fh:
        for fila in csv.DictReader(fh):
            nro = (fila.get("Nro") or "").strip()
            if nro:
                original[nro] = (fila.get("Saldo") or "").strip()
    print(f"  {len(original)} cuentas en el CSV\n")

    print(f"{'Banco':<28} {'Verificadas':>12} {'Correctas':>10} {'ERRORES':>9}")
    print("-" * 63)

    total_errores = 0
    total_verificadas = 0
    ejemplos: list[str] = []

    for banco in bancos:
        archivo = args.seed_dir / f"bank_{banco:02d}.jsonl"
        if not archivo.exists():
            print(f"{NOMBRES.get(banco, banco):<28} {'(sin archivo)':>12}")
            continue

        cifrador, llave = CipherFactory.get_cipher_for_bank(banco)
        verificadas = correctas = errores = 0

        with archivo.open(encoding="utf-8") as fh:
            for linea in fh:
                if args.muestra and verificadas >= args.muestra:
                    break
                if not linea.strip():
                    continue
                registro = json.loads(linea)
                esperado = original.get(str(registro.get("Nro")))
                if esperado is None:
                    continue
                verificadas += 1
                try:
                    obtenido = cifrador.decrypt(registro["Saldo"], llave)
                    if Decimal(obtenido) == Decimal(esperado):
                        correctas += 1
                    else:
                        errores += 1
                        if len(ejemplos) < 5:
                            proporcion = ""
                            try:
                                if Decimal(esperado) != 0:
                                    proporcion = f"  (x{Decimal(obtenido) / Decimal(esperado):.0f})"
                            except Exception:
                                pass
                            ejemplos.append(
                                f"    Banco {banco} cuenta {registro['Nro']}: "
                                f"CSV={esperado}  descifrado={obtenido}{proporcion}")
                except Exception as exc:
                    errores += 1
                    if len(ejemplos) < 5:
                        ejemplos.append(f"    Banco {banco} cuenta {registro.get('Nro')}: "
                                        f"{type(exc).__name__}: {exc}")

        total_errores += errores
        total_verificadas += verificadas
        marca = "" if errores == 0 else "   <-- REVISAR"
        print(f"{NOMBRES.get(banco, banco):<28} {verificadas:>12} {correctas:>10} {errores:>9}{marca}")

    print("-" * 63)
    print(f"{'TOTAL':<28} {total_verificadas:>12} {total_verificadas - total_errores:>10} {total_errores:>9}")

    if ejemplos:
        print("\nEjemplos de diferencias:")
        for linea in ejemplos:
            print(linea)

    print()
    if total_errores:
        print("RESULTADO: FALLO. Los saldos cifrados no coinciden con el dataset.")
        print("No cargues las bases con estos datos. Revisa shared/money.py y")
        print("vuelve a ejecutar el seeder.")
        return 1

    if total_verificadas == 0:
        print("RESULTADO: no se verificó ninguna cuenta. ¿Ejecutaste el seeder?")
        return 1

    print("RESULTADO: OK. Todos los saldos descifran al valor exacto del CSV.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
