import json

from django.urls import reverse
from rest_framework.test import APITestCase
from ..models import ConfigValue
from rest_framework import status
import os


class PublicTests(APITestCase):

    def setUp(self):
        self.access_token = os.environ.get('ACCESS_TOKEN')
        ConfigValue.objects.create(key='key.1', value='<p>test</p>', type='TEXTAREA', show_id=1)
        ConfigValue.objects.create(key='key.2', value='<p>test2</p>', type='TEXTAREA', show_id=1)
        ConfigValue.objects.create(key='key.3', value='<p>test3</p>', type='TEXTAREA', show_id=1)
        ConfigValue.objects.create(key='key.4', value='<p>test</p>', type='TEXTAREA', show_id=2)
        ConfigValue.objects.create(key='key.5', value='<p>test2</p>', type='TEXTAREA', show_id=2)
        ConfigValue.objects.create(key='key.6', value='<p>test3</p>', type='TEXTAREA', show_id=2)

    def test_get_by_show_id(self):
        show_id = 1
        url = reverse('config-values-read:index_by_show',  kwargs={'show_id': show_id})

        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json_response = json.loads(response.content)
        self.assertEqual(json_response['count'] == 3)