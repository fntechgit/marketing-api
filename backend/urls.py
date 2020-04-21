"""backend URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from api.urls import public_urlpatterns as public_api_v1
from api.urls import private_urlpatterns as private_api_v1
from rest_framework.schemas import get_schema_view


api_urlpatterns = [
    path('public/v1/', include(public_api_v1)),
    path('v1/',  include(private_api_v1)),
]

urlpatterns = [
    path('api/', include(api_urlpatterns)),
    path('admin', admin.site.urls),
    path('openapi', get_schema_view(
        title="Marketing API",
        description="Marketing API",
        version="1.0.0",
        patterns=api_urlpatterns,
    ), name='openapi-schema'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
