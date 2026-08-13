from api_services.skills.registry import registry as skill_registry
from django.http import JsonResponse, HttpResponseBadRequest

def skill_details(request):
    """API to fetch details of a specific skill."""
    skill_name = request.GET.get('skill_name')
    if not skill_name:
        return HttpResponseBadRequest("Missing skill_name parameter")
    
    details = skill_registry.get_skill_details(skill_name)
    if not details:
        return JsonResponse({"error": "Skill not found"}, status=404)
        
    return JsonResponse(details)
