from django.urls import reverse
from rest_framework.test import APITestCase
from ..models import ConfigValue
from rest_framework import status
import io
from PIL import Image
import os
import json


class PrivateTests(APITestCase):

    @staticmethod
    def generate_photo_file():
        file = io.BytesIO()
        image = Image.new('RGBA', size=(100, 100), color=(155, 0, 0))
        image.save(file, 'png')
        file.name = 'test.png'
        file.seek(0)
        return file

    def setUp(self):
        self.access_token = os.environ.get('ACCESS_TOKEN', 'TEST')
        ConfigValue.objects.create(key='key.11', value='<p>test</p>', type='TEXTAREA', show_id=1)
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

        response = self.client.post(url, data, format='multipart')
        json_response = json.loads(response.content)
        self.assertEqual(1, ConfigValue.objects.filter(id=json_response['id']).count())
        db_object = ConfigValue.objects.filter(id=json_response['id']).get()
        self.assertEqual(db_object.key, 'key.1')

    def test_create_without_value(self):
        url = reverse('config-values-write:add')

        data = {
            'key': 'key.1',
            'type': 'TEXTAREA',
            'show_id': '1'
        }

        response = self.client.post(url, data, format='multipart')

        self.assertEqual(status.HTTP_412_PRECONDITION_FAILED, response.status_code)

    def test_create_update_textarea(self):

        url = reverse('config-values-write:add')

        data = {
            'key': 'key.1',
            'type': 'TEXTAREA',
            'show_id': '1',
            'value': '<p>this is a test</p>'
        }

        response = self.client.post(url, data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        json_response = json.loads(response.content)
        self.assertEqual(ConfigValue.objects.filter(id=json_response['id']).count(), 1)
        db_object = ConfigValue.objects.filter(id=json_response['id']).get()
        self.assertEqual(db_object.key, 'key.1')

        url = reverse('config-values-write:update_destroy',  kwargs={'pk': db_object.id})

        data = {
            #'key': 'key.1.update',
            'value': '<p>update</p>',
            #'type': 'TEXTAREA',
        }

        response = self.client.put(url, data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json_response = json.loads(response.content)
        self.assertEqual(ConfigValue.objects.filter(id=json_response['id']).count(), 1)
        db_object = ConfigValue.objects.filter(id=json_response['id']).get()
        self.assertEqual(db_object.key, 'key.1')
        self.assertEqual(db_object.value, '<p>update</p>')

    def test_create_delete_textarea(self):

        url = reverse('config-values-write:add')

        data = {
            'key': 'key.1',
            'type': 'TEXTAREA',
            'show_id': '1',
            'value': '<p>this is a test</p>'
        }

        current_qty = ConfigValue.objects.count()

        response = self.client.post(url, data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(current_qty + 1, ConfigValue.objects.count())
        db_object = ConfigValue.objects.last()
        self.assertEqual(db_object.key, 'key.1')

        url = reverse('config-values-write:update_destroy', kwargs={'pk': db_object.id})

        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(current_qty, ConfigValue.objects.count())

    def test_create_update_hexcolor(self):
        url = reverse('config-values-write:add')

        data = {
            'key': 'key.1',
            'type': 'HEX_COLOR',
            'show_id': '1',
            'value': '#c4c4c4'
        }

        response = self.client.post(url, data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        json_response = json.loads(response.content)
        self.assertEqual(ConfigValue.objects.filter(id=json_response['id']).count(), 1)
        db_object = ConfigValue.objects.filter(id=json_response['id']).get()
        self.assertEqual(db_object.key, 'key.1')

        url = reverse('config-values-write:update_destroy', kwargs={'pk': db_object.id})

        data = {
            'value': '#050505',
        }

        response = self.client.put(url, data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json_response = json.loads(response.content)
        self.assertEqual(ConfigValue.objects.filter(id=json_response['id']).count(), 1)
        db_object = ConfigValue.objects.filter(id=json_response['id']).get()
        self.assertEqual(db_object.key, 'key.1')
        self.assertEqual(db_object.value, '#050505')

    def test_create_invalid_hexcolor(self):
        url = reverse('config-values-write:add')

        data = {
            'key': 'key.1',
            'type': 'HEX_COLOR',
            'show_id': '1',
            'value': '#c4c4c4c4c4'
        }

        response = self.client.post(url, data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_412_PRECONDITION_FAILED)

    def test_create_clone(self):
        url = reverse('config-values-write:clone',  kwargs={'show_id': 1, 'to_show_id': 3})

        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ConfigValue.objects.filter(show_id=3).count() > 0, True)
