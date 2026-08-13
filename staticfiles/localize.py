资源类型,原始网络引用 (CDN),本地化修改后引用 (Django Static)
基础样式 (Bootstrap),"<link href=""https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"" rel=""stylesheet"">","<link href=""{% static 'css/bootstrap.min.css' %}"" rel=""stylesheet"">"
图标库 (Icons),"<link href=""https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css"" rel=""stylesheet"">","<link href=""{% static 'css/bootstrap-icons.css' %}"" rel=""stylesheet"">"
原子化 CSS (Tailwind),"<script src=""https://cdn.tailwindcss.com""></script>","<script src=""{% static 'js/tailwind.js' %}""></script>"
脚本 (Bootstrap JS),"<script src=""https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js""></script>","<script src=""{% static 'js/bootstrap.bundle.min.js' %}""></script>"
字体 (Inter),"<link href=""https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap"" rel=""stylesheet"">","<link href=""{% static 'css/inter.css' %}"" rel=""stylesheet"">"