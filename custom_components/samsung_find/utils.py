import logging
import pytz
import aiohttp
import html
from datetime import datetime, timedelta
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry

from .const import (
    DOMAIN,
    BATTERY_LEVELS,
    CONF_REFRESH_TOKEN,
    CONF_OAUTH2_TOKEN_URL,
    CONF_CLIENT_ID,
    CONF_ACCESS_TOKEN,
    CONF_LAST_TOKEN_REFRESH,
    CONF_TOKEN_EXPIRES_IN,
    CONF_HEADERS,
)

_LOGGER = logging.getLogger(__name__)

SAMSUNG_FIND_API_URL_BASE = "https://api.samsungfind.com"
OAUTH2_REFRESH_TOKEN_URL_FALLBACK = "eu-auth2.samsungosp.com"
OAUTH2_TOKEN_URL_SUFFIX = "/auth/oauth2/v2/token"


def _raise_auth_failed() -> None:
    raise ConfigEntryAuthFailed("Failed to authenticate with Samsung Find API")


async def renew_tokens(
    hass: HomeAssistant, session: aiohttp.ClientSession, entry_id: str
) -> str:
    """Renew tokens using refresh token."""
    try:
        # Get config entry
        entry = hass.config_entries.async_get_entry(entry_id)
        if not entry:
            raise ConfigEntryAuthFailed("Config entry not found")

        # Get stored tokens from config entry data
        refresh_token = entry.data.get(CONF_REFRESH_TOKEN)
        client_id = entry.data.get(CONF_CLIENT_ID)
        auth_server_url = entry.data.get(
            CONF_OAUTH2_TOKEN_URL, OAUTH2_REFRESH_TOKEN_URL_FALLBACK
        )

        _LOGGER.warning(
            "Access Token requested, using refresh token: %s***",
            refresh_token[:4] if refresh_token else "None",
        )

        data = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        }

        async with (
            aiohttp.ClientSession() as auth_session,
            auth_session.post(
                f"https://{auth_server_url}/{OAUTH2_TOKEN_URL_SUFFIX}", data=data
            ) as resp,
        ):
            if resp.status != 200:
                _LOGGER.error(
                    "Token refresh failed with status %s: %s",
                    resp.status,
                    await resp.text(),
                )
                raise ConfigEntryAuthFailed("Failed to refresh access token")

            tokens = await resp.json()

            # Store new refresh tokens in config entry
            new_data = {
                **entry.data,
                CONF_REFRESH_TOKEN: tokens.get("refresh_token", refresh_token),
            }

            # Update config entry with new tokens
            hass.config_entries.async_update_entry(entry, data=new_data)

            # Store runtime data in hass.data
            hass.data[DOMAIN][entry_id].update(
                {
                    CONF_ACCESS_TOKEN: tokens["access_token"],
                    CONF_LAST_TOKEN_REFRESH: datetime.now().isoformat(),
                    CONF_TOKEN_EXPIRES_IN: tokens.get("expires_in", 86400),
                }
            )

            return tokens["access_token"]

    except Exception as ex:
        _LOGGER.error("Failed to refresh tokens: %s", ex)
        raise ConfigEntryAuthFailed("Failed to refresh access token") from ex


