lang1=${1:-"en"}
lang2=${2:-"he"}
OUTPUT_DIR=${3:-"./data/OpenSubtitles2016"}

SITE="http://opus.lingfil.uu.se/download.php?f=OpenSubtitles2016/"

OSUB_PREFIX="${OUTPUT_DIR}/train.${lang1}-${lang2}"
TMX_FILE="${lang1}-${lang2}.tmx"

mkdir -p $OUTPUT_DIR
wget -nc "${SITE}${TMX_FILE}.gz" -O "${OUTPUT_DIR}/${TMX_FILE}.gz";
gunzip "${OUTPUT_DIR}/${TMX_FILE}.gz";
cat "${OUTPUT_DIR}/${TMX_FILE}" | sed -n "s/.*xml:lang=\"${lang1}\"><seg>\(.*\)<\/seg>.*/\1/p" > "${OSUB_PREFIX}.${lang1}";
cat "${OUTPUT_DIR}/${TMX_FILE}" | sed -n "s/.*xml:lang=\"${lang2}\"><seg>\(.*\)<\/seg>.*/\1/p" > "${OSUB_PREFIX}.${lang2}";
rm "${OUTPUT_DIR}/${TMX_FILE}";
