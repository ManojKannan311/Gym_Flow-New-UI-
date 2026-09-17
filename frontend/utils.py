from datetime import date, timedelta
from django.utils import timezone
import re
import requests


def get_member_status(expiry_date):
    today = date.today()
    if expiry_date < today:
        return 'expired'
    elif expiry_date <= today + timedelta(days=3):
        return 'expiring'
    return 'active'

def apply_branch_scope(request, qs):
    """
    Owner: full gym scope
    Trainer: only their branch
    """
    if request.user.role == "TRAINER":
        return qs.filter(branch_id=request.user.branch_id)
    return qs

from frontend.models import WhatsAppMessageLog

INTERAKT_MESSAGE_URL = "https://api.interakt.ai/v1/public/message/"


def get_member_status(expiry_date):
    today = date.today()
    if expiry_date < today:
        return "expired"
    elif expiry_date <= today + timedelta(days=3):
        return "expiring"
    return "active"


def apply_branch_scope(request, qs):
    """
    Owner: full gym scope
    Trainer: only their branch
    """
    if request.user.role == "TRAINER":
        return qs.filter(branch_id=request.user.branch_id)
    return qs


def normalize_indian_phone(raw_phone: str):
    """
    Converts:
    9876543210
    09876543210
    +919876543210
    91 9876543210
    into:
    country_code = +91
    phone_number = 9876543210
    """
    if not raw_phone:
        return None, None

    phone = re.sub(r"\D", "", raw_phone)

    if phone.startswith("91") and len(phone) == 12:
        return "+91", phone[2:]

    if phone.startswith("0") and len(phone) == 11:
        return "+91", phone[1:]

    if len(phone) == 10:
        return "+91", phone

    return None, None


def get_next_birthday(dob, today=None):
    if not dob:
        return None

    if today is None:
        today = date.today()

    try:
        next_birthday = dob.replace(year=today.year)
    except ValueError:
        # Feb 29 -> Feb 28 in non-leap year
        next_birthday = date(today.year, 2, 28)

    if next_birthday < today:
        try:
            next_birthday = dob.replace(year=today.year + 1)
        except ValueError:
            next_birthday = date(today.year + 1, 2, 28)

    return next_birthday


def send_interakt_template(
    *,
    gym,
    member,
    template_name: str,
    body_values: list,
    message_type: str,
    callback_data: str = None,
):
    country_code, phone_number = normalize_indian_phone(member.phone)

    if not country_code or not phone_number:
        return WhatsAppMessageLog.objects.create(
            gym=gym,
            member=member,
            phone=member.phone or "",
            template_name=template_name,
            message_type=message_type,
            status="failed",
            error_message="Invalid phone number format",
        )

    payload = {
        "countryCode": country_code,
        "phoneNumber": phone_number,
        "type": "Template",
        "callbackData": callback_data or f"{gym.id}:{member.id}:{message_type}",
        "template": {
            "name": template_name,
            "languageCode": "en",
            "bodyValues": body_values,
        },
    }

    headers = {
        "Authorization": f"Basic {gym.interakt_api_key}",
        "Content-Type": "application/json",
    }

    print("---- WhatsApp API ----")
    print("Member:", member.name)
    print("Phone:", phone_number)
    print("Template:", template_name)
    print("Values:", body_values)
    print("----------------------")

    log = WhatsAppMessageLog.objects.create(
        gym=gym,
        member=member,
        phone=f"{country_code}{phone_number}",
        template_name=template_name,
        message_type=message_type,
        status="send",
        callback_data=payload["callbackData"],
    )

    try:
        response = requests.post(
            INTERAKT_MESSAGE_URL,
            json=payload,
            headers=headers,
            timeout=20,
        )

        try:
            data = response.json()
        except Exception:
            data = {"raw_text": response.text}

        if response.status_code in (200, 201) and data.get("result") is True:
            log.interakt_message_id = data.get("id")
            log.sent_at = timezone.now()
            log.status = "sent"
            log.save(update_fields=["interakt_message_id", "sent_at", "status", "updated_at"])
        else:
            log.status = "send"
            log.error_message = str(data)
            log.failed_at = timezone.now()
            log.save(update_fields=["status", "error_message", "failed_at", "updated_at"])

    except Exception as e:
        log.status = "failed"
        log.error_message = str(e)
        log.failed_at = timezone.now()
        log.save(update_fields=["status", "error_message", "failed_at", "updated_at"])

    return log


def already_sent_today(member, message_type):
    today = timezone.localdate()

    return WhatsAppMessageLog.objects.filter(
        gym=member.gym,
        member=member,
        message_type=message_type,
        created_at__date=today,
    ).exists()
    
    
    