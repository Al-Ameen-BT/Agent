import hmac
import hashlib
from fastapi import Request, HTTPException, Security, Depends
from fastapi.security.api_key import APIKeyHeader
from .config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_auth(request: Request, api_key: str = Security(api_key_header)):
    if not settings.AGENT_BRIDGE_REQUIRE_API_KEY:
        return True

    if api_key != settings.AGENT_BRIDGE_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")

    # Verify HMAC if a signature is provided
    hmac_header = request.headers.get("X-HMAC-Signature")
    if not hmac_header:
        raise HTTPException(status_code=401, detail="Missing HMAC Signature")

    body = await request.body()
    
    # Calculate HMAC
    secret = settings.AGENT_BRIDGE_HMAC_SECRET.encode("utf-8")
    expected_hmac = hmac.new(secret, body, hashlib.sha256).hexdigest()
    
    if not hmac.compare_digest(expected_hmac, hmac_header):
        raise HTTPException(status_code=401, detail="Invalid HMAC Signature")
        
    return True
