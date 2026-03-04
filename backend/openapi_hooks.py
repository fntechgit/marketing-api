def custom_postprocessing_hook(result, generator, request, public):
    for path, methods in result.get('paths', {}).items():
        is_public = path.startswith('/api/public/')
        tag = 'Public' if is_public else 'Private'
        for method, operation in methods.items():
            if not isinstance(operation, dict):
                continue
            operation['tags'] = [tag]
            if is_public:
                operation['security'] = []
    return result
