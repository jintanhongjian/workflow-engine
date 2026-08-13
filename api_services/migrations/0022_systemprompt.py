from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api_services", "0021_emailconfig_use_tls_alter_emailconfig_use_ssl"),
    ]

    operations = [
        migrations.CreateModel(
            name="SystemPrompt",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role_name", models.CharField(max_length=150, unique=True, verbose_name="角色名称")),
                ("role_definition", models.TextField(verbose_name="角色定义")),
                ("prompt_content", models.TextField(verbose_name="提示词内容")),
                ("is_active", models.BooleanField(default=True, verbose_name="是否启用")),
                ("is_default", models.BooleanField(default=False, verbose_name="是否默认")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "系统提示词",
                "verbose_name_plural": "系统提示词",
                "ordering": ["-updated_at"],
            },
        ),
    ]
