from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
from accounts.views import login_view
urlpatterns = [
    path('admin/', admin.site.urls),
    path("login/", login_view, name="login"),
    # path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('', include('frontend.urls')),
    path("", include("frontend.urls")),     # your main app
    path("", include("accounts.urls")),
]+ static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
