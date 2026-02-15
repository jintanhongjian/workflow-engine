mkdir -p static/css static/js static/fonts

# 2. 下载 Bootstrap 5.3.0
curl -L https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css -o static/css/bootstrap.min.css
curl -L https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js -o static/js/bootstrap.bundle.min.js

# 3. 下载 Bootstrap Icons (需要 CSS 和 字体文件)
curl -L https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css -o static/css/bootstrap-icons.css
# 注意：Icons 还需要字体文件，建议直接下载整个字体包或保持此项 CSS 指向相对路径

# 4 下载对应的字体文件到 static/fonts/ 目录
curl -L https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/fonts/bootstrap-icons.woff2 -o static/css/fonts/bootstrap-icons.woff2
curl -L https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/fonts/bootstrap-icons.woff? -o static/css/fonts/bootstrap-icons.woff

uv run manage.py collectstatic --noinput