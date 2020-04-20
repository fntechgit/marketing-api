from django.urls import path, include
from .views import ConfigValueRetrieveAPIView, ConfigValueListAPIView, ConfigValueCreateAPIView, \
    ConfigValueUpdateDestroyAPIView, ConfigValueCloneAPIView, ConfigValueAllListAPIView

config_values_read_patterns = ([
    path('', ConfigValueListAPIView.as_view(), name='index'),
    path('/all/shows/<int:show_id>', ConfigValueAllListAPIView.as_view(), name='index_by_show'),
    path('/<int:pk>', ConfigValueRetrieveAPIView.as_view(), name='detail'),
], 'config-values-read')

config_values_shows_patterns = [
    path('/clone/<int:to_show_id>', ConfigValueCloneAPIView.as_view(), name='clone')
]

config_values_write_patterns = ([
    path('', ConfigValueCreateAPIView.as_view(), name='add'),
    path('/<int:pk>', ConfigValueUpdateDestroyAPIView.as_view(), name='update_destroy'),
    path('/all/shows/<int:show_id>', include(config_values_shows_patterns))
], 'config-values-write')

public_urlpatterns = [
    path('config-values', include(config_values_read_patterns)),
]

private_urlpatterns = [
    path('config-values', include(config_values_write_patterns)),
]
