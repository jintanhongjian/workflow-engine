#!/usr/bin/env bash

set -euo pipefail

SKIP_COLLECTSTATIC=false

for arg in "$@"; do
	case "$arg" in
		--skip-collectstatic)
			SKIP_COLLECTSTATIC=true
			;;
		-h|--help)
			echo "用法: ./static_install.sh [--skip-collectstatic]"
			echo "  --skip-collectstatic  仅下载/更新本地静态资源，不执行 Django collectstatic"
			exit 0
			;;
		*)
			echo "未知参数: $arg"
			echo "使用 --help 查看可用参数"
			exit 1
			;;
	esac
done

echo "[1/4] 创建静态资源目录..."
mkdir -p \
	static/css/fonts \
	static/js \
	static/fonts/inter \
	static/plugins/fontawesome/css \
	static/plugins/fontawesome/webfonts

download() {
	local url="$1"
	local output="$2"
	echo "  - 下载: $output"
	curl -fL --retry 3 --retry-delay 1 --connect-timeout 15 --max-time 180 "$url" -o "$output"
}

echo "[2/4] 本地化 CSS / JS ..."
download "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" "static/css/bootstrap.min.css"
download "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js" "static/js/bootstrap.bundle.min.js"
download "https://cdn.tailwindcss.com" "static/js/tailwind.js"
download "https://unpkg.com/tailwindcss@2.2.19/dist/tailwind.min.css" "static/css/tailwind.min.css"
download "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" "static/css/bootstrap-icons.css"
download "https://cdn.jsdelivr.net/npm/sortablejs@1.15.0/Sortable.min.js" "static/js/Sortable.min.js"
download "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" "static/plugins/fontawesome/css/all.min.css"

echo "[3/4] 本地化字体文件..."
download "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/fonts/bootstrap-icons.woff2" "static/css/fonts/bootstrap-icons.woff2"
download "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/fonts/bootstrap-icons.woff" "static/css/fonts/bootstrap-icons.woff"

download "https://cdnjs.cloudflare.com/ajax/libs/inter-ui/3.19.3/Inter%20(web)/Inter-Regular.woff2" "static/fonts/inter/inter-v13-latin-400.woff2"
download "https://cdnjs.cloudflare.com/ajax/libs/inter-ui/3.19.3/Inter%20(web)/Inter-SemiBold.woff2" "static/fonts/inter/inter-v13-latin-600.woff2"
download "https://cdnjs.cloudflare.com/ajax/libs/inter-ui/3.19.3/Inter%20(web)/Inter-ExtraBold.woff2" "static/fonts/inter/inter-v13-latin-800.woff2"

download "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/webfonts/fa-solid-900.woff2" "static/plugins/fontawesome/webfonts/fa-solid-900.woff2"
download "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/webfonts/fa-regular-400.woff2" "static/plugins/fontawesome/webfonts/fa-regular-400.woff2"
download "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/webfonts/fa-brands-400.woff2" "static/plugins/fontawesome/webfonts/fa-brands-400.woff2"

if [ "$SKIP_COLLECTSTATIC" = true ]; then
	echo "[4/4] 已跳过 collectstatic（--skip-collectstatic）"
else
	echo "[4/4] 执行 collectstatic..."
	if command -v uv >/dev/null 2>&1; then
		uv run manage.py collectstatic --noinput
	else
		python manage.py collectstatic --noinput
	fi
fi

echo "✅ 本地化完成"