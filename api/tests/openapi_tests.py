import json

import yaml
from django.test import TestCase
from django.urls import reverse


class OpenAPISchemaTests(TestCase):

    SCHEMA_URL = reverse('openapi-schema')
    SCHEMA_URL_JSON = SCHEMA_URL + '?format=json'
    SCHEMA_URL_YAML = SCHEMA_URL + '?format=yaml'

    def _get_schema(self):
        response = self.client.get(self.SCHEMA_URL_JSON)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)

    def test_schema_default_format_returns_valid_yaml_on_default_url(self):
        response = self.client.get(self.SCHEMA_URL)
        self.assertEqual(response.status_code, 200)
        schema = yaml.safe_load(response.content)
        self.assertIn('openapi', schema)
        self.assertIn('paths', schema)

    def test_schema_default_format_returns_valid_yaml(self):
        response = self.client.get(self.SCHEMA_URL_YAML)
        self.assertEqual(response.status_code, 200)
        schema = yaml.safe_load(response.content)
        self.assertIn('openapi', schema)
        self.assertIn('paths', schema)

    def test_schema_returns_200(self):
        response = self.client.get(self.SCHEMA_URL_JSON)
        self.assertEqual(response.status_code, 200)

    def test_schema_is_valid_json(self):
        schema = self._get_schema()
        self.assertIn('openapi', schema)
        self.assertIn('paths', schema)
        self.assertIn('info', schema)

    def test_schema_version_is_3_1(self):
        schema = self._get_schema()
        self.assertTrue(schema['openapi'].startswith('3.1'))

    def test_schema_info(self):
        schema = self._get_schema()
        self.assertEqual(schema['info']['title'], 'Marketing API')

    def test_schema_contains_public_and_private_tags(self):
        schema = self._get_schema()
        tag_names = [t['name'] for t in schema.get('tags', [])]
        self.assertIn('Public', tag_names)
        self.assertIn('Private', tag_names)

    def test_schema_contains_oauth2_security_scheme(self):
        schema = self._get_schema()
        security_schemes = schema.get('components', {}).get('securitySchemes', {})
        self.assertIn('OAuth2', security_schemes)
        self.assertEqual(security_schemes['OAuth2']['type'], 'oauth2')

    def test_schema_has_paths(self):
        schema = self._get_schema()
        self.assertGreater(len(schema['paths']), 0)

    def test_public_endpoints_have_no_security(self):
        schema = self._get_schema()
        for path, methods in schema['paths'].items():
            if path.startswith('/api/public/'):
                for method, spec in methods.items():
                    if method in ('get', 'post', 'put', 'patch', 'delete'):
                        self.assertEqual(
                            spec.get('security', []),
                            [],
                            f'{method.upper()} {path} should have empty security'
                        )


    def test_admin_endpoints_not_in_schema(self):
        schema = self._get_schema()
        for path in schema['paths']:
            self.assertFalse(
                path.startswith('/admin'),
                f'Admin endpoint {path} should not appear in schema'
            )

    def test_all_paths_are_under_api_prefix(self):
        schema = self._get_schema()
        for path in schema['paths']:
            self.assertTrue(
                path.startswith('/api/'),
                f'Path {path} should be under /api/ prefix'
            )


class SwaggerUITests(TestCase):

    DOCS_URL = reverse('swagger-ui')

    def test_swagger_ui_returns_200(self):
        response = self.client.get(self.DOCS_URL)
        self.assertEqual(response.status_code, 200)

    def test_swagger_ui_contains_html(self):
        response = self.client.get(self.DOCS_URL)
        self.assertIn('text/html', response['Content-Type'])


class RedocTests(TestCase):

    DOCS_URL = reverse('redoc')

    def test_redoc_returns_200(self):
        response = self.client.get(self.DOCS_URL)
        self.assertEqual(response.status_code, 200)

    def test_redoc_contains_html(self):
        response = self.client.get(self.DOCS_URL)
        self.assertIn('text/html', response['Content-Type'])
