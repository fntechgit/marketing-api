from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from collections import OrderedDict


class LargeResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'per_page'
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response(OrderedDict([
            ('total', self.page.paginator.count),
            ('per_page', self.page.paginator.per_page),
            ('current_page', self.page.number),
            ('last_page', self.page.paginator.num_pages),
            ('data', data)
        ]))

    def get_paginated_response_schema(self, schema):
        return {
            'type': 'object',
            'properties': {
                'total': {
                    'type': 'integer',
                    'example': 123,
                },
                'per_page': {
                    'type': 'integer',
                    'example': 123,
                },
                'current_page': {
                    'type': 'integer',
                    'example': 123,
                },
                'last_page': {
                    'type': 'integer',
                    'example': 123,
                },
                'data': schema,
            },
        }