async def get_devices(
    hass: HomeAssistant,
    session: aiohttp.ClientSession,
    entry_id: str,
) -> list:
    """Get devices from Samsung Find API.

    Args:
        hass (HomeAssistant): Home Assistant instance
        session (aiohttp.ClientSession): Session with valid OAuth2 token
        entry_id (str): Config entry ID

    Returns:
        list: List of formatted device dictionaries
    """
    try:
        if not await is_token_valid(hass, entry_id):
            _LOGGER.error("Token expired, refreshing before device request")
            await renew_tokens(hass, session, entry_id)

        access_token = hass.data[DOMAIN][entry_id][CONF_ACCESS_TOKEN]
        headers = hass.data[DOMAIN][entry_id][CONF_HEADERS]

        headers.update(
            {"x-sec-sa-authtoken": access_token, "x-sec-tab-name": "DEVICES"}
        )

        async with session.get(
            f"{SAMSUNG_FIND_API_URL_BASE}/devices", headers=headers
        ) as response:
            if response.status != 200:
                _LOGGER.error(
                    "Failed to retrieve devices [%s]: %s",
                    response.status,
                    await response.text(),
                )
                if response.status in [401, 403]:
                    _LOGGER.error(
                        "Authentication failed while fetching devices -> Triggering reauth"
                    )

                    _raise_auth_failed()
                return []

            data = await response.json()
            devices = []

            for item in data.get("items", []):
                device_type = item.get("type")
                device_id = item.get("deviceId")

                if device_type == "TAG":
                    # For TAG type, get info from metadata
                    metadata = item.get("metadata", {})
                    vendor = metadata.get("vendor", {})
                    firmware_section = metadata.get("firmware", {})
                    firmware_version = firmware_section.get("version", "")
                    mn_id = vendor.get("mnId", "")
                    setup_id = vendor.get("setupId", "")
                    model_id = vendor.get("modelName", "")
                    device_name = model_id

                    # Tags don't have displayName, display name is saved in label property in device detail. Another API call is needed.
                    device_detail = await get_tag_detail(
                        hass, session, entry_id, device_id
                    )
                    if device_detail:
                        device_name = device_detail.get("label", device_name)

                else:
                    model_info = item.get("modelInfo", {})
                    model_id = model_info.get("modelName", "")
                    brand_name = model_info.get("brandName", "")

                    # Use unescaped displayName. If not available, fallback to brand name.
                    device_name = html.unescape(
                        html.unescape(model_info.get("displayName", brand_name))
                    )

                identifier = (DOMAIN, device_id)
                ha_dev = device_registry.async_get(hass).async_get_device({identifier})

                if ha_dev and ha_dev.disabled:
                    _LOGGER.error(
                        f"Ignoring disabled device: '{device_name}' (disabled by {ha_dev.disabled_by})"
                    )
                    continue

                ha_dev_info = DeviceInfo(
                    identifiers={identifier},
                    manufacturer="Samsung",
                    name=device_name,
                    model=model_id,
                    configuration_url="https://smartthingsfind.samsung.com/",
                )

                # Format device data to maintain compatibility
                formatted_device = {
                    "data": {
                        "dvceID": device_id,
                        "modelName": device_name,
                        "modelID": model_id,
                        "deviceTypeCode": device_type,
                        "metadata": {
                            "mnId": mn_id if device_type == "TAG" else "",
                            "setupId": setup_id if device_type == "TAG" else "",
                            "firmwareVersion": firmware_version
                            if device_type == "TAG"
                            else "",
                        },
                    },
                    "ha_dev_info": ha_dev_info,
                }

                _LOGGER.info("Adding device: %s (%s)", device_name, model_id)
                _LOGGER.debug("Formated devices: %s", formatted_device)
                devices.append(formatted_device)

            _LOGGER.debug("Returning devices: %s", devices)
            return devices

    except ConfigEntryAuthFailed:
        raise
    except Exception as e:
        _LOGGER.exception(f"Error fetching devices: {str(e)}", exc_info=True)
        return []


async def get_tag_detail(
    hass: HomeAssistant, session: aiohttp.ClientSession, entry_id: str, device_id: str
) -> list:
    """Get device detail from Samsung Find API.

    Args:
        hass (HomeAssistant): Home Assistant instance
        session (aiohttp.ClientSession): Session with valid OAuth2 token
        entry_id (str): Config entry ID
        device_id (str): Device ID

    Returns:
        list: List of formatted device dictionaries
    """
    try:
        if not await is_token_valid(hass, entry_id):
            _LOGGER.error("Token expired, refreshing before device request")
            await renew_tokens(hass, session, entry_id)

        access_token = hass.data[DOMAIN][entry_id][CONF_ACCESS_TOKEN]
        headers = hass.data[DOMAIN][entry_id][CONF_HEADERS]

        headers.update(
            {"x-sec-sa-authtoken": access_token, "x-sec-tab-name": "DEVICES"}
        )

        _LOGGER.debug("Getting TAG detail for device: %s", device_id)

        async with session.get(
            f"{SAMSUNG_FIND_API_URL_BASE}/tag/devices/{device_id}", headers=headers
        ) as response:
            if response.status != 200:
                _LOGGER.error(
                    "Failed to retrieve device detail [%s]: %s",
                    response.status,
                    await response.text(),
                )

                if response.status in [401, 403]:
                    _raise_auth_failed()
                return None

            data = await response.json()
            if not data or "item" not in data:
                _LOGGER.error("Invalid response format: %s", data)
                return None

            device_detail = data["item"]
            _LOGGER.debug("Received device detail: %s", device_detail)
            return device_detail

    except ConfigEntryAuthFailed:
        raise
    except Exception as e:
        _LOGGER.error(f"Error fetching device detail: {str(e)}", exc_info=True)
        return None


