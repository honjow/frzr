#!/bin/bash

source ../__frzr-deploy

set -e

REPO="3003n/chimeraos"
CHANNEL="matrix"
BRANCH="kde"

# CHANNEL="gnome_nvidia"
# BRANCH=""

RELEASES_API_URL="https://api.github.com/repos/${REPO}/releases?per_page=100"
RELEASES=$(curl --http1.1 -L -s --connect-timeout 15 -m 15 "${RELEASES_API_URL}")

IMG_LIST_URL=$(echo $RELEASES | get_img_url "${CHANNEL}")

echo -e "\nIMG_LIST_URL: $IMG_LIST_URL"

# 筛选包含BRANCH的URL
if [ -n "$BRANCH" ]; then
    echo -e "\n筛选包含 '$BRANCH' 的URL:"
    FILTERED_URLS=$(echo "$IMG_LIST_URL" | tr ' ' '\n' | grep -i "\-${BRANCH}\.")
    echo "$FILTERED_URLS"
    
    # 选择第一个匹配的URL
    SELECTED_URL=$(echo "$FILTERED_URLS" | head -n 1)
    echo -e "\n选择的URL: $SELECTED_URL"
    
    if [ -n "$SELECTED_URL" ]; then
        IMG_LIST_URL="$SELECTED_URL"
    else
        echo "警告: 没有找到包含 '$BRANCH' 的URL，使用原始URL列表的第一个URL"
        IMG_LIST_URL=$(echo "$IMG_LIST_URL" | cut -d' ' -f1)
    fi
else
    # 如果没有指定BRANCH，使用第一个URL
    IMG_LIST_URL=$(echo "$IMG_LIST_URL" | cut -d' ' -f1)
fi

echo -e "\n使用的IMG_LIST_URL: $IMG_LIST_URL"

IMG_FILE_NAME=$(basename "$IMG_LIST_URL" | sed 's/-[0-9]*$//')
NAME=$(echo "${IMG_FILE_NAME}" | cut -f 1 -d '.')
echo -e "\nIMG_FILE_NAME: $IMG_FILE_NAME,   NAME: $NAME"

BASE_URL=$(dirname "$IMG_LIST_URL")
echo -e "\nBASE_URL: $BASE_URL"

# 根据是否有BRANCH获取不同的sha256sum文件
if [ -n "$BRANCH" ]; then
    echo -e "\n获取 sha256sum-${BRANCH}.txt:"
    IMG_LIST_STR="$(curl --http1.1 -L -s --connect-timeout 15 -m 15 ${BASE_URL}/sha256sum-${BRANCH}.txt)"
    echo "$IMG_LIST_STR"
else
    echo -e "\n获取 sha256sum.txt:"
    IMG_LIST_STR="$(curl --http1.1 -L -s --connect-timeout 15 -m 15 ${BASE_URL}/sha256sum.txt)"
    echo "$IMG_LIST_STR"
fi