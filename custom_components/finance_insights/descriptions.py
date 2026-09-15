"""Shared sensor description type."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntityDescription, SensorStateClass

EUR = "EUR"


@dataclass(frozen=True, kw_only=True)
class FISensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict], Any]
    attrs_fn: Callable[[dict], dict] | None = None


def money(key: str, value_fn: Callable[[dict], Any], icon: str | None = None, attrs=None) -> FISensorDescription:
    return FISensorDescription(
        key=key, translation_key=key, native_unit_of_measurement=EUR,
        device_class=SensorDeviceClass.MONETARY, state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2, icon=icon, value_fn=value_fn, attrs_fn=attrs,
    )