async def get_tag_location(
    hass: HomeAssistant, session: aiohttp.ClientSession, dev_data: dict, entry_id: str
) -> dict:
    """Get tag location from Samsung Find API.

    Args:
        hass: Home Assistant instance
        session: Session with valid OAuth2 token
        dev_data: Device data dictionary
        entry_id: Config entry ID

    Returns:
        dict: Location data in the original format
    """
    try:
        if not await is_token_valid(hass, entry_id):
            _LOGGER.error("Token expired, refreshing before device location request")
            await renew_tokens(hass, session, entry_id)

        dev_id = dev_data["dvceID"]
        dev_name = dev_data["modelName"]
        user_id = hass.data[DOMAIN][entry_id]["user_id"]
        access_token = hass.data[DOMAIN][entry_id][CONF_ACCESS_TOKEN]

        headers = hass.data[DOMAIN][entry_id][CONF_HEADERS]
        headers.update(
            {"x-sec-sa-authtoken": access_token, "x-sec-tab-name": "DEVICES"}
        )

        # Build URL with query parameters
        params = {
            "deviceId": dev_id,
            "userId": user_id,
            "requestUserName": user_id,
        }

        async with session.get(
            f"{SAMSUNG_FIND_API_URL_BASE}/tag/geolocations",
            headers=headers,
            params=params,
        ) as response:
            if response.status != 200:
                _LOGGER.error(
                    "[%s]Failed to fetch location [%s]: %s",
                    dev_name,
                    response.status,
                    await response.text(),
                )
                if response.status in [401, 403]:
                    raise ConfigEntryAuthFailed("Authentication failed")
                return None

            data = await response.json()

            # Process response into original format
            res = {
                "dev_name": dev_name,
                "dev_id": dev_id,
                "update_success": True,
                "location_found": False,
                "used_op": None,
                "used_loc": None,
                "nearby_loc": None,
                "ops": [],
            }

            # Extract location from first item's geolocations
            if not data.get("items"):
                return res

            item = data["items"][0]
            if not item.get("geolocations"):
                return res

            # Get most recent location
            location = item["geolocations"][0]

            # Convert to original format
            used_loc = {
                "latitude": float(location["latitude"]),
                "longitude": float(location["longitude"]),
                "gps_accuracy": float(location["accuracy"]),
                "gps_date": datetime.fromtimestamp(
                    location["lastUpdateTime"] / 1000, pytz.UTC
                )
            }

            res.update(
                {
                    "location_found": True,
                    "used_loc": used_loc,
                    "geolocation": location,
                    "geolocations": item["geolocations"],
                    "nearby_loc": location.get("nearby", "false"),
                }
            )

            _LOGGER.debug("[%s] Location data: %s", dev_name, res)
            return res

    except ConfigEntryAuthFailed:
        raise
    except Exception as e:
        _LOGGER.error(f"[{dev_name}] Error getting location: {str(e)}", exc_info=True)
        return None


async def get_device_location(
    hass: HomeAssistant, session: aiohttp.ClientSession, dev_data: dict, entry_id: str
) -> dict:
    """Get device location from Samsung Find API.

    Args:
        hass: Home Assistant instance
        session: Session with valid OAuth2 token
        dev_data: Device data dictionary
        entry_id: Config entry ID

    Returns:
        dict: Location data in the original format
    """
    try:
        if not await is_token_valid(hass, entry_id):
            _LOGGER.debug("Token expired, refreshing before device location request")
            await renew_tokens(hass, session, entry_id)

        device_id = dev_data["dvceID"]
        dev_name = dev_data["modelName"]
        access_token = hass.data[DOMAIN][entry_id][CONF_ACCESS_TOKEN]
        headers = hass.data[DOMAIN][entry_id][CONF_HEADERS]

        headers.update(
            {"x-sec-sa-authtoken": access_token, "x-sec-tab-name": "DEVICES"}
        )

        async with session.get(
            f"{SAMSUNG_FIND_API_URL_BASE}/find/devices/{device_id}",
            headers=headers,
        ) as response:
            if response.status != 200:
                _LOGGER.error(
                    "[%s] Failed to fetch location (%s): %s",
                    dev_name,
                    response.status,
                    await response.text(),
                )
                if response.status in [401, 403]:
                    raise ConfigEntryAuthFailed("Authentication failed")
                return None

            data = await response.json()

            # Process response into original format
            res = {
                "dev_name": dev_name,
                "dev_id": device_id,
                "update_success": True,
                "location_found": False,
                "used_op": None,
                "used_loc": None,
                "ops": [],
            }

            # Check if we have item and operations
            if not data.get("item") or not data["item"].get("operation"):
                return res

            # Find operation with type LOCATION
            location_op = None
            for op in data["item"]["operation"]:
                if op.get("oprnType") == "LOCATION":
                    location_op = op
                    break

            if not location_op:
                return res

            # Convert to original format
            used_loc = {
                "latitude": float(location_op["latitude"]),
                "longitude": float(location_op["longitude"]),
                "gps_accuracy": calc_gps_accuracy(
                    location_op.get("horizontalUncertainty", 0),
                    location_op.get("verticalUncertainty", 0),
                ),
                "gps_date": datetime.fromtimestamp(
                    int(
                        datetime.strptime(
                            location_op["oprnDoneDate"], "%Y%m%d%H%M%S"
                        ).timestamp()
                    ),
                    pytz.UTC,
                ),
            }

            # Create operation in original format
            operation = {
                "oprnType": "LOCATION",
                "battery": None,  # Battery info might be in CHECK_CONNECTION operation
                "extra": {"gpsUtcDt": used_loc["gps_date"].strftime("%Y%m%d%H%M%S")},
            }

            # Try to get battery info from CHECK_CONNECTION operation
            for op in data["item"]["operation"]:
                if op.get("oprnType") == "CHECK_CONNECTION" and "battery" in op:
                    operation["battery"] = op["battery"]
                    break

            res.update(
                {
                    "location_found": True,
                    "used_loc": used_loc,
                    "used_op": operation,
                    "ops": [operation],
                }
            )

            _LOGGER.debug("[%s] Location data: %s", dev_name, res)
            return res

    except ConfigEntryAuthFailed:
        raise
    except Exception as e:
        _LOGGER.error(f"[{dev_name}] Error getting location: {str(e)}", exc_info=True)
        return None


