"""Config flow for Samsung Find integration.

Handles OAuth2 authentication and options flow for Samsung Find.
"""

import base64
import hashlib
import logging
import secrets
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
)

_LOGGER = logging.getLogger(__name__)


class SamsungFindConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow handler for the Samsung Find integration.

    Manages the OAuth2 authentication process and configuration steps.
    """

    OAUTH2_AUTH_URL = "https://account.samsung.com/accounts/v1/FMM2/signInGate"
    OAUTH2_TOKEN_URL_SUFFIX = "/auth/oauth2/v2/token"
    REDIRECT_URI = "https://smartthingsfind.samsung.com/login.do"
    CLIENT_ID = "27zmg0v1oo"  # Client ID for Samsung Find

    async def async_step_user(self, user_input=None):
        """Start OAuth2 flow: generate code_verifier, code_challenge, show auth URL and input for code."""
        errors = {}

        # Generate code_verifier and auth_url only if not already stored
        if not hasattr(self, "code_verifier") or not hasattr(self, "auth_url"):
            # Generate PKCE code_verifier and code_challenge
            code_verifier = secrets.token_urlsafe(64)
            code_challenge = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(code_verifier.encode()).digest()
                )
                .rstrip(b"=")
                .decode("utf-8")
            )

            self.code_verifier = code_verifier
            self.code_challenge = code_challenge

            _LOGGER.debug("OAuthFlow: code_verifier: %s", code_verifier)
            _LOGGER.debug("OAuthFlow: code_challenge: %s", code_challenge)

            # Build authorization URL
            state = secrets.token_urlsafe(16)
            self.auth_url = (
                f"{self.OAUTH2_AUTH_URL}?response_type=code"
                f"&client_id={self.CLIENT_ID}"
                f"&redirect_uri={self.REDIRECT_URI}"
                f"&code_challenge={code_challenge}"
                f"&code_challenge_method=S256"
                f"&scope=offline.access"
                f"&state={state}"
            )
            _LOGGER.debug("OAuthFlow: Generated new code_verifier and auth_url")

        if user_input is not None:
            code = user_input.get("code")
            if not code:
                errors["base"] = "missing_code"
            auth_server_url = user_input.get("auth_server_url")
            if not auth_server_url:
                errors["base"] = "missing_auth_server_url"
            else:
                # Exchange code for tokens
                async with aiohttp.ClientSession() as session:
                    data = {
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": self.REDIRECT_URI,
                        "client_id": self.CLIENT_ID,
                        "code_verifier": self.code_verifier,
                    }

                    _LOGGER.debug(
                        "OAuthFlow: Exchanging code for tokens with data: %s", data
                    )

                    session.headers.update(
                        {"Content-Type": "application/x-www-form-urlencoded"}
                    )

                    async with session.post(
                        f"https://{auth_server_url}{self.OAUTH2_TOKEN_URL_SUFFIX}",
                        data=data,
                    ) as resp:
                        if resp.status != 200:
                            _LOGGER.error(
                                "Token exchange failed with status %s", resp.status
                            )
                            errors["base"] = "token_error"
                        else:
                            tokens = await resp.json()
                            access_token = tokens.get("access_token")
                            refresh_token = tokens.get("refresh_token")

                            _LOGGER.error("refresh token: %s", refresh_token)

                            user_id = tokens.get("userId")
                            if not access_token or not refresh_token:
                                errors["base"] = "token_error"
                            else:
                                # Save tokens
                                return self.async_create_entry(
                                    title="Samsung Find",
                                    data={
                                        CONF_ACCESS_TOKEN: access_token,
                                        CONF_CLIENT_ID: self.CLIENT_ID,
                                        CONF_REFRESH_TOKEN: refresh_token,
                                        CONF_USER_ID: user_id,
                                        CONF_OAUTH2_TOKEN_URL: auth_server_url,
                                    },
                                )
        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=vol.Schema(
                {vol.Required("code"): str, vol.Required("auth_server_url"): str}
            ),
            description_placeholders={"auth_url": self.auth_url},
        )

    async def async_step_code(self, user_input=None):
        """Receive authorization code, exchange for refresh and access tokens."""
        errors = {}
        _LOGGER.error("ASYNC STEP CODE")
        if user_input is not None:
            code = user_input.get("code")
            if not code:
                errors["base"] = "missing_code"
            else:
                # Exchange code for tokens
                async with aiohttp.ClientSession() as session:
                    data = {
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": self.REDIRECT_URI,
                        "client_id": self.CLIENT_ID,
                        "code_verifier": self.code_verifier,
                    }
                    async with session.post(self.OAUTH2_TOKEN_URL, data=data) as resp:
                        if resp.status != 200:
                            errors["base"] = "token_error"
                        else:
                            tokens = await resp.json()
                            access_token = tokens.get("access_token")
                            refresh_token = tokens.get("refresh_token")
                            user_id = tokens.get("userId")
                            if not access_token or not refresh_token:
                                errors["base"] = "token_error"
                            else:
                                # Save tokens
                                data = {
                                    CONF_ACCESS_TOKEN: access_token,
                                    CONF_CLIENT_ID: self.CLIENT_ID,
                                    CONF_REFRESH_TOKEN: refresh_token,
                                    CONF_USER_ID: user_id,
                                }
                                return self.async_create_entry(
                                    title="Samsung Find", data=data
                                )

        return self.async_show_form(
            step_id="code",
            errors=errors,
            data_schema=vol.Schema({vol.Required("code"): str}),
        )

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    reauth_entry: ConfigEntry | None = None

    async def async_step_reauth(self, user_input=None):
        self.reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
            )
        return await self.async_step_user()

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        return await self.async_step_reauth_confirm(self)

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
