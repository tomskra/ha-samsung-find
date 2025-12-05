"""Samsung Find advanced authentication service.

This service implements the Samsung Android SDK style authentication flow
as reverse engineered and described in the uTag wiki:
    https://github.com/KieronQuinn/uTag/wiki/Authentication

It replaces the simple OAuth2 flow with an encrypted multi‑step process:
1. Get entry point (contains signInURI, RSA public key, chkDoNum)
2. Generate device info & PKCE values & state
3. Build encrypted svcParam payload (PBKDF2 + RSA + AES/CBC)
4. User visits signInURI with encrypted payload and logs in
5. Redirect URL contains encrypted parameters (state, code, auth_server_url, retValue)
6. Decrypt state -> intermediate key -> decrypt remaining params
7. Use auth code to obtain userauth_token (/auth/oauth2/authenticate)
8. Use userauth_token to obtain API tokens (Find API etc.)

Only the pieces necessary for Home Assistant config flow are exposed.
The class purposefully avoids direct Home Assistant imports to stay pure.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
import logging
import secrets
from typing import Any, Dict, Tuple

import aiohttp
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import PBKDF2
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad, unpad
from Crypto.Random import get_random_bytes

_LOGGER = logging.getLogger(__name__)


@dataclass
class DecryptedLogin:
    """Container for decrypted login redirect parameters."""

    auth_server_url: str | None
    code: str | None
    user_email: str | None
    raw: dict[str, Any]


class SamsungAuthService:
    """Encapsulates Samsung authentication logic for use in HA config flow."""

    ENTRY_POINT_URL = "https://account.samsung.com/accounts/ANDROIDSDK/getEntryPoint"
    REDIRECT_URI = (
        "ms-app://s-1-15-2-4027708247-2189610-1983755848-2937435718-1578786913-"
        "2158692839-1974417358"
    )

    FIND_CLIENT_ID = "27zmg0v1oo"  # Samsung Find API client id
    SMARTTHINGS_CLIENT_ID = "yfrtglt53o"  # Used for initial user auth token

    def __init__(self) -> None:
        self.entry_point_data: dict[str, Any] | None = None
        self.code_verifier: str | None = None
        self.code_challenge: str | None = None
        self.state_key: str | None = None
        self.user_auth_token: str | None = None
        self.auth_server_url: str | None = None
        self.device_info: dict[str, Any] | None = None

    # ----------------------------- helpers ---------------------------------
    def _prefix_base(self, base: str) -> str:
        if not base:
            return base
        if not base.startswith("https://"):
            return f"https://{base}"
        return base

    def _join(self, base: str, path: str) -> str:
        base = self._prefix_base(base).rstrip("/")
        return f"{base}{path}" if path.startswith("/") else f"{base}/{path}"

    # --------------------------- initial steps -----------------------------
    async def get_entry_point(self) -> dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            async with session.get(self.ENTRY_POINT_URL) as resp:
                if resp.status != 200:
                    raise RuntimeError(
                        f"Failed to get entry point: HTTP {resp.status}"
                    )
                self.entry_point_data = await resp.json()
                _LOGGER.debug("Entry point: %s", self.entry_point_data)
                return self.entry_point_data

    def generate_device_info(self) -> dict[str, str]:
        android_id = secrets.token_hex(16)
        
        # Pool of realistic Android devices to avoid all users appearing as same device
        devices = [
            ("Pixel 8 Pro", "Google Pixel 8 Pro", "35"),
            ("Pixel 8", "Google Pixel 8", "35"),
            ("Pixel 7 Pro", "Google Pixel 7 Pro", "34"),
            ("Pixel 7", "Google Pixel 7", "34"),
            ("Pixel 6 Pro", "Google Pixel 6 Pro", "33"),
            ("Pixel 6", "Google Pixel 6", "33"),
            ("Pixel 5", "Google Pixel 5", "33"),
            ("OnePlus 12", "OnePlus 12", "35"),
            ("OnePlus 11", "OnePlus 11", "34"),
            ("OnePlus 10 Pro", "OnePlus 10 Pro", "33"),
            ("OnePlus 10T", "OnePlus 10T", "33"),
            ("OnePlus 9 Pro", "OnePlus 9 Pro", "33"),
            ("2211133G", "Xiaomi 13", "34"),
            ("2210132G", "Xiaomi 12", "33"),
            ("MI 11", "Xiaomi Mi 11", "33"),
            ("23013RK75C", "Xiaomi Redmi Note 12 Pro", "33"),
            ("22101316G", "Xiaomi Redmi Note 11 Pro", "33"),
            ("M2101K6G", "Xiaomi Poco F3", "33"),
            ("motorola edge 40 pro", "Motorola Edge 40 Pro", "34"),
            ("motorola edge 30 pro", "Motorola Edge 30 Pro", "33"),
            ("moto g84 5G", "Motorola Moto G84 5G", "34"),
            ("ASUS_AI2302", "ASUS Zenfone 10", "34"),
            ("ASUS_AI2205", "ASUS Zenfone 9", "33"),
            ("2201116PG", "POCO F4", "33"),
        ]
        
        device_model, device_name, os_version = secrets.choice(devices)
        
        self.device_info = {
            "android_id": android_id,
            "device_info": "Google|com.android.chrome",
            "device_model": device_model,
            "device_name": device_name,
            "device_os_version": os_version,
            "physical_address": f"ANID:{android_id}",
        }
        return self.device_info

    # --------------------------- PKCE / state ------------------------------
    def _generate_pkce(self) -> Tuple[str, str]:
        random_bytes = secrets.token_bytes(32)
        verifier = base64.urlsafe_b64encode(random_bytes).decode("utf-8").rstrip("=")
        if len(verifier) < 43:
            verifier = verifier.ljust(43, "A")
        elif len(verifier) > 43:
            verifier = verifier[:43]
        hash_bytes = hashlib.sha256(verifier.encode("utf-8")).digest()
        challenge = (
            base64.b64encode(hash_bytes)
            .decode("utf-8")
            .replace("=", "")
            .replace("+", "-")
            .replace("/", "_")
        )
        self.code_verifier = verifier
        self.code_challenge = challenge
        return verifier, challenge

    def _generate_state(self) -> str:
        self.state_key = secrets.token_urlsafe(15)[:20].ljust(20, "0")
        return self.state_key

    def _create_svc_param(self, country_code: str) -> dict[str, Any]:
        if not self.device_info:
            raise RuntimeError("Device info not generated")
        _, challenge = self._generate_pkce()
        state = self._generate_state()
        di = self.device_info
        return {
            "clientId": self.SMARTTHINGS_CLIENT_ID,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "competitorDeviceYNFlag": "N",
            "countryCode": country_code,
            "deviceInfo": di["device_info"],
            "deviceModelID": di["device_model"],
            "deviceName": di["device_name"],
            "deviceOSVersion": di["device_os_version"],
            "devicePhysicalAddressText": di["physical_address"],
            "deviceType": "APP",
            "deviceUniqueID": di["android_id"],
            "redirect_uri": self.REDIRECT_URI,
            "replaceableClientConnectYN": "N",
            "replaceableClientId": "",
            "replaceableDevicePhysicalAddressText": "",
            "responseEncryptionType": "1",
            "responseEncryptionYNFlag": "Y",
            "scope": "",
            "state": state,
            "svcIptLgnID": "",
            "iosYNFlag": "Y",
        }

    # --------------------------- encryption --------------------------------
    def _encrypt_payload(self, svc_param: dict[str, Any]) -> str:
        if not self.entry_point_data:
            raise RuntimeError("Entry point not loaded")
        chk_do_num_str = self.entry_point_data["chkDoNum"]
        chk_do_num = int(chk_do_num_str)
        public_key_b64 = self.entry_point_data["pkiPublicKey"]

        hashed_data = base64.b64encode(
            hashlib.sha256(chk_do_num_str.encode("utf-8")).digest()
        )
        salt = get_random_bytes(16)
        pbkdf2_key = PBKDF2(
            hashed_data, salt, dkLen=16, count=chk_do_num, hmac_hash_module=SHA256
        )
        public_key = RSA.import_key(base64.b64decode(public_key_b64))
        rsa_cipher = PKCS1_v1_5.new(public_key)
        b64_key = base64.b64encode(pbkdf2_key)
        encrypted_key = rsa_cipher.encrypt(b64_key)
        svc_enc_ky = base64.b64encode(encrypted_key).decode()
        iv = get_random_bytes(16)
        aes_cipher = AES.new(pbkdf2_key, AES.MODE_CBC, iv)
        json_body = json.dumps(svc_param, separators=(",", ":"))
        encrypted_param = aes_cipher.encrypt(pad(json_body.encode(), AES.block_size))
        svc_enc_param = base64.b64encode(encrypted_param).decode()
        payload_json = {
            "chkDoNum": chk_do_num_str,
            "svcEncParam": svc_enc_param,
            "svcEncKY": svc_enc_ky,
            "svcEncIV": iv.hex(),
        }
        return base64.b64encode(
            json.dumps(payload_json, separators=(",", ":")).encode()
        ).decode()

    def build_auth_url(self, country_code: str, locale: str = "en") -> str:
        if not self.entry_point_data:
            raise RuntimeError("Must load entry point first")
        if not self.device_info:
            raise RuntimeError("Must generate device info first")
        svc_param = self._create_svc_param(country_code)
        encrypted_payload = self._encrypt_payload(svc_param)
        from urllib.parse import quote

        svc_param_encoded = quote(encrypted_payload, safe="")
        sign_in_uri = self.entry_point_data["signInURI"]
        url = f"{sign_in_uri}?locale={locale}&svcParam={svc_param_encoded}&mode=C"
        _LOGGER.debug("Generated auth URL length=%d", len(url))
        return url

    # --------------------------- decryption --------------------------------
    def _decrypt_aes(self, encrypted_data: str, key: str) -> str | None:
        try:
            try:
                encrypted_bytes = bytes.fromhex(encrypted_data)
            except ValueError:
                encrypted_bytes = base64.b64decode(encrypted_data)
            key_bytes = key.encode("utf-8")[:16]
            if len(key_bytes) < 16:
                _LOGGER.error("State key too short (%d)", len(key_bytes))
                return None
            cipher = AES.new(key_bytes, AES.MODE_ECB)
            decrypted = cipher.decrypt(encrypted_bytes)
            try:
                plaintext = unpad(decrypted, AES.block_size)
            except ValueError as e:
                _LOGGER.error("Padding error decrypting response: %s", e)
                return None
            return plaintext.decode("utf-8")
        except Exception as exc:  # pragma: no cover (defensive)
            _LOGGER.error("Failed to decrypt response: %s", exc)
            return None

    def decrypt_login_redirect(self, params: dict[str, str]) -> DecryptedLogin:
        if not self.state_key:
            raise RuntimeError("State key missing")
        if "state" not in params:
            raise RuntimeError("Redirect missing 'state' parameter")
        intermediate = self._decrypt_aes(params["state"], self.state_key)
        if not intermediate:
            raise RuntimeError("Failed to decrypt intermediate state value")
        decrypted: Dict[str, Any] = {"intermediate_state": intermediate}
        for key in ["auth_server_url", "code", "retValue"]:
            enc_val = params.get(key)
            if not enc_val:
                continue
            plain = self._decrypt_aes(enc_val, intermediate)
            if plain:
                decrypted[key] = plain
            else:
                _LOGGER.warning("Failed to decrypt %s", key)
        self.auth_server_url = decrypted.get("auth_server_url")
        return DecryptedLogin(
            auth_server_url=decrypted.get("auth_server_url"),
            code=decrypted.get("code"),
            user_email=decrypted.get("retValue"),
            raw=decrypted,
        )

    # ---------------------- token acquisition ------------------------------
    async def get_user_auth_token(
        self, auth_code: str, user_email: str
    ) -> dict[str, Any]:
        if not self.auth_server_url:
            raise RuntimeError("Auth server URL not set")
        if not self.code_verifier:
            raise RuntimeError("PKCE verifier missing")
        if not self.device_info:
            raise RuntimeError("Device info missing")
        url = self._join(self.auth_server_url, "/auth/oauth2/authenticate")
        form = {
            "grant_type": "authorization_code",
            "serviceType": "M",
            "code": auth_code,
            "client_id": self.SMARTTHINGS_CLIENT_ID,
            "code_verifier": self.code_verifier,
            "username": user_email,
            "physical_address_text": self.device_info["android_id"],
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=form) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(
                        f"Authenticate failed HTTP {resp.status}: {text[:200]}"
                    )
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    raise RuntimeError("Authenticate response not JSON")
        self.user_auth_token = data.get("userauth_token")
        if not self.user_auth_token:
            raise RuntimeError("userauth_token missing in authenticate response")
        return data

    async def get_api_token(
        self, client_id: str, scope: str, user_email: str
    ) -> dict[str, Any]:
        if not self.user_auth_token or not self.auth_server_url or not self.device_info:
            raise RuntimeError("Prerequisites missing for API token")
        # Create new PKCE for API token
        api_verifier = (
            base64.urlsafe_b64encode(secrets.token_bytes(32))
            .decode("utf-8")
            .rstrip("=")
        )
        api_challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(api_verifier.encode()).digest()
            )
            .decode("utf-8")
            .rstrip("=")
        )
        auth_params = {
            "response_type": "code",
            "serviceType": "M",
            "client_id": client_id,
            "code_challenge_method": "S256",
            "childAccountSupported": "Y",
            "userauth_token": self.user_auth_token,
            "code_challenge": api_challenge,
            "physical_address_text": self.device_info["android_id"],
            "scope": scope,
            "login_id": user_email,
        }
        async with aiohttp.ClientSession() as session:
            auth_url = self._join(self.auth_server_url, "/auth/oauth2/v2/authorize")
            async with session.get(auth_url, params=auth_params) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(
                        f"Authorize failed HTTP {resp.status}: {text[:200]}"
                    )
                try:
                    auth_result = json.loads(text)
                except json.JSONDecodeError:
                    raise RuntimeError("Authorize response not JSON")
            auth_code = auth_result.get("code")
            if not auth_code:
                raise RuntimeError("Missing code in authorize response")
            token_form = {
                "grant_type": "authorization_code",
                "code": auth_code,
                "client_id": client_id,
                "code_verifier": api_verifier,
                "physical_address_text": self.device_info["android_id"],
            }
            token_url = self._join(self.auth_server_url, "/auth/oauth2/token")
            async with session.post(token_url, data=token_form) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(
                        f"Token exchange failed HTTP {resp.status}: {text[:200]}"
                    )
                try:
                    tokens = json.loads(text)
                except json.JSONDecodeError:
                    raise RuntimeError("Token exchange response not JSON")
        return tokens
