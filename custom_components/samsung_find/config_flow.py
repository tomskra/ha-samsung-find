"""Config flow for Samsung Find integration.

Handles OAuth2 authentication and options flow for Samsung Find.
"""
from __future__ import annotations

import logging
import secrets
from urllib.parse import urlparse, parse_qs
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlowWithConfigEntry,
)
from homeassistant.core import callback

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_CLIENT_ID,
    CONF_REFRESH_TOKEN,
    CONF_UPDATE_INTERVAL,
    CONF_UPDATE_INTERVAL_DEFAULT,
    CONF_USER_ID,
    DOMAIN,
    CONF_OAUTH2_TOKEN_URL,
    CONF_USERAUTH_TOKEN,
)
from .auth_service import SamsungAuthService

_LOGGER = logging.getLogger(__name__)


class SamsungFindConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow using advanced encrypted Samsung Android SDK auth flow."""

    VERSION = 2
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self) -> None:
        self._auth = SamsungAuthService()
        self._auth_url: str | None = None
        self._country_code: str = "us"  # fallback; HA country not accessible here yet
        self._step: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """First step: prepare auth URL or process redirect URL."""
        errors: dict[str, str] = {}

        # Initial call -> build URL
        if user_input is None:
            try:
                await self._auth.get_entry_point()
                self._auth.generate_device_info()
                self._auth_url = self._auth.build_auth_url(self._country_code)
                self._step = "await_redirect"
            except Exception as exc:  # pragma: no cover
                _LOGGER.exception("Failed to build auth URL")
                errors["base"] = "auth_url_error"
            return self.async_show_form(
                step_id="user",
                errors=errors,
                data_schema=vol.Schema({vol.Required("redirect_url"): str}),
                description_placeholders={"auth_url": self._auth_url or ""},
            )

        # We have user input -> expect redirect_url from browser
        redirect_url = user_input.get("redirect_url")
        if not redirect_url:
            errors["base"] = "missing_redirect"
            return self.async_show_form(
                step_id="user",
                errors=errors,
                data_schema=vol.Schema({vol.Required("redirect_url"): str}),
                description_placeholders={"auth_url": self._auth_url or ""},
            )

        try:
            parsed = urlparse(redirect_url)
            params_qs = parse_qs(parsed.query)
            # Flatten expected params
            flat: dict[str, str] = {}
            for key in ["state", "code", "auth_server_url", "retValue"]:
                if key in params_qs:
                    flat[key] = params_qs[key][0]
            decrypted = self._auth.decrypt_login_redirect(flat)
            if not decrypted.code or not decrypted.auth_server_url:
                errors["base"] = "decrypt_failed"
                raise ValueError("Missing decrypted code or auth_server_url")

            user_email = decrypted.user_email or secrets.token_hex(4) + "@example.com"
            auth_res = await self._auth.get_user_auth_token(decrypted.code, user_email)
            userauth_token = auth_res.get("userauth_token")
            if not userauth_token:
                raise ValueError("userauth_token missing")
            # Request Samsung Find API offline.access token
            find_tokens = await self._auth.get_api_token(
                self._auth.FIND_CLIENT_ID, "offline.access", user_email
            )
            access_token = find_tokens.get("access_token")
            refresh_token = find_tokens.get("refresh_token")
            user_id = find_tokens.get("userId")
            if not access_token or not refresh_token:
                errors["base"] = "token_error"
                raise ValueError("Missing required tokens")

            # auth_server_url may include https:// prefix; utils expect host only
            auth_server_url = decrypted.auth_server_url or ""
            auth_server_url = auth_server_url.replace("https://", "").rstrip("/")

            return self.async_create_entry(
                title="Samsung Find",
                data={
                    CONF_ACCESS_TOKEN: access_token,
                    CONF_CLIENT_ID: self._auth.FIND_CLIENT_ID,
                    CONF_REFRESH_TOKEN: refresh_token,
                    CONF_USER_ID: user_id,
                    CONF_OAUTH2_TOKEN_URL: auth_server_url,
                    CONF_USERAUTH_TOKEN: userauth_token,
                },
            )
        except Exception as exc:  # pragma: no cover
            if not errors:
                errors["base"] = "unknown"
            _LOGGER.exception("Authentication process failed: %s", exc)
            return self.async_show_form(
                step_id="user",
                errors=errors,
                data_schema=vol.Schema({vol.Required("redirect_url"): str}),
                description_placeholders={"auth_url": self._auth_url or ""},
            )

    reauth_entry: ConfigEntry | None = None

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle reauth flow.
        
        Args:
            user_input: User input data
            
        Returns:
            Config flow result
        """
        self.reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle reauth confirmation.
        
        Args:
            user_input: User input data
            
        Returns:
            Config flow result
        """
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
            )
        return await self.async_step_user()

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle reconfigure flow.
        
        Args:
            user_input: User input data
            
        Returns:
            Config flow result
        """
        return await self.async_step_reauth_confirm()

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return SamsungFindOptionsFlowHandler(config_entry)


class SamsungFindOptionsFlowHandler(OptionsFlowWithConfigEntry):
    """Handle an options flow."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle options flow."""

        if user_input is not None:
            res = self.async_create_entry(title="", data=user_input)

            # Reload the integration entry to make sure the newly set options take effect
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
            return res

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_UPDATE_INTERVAL,
                    default=self.options.get(
                        CONF_UPDATE_INTERVAL, CONF_UPDATE_INTERVAL_DEFAULT
                    ),
                ): vol.All(vol.Coerce(int), vol.Clamp(min=30)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=data_schema)
