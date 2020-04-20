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
        ConfigValue.objects.create(key='key.1', value='<p>test</p>', type='TEXTAREA', show_id=1)
        ConfigValue.objects.create(key='key.2', value='<p>test2</p>', type='TEXTAREA', show_id=1)
        ConfigValue.objects.create(key='key.3', value='<p>test3</p>', type='TEXTAREA', show_id=1)
        ConfigValue.objects.create(key='key.4', value='<p>test</p>', type='TEXTAREA', show_id=2)
        ConfigValue.objects.create(key='key.5', value='<p>test2</p>', type='TEXTAREA', show_id=2)
        ConfigValue.objects.create(key='key.6', value='<p>test3</p>', type='TEXTAREA', show_id=2)

    def test_create_with_file(self):
        url = reverse('config-values-write:add')
        file = self.generate_photo_file()

        data = {
            'key' : 'key.1',
            'type': 'FILE',
            'file': file,
            'show_id': '1'
        }

        logging.getLogger('test').info('using access token {token}'.format(token=self.access_token))
        response = self.client.post('{url}?access_token={token}'.format(url=url, token= self.access_token), data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ConfigValue.objects.count(), 1)
        self.assertEqual(ConfigValue.objects.get().key, 'key.1')

    def test_create_without_value(self):
        url = reverse('config-values-write:add')

        data = {
            'key': 'key.1',
            'type': 'TEXTAREA',
            'show_id': '1'
        }

        logging.getLogger('test').info('using access token {token}'.format(token=self.access_token))
        response = self.client.post('{url}?access_token={token}'.format(url=url, token=self.access_token), data,
                                    format='multipart')
        self.assertEqual(response.status_code, status.HTTP_412_PRECONDITION_FAILED)

    def test_create_update_textarea(self):

        url = reverse('config-values-write:add')

        data = {
            'key': 'key.1',
            'type': 'TEXTAREA',
            'show_id': '1',
            'value': '<p>this is a test</p>'
        }

        logging.getLogger('test').info('using access token {token}'.format(token=self.access_token))

        response = self.client.post('{url}?access_token={token}'.format(url=url, token=self.access_token), data,
                                    format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ConfigValue.objects.count(), 1)
        db_object = ConfigValue.objects.get()
        self.assertEqual(db_object.key, 'key.1')

        url = reverse('config-values-write:update_destroy',  kwargs={'pk': db_object.id})

        data = {
            'key': 'key.1',
            'type': 'TEXTAREA',
            'show_id': '1',
            'value': '<p>update</p>'
        }

        response = self.client.put('{url}?access_token={token}'.format(url=url, token=self.access_token), data,
                                    format='multipart')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(ConfigValue.objects.count(), 1)
        self.assertEqual(ConfigValue.objects.get().key, 'key.1')
        self.assertEqual(ConfigValue.objects.get().value, '<p>update</p>')

    def test_create_delete_textarea(self):

        url = reverse('config-values-write:add')

        data = {
            'key': 'key.1',
            'type': 'TEXTAREA',
            'show_id': '1',
            'value': '<p>this is a test</p>'
        }

        logging.getLogger('test').info('using access token {token}'.format(token=self.access_token))

        response = self.client.post('{url}?access_token={token}'.format(url=url, token=self.access_token), data,
                                    format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ConfigValue.objects.count(), 1)
        db_object = ConfigValue.objects.get()
        self.assertEqual(db_object.key, 'key.1')

        url = reverse('config-values-write:update_destroy', kwargs={'pk': db_object.id})

        response = self.client.delete('{url}?access_token={token}'.format(url=url, token=self.access_token))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(ConfigValue.objects.count(), 0)

    def test_create_clone(self):
        url = reverse('config-values-write:clone',  kwargs={'show_id': 1, 'to_show_id': 3})

        logging.getLogger('test').info('using access token {token}'.format(token=self.access_token))
        response = self.client.post('{url}?access_token={token}'.format(url=url, token=self.access_token), )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ConfigValue.objects.filter(show_id=3).count() > 0, True)
