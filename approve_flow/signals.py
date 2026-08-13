from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import UserRoleAssignment

@receiver(post_save, sender=UserRoleAssignment)
def notify_user_role_assigned(sender, instance, created, **kwargs):
    if created:
        print(f"信号触发：用户 {instance.user.username} 被赋予了角色 {instance.role.name}")