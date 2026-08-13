chmod +x DB_migrate.sh
uv run manage.py makemigrations
uv run manage.py migrate