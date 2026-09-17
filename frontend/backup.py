import io
import zipfile
from django.http import HttpResponse
from django.core.serializers import serialize
from django.utils import timezone
from django.contrib.auth.decorators import login_required

@login_required
def download_full_backup(request):
    gym = request.user.gym

    # Owner restriction (recommended)
    if request.user.role not in ["ADMIN", "OWNER"]:
        return HttpResponse("Not allowed", status=403)

    from .models import Gym, Branch, MembershipPlan, Member, Payment,Enquiry , WhatsAppMessageLog,InvoiceSettings,WhatsAppLog

    # ✅ Collect all objects
    all_objs = (
        list(Gym.objects.filter(id=gym.id))
        + list(Branch.objects.filter(gym=gym))
        + list(MembershipPlan.objects.filter(branch__gym=gym))
        + list(Member.objects.filter(gym=gym))
        + list(Payment.objects.filter(gym=gym))
        + list(Enquiry.objects.filter(gym=gym))
        + list(WhatsAppMessageLog.objects.filter(gym=gym))
        + list(InvoiceSettings.objects.filter(gym=gym))
        + list(WhatsAppLog.objects.filter(gym=gym))
        
    )

    # ✅ Create proper Django fixture
    fixture = serialize("json", all_objs)

    # ✅ Create zip in memory
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("backup.json", fixture)

    buffer.seek(0)

    filename = f"gymflow_backup_{gym.id}_{timezone.localdate()}.zip"
    response = HttpResponse(buffer, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    return response