"""Device tracker platform for Samsung Find integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.device_tracker import TrackerEntity as DeviceTrackerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .utils import get_sub_location, get_battery_level

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, 
    entry: ConfigEntry, 
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Samsung Find device tracker entities.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Function to add entities
    """
    devices = hass.data[DOMAIN][entry.entry_id]["devices"]
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities = []
    
    for device in devices:
        device_data = device['data']
        # Check if device has sub-devices (like earbuds with left/right)
        if 'subType' in device_data and device_data['subType'] == 'CANAL2':
            entities.append(SamsungDeviceTracker(hass, coordinator, device, "left"))
            entities.append(SamsungDeviceTracker(hass, coordinator, device, "right"))
        entities.append(SamsungDeviceTracker(hass, coordinator, device))
        
    async_add_entities(entities)

class SamsungDeviceTracker(DeviceTrackerEntity):
    """Representation of a Samsung Find device tracker."""

    def __init__(
        self, 
        hass: HomeAssistant, 
        coordinator: DataUpdateCoordinator, 
        device: dict[str, Any], 
        sub_device_name: str | None = None
    ) -> None:
        """Initialize the device tracker.
        
        Args:
            hass: Home Assistant instance
            coordinator: Data update coordinator
            device: Device data
            sub_device_name: Name of sub-device (for earbuds etc.)
        """
        self.coordinator = coordinator
        self.hass = hass
        self.device = device['data']
        self.device_id = device['data']['dvceID']
        self.sub_device_name = sub_device_name

        device_name = device['data']['modelName']
        sub_suffix = f" {sub_device_name.capitalize()}" if sub_device_name else ""
        
        self._attr_unique_id = f"stf_device_tracker_{self.device_id}{f'_{sub_device_name}' if sub_device_name else ''}"
        self._attr_name = f"{device_name}{sub_suffix}"
        self._attr_device_info = device['ha_dev_info']
        self._attr_latitude = None
        self._attr_longitude = None

        if 'icons' in device['data'] and 'coloredIcon' in device['data']['icons']:
            self._attr_entity_picture = device['data']['icons']['coloredIcon']
            
        self.async_update = coordinator.async_add_listener(self.async_write_ha_state)

    def async_write_ha_state(self) -> None:
        """Write state to Home Assistant if entity is enabled."""
        if not self.enabled:
            _LOGGER.debug("Ignoring state write request for disabled entity '%s'", self.entity_id)
            return
        super().async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return true if the device is available."""
        tag_data = self.coordinator.data.get(self.device_id, {})
        if not tag_data:
            _LOGGER.debug("No data available for '%s'; rendering state unavailable", self.name)
            return False
        if not tag_data.get('update_success', False):
            _LOGGER.debug("Last update for '%s' failed; rendering state unavailable", self.name)
            return False
        return True

    @property
    def source_type(self) -> str:
        """Return the source type of the device tracker."""
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        """Return the latitude of the device."""
        data = self.coordinator.data.get(self.device_id, {})
        if not self.sub_device_name:
            if data.get('location_found'):
                return data.get('used_loc', {}).get('latitude')
            return None
        else:
            _, loc = get_sub_location(data.get('ops', []), self.sub_device_name)
            return loc.get('latitude')

    @property
    def longitude(self) -> float | None:
        """Return the longitude of the device."""
        data = self.coordinator.data.get(self.device_id, {})
        if not self.sub_device_name:
            if data.get('location_found'):
                return data.get('used_loc', {}).get('longitude')
            return None
        else:
            _, loc = get_sub_location(data.get('ops', []), self.sub_device_name)
            return loc.get('longitude')

    @property
    def location_accuracy(self) -> int | None:
        """Return the location accuracy of the device."""
        data = self.coordinator.data.get(self.device_id, {})
        if not self.sub_device_name:
            if data.get('location_found'):
                return data.get('used_loc', {}).get('gps_accuracy')
            return None
        else:
            _, loc = get_sub_location(data.get('ops', []), self.sub_device_name)
            return loc.get('gps_accuracy')

    @property
    def battery_level(self) -> int | None:
        """Return the battery level of the device."""
        if self.sub_device_name:
            # Sub-devices don't have individual battery levels
            return None
            
        data = self.coordinator.data.get(self.device_id, {})
        return get_battery_level(self.name, data.get('battery'))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        tag_data = self.coordinator.data.get(self.device_id, {})
        device_data = self.device
        
        if self.sub_device_name:
            used_op, used_loc = get_sub_location(tag_data.get('ops', []), self.sub_device_name)
            tag_data = {**tag_data, **used_op, **used_loc}
            
        used_loc = tag_data.get('used_loc', {})
        if used_loc:
            tag_data['last_seen'] = used_loc.get('gps_date')
        else:
            tag_data['last_seen'] = None
            
        return {**tag_data, **device_data}
