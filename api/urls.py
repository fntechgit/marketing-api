from django.urls import path, include
from .views import ConfigValueRetrieveAPIView, ConfigValueListAPIView

config_values_patterns = ([
    path('', ConfigValueListAPIView.as_view(), name='index'),
    path('/<int:pk>', ConfigValueRetrieveAPIView.as_view(), name='detail'),
], 'config-values')

public_urlpatterns = [
    path('config-values', include(config_values_patterns)),
]
