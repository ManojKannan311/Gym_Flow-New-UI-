from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect
from django.contrib import messages

def login_view(request):
    if request.user.is_authenticated:
        if request.user.role == "TRAINER":
            return redirect("member_list")
        return redirect("dashboard")

    if request.method == "POST":
        
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        user = authenticate(request, username=username, password=password)
        
        if user is None:
            messages.error(request, "Invalid username or password")
            return redirect("login")

        if not user.is_active:
            messages.error(request, "Account is inactive. Contact owner.")
            return redirect("login")

        login(request, user)

        # Trainer must have branch
        if user.role == "TRAINER" and not getattr(user, "branch_id", None):
            messages.warning(request, "Branch not assigned. Contact owner.")
            logout(request)
            return redirect("login")

        # ✅ Role based landing page
        if user.role == "TRAINER":
            return redirect("member_list")      # or renewals_page / unpaid_members
        return redirect("dashboard")            # owner

    return render(request, "login.html")


def logout_view(request):
    logout(request)
    return redirect("login")
