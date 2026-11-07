"""Cálculos locales para la futura fase de perfil; no envía datos."""
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo


def age(birth_date: date, today: date) -> int:
    if birth_date > today:
        raise ValueError("La fecha de nacimiento está en el futuro")
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


def salary(amount, source_period, target_period, weekly_hours):
    amount, hours = Decimal(str(amount)), Decimal(str(weekly_hours))
    if not amount.is_finite() or not hours.is_finite() or amount < 0 or hours <= 0:
        raise ValueError("Salario u horas inválidos")
    factors = {"hour": hours * 52, "week": Decimal(52), "month": Decimal(12), "year": Decimal(1)}
    if source_period not in factors or target_period not in factors:
        raise ValueError("Periodo inválido")
    return amount * factors[source_period] / factors[target_period]


def convert_time(value: datetime, source_zone: str, target_zone: str):
    if value.tzinfo is None:
        raise ValueError("Se requiere fecha y hora con zona horaria explícita")
    if getattr(value.tzinfo, "key", None) != source_zone:
        raise ValueError("La zona de origen debe coincidir con la fecha proporcionada")
    return value.astimezone(ZoneInfo(target_zone))
