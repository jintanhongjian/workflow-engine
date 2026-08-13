from django.conf import settings

def global_api_version(request):
    return {'CURRENT_API_VERSION': settings.API_VERSION}