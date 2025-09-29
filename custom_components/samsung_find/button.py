import logging

from .utils import SAMSUNG_FIND_API_URL_BASE
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ACCESS_TOKEN, CONF_HEADERS, CONF_USER_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up SmartThings Find button entities."""
    devices = hass.data[DOMAIN][entry.entry_id]["devices"]
    entities = []
    for device in devices:
        entities += [RingButton(hass, device)]
    async_add_entities(entities)


class RingButton(ButtonEntity):
    """Representation a button entity to make a SmartThings Find device ring."""

    def __init__(self, hass: HomeAssistant, device):
        """Initialize the button."""
        self._attr_unique_id = f"stf_ring_button_{device['data']['dvceID']}"
        self._attr_name = f"{device['data']['modelName']} Ring"

        if "icons" in device["data"] and "coloredIcon" in device["data"]["icons"]:
            self._attr_entity_picture = device["data"]["icons"]["coloredIcon"]
        self._attr_icon = "mdi:nfc-search-variant"
        self.device = device["data"]
        self._attr_device_info = device["ha_dev_info"]

    async def async_press(self):
        """Handle the button press."""
        entry_id = self.registry_entry.config_entry_id
        session = self.hass.data[DOMAIN][entry_id]["session"]
        device_id = self.device["dvceID"]
        user_id = self.hass.data[DOMAIN][entry_id]["user_id"]
        device_type = self.device.get("deviceTypeCode", "")
        metadata = self.device.get("metadata", "")
        params = {"type": device_type}

        if device_type == "TAG":
            ring_payload = {
                "operation": "RING",
                "usrId": user_id,
                "mnid": metadata.get("mnId", "0AFD"),
                "setupid": metadata.get("setupId", "430"),
                "firmwareversion": metadata.get("firmwareVersion", "01.04.01"),
            }
        else:
            ring_payload = {
                "operation": "RING",
                "usrId": user_id,
            }

        access_token = self.hass.data[DOMAIN][entry_id][CONF_ACCESS_TOKEN]
        user_id = self.hass.data[DOMAIN][entry_id][CONF_USER_ID]
        headers = self.hass.data[DOMAIN][entry_id][CONF_HEADERS]
        _LOGGER.info("Ringing device %s with payload: %s", device_id, ring_payload)

        # Set up headers
        headers.update(
            {"Content-Type": "application/json", "x-sec-sa-authtoken": access_token}
        )

        try:
            async with session.post(
                f"{SAMSUNG_FIND_API_URL_BASE}/find/devices/{device_id}/operation",
                json=ring_payload,
                headers=headers,
                params=params,
            ) as response:
                _LOGGER.debug("HTTP response status: %s", response.status)
                if response.status == 200:
                    _LOGGER.info(
                        "Successfully rang device %s", self.device["modelName"]
                    )
                else:
                    _LOGGER.error(
                        "Failed ring operation. Response from find operation API %s:",
                        await response.text(),
                    )
        except Exception as e:
            _LOGGER.error(
                f"Exception occurred while ringing '{self.device['modelName']}': %s", e
            )
