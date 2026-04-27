"""Accounts app utils — OTP generation and SMS sending."""
import random
import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def generate_otp(digits: int = 6) -> str:
    """Generate a numeric OTP of the given length."""
    return ''.join([str(random.randint(0, 9)) for _ in range(digits)])


def send_sms_sparrow(phone_number: str, message: str) -> bool:
    """
    Send SMS via Sparrow SMS Nepal.
    Returns True on success, False on failure.
    """
    # =========================================================================
    # DEVELOPMENT MODE: print OTP to console instead of sending SMS
    # =========================================================================
    print("\n" + "=" * 50)
    print("DEVELOPMENT MODE - OTP NOT SENT VIA SMS")
    print(f"To: {phone_number}")
    print(f"Message: {message}")
    print("=" * 50 + "\n")
    
    return True

    # =========================================================================
    # FUTURE SMS IMPLEMENTATION (UNCOMMENT AND UPDATE WHEN READY)
    # =========================================================================
    # try:
    #     url = "http://api.sparrowsms.com/v2/sms/"
    #     payload = {
    #         'token': settings.SPARROW_SMS_TOKEN,
    #         'from': settings.SPARROW_SMS_FROM,
    #         'to': phone_number,
    #         'text': message,
    #     }
    #     response = requests.post(url, data=payload, timeout=10)
    #     data = response.json()
    #     if data.get('response_code') == 200:
    #         return True
    #     logger.error(f"Sparrow SMS error: {data}")
    #     return False
    # except Exception as e:
    #     logger.error(f"SMS send exception: {e}")
    #     return False


def send_otp_sms(phone_number: str, otp_code: str) -> bool:
    """Send OTP via SMS."""
    message = f"Your CafeApp verification code is: {otp_code}. Valid for {settings.OTP_EXPIRY_MINUTES} minutes. Do not share."
    return send_sms_sparrow(phone_number, message)
