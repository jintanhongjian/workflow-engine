from django.db import migrations, models
import django.db.models.deletion


MODES = [
    ("run_intelligent_task", "智能任务", "多轮工具编排，支持流式输出"),
    ("skill_call", "技能调用", "指定 skill_name 调用注册技能"),
    ("get_content", "内容生成", "纯内容生成，可选系统提示词"),
]


def seed_conversation_modes(apps, schema_editor):
    ConversationMode = apps.get_model("api_services", "ConversationMode")
    for code, label, desc in MODES:
        ConversationMode.objects.update_or_create(
            code=code,
            defaults={
                "label": label,
                "description": desc,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("api_services", "0024_merge_20260301_1300"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConversationMode",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(help_text="如 run_intelligent_task / skill_call / get_content", max_length=64, unique=True, verbose_name="模式代码")),
                ("label", models.CharField(max_length=128, verbose_name="模式名称")),
                ("description", models.TextField(blank=True, default="", verbose_name="模式说明")),
                ("is_active", models.BooleanField(default=True, verbose_name="是否启用")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("default_system_prompt", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="conversation_modes", to="api_services.systemprompt", verbose_name="默认系统提示词")),
            ],
            options={
                "verbose_name": "对话模式",
                "verbose_name_plural": "对话模式",
                "ordering": ["code"],
            },
        ),
        migrations.RunPython(seed_conversation_modes, migrations.RunPython.noop),
    ]
