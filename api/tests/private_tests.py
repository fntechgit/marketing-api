from django.urls import reverse
from rest_framework.test import APITestCase
from ..models import ConfigValue
from rest_framework import status
import io
from PIL import Image
import requests, logging, sys,os


class PrivateTests(APITestCase):

    access_token = None

    @staticmethod
    def generate_photo_file():
        file = io.BytesIO()
        image = Image.new('RGBA', size=(100, 100), color=(155, 0, 0))
        image.save(file, 'png')
        file.name = 'test.png'
        file.seek(0)
        return file

    def setUp(self):
        self.access_token = os.environ.get('ACCESS_TOKEN')

    def test_create_with_file(self):
        url = reverse('config-values-write:add')
        file = self.generate_photo_file()

        data = {
            'key' : 'key.1',
            'type': 'FILE',
            'file': file
        }

        logging.getLogger('test').info('using access token {token}'.format(token=self.access_token))
        response = self.client.post('{url}?access_token={token}'.format(url=url, token= self.access_token), data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ConfigValue.objects.count(), 1)
        self.assertEqual(ConfigValue.objects.get().key, 'key.1')