"""Sipariş kodu üretimi."""

import secrets

# Karıştırılabilecek karakterler (0/O, 1/I/L) çıkarıldı; müşteri kodu okurken hata yapmasın.
_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def new_order_code(length: int = 6) -> str:
    """Ör. 'BLT-7K3QX9'. Benzersizliği veritabanındaki UNIQUE kısıtı garanti eder."""
    return "BLT-" + "".join(secrets.choice(_ALPHABET) for _ in range(length))
