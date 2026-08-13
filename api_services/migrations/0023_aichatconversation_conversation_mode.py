from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api_services", "0022_systemprompt"),
    ]

    operations = [
        migrations.AddField(
            model_name="aichatconversation",
            name="conversation_mode",
            field=models.CharField(
                choices=[
                    ("run_intelligent_task", "智能任务"),
                    ("skill_call", "技能调用"),
                    ("get_content", "内容生成"),
                ],
                default="run_intelligent_task",
                max_length=32,
                verbose_name="对话模式",
            ),
        ),
    ]
