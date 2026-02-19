"""Samsung Find integration for Home Assistant."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import aiohttp

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
    CONF_IGNORE_MOBILE_DEVICES,
    CONF_IGNORE_MOBILE_DEVICES_DEFAULT,
    CONF_REFRESH_TOKEN,
    CONF_UPDATE_INTERVAL,
    CONF_UPDATE_INTERVAL_DEFAULT,
    CONF_USER_ID,
    CONF_USERAUTH_TOKEN,
    DOMAIN,
    MOBILE_DEVICE_TYPES,
)
from .utils import get_device_location, get_devices, get_tag_location, renew_tokens

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON, Platform.DEVICE_TRACKER, Platform.SENSOR]

# Country code mapping to avoid blocking I/O calls
COUNTRY_CODE_MAPPING = {
    "AD": "AND", "AE": "ARE", "AF": "AFG", "AG": "ATG", "AI": "AIA", "AL": "ALB",
    "AM": "ARM", "AO": "AGO", "AQ": "ATA", "AR": "ARG", "AS": "ASM", "AT": "AUT",
    "AU": "AUS", "AW": "ABW", "AX": "ALA", "AZ": "AZE", "BA": "BIH", "BB": "BRB",
    "BD": "BGD", "BE": "BEL", "BF": "BFA", "BG": "BGR", "BH": "BHR", "BI": "BDI",
    "BJ": "BEN", "BL": "BLM", "BM": "BMU", "BN": "BRN", "BO": "BOL", "BQ": "BES",
    "BR": "BRA", "BS": "BHS", "BT": "BTN", "BV": "BVT", "BW": "BWA", "BY": "BLR",
    "BZ": "BLZ", "CA": "CAN", "CC": "CCK", "CD": "COD", "CF": "CAF", "CG": "COG",
    "CH": "CHE", "CI": "CIV", "CK": "COK", "CL": "CHL", "CM": "CMR", "CN": "CHN",
    "CO": "COL", "CR": "CRI", "CU": "CUB", "CV": "CPV", "CW": "CUW", "CX": "CXR",
    "CY": "CYP", "CZ": "CZE", "DE": "DEU", "DJ": "DJI", "DK": "DNK", "DM": "DMA",
    "DO": "DOM", "DZ": "DZA", "EC": "ECU", "EE": "EST", "EG": "EGY", "EH": "ESH",
    "ER": "ERI", "ES": "ESP", "ET": "ETH", "FI": "FIN", "FJ": "FJI", "FK": "FLK",
    "FM": "FSM", "FO": "FRO", "FR": "FRA", "GA": "GAB", "GB": "GBR", "GD": "GRD",
    "GE": "GEO", "GF": "GUF", "GG": "GGY", "GH": "GHA", "GI": "GIB", "GL": "GRL",
    "GM": "GMB", "GN": "GIN", "GP": "GLP", "GQ": "GNQ", "GR": "GRC", "GS": "SGS",
    "GT": "GTM", "GU": "GUM", "GW": "GNB", "GY": "GUY", "HK": "HKG", "HM": "HMD",
    "HN": "HND", "HR": "HRV", "HT": "HTI", "HU": "HUN", "ID": "IDN", "IE": "IRL",
    "IL": "ISR", "IM": "IMN", "IN": "IND", "IO": "IOT", "IQ": "IRQ", "IR": "IRN",
    "IS": "ISL", "IT": "ITA", "JE": "JEY", "JM": "JAM", "JO": "JOR", "JP": "JPN",
    "KE": "KEN", "KG": "KGZ", "KH": "KHM", "KI": "KIR", "KM": "COM", "KN": "KNA",
    "KP": "PRK", "KR": "KOR", "KW": "KWT", "KY": "CYM", "KZ": "KAZ", "LA": "LAO",
    "LB": "LBN", "LC": "LCA", "LI": "LIE", "LK": "LKA", "LR": "LBR", "LS": "LSO",
    "LT": "LTU", "LU": "LUX", "LV": "LVA", "LY": "LBY", "MA": "MAR", "MC": "MCO",
    "MD": "MDA", "ME": "MNE", "MF": "MAF", "MG": "MDG", "MH": "MHL", "MK": "MKD",
    "ML": "MLI", "MM": "MMR", "MN": "MNG", "MO": "MAC", "MP": "MNP", "MQ": "MTQ",
    "MR": "MRT", "MS": "MSR", "MT": "MLT", "MU": "MUS", "MV": "MDV", "MW": "MWI",
    "MX": "MEX", "MY": "MYS", "MZ": "MOZ", "NA": "NAM", "NC": "NCL", "NE": "NER",
    "NF": "NFK", "NG": "NGA", "NI": "NIC", "NL": "NLD", "NO": "NOR", "NP": "NPL",
    "NR": "NRU", "NU": "NIU", "NZ": "NZL", "OM": "OMN", "PA": "PAN", "PE": "PER",
    "PF": "PYF", "PG": "PNG", "PH": "PHL", "PK": "PAK", "PL": "POL", "PM": "SPM",
    "PN": "PCN", "PR": "PRI", "PS": "PSE", "PT": "PRT", "PW": "PLW", "PY": "PRY",
    "QA": "QAT", "RE": "REU", "RO": "ROU", "RS": "SRB", "RU": "RUS", "RW": "RWA",
    "SA": "SAU", "SB": "SLB", "SC": "SYC", "SD": "SDN", "SE": "SWE", "SG": "SGP",
    "SH": "SHN", "SI": "SVN", "SJ": "SJM", "SK": "SVK", "SL": "SLE", "SM": "SMR",
    "SN": "SEN", "SO": "SOM", "SR": "SUR", "SS": "SSD", "ST": "STP", "SV": "SLV",
    "SX": "SXM", "SY": "SYR", "SZ": "SWZ", "TC": "TCA", "TD": "TCD", "TF": "ATF",
    "TG": "TGO", "TH": "THA", "TJ": "TJK", "TK": "TKL", "TL": "TLS", "TM": "TKM",
    "TN": "TUN", "TO": "TON", "TR": "TUR", "TT": "TTO", "TV": "TUV", "TW": "TWN",
    "TZ": "TZA", "UA": "UKR", "UG": "UGA", "UM": "UMI", "US": "USA", "UY": "URY",
    "UZ": "UZB", "VA": "VAT", "VC": "VCT", "VE": "VEN", "VG": "VGB", "VI": "VIR",
    "VN": "VNM", "VU": "VUT", "WF": "WLF", "WS": "WSM", "YE": "YEM", "YT": "MYT",
    "ZA": "ZAF", "ZM": "ZMB", "ZW": "ZWE"
}


def convert_country_code(country_code: str) -> str:
    """Convert 2-letter country code to 3-letter code.
    
    Args:
        country_code: 2-letter ISO country code
        
    Returns:
        3-letter ISO country code, defaults to 'USA' if conversion fails
    """
    if not country_code:
        return "USA"
    
    # Use static mapping to avoid blocking I/O calls
    return COUNTRY_CODE_MAPPING.get(country_code.upper(), "USA")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Samsung Find component."""
    hass.data[DOMAIN] = {}
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Samsung Find from a config entry.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry
        
    Returns:
        True if setup was successful
    """
    hass.data[DOMAIN][entry.entry_id] = {}

    # Load OAuth2 PKCE credentials from config
    access_token = entry.data.get(CONF_ACCESS_TOKEN)
    client_id = entry.data.get(CONF_CLIENT_ID)
    refresh_token = entry.data.get(CONF_REFRESH_TOKEN)
    user_id = entry.data.get(CONF_USER_ID)
    userauth_token = entry.data.get(CONF_USERAUTH_TOKEN)

    # Get country from HA config, fallback to US
    country_code = hass.config.country or "US"
    _LOGGER.debug("Using country code: %s", country_code)

    # Convert to 3-letter code using our conversion function
    country_code_3 = convert_country_code(country_code)
    _LOGGER.debug("Converted to 3-letter country code: %s", country_code_3)

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
            CONF_USERAUTH_TOKEN: userauth_token,
        }
    )

    await renew_tokens(hass, session, entry.entry_id)

    # Load all Samsung-Find devices from the users account
    devices = await get_devices(hass, session, entry.entry_id)
    _LOGGER.info("Found %d devices", len(devices))

    # Filter out mobile devices if option is enabled
    if entry.options.get(CONF_IGNORE_MOBILE_DEVICES, CONF_IGNORE_MOBILE_DEVICES_DEFAULT):
        original_count = len(devices)
        devices = [
            device for device in devices
            if device['data'].get('deviceTypeCode') not in MOBILE_DEVICE_TYPES
        ]
        if (filtered_count := original_count - len(devices)) > 0:
            _LOGGER.info(
                "Filtered out %d mobile device(s). %d devices remaining",
                filtered_count,
                len(devices)
            )

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
        _LOGGER.error("Unload failed: %s", unload_success)
    return unload_success


class SamsungFindCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Samsung Find data."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        devices: list[dict[str, Any]],
        update_interval: int,
    ) -> None:
        """Initialize the coordinator.
        
        Args:
            hass: Home Assistant instance
            session: aiohttp client session
            devices: List of device data
            update_interval: Update interval in seconds
        """
        self.session = session
        self.devices = devices
        self.hass = hass
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Samsung Find.
        
        Returns:
            Dictionary of device locations keyed by device ID
            
        Raises:
            UpdateFailed: When data update fails
        """
        try:
            device_locations = {}
            for device in self.devices:
                dev_data = device["data"]
                device_type = dev_data.get("deviceTypeCode", "UNKNOWN")
                device_id = dev_data["dvceID"]
                
                if device_type == "TAG":
                    _LOGGER.debug("Getting location for TAG device: %s", device_id)
                    tag_data = await get_tag_location(
                        self.hass, self.session, dev_data, self.config_entry.entry_id
                    )
                    if tag_data:
                        device_locations[device_id] = tag_data
                elif device_type in ["PHONE", "TABLET", "WATCH", "BUDS"]:
                    _LOGGER.debug("Getting location for %s device: %s", device_type, device_id)
                    device_data = await get_device_location(
                        self.hass, self.session, dev_data, self.config_entry.entry_id
                    )
                    if device_data:
                        device_locations[device_id] = device_data
                else:
                    _LOGGER.info(
                        "Unsupported device type. Skipping location for device %s with type: %s",
                        device_id,
                        device_type,
                    )

            _LOGGER.info("Fetched location for %d devices", len(device_locations))
            return device_locations

        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Error fetching data: {err}") from err
