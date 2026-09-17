from functools import wraps
from django.http import HttpResponseForbidden
from django.shortcuts import redirect , render

def owner_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = request.user

        # not logged in
        if not user.is_authenticated:
            return redirect("login")
            
        # Owner role check
        # (In DB it will be 'ADMIN' if your ROLE_CHOICES uses ('ADMIN', 'Owner'))
        if user.role != "ADMIN":
            return render(request, "403.html", status=403)

        return view_func(request, *args, **kwargs)

    return _wrapped

def owner_or_trainer(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return HttpResponseForbidden("Login required")
        if request.user.role not in ("ADMIN", "TRAINER"):
            return HttpResponseForbidden("Not allowed")
        return view_func(request, *args, **kwargs)
    return _wrapped