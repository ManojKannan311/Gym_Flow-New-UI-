from django.db import transaction
from frontend.models import InvoiceSettings

def generate_invoice_number(gym):
    """
    Generates invoice like: MFG-1001 or INV-0001 (with padding)
    Safe for concurrent requests (no duplicates).
    """
    with transaction.atomic():
        settings, _ = InvoiceSettings.objects.select_for_update().get_or_create(
            gym=gym,
            defaults={"prefix": "INV", "next_number": 1000, "padding": 4}
        )
        
        number = settings.next_number
        padded = str(number).zfill(settings.padding)
        invoice_no = f"{settings.prefix}-{padded}"

        settings.next_number = number + 1
        settings.save(update_fields=["next_number"])
        print(invoice_no)
        return invoice_no
