from django.urls import path, include
from .views import ConfigValueRetrieveAPIView, ConfigValueListAPIView, ConfigValueCreateAPIView, \
    ConfigValueDestroyAPIView, ConfigValueUpdateAPIView

config_values_read_patterns = ([
    path('', ConfigValueListAPIView.as_view(), name='index'),
    path('/<int:pk>', ConfigValueRetrieveAPIView.as_view(), name='detail'),
], 'config-values-read')

config_values_write_patterns = ([
    path('', ConfigValueCreateAPIView.as_view(), name='add'),
    path('/<int:pk>', ConfigValueUpdateAPIView.as_view(), name='update'),
    path('/<int:pk>', ConfigValueDestroyAPIView.as_view(), name='delete'),
], 'config-values-write')

public_urlpatterns = [
    path('config-values', include(config_values_read_patterns)),
]

private_urlpatterns = [
    path('config-values', include(config_values_write_patterns)),
]
