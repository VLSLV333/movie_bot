import base64
import hmac
import json
import time
import hashlib
from typing import Tuple, Dict
import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("BACKEND_DOWNLOAD_SECRET", "").encode()

class SignedTokenManager:
    @staticmethod
    def generate_token(data: dict) -> Tuple[str, str]:
        """
        Returns (data_b64, signature)
        """
        payload_json = json.dumps(data, separators=(",", ":"))  # compact encoding
        data_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode()
        signature = hmac.new(SECRET_KEY, data_b64.encode(), hashlib.sha256).hexdigest()
        return data_b64, signature

    @staticmethod
    def verify_token(data_b64: str, sig: str) -> Dict:
        """
        Verifies the HMAC and returns parsed JSON payload
        Raises ValueError if invalid or expired
        """
        expected_sig = hmac.new(SECRET_KEY, data_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, sig):
            raise ValueError("Invalid signature")

        try:
            decoded_json = base64.urlsafe_b64decode(data_b64.encode()).decode()
            payload = json.loads(decoded_json)
        except Exception as e:
            raise ValueError(f"Invalid payload format: {e}")

        if "exp" in payload and payload["exp"] < int(time.time()):
            raise ValueError("Token expired")

        return payload