def calc_gps_accuracy(hu: float, vu: float) -> float:
    """Calculate the GPS accuracy using the Pythagorean theorem.
    Returns the combined GPS accuracy based on the horizontal
    and vertical uncertainties provided by the API

    Args:
        hu (float): Horizontal uncertainty.
        vu (float): Vertical uncertainty.

    Returns:
        float: Calculated GPS accuracy.
    """
    try:
        return round((float(hu) ** 2 + float(vu) ** 2) ** 0.5, 1)
    except ValueError:
        return None


def get_sub_location(ops: list, subDeviceName: str) -> tuple:
    """Extracts sub-location data for devices that contain multiple sub-locations (e.g., left and right earbuds).

    Args:
        ops (list): List of operations from the API.
        subDeviceName (str): Name of the sub-device.

    Returns:
        tuple: The operation and sub-location data.
    """
    if not ops or not subDeviceName or len(ops) < 1:
        return {}, {}
    for op in ops:
        if subDeviceName in op.get("encLocation", {}):
            loc = op["encLocation"][subDeviceName]
            sub_loc = {
                "latitude": float(loc["latitude"]),
                "longitude": float(loc["longitude"]),
                "gps_accuracy": calc_gps_accuracy(
                    loc.get("horizontalUncertainty"), loc.get("verticalUncertainty")
                ),
                "gps_date": parse_stf_date(loc["gpsUtcDt"]),
            }
            return op, sub_loc
    return {}, {}


def parse_stf_date(datestr: str) -> datetime:
    """Parses a date string in the format "%Y%m%d%H%M%S" to a datetime object.

    Args:
        datestr (str): The date string in the format "%Y%m%d%H%M%S".

    Returns:
        datetime: A datetime object representing the input date string.
    """
    return datetime.strptime(datestr, "%Y%m%d%H%M%S").replace(tzinfo=pytz.UTC)


def get_battery_level(dev_name: str, ops: list) -> int | None:
    """Try to extract the device battery level from the received operation.

    Args:
        dev_name (str): The name of the device.
        ops (list): List of operations from the API.

    Returns:
        int | None: The battery level (0-100) if found, None otherwise.
    """
    if not ops:
        return None

    for op in ops:
        if op["oprnType"] == "LOCATION" and "battery" in op:
            batt_raw = op["battery"]

            # Handle None case
            if batt_raw is None:
                return None

            # Try predefined levels first
            if batt := BATTERY_LEVELS.get(batt_raw):
                return batt

            # Try converting to integer if it's a string or number
            try:
                if isinstance(batt_raw, (str, int, float)):
                    return int(float(batt_raw))
                return None
            except (ValueError, TypeError):
                _LOGGER.warning(
                    "[%s]: Invalid battery level received: %r", dev_name, batt_raw
                )
                return None
    return None


async def is_token_valid(hass: HomeAssistant, entry_id: str) -> bool:
    """Check if current token is still valid."""
    access_token = hass.data[DOMAIN][entry_id].get(CONF_ACCESS_TOKEN)
    last_refresh = hass.data[DOMAIN][entry_id].get("last_token_refresh")
    expires_in = hass.data[DOMAIN][entry_id].get("token_expires_in", 86400)

    _LOGGER.debug(
        "Checking token validity: %s****, last refresh:%s",
        access_token[:4],
        last_refresh,
    )

    if not last_refresh:
        return False

    last_refresh_time = datetime.fromisoformat(last_refresh)
    expiration_time = last_refresh_time + timedelta(seconds=expires_in)

    _LOGGER.debug(
        "Access token %s****, expires in::%s",
        access_token[:4],
        expiration_time,
    )

    # Refresh if token expires in less than 5 minutes
    return datetime.now() < (expiration_time - timedelta(minutes=5))
