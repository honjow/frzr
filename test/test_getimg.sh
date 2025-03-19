#! /bin/bash

source ../__frzr-deploy

set -e

REPO="3003n/chimeraos"
CHANNEL="matrix"
BRANCH="gnome-nv"

RELEASES_API_URL="https://api.github.com/repos/${REPO}/releases?per_page=100"
RELEASES=$(curl --http1.1 -L -s --connect-timeout 15 -m 15 "${RELEASES_API_URL}")

IMG_LIST_URL=$(echo $RELEASES | get_img_url "${CHANNEL}")

BASE_URL=$(dirname $(echo "${IMG_LIST_URL}" | cut -d' ' -f1))

echo "BASE_URL: $BASE_URL"

if [ -n "$BRANCH" ]; then
	IMG_LIST_STR="$(curl --http1.1 -L -s --connect-timeout 15 -m 15 ${BASE_URL}/sha256sum-${BRANCH}.txt)"
else
	IMG_LIST_STR="$(curl --http1.1 -L -s --connect-timeout 15 -m 15 ${BASE_URL}/sha256sum.txt)"
fi
echo "$IMG_LIST_STR"