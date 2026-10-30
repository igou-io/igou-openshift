#!/usr/bin/env bash
# The upstream entrypoint generates PreConfig.js before invoking this script.
set -euo pipefail

webapp="${CATALINA_HOME:?}/webapps/draw"
for field in github_client_id github_client_secret; do
    if [[ ! -s "$webapp/WEB-INF/$field" ]]; then
        echo "GitHub storage requires a populated $field file" >&2
        exit 1
    fi
done

github_client_id=$(<"$webapp/WEB-INF/github_client_id")
if [[ ! "$github_client_id" =~ ^[A-Za-z][A-Za-z0-9._-]+$ ]]; then
    echo "GitHub storage requires a GitHub App Client ID" >&2
    exit 1
fi
if [[ ! "${DRAWIO_GITHUB_APP_URL:-}" =~ ^https://github\.com/apps/[a-z0-9-]+$ ]]; then
    echo "DRAWIO_GITHUB_APP_URL must name the installed GitHub App" >&2
    exit 1
fi

# The client ID is public. The client secret is read only by the auth servlet.
printf '\nwindow.DRAWIO_GITHUB_ID = "%s";\nurlParams["gh"] = "1";\n' \
    "$github_client_id" >> "$webapp/js/PreConfig.js"

# The pinned production bundle otherwise directs installation to draw.io's App.
sed -i "s|https://github[.]com/apps/draw-io-app|${DRAWIO_GITHUB_APP_URL}|g" \
    "$webapp/js/app.min.js"

exec catalina.sh run
