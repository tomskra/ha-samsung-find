"""Sensor platform for Samsung Find integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .utils import get_battery_level

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, 
    entry: ConfigEntry, 
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Samsung Find sensor entities.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Function to add entities
    """
    devices = hass.data[DOMAIN][entry.entry_id]["devices"]
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities = []
    
    for device in devices:
        entities.append(DeviceBatterySensor(hass, coordinator, device))
        
    async_add_entities(entities)


class DeviceBatterySensor(SensorEntity):
    """Representation of a Samsung Find device battery sensor."""

    def __init__(
        self, 
        hass: HomeAssistant, 
        coordinator: DataUpdateCoordinator, 
        device: dict[str, Any]
    ) -> None:
        """Initialize the sensor.
        
        Args:
            hass: Home Assistant instance
            coordinator: Data update coordinator
            device: Device data
        """
        self.coordinator = coordinator
        self.hass = hass
        self.device = device["data"]
        self.device_id = device["data"]["dvceID"]
        
        self._attr_unique_id = f"stf_device_battery_{self.device_id}"
        self._attr_name = f"{device['data']['modelName']} Battery"
        self._attr_device_info = device["ha_dev_info"]
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "%"

    @property
    def available(self) -> bool:
        """Return True if the entity is available.
        
        Makes the entity show unavailable state if no data was received
        or there was an error during last update.
        """
        tag_data = self.coordinator.data.get(self.device_id, {})
        if not tag_data:
            _LOGGER.debug(
                "Battery sensor: No data available for '%s'; rendering state unavailable", 
                self.name
            )
            return False
        if not tag_data.get("update_success", False):
            _LOGGER.debug(
                "Last update for battery sensor '%s' failed; rendering state unavailable", 
                self.name
            )
            return False
        return True

    @property
    def unit_of_measurement(self) -> str:
        return "%"

    @property
    def state(self):
        return get_battery_level(
            self.name,
            self.coordinator.data.get(self.device_id, {}).get("battery", None),
        )
