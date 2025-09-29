from datetime import timedelta
import logging

import aiohttp
import pycountry

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_CLIENT_ID,
    CONF_COUNTRY_CODE,
    CONF_HEADERS,
    CONF_REFRESH_TOKEN,
    CONF_UPDATE_INTERVAL,
    CONF_UPDATE_INTERVAL_DEFAULT,
    CONF_USER_ID,
    DOMAIN,
)
from .utils import get_device_location, get_devices, get_tag_location, renew_tokens

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON, Platform.DEVICE_TRACKER, Platform.SENSOR]


def convert_country_code(country_code: str) -> str:
    """Convert 2-letter country code to 3-letter code."""
    try:
        country = pycountry.countries.get(alpha_2=country_code)
        if country:
            return country.alpha_3
        return "USA"  # Fallback
    except (AttributeError, LookupError):
        return "USA"  # Fallback


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Samsung Find component."""
    hass.data[DOMAIN] = {}
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Samsung Find from a config entry."""
    hass.data[DOMAIN][entry.entry_id] = {}

    # Load OAuth2 PKCE credentials from config
    access_token = entry.data.get(CONF_ACCESS_TOKEN)
    client_id = entry.data.get(CONF_CLIENT_ID)
    refresh_token = entry.data.get(CONF_REFRESH_TOKEN)
    user_id = entry.data.get(CONF_USER_ID)

    # Get country from HA config, fallback to US
    country_code = hass.config.country or "US"
    _LOGGER.debug("country_code: %s", country_code)

    # Convert to 3-letter code using our new function
    country_code_3 = convert_country_code(country_code)
    _LOGGER.debug("country_code_3: %s", country_code_3)

    # Create session with required headers
    session = async_get_clientsession(hass)
    headers = {
        "x-sec-sa-userid": user_id,
        "x-sec-sa-countrycode": country_code_3,
        "Accept": "*/*",
    }

    hass.data[DOMAIN][entry.entry_id].update(
        {
            CONF_ACCESS_TOKEN: access_token,
            CONF_REFRESH_TOKEN: refresh_token,
            CONF_CLIENT_ID: client_id,
            CONF_HEADERS: headers,
            CONF_USER_ID: user_id,
            CONF_COUNTRY_CODE: country_code_3,
        }
    )

    await renew_tokens(hass, session, entry.entry_id)

    # Load all Samsung-Find devices from the users account
    devices = await get_devices(hass, session, entry.entry_id)

    _LOGGER.info("Found %s devices", len(devices))

    # Create an update coordinator. This is responsible to regularly
    # fetch data from Samsung Find API and update the device_tracker
    # and sensor entities

    update_interval = entry.options.get(
        CONF_UPDATE_INTERVAL, CONF_UPDATE_INTERVAL_DEFAULT
    )
    coordinator = SamsungFindCoordinator(hass, session, devices, update_interval)

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id].update(
        {"session": session, "coordinator": coordinator, "devices": devices}
    )

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_success = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_success:
        hass.data[DOMAIN].pop(entry.entry_id)
    else:
        _LOGGER.error(f"Unload failed: {unload_success}")
    return unload_success


class SamsungFindCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Samsung Find data."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        devices,
        update_interval: int,
    ):
        """Initialize the coordinator."""
        self.session = session
        self.devices = devices
        self.hass = hass
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=update_interval
            ),  # Update interval for all entities
        )

    async def _async_update_data(self):
        """Fetch data from Samsung Find."""
        try:
            device_locations = {}
            for device in self.devices:
                dev_data = device["data"]
                device_type = dev_data.get("deviceTypeCode", "UNKNOWN")
                if device_type == "TAG":
                    _LOGGER.debug("Getting location for %s", device_type)
                    tag_data = await get_tag_location(
                        self.hass, self.session, dev_data, self.config_entry.entry_id
                    )
                    device_locations[dev_data["dvceID"]] = tag_data
                    continue
                if device_type in ["PHONE", "TABLET", "WATCH", "BUDS"]:
                    _LOGGER.debug("Getting location for %s", device_type)
                    device_data = await get_device_location(
                        self.hass, self.session, dev_data, self.config_entry.entry_id
                    )
                    device_locations[dev_data["dvceID"]] = device_data
                else:
                    _LOGGER.info(
                        "Unsuported type of device. Skipping getting location for %s device with type: %s",
                        dev_data["dvceID"],
                        device_type,
                    )
                    continue

            _LOGGER.info("Fetched location for %s device", len(device_locations))
            return device_locations

        except ConfigEntryAuthFailed as err:
            raise
        except Exception as err:
            raise UpdateFailed(f"Error fetching data: {err}")
