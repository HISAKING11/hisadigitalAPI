from twilio.rest import Client
import random
import os
from dotenv import load_dotenv

load_dotenv()

account_sid = os.getenv("TWILIO_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
twilio_phone = os.getenv("TWILIO_PHONE")

client = Client(account_sid, auth_token)

otp_store = {}

def generate_otp(phone):

    otp = str(random.randint(100000, 999999))

    otp_store[phone] = otp

    client.messages.create(
        body=f"Your OTP is: {otp}",
        from_=twilio_phone,
        to=phone
    )

    return otp


def verify_otp(phone, otp):

    return otp_store.get(phone) == otp