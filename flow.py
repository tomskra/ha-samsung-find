import aiohttp
import asyncio
import hashlib
import base64
import secrets
import logging

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)

class SmartThingsAuth:
    OAUTH2_AUTH_URL = "https://account.samsung.com/accounts/v1/FMM2/signInGate"
    OAUTH2_TOKEN_URL = "https://account.samsung.com/accounts/v1/FMM2/token"
    OAUTH2_TOKEN_URL2 = "https://eu-auth2.samsungosp.com/auth/oauth2/v2/token"
    OAUTH2_REFRESH_TOKEN_URL = "https://eu-auth2.samsungosp.com/auth/oauth2/token"
    REDIRECT_URI = "https://smartthingsfind.samsung.com/login.do"
    # CLIENT_ID = "ntly6zvfpn"
    CLIENT_ID = "27zmg0v1oo" # client ID for Find

    def __init__(self):
        self.code_verifier = None
        self.code_challenge = None
        
    def generate_auth_url(self):
        """Generate authentication URL with PKCE"""
        # Generate PKCE code_verifier and code_challenge
        self.code_verifier = secrets.token_urlsafe(64)
        self.code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(self.code_verifier.encode()).digest())
            .rstrip(b"=")
            .decode("utf-8")
        )

        state = secrets.token_urlsafe(16)
        auth_url = (
            f"{self.OAUTH2_AUTH_URL}?response_type=code"
            f"&client_id={self.CLIENT_ID}"
            f"&redirect_uri={self.REDIRECT_URI}"
            f"&code_challenge={self.code_challenge}"
            f"&code_challenge_method=S256"
            f"&scope=offline.access"
            f"&state={state}"
        )
        return auth_url

    async def exchange_code(self, code):
        """Exchange authorization code for tokens"""
        async with aiohttp.ClientSession() as session:
            # data = {
            #     "grant_type": "authorization_code",
            #     "code": code,
            #     "redirect_uri": self.REDIRECT_URI,
            #     "client_id": "27zmg0v1oo",
            #     "code_verifier": self.code_verifier,
            # }
            
            data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.REDIRECT_URI,
                "client_id": self.CLIENT_ID,
                "code_verifier": self.code_verifier,
            }

            async with session.post(self.OAUTH2_TOKEN_URL2, data=data) as resp:
                if resp.status != 200:
                    _LOGGER.error("Token exchange failed with status %s", resp.status)
                    return None
                
                _LOGGER.warning("RES: %s", resp)
                tokens = await resp.json()
                _LOGGER.warning("tokens: %s", tokens)
                return {
                    "access_token": tokens.get("access_token"),
                    "refresh_token": tokens.get("refresh_token")
                }

    async def get_access_token(self):
        """Renew tokens using refresh token"""
        async with aiohttp.ClientSession() as session:

            refresh_token = "JzlMxpGY1ScLZI27WXGmGKoyM"  # Replace with your actual refresh token

            data = {
                "grant_type": "refresh_token",
                "client_id": self.CLIENT_ID,
                "refresh_token": refresh_token,
            }

            async with session.post(self.OAUTH2_REFRESH_TOKEN_URL, data=data) as resp:
                if resp.status != 200:
                    _LOGGER.error("Token exchange failed with status %s", resp.status)
                    return None
                
                _LOGGER.warning("RES: %s", resp)
                tokens = await resp.json()
                _LOGGER.warning("tokens: %s", tokens)
                return {
                    "access_token": tokens.get("access_token"),
                    "refresh_token": tokens.get("refresh_token")
                }

async def main():
    auth = SmartThingsAuth()
    


    # acess_token = await auth.get_access_token()    
    # print(f"\nAccess Token: {acess_token}\n")
    


    # Step 1: Get auth URL
    auth_url = auth.generate_auth_url()
    print(f"\nOpen this URL in your browser:\n{auth_url}\n")
    
    # Step 2: Get code from user
    code = input("Enter the code from the redirect URL: ")
    
    # Step 3: Exchange code for tokens
    tokens = await auth.exchange_code(code)
    if tokens:
        print("\nAuthentication successful!")
        print(f"Access Token: {tokens['access_token']}")
        print(f"Refresh Token: {tokens['refresh_token']}")
    else:
        print("Authentication failed")

if __name__ == "__main__":
    asyncio.run(main())